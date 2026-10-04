"""テーブル片付け＋拭き上げタスクの Gymnasium 環境。

行動（15 次元、すべて [-1, 1]）
    0-2  : 台車の速度指令（ロボット座標系の 前, 左, 旋回）
    3-8  : 右腕 6 関節の目標角の増分（Rotation, Pitch, Elbow, Wrist_Pitch, Wrist_Roll, Jaw）
    9-14 : 左腕 6 関節の目標角の増分

観測は真値（物体位置・汚れの残り具合）を返す。まずはこれで方策や
スクリプトを作り、あとで perception の推定値やカメラ画像に差し替える。
"""

from __future__ import annotations

from typing import Any

import gymnasium as gym
import mujoco
import numpy as np
from gymnasium import spaces

from tabulasense.sim.scene import OBJECT_TYPES, STAIN_RGBA, SceneConfig, build_scene

ARM_JOINTS = [
    "Rotation_R", "Pitch_R", "Elbow_R", "Wrist_Pitch_R", "Wrist_Roll_R", "Jaw_R",
    "Rotation_L", "Pitch_L", "Elbow_L", "Wrist_Pitch_L", "Wrist_Roll_L", "Jaw_L",
]
BASE_ACTUATORS = ["slider_actuator_x", "slider_actuator_y", "hinge_actuator_z"]
BASE_JOINTS = ["slide_joint_x", "slide_joint_y", "hinge_joint_z"]
HEAD_ACTUATORS = ["head_pan", "head_tilt"]

# 置き場所が重ならないように使う、物体の xy 方向のおおよその半径
_FOOTPRINT = {"cup": 0.04, "plate": 0.095, "bottle": 0.035, "box": 0.05, "glass": 0.03}


