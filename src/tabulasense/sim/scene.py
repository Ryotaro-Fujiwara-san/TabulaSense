"""XLeRobot・テーブル・食器・汚れを一つの MuJoCo シーンに組み立てる。

XLeRobot の MJCF はそのまま読み込み、MjSpec で周りの物を足す。
ロボット本体のファイルを書き換えないので、上流の更新を取り込みやすい。

座標系の注意: XLeRobot の chassis は z 軸まわりに 90° 回っているので、
ロボットの「前」（腕が伸びる方向）はワールドの +y になる。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import mujoco
import numpy as np

from tabulasense.paths import xlerobot_xml

# 片付け対象の種類: (形状, size, rgba, 質量kg)
OBJECT_TYPES: dict[str, tuple[int, list[float], list[float], float]] = {
    "cup": (mujoco.mjtGeom.mjGEOM_CYLINDER, [0.035, 0.045], [0.9, 0.9, 0.95, 1], 0.15),
    "plate": (mujoco.mjtGeom.mjGEOM_CYLINDER, [0.09, 0.008], [0.95, 0.95, 0.9, 1], 0.30),
    "bottle": (mujoco.mjtGeom.mjGEOM_CYLINDER, [0.03, 0.08], [0.2, 0.6, 0.3, 1], 0.25),
    "box": (mujoco.mjtGeom.mjGEOM_BOX, [0.04, 0.03, 0.02], [0.8, 0.5, 0.2, 1], 0.10),
}

STAIN_RGBA = np.array([0.45, 0.28, 0.12, 1.0])


@dataclass
class SceneConfig:
    """シーンの寸法と配置。単位は m。"""

    table_center: tuple[float, float] = (0.0, 0.70)
    table_half_size: tuple[float, float] = (0.45, 0.30)
    table_height: float = 0.72
    object_types: list[str] = field(default_factory=lambda: ["cup", "plate", "bottle", "box"])
    n_stains: int = 3
    stain_radius_range: tuple[float, float] = (0.03, 0.06)
    # 回収した食器を入れる下げ膳用のビン（テーブルの横に固定）
    bin_center: tuple[float, float] = (0.65, 0.35)
    bin_half_size: tuple[float, float, float] = (0.15, 0.12, 0.10)
    # 右手にスポンジ（拭き取り具）を持たせる
    attach_wiper: bool = True
    # 台車（IKEA ワゴン＋棚）の質量。上流モデルでは密度の既定値から約 120kg になってしまう
    cart_mass: float = 8.0
    base_velocity_gain: float = 300.0
    margin: float = 0.06

    @property
    def table_top_z(self) -> float:
        return self.table_height


@dataclass
class SceneHandles:
    """シーン内の名前のついた要素。env が ID を引くのに使う。"""

    object_bodies: list[str]
    object_geoms: list[str]
    stain_geoms: list[str]
    wiper_site: str | None
    gripper_sites: list[str]
    table_geom: str = "table_top"
    bin_site: str = "bin_center"


def _xyaxes_to_quat(xyaxes: list[float]) -> np.ndarray:
    x = np.array(xyaxes[:3], dtype=float)
    y = np.array(xyaxes[3:], dtype=float)
    x /= np.linalg.norm(x)
    y -= x * (x @ y)
    y /= np.linalg.norm(y)
    mat = np.stack([x, y, np.cross(x, y)], axis=1).flatten()
    quat = np.zeros(4)
    mujoco.mju_mat2Quat(quat, mat)
    return quat


def build_scene(
    config: SceneConfig | None = None,
    robot_xml: Path | None = None,
) -> tuple[mujoco.MjSpec, SceneHandles]:
    """シーンの MjSpec を作る。物体や汚れの位置は env.reset() で毎回ランダムに決める。"""
    cfg = config or SceneConfig()
    spec = mujoco.MjSpec.from_file(str(robot_xml or xlerobot_xml()))
    spec.modelname = "tabulasense_scene"
    spec.option.timestep = 0.002
    spec.option.integrator = mujoco.mjtIntegrator.mjINT_IMPLICITFAST
    spec.visual.global_.offwidth = 1280
    spec.visual.global_.offheight = 960
    world = spec.worldbody

    # 床と照明
    world.add_geom(
        name="floor", type=mujoco.mjtGeom.mjGEOM_PLANE, size=[0, 0, 0.05], rgba=[0.55, 0.55, 0.5, 1]
    )
    # XLeRobot 側の真上からの照明は真上カメラで白飛びするので弱める
    for light in world.lights:
        light.diffuse = [0.45, 0.45, 0.45]
        light.specular = [0.05, 0.05, 0.05]
    world.add_light(pos=[1.5, -1.0, 2.5], dir=[-0.5, 0.5, -1], diffuse=[0.25, 0.25, 0.25])
    spec.visual.headlight.diffuse = [0.3, 0.3, 0.3]
    spec.visual.headlight.ambient = [0.2, 0.2, 0.2]

    _tune_robot(spec, cfg)

    _add_table(world, cfg)
    _add_bin(world, cfg)

    object_bodies, object_geoms = [], []
    for i, kind in enumerate(cfg.object_types):
        gtype, size, rgba, mass = OBJECT_TYPES[kind]
        name = f"obj{i}_{kind}"
        body = world.add_body(name=name, pos=[0, 0, cfg.table_top_z + 0.1])
        body.add_freejoint(name=f"{name}_free")
        body.add_geom(
            name=f"{name}_geom", type=gtype, size=size, rgba=rgba, mass=mass,
            friction=[1.0, 0.01, 0.001], condim=4,
        )
        object_bodies.append(name)
        object_geoms.append(f"{name}_geom")

    # 汚れ: 衝突しない薄い円盤。テーブル天板の子にして、半径と位置は reset で変える。
    table = spec.body("table")
    stain_geoms = []
    for i in range(cfg.n_stains):
        name = f"stain{i}"
        table.add_geom(
            name=name, type=mujoco.mjtGeom.mjGEOM_CYLINDER,
            size=[cfg.stain_radius_range[1], 0.0005],
            pos=[0, 0, cfg.table_top_z + 0.0006],
            rgba=STAIN_RGBA, contype=0, conaffinity=0, group=1, mass=0,
        )
        stain_geoms.append(name)

    gripper_sites = []
    for jaw, site in (("Fixed_Jaw_2", "grip_R"), ("Fixed_Jaw", "grip_L")):
        spec.body(jaw).add_site(name=site, pos=[-0.01, -0.09, 0], size=[0.008, 0, 0], rgba=[1, 0, 0, 0.5])
        gripper_sites.append(site)

    wiper_site = None
    if cfg.attach_wiper:
        jaw = spec.body("Fixed_Jaw_2")
        jaw.add_geom(
            name="wiper", type=mujoco.mjtGeom.mjGEOM_BOX, size=[0.03, 0.015, 0.02],
            pos=[-0.01, -0.09, 0], rgba=[0.2, 0.5, 0.9, 1], mass=0.02, friction=[0.4, 0.01, 0.001],
        )
        wiper_site = "grip_R"

    # カメラ: 頭部（XLeRobot 実機の頭カメラ相当）とテーブル真上（評価・可視化用）
    spec.body("head_tilt_link").add_camera(
        name="head_cam", pos=[0.05, 0, 0.05], quat=_xyaxes_to_quat([0, -1, 0, 0, 0, 1]), fovy=70,
    )
    world.add_camera(
        name="top_cam", pos=[cfg.table_center[0], cfg.table_center[1], 2.0], fovy=45,
    )
    world.add_camera(
        name="overview_cam", pos=[1.6, -0.9, 1.7],
        quat=_xyaxes_to_quat([0.6, 0.8, 0, -0.45, 0.34, 0.83]), fovy=50,
    )

    return spec, SceneHandles(
        object_bodies=object_bodies,
        object_geoms=object_geoms,
        stain_geoms=stain_geoms,
        wiper_site=wiper_site,
        gripper_sites=gripper_sites,
    )


def _tune_robot(spec: mujoco.MjSpec, cfg: SceneConfig) -> None:
    """上流の XLeRobot モデルを、このタスク用に調整する（元ファイルは書き換えない）。"""
    # 台車を表す半透明の箱: 質量を実機相当にし、描画しないグループ 3 に移す（衝突判定は残る）
    for geom in spec.body("chassis").geoms:
        if geom.type == mujoco.mjtGeom.mjGEOM_BOX:
            geom.mass = cfg.cart_mass
            geom.group = 3

    # 台車はスライド関節で直接動かすので、オムニホイールは見た目だけにする
    # （普通の車輪として床と接触すると横方向の移動を妨げる）
    for body in spec.bodies:
        if "Omni-Directional-Wheel" in body.name:
            for geom in body.geoms:
                geom.contype = 0
                geom.conaffinity = 0

    # 速度指令への追従を良くする（上流は kv=10 で、質量に対して弱すぎる）
    for name in ("slider_actuator_x", "slider_actuator_y", "hinge_actuator_z"):
        spec.actuator(name).set_to_velocity(kv=cfg.base_velocity_gain)

    _add_head_actuators(spec)


def _add_head_actuators(spec: mujoco.MjSpec) -> None:
    """上流モデルでは頭の関節に駆動がなく、重力で垂れてしまうので位置制御を足す。

    実機の頭も 2 軸サーボなので、それに合わせる。head_tilt は正の値で下を向く。
    """
    for joint, kp in (("head_pan_joint", 2.0), ("head_tilt_joint", 5.0)):
        act = spec.add_actuator(name=joint.replace("_joint", ""), target=joint)
        act.trntype = mujoco.mjtTrn.mjTRN_JOINT
        act.set_to_position(kp=kp, dampratio=1.0)
        act.ctrlrange = spec.joint(joint).range
        act.ctrllimited = mujoco.mjtLimited.mjLIMITED_TRUE


def _add_table(world: mujoco.MjsBody, cfg: SceneConfig) -> None:
    cx, cy = cfg.table_center
    hx, hy = cfg.table_half_size
    top_thickness = 0.02
    table = world.add_body(name="table", pos=[cx, cy, 0])
    table.add_geom(
        name="table_top", type=mujoco.mjtGeom.mjGEOM_BOX,
        size=[hx, hy, top_thickness / 2], pos=[0, 0, cfg.table_top_z - top_thickness / 2],
        rgba=[0.72, 0.62, 0.48, 1], friction=[0.8, 0.01, 0.001],
    )
    leg_h = (cfg.table_top_z - top_thickness) / 2
    for sx in (-1, 1):
        for sy in (-1, 1):
            table.add_geom(
                type=mujoco.mjtGeom.mjGEOM_BOX, size=[0.02, 0.02, leg_h],
                pos=[sx * (hx - 0.04), sy * (hy - 0.04), leg_h], rgba=[0.4, 0.3, 0.2, 1],
            )


def _add_bin(world: mujoco.MjsBody, cfg: SceneConfig) -> None:
    bx, by = cfg.bin_center
    hx, hy, hz = cfg.bin_half_size
    wall = 0.01
    # 下げ膳は腕が届く高さに置く（台の上のビン）
    floor_z = 0.55
    body = world.add_body(name="bin", pos=[bx, by, 0])
    gray = [0.3, 0.3, 0.35, 1]
    body.add_geom(type=mujoco.mjtGeom.mjGEOM_BOX, size=[0.08, 0.08, floor_z / 2], pos=[0, 0, floor_z / 2], rgba=[0.5, 0.5, 0.5, 1])
    body.add_geom(type=mujoco.mjtGeom.mjGEOM_BOX, size=[hx, hy, wall], pos=[0, 0, floor_z + wall], rgba=gray)
    for sx in (-1, 1):
        body.add_geom(type=mujoco.mjtGeom.mjGEOM_BOX, size=[wall, hy, hz], pos=[sx * hx, 0, floor_z + hz], rgba=gray)
    for sy in (-1, 1):
        body.add_geom(type=mujoco.mjtGeom.mjGEOM_BOX, size=[hx, wall, hz], pos=[0, sy * hy, floor_z + hz], rgba=gray)
    body.add_site(name="bin_center", pos=[0, 0, floor_z + hz], size=[hx, hy, hz], type=mujoco.mjtGeom.mjGEOM_BOX, rgba=[0, 1, 0, 0])