class TableCleanEnv(gym.Env):
    metadata = {"render_modes": ["rgb_array", "human"], "render_fps": 20}

    def __init__(
        self,
        scene_config: SceneConfig | None = None,
        render_mode: str | None = None,
        render_camera: str = "overview_cam",
        render_size: tuple[int, int] = (480, 640),
        frame_skip: int = 25,
        max_episode_steps: int = 1000,
        max_base_speed: tuple[float, float, float] = (0.3, 0.3, 1.0),
        max_joint_delta: float = 0.05,
        wipe_gain: float = 0.5,
        head_pose: tuple[float, float] = (0.0, 0.8),
    ) -> None:
        self.cfg = scene_config or SceneConfig()
        self.spec, self.handles = build_scene(self.cfg)
        self.model = self.spec.compile()
        self.data = mujoco.MjData(self.model)

        self.render_mode = render_mode
        self.render_camera = render_camera
        self.render_size = render_size
        self.frame_skip = frame_skip
        self.max_episode_steps = max_episode_steps
        self.max_base_speed = np.asarray(max_base_speed)
        self.max_joint_delta = max_joint_delta
        self.wipe_gain = wipe_gain
        self.head_pose = np.asarray(head_pose, dtype=float)
        self._renderer: mujoco.Renderer | None = None
        self._viewer = None

        m = self.model
        self._arm_act = np.array([m.actuator(n).id for n in ARM_JOINTS])
        self._base_act = np.array([m.actuator(n).id for n in BASE_ACTUATORS])
        self._head_act = np.array([m.actuator(n).id for n in HEAD_ACTUATORS])
        self._head_qadr = np.array([m.jnt_qposadr[m.actuator_trnid[a, 0]] for a in self._head_act])
        self._arm_qadr = np.array([m.jnt_qposadr[m.joint(n).id] for n in ARM_JOINTS])
        self._arm_dadr = np.array([m.jnt_dofadr[m.joint(n).id] for n in ARM_JOINTS])
        self._arm_range = np.array([m.jnt_range[m.joint(n).id] for n in ARM_JOINTS])
        self._base_qadr = np.array([m.jnt_qposadr[m.joint(n).id] for n in BASE_JOINTS])
        self._base_dadr = np.array([m.jnt_dofadr[m.joint(n).id] for n in BASE_JOINTS])
        self._obj_body = np.array([m.body(n).id for n in self.handles.object_bodies])
        self._obj_qadr = np.array(
            [m.jnt_qposadr[m.body_jntadr[b]] for b in self._obj_body]
        )
        self._stain_geom = np.array([m.geom(n).id for n in self.handles.stain_geoms])
        self._table_geom = m.geom(self.handles.table_geom).id
        self._bin_site = m.site(self.handles.bin_site).id
        self._wiper_geom = m.geom("wiper").id if self.cfg.attach_wiper else -1

        n_obj, n_stain = len(self._obj_body), len(self._stain_geom)
        self.action_space = spaces.Box(-1.0, 1.0, shape=(15,), dtype=np.float32)
        self.observation_space = spaces.Dict(
            {
                # 腕の角度12・角速度12・台車の姿勢(x, y, yaw)3・台車の速度3
                "robot": spaces.Box(-np.inf, np.inf, shape=(30,), dtype=np.float64),
                # 物体ごとに 位置3 + [テーブル上, ビン内, 落下] の3フラグ
                "objects": spaces.Box(-np.inf, np.inf, shape=(n_obj, 6), dtype=np.float64),
                # 汚れごとに x, y, 半径, 残り具合(0〜1)
                "stains": spaces.Box(-np.inf, np.inf, shape=(n_stain, 4), dtype=np.float64),
            }
        )

        self.dirt = np.ones(n_stain)
        self._arm_target = np.zeros(len(ARM_JOINTS))
        self._obj_status = np.zeros((n_obj, 3), dtype=bool)
        self._steps = 0

    # ------------------------------------------------------------------ gym API
    def reset(self, *, seed: int | None = None, options: dict[str, Any] | None = None):
        super().reset(seed=seed)
        mujoco.mj_resetData(self.model, self.data)

        self._arm_target = np.zeros(len(ARM_JOINTS))
        self.data.qpos[self._arm_qadr] = self._arm_target
        self.data.qpos[self._head_qadr] = self.head_pose
        self._place_objects()
        self._place_stains()

        mujoco.mj_forward(self.model, self.data)
        self._apply_controls(np.zeros(3))
        # 物体を天板に落ち着かせる
        for _ in range(100):
            mujoco.mj_step(self.model, self.data)

        self._obj_status = self._object_status()
        self._steps = 0
        return self._get_obs(), self._get_info()

    def step(self, action: np.ndarray):
        action = np.clip(np.asarray(action, dtype=np.float64), -1.0, 1.0)
        self._arm_target = np.clip(
            self._arm_target + action[3:] * self.max_joint_delta,
            self._arm_range[:, 0],
            self._arm_range[:, 1],
        )
        self._apply_controls(action[:3] * self.max_base_speed)

        dirt_before = self.dirt.sum()
        for _ in range(self.frame_skip):
            mujoco.mj_step(self.model, self.data)
            self._update_dirt(self.model.opt.timestep)
        self._update_stain_rgba()

        status = self._object_status()
        newly_binned = np.sum(status[:, 1] & ~self._obj_status[:, 1])
        newly_dropped = np.sum(status[:, 2] & ~self._obj_status[:, 2])
        self._obj_status = status

        success = bool(status[:, 1].all() and (self.dirt < 0.05).all())
        reward = (
            1.0 * newly_binned
            - 0.5 * newly_dropped
            + 1.0 * (dirt_before - self.dirt.sum())
            - 1e-3 * float(np.square(action).sum())
            + (5.0 if success else 0.0)
        )

        self._steps += 1
        truncated = self._steps >= self.max_episode_steps
        if self.render_mode == "human":
            self.render()
        return self._get_obs(), reward, success, truncated, self._get_info()

    def render(self):
        if self.render_mode == "rgb_array":
            return self.render_camera_image(self.render_camera)
        if self.render_mode == "human":
            if self._viewer is None:
                import mujoco.viewer

                self._viewer = mujoco.viewer.launch_passive(self.model, self.data)
            self._viewer.sync()
        return None

    def render_camera_image(
        self, camera: str, segmentation: bool = False, depth: bool = False
    ) -> np.ndarray:
        """任意のカメラから RGB / セグメンテーション / 深度を描画する。"""
        if self._renderer is None:
            h, w = self.render_size
            self._renderer = mujoco.Renderer(self.model, h, w)
        r = self._renderer
        if segmentation:
            r.enable_segmentation_rendering()
        elif depth:
            r.enable_depth_rendering()
        r.update_scene(self.data, camera=camera)
        img = r.render().copy()
        r.disable_segmentation_rendering()
        r.disable_depth_rendering()
        return img

    def close(self) -> None:
        if self._renderer is not None:
            self._renderer.close()
            self._renderer = None
        if self._viewer is not None:
            self._viewer.close()
            self._viewer = None

    # --------------------------------------------------------------- internals
    def _base_pose(self) -> np.ndarray:
        """台車のワールド座標 (x, y, yaw)。yaw=0 でワールド +x を向く。"""
        xy = self.data.xpos[self.model.body("chassis").id][:2]
        yaw = self.data.qpos[self._base_qadr[2]] + np.pi / 2
        return np.array([xy[0], xy[1], yaw])

    def _base_velocity(self) -> np.ndarray:
        """台車の速度（ロボット座標系の 前, 左, 旋回）。"""
        theta = self.data.qpos[self._base_qadr[2]]
        c, s = np.cos(theta), np.sin(theta)
        vx, vy, wz = self.data.qvel[self._base_dadr]
        return np.array([c * vx + s * vy, -s * vx + c * vy, wz])

    def _apply_controls(self, base_cmd: np.ndarray) -> None:
        # 台車のスライド関節は向きが固定なので、ロボット座標系の指令を回して渡す
        theta = self.data.qpos[self._base_qadr[2]]
        c, s = np.cos(theta), np.sin(theta)
        vx, vy, wz = base_cmd
        self.data.ctrl[self._base_act] = [c * vx - s * vy, s * vx + c * vy, wz]
        self.data.ctrl[self._arm_act] = self._arm_target
        self.data.ctrl[self._head_act] = self.head_pose

    def set_head_pose(self, pan: float, tilt: float) -> None:
        """頭カメラの向き（rad）。行動空間には含めず、ここで指定する。"""
        self.head_pose = np.array([pan, tilt])

    def _table_bounds(self, margin: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
        c = np.asarray(self.cfg.table_center)
        h = np.asarray(self.cfg.table_half_size) - margin
        return c - h, c + h

    def _place_objects(self) -> None:
        lo, hi = self._table_bounds(self.cfg.margin)
        # 手前側は初期姿勢の腕と干渉するので空けておく
        lo, hi = lo.copy(), hi.copy()
        lo[1] += 0.10
        if self.cfg.object_max_depth is not None:
            hi[1] = min(hi[1], lo[1] - 0.10 - self.cfg.margin + self.cfg.object_max_depth)
        placed: list[tuple[np.ndarray, float]] = []
        for i, kind in enumerate(self.cfg.object_types):
            r = _FOOTPRINT[kind]
            for _ in range(200):
                # 範囲が物より狭いときは手前の端に寄せる
                xy = self.np_random.uniform(lo + r, np.maximum(hi - r, lo + r))
                if all(np.linalg.norm(xy - p) > r + pr + 0.01 for p, pr in placed):
                    break
            placed.append((xy, r))
            gtype, size, *_ = OBJECT_TYPES[kind]
            half_h = size[1] if gtype == mujoco.mjtGeom.mjGEOM_CYLINDER else size[2]
            yaw = self.np_random.uniform(-np.pi, np.pi)
            q = self._obj_qadr[i]
            self.data.qpos[q : q + 3] = [xy[0], xy[1], self.cfg.table_top_z + half_h + 0.002]
            self.data.qpos[q + 3 : q + 7] = [np.cos(yaw / 2), 0, 0, np.sin(yaw / 2)]

    def _place_stains(self) -> None:
        lo, hi = self._table_bounds(self.cfg.margin)
        table_xy = np.asarray(self.cfg.table_center)
        for gid in self._stain_geom:
            r = self.np_random.uniform(*self.cfg.stain_radius_range)
            xy = self.np_random.uniform(lo + r, hi - r)
            self.model.geom_size[gid, 0] = r
            self.model.geom_pos[gid, :2] = xy - table_xy
        self.dirt[:] = 1.0
        self._update_stain_rgba()

    def _update_dirt(self, dt: float) -> None:
        """スポンジが天板に触れながら動いていると、触れている汚れが薄くなる。"""
        if self._wiper_geom < 0 or not (self.dirt > 0).any():
            return
        m, d = self.model, self.data
        for k in range(d.ncon):
            con = d.contact[k]
            if {con.geom1, con.geom2} != {self._wiper_geom, self._table_geom}:
                continue
            vel = np.zeros(6)
            mujoco.mj_objectVelocity(m, d, mujoco.mjtObj.mjOBJ_GEOM, self._wiper_geom, vel, 0)
            speed = np.linalg.norm(vel[3:5])
            for j, gid in enumerate(self._stain_geom):
                r = m.geom_size[gid, 0]
                if np.linalg.norm(con.pos[:2] - d.geom_xpos[gid][:2]) < r + 0.03:
                    self.dirt[j] = max(0.0, self.dirt[j] - self.wipe_gain * speed * dt / r)
            break

    def _update_stain_rgba(self) -> None:
        for j, gid in enumerate(self._stain_geom):
            self.model.geom_rgba[gid] = STAIN_RGBA * [1, 1, 1, self.dirt[j]]

    def _object_status(self) -> np.ndarray:
        """各物体が [テーブル上, ビン内, 落下] のどれか。"""
        lo, hi = self._table_bounds()
        top = self.cfg.table_top_z
        bin_pos = self.data.site_xpos[self._bin_site]
        bin_half = self.model.site_size[self._bin_site]
        status = np.zeros((len(self._obj_body), 3), dtype=bool)
        for i, b in enumerate(self._obj_body):
            p = self.data.xpos[b]
            on_table = bool((p[:2] > lo).all() and (p[:2] < hi).all() and p[2] > top - 0.01)
            in_bin = bool((np.abs(p - bin_pos) < bin_half).all())
            dropped = (not on_table) and (not in_bin) and p[2] < top - 0.1
            status[i] = [on_table, in_bin, dropped]
        return status

    def _get_obs(self) -> dict[str, np.ndarray]:
        d = self.data
        robot = np.concatenate(
            [
                d.qpos[self._arm_qadr],
                d.qvel[self._arm_dadr],
                self._base_pose(),
                self._base_velocity(),
            ]
        )
        objects = np.concatenate([d.xpos[self._obj_body], self._obj_status.astype(float)], axis=1)
        stains = np.stack(
            [
                np.r_[d.geom_xpos[g][:2], self.model.geom_size[g, 0], self.dirt[j]]
                for j, g in enumerate(self._stain_geom)
            ]
        )
        return {"robot": robot, "objects": objects, "stains": stains}

    def _get_info(self) -> dict[str, Any]:
        return {
            "objects_on_table": int(self._obj_status[:, 0].sum()),
            "objects_in_bin": int(self._obj_status[:, 1].sum()),
            "objects_dropped": int(self._obj_status[:, 2].sum()),
            "dirt_remaining": float(self.dirt.sum()),
        }
