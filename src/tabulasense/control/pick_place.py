"""手書きの「物をつかんでビンに入れる」動作（スクリプト方策）。

シミュレーションの真値（物の位置）を使って、次の順に動かす。

    1. 腕をたたむ
    2. 台車でテーブルに近づき、物を腕の届く範囲に入れる
    3. グリッパーを開いて、物の手前に手を出す
    4. 手をまっすぐ差し込み、グリッパーを閉じてつかむ
    5. 持ち上げる
    6. 台車でテーブルから離れ、ビンの前へ移動する
    7. ビンの上で手を開いて落とす
    8. 腕をたたむ

各ステップは「行動（15 次元）」を 1 つずつ返すジェネレータで書いてある。

    for action in pick_and_place(env, "obj0_glass"):
        env.step(action)

これがそのまま模倣学習用のデモデータの生成器になる。
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np

from tabulasense.control.ik import ARM_JOINTS_L, ArmIK
from tabulasense.sim.env import TableCleanEnv
from tabulasense.sim.scene import SceneConfig

# 左腕（`_L`。ロボットから見て右側にある。右腕 `_R` はスポンジを持っている）が、
# 行動ベクトル / env._arm_target のどこにあるか
ACTION_ARM_L = slice(9, 15)  # 5 関節 + グリッパー
TARGET_ARM_L = slice(6, 12)

JAW_OPEN = 1.25  # 指先の間が約 8.5cm
JAW_CLOSED = 0.3  # 物に当たって止まるので、物の幅より閉じた値を指令して握る

SHOULDER_L_IN_ROBOT = np.array([0.135, -0.15])  # 台車中心から見た左肩の位置（前, 左）
GRASP_HEIGHT = 0.065  # 天板からつかむ高さ [m]（低いと開いた指が天板に当たる）
REACH = 0.30  # 肩から物まで、この距離になるように台車を寄せる
CART_FRONT = 0.17  # 台車中心から前端まで（台車の衝突用の箱）
# 指先を水平から何度下に向けるかの候補（前から順に試す）。水平だと物の奥まで指が入るので握りやすい。
# 届かないときだけ下に傾ける（テーブルは肩より低いので、傾けると少し遠くまで届く）
FINGER_TILTS_DEG = (0, 15, 30, 45)


class PickFailed(RuntimeError):
    pass


def pick_scene_config() -> SceneConfig:
    """つかむ練習用のシーン: 細いコップ（glass）を腕の届くテーブル手前に置き、ほかの食器も少し並べる。"""
    return SceneConfig(object_types=["glass", "cup", "box"], object_max_depth=0.30)


@dataclass
class _Ctx:
    env: TableCleanEnv
    ik: ArmIK
    base_goal: np.ndarray  # 台車をとどめておく位置 (x, y, yaw)。腕を動かす間もここに保つ


def pick_and_place(env: TableCleanEnv, object_name: str) -> Iterator[np.ndarray]:
    """object_name の物をつかんでビンに入れるまでの行動を順に返す。"""
    ctx = _Ctx(env, ArmIK(env.model, ARM_JOINTS_L, "pinch_L"), env._base_pose())
    obj = env.data.body(object_name)
    table_top = env.cfg.table_top_z
    table_near_y = env.cfg.table_center[1] - env.cfg.table_half_size[1]
    bin_xy = np.asarray(env.cfg.bin_center)
    tuck = (0.20, -0.15, table_top + 0.25)  # 腕をたたんだときの手先（台車から見た 前, 左, 高さ）

    # 1. 腕をたたむ（テーブルや他の物に当たらない高さ）
    yield from _move_arm_to(ctx, _robot_point(env, *tuck), jaw=0.0)

    # 2. 物の真後ろに肩が来るように台車を寄せる（台車の前端がテーブルに当たらない範囲で）
    target = obj.xpos.copy()
    base_y = min(target[1] - SHOULDER_L_IN_ROBOT[0] - REACH, table_near_y - CART_FRONT - 0.02)
    yield from _move_base_to(ctx, target[0] + SHOULDER_L_IN_ROBOT[1], base_y, np.pi / 2)

    # 3. 届く向きを探してから、グリッパーを開いて物の 8cm 手前に手を出す
    target = obj.xpos.copy()
    grasp = np.array([target[0], target[1], table_top + GRASP_HEIGHT])
    finger = _best_finger_dir(ctx, grasp)
    pre = grasp - 0.08 * finger
    yield from _move_arm_to(ctx, pre + [0, 0, 0.05], jaw=JAW_OPEN, finger_dir=finger)
    yield from _move_arm_to(ctx, pre, jaw=JAW_OPEN, finger_dir=finger, straight=True)

    # 4. 手をまっすぐ差し込んで、閉じる
    yield from _move_arm_to(ctx, grasp, jaw=JAW_OPEN, finger_dir=finger, straight=True)
    yield from _move_jaw(ctx, JAW_CLOSED, steps=25)

    # 5. 持ち上げる
    yield from _move_arm_to(ctx, grasp + [0, 0, 0.12], jaw=JAW_CLOSED, finger_dir=finger, straight=True)

    # 6. テーブルから離れて、ビンの前へ（ビンが肩の 22cm 前に来る位置）
    stand_y = bin_xy[1] - SHOULDER_L_IN_ROBOT[0] - 0.22
    yield from _move_base_to(ctx, ctx.base_goal[0], stand_y, np.pi / 2)
    yield from _move_base_to(ctx, bin_xy[0] + SHOULDER_L_IN_ROBOT[1], stand_y, np.pi / 2)

    # 7. ビンの上で離す（手首の向きを変えずに直線で動かす。急に向きを変えると物が振り飛ばされる）
    above_bin = np.array([bin_xy[0], bin_xy[1], table_top + 0.12])
    yield from _move_arm_to(ctx, above_bin, jaw=JAW_CLOSED, finger_dir=finger, straight=True)
    yield from _move_jaw(ctx, JAW_OPEN, steps=25)

    # 8. 腕をたたむ
    yield from _move_arm_to(ctx, _robot_point(env, *tuck), jaw=0.0)


# ---------------------------------------------------------------- 腕


def _best_finger_dir(ctx: _Ctx, grasp: np.ndarray) -> np.ndarray:
    """指先の傾きの候補から、IK の誤差が 6mm 未満になる最初の向きを選ぶ。"""
    horizontal = _horizontal(grasp - ctx.env.data.body("Rotation_Pitch").xpos)
    best_err = np.inf
    for tilt in FINGER_TILTS_DEG:
        finger = _tilted(horizontal, tilt)
        _, err = _solve(ctx, grasp, finger)
        if err < 0.006:
            return finger
        best_err = min(best_err, err)
    raise PickFailed(f"腕が届きません（最小誤差 {best_err * 100:.1f}cm）。物が遠すぎます。")


def _solve(
    ctx: _Ctx, target: np.ndarray, finger: np.ndarray | None, q_init: np.ndarray | None = None
) -> tuple[np.ndarray, float]:
    """IK を解く。グリッパーは水平に開く（開く向きは左右どちらでもよい）。

    q_init を渡したとき（直線移動の途中）はその近くの解だけを探し、関節が急に跳ばないようにする。
    渡さないときは初期値を変えて何回か解き、左右の開き方のうち誤差の小さい方を使う。
    """
    env, ik = ctx.env, ctx.ik
    if finger is None:
        if q_init is None:
            return ik.solve_best(env.data, target, q_init=env._arm_target[TARGET_ARM_L][:5])
        return ik.solve(env.data, target, q_init=q_init)
    side = np.cross(finger, [0, 0, 1])
    side /= np.linalg.norm(side)
    if q_init is None:
        q0 = env._arm_target[TARGET_ARM_L][:5]
        return min(
            (ik.solve_best(env.data, target, q_init=q0, finger_dir=finger, side_dir=s) for s in (side, -side)),
            key=lambda r: r[1],
        )
    # 直線移動の途中: 手首が途中で 180° 回らないよう、いまの開く向きに近い方に固定する
    if side @ env.data.site("pinch_L").xmat.reshape(3, 3)[:, 0] < 0:
        side = -side
    return ik.solve(env.data, target, q_init=q_init, finger_dir=finger, side_dir=side)


def _move_arm_to(
    ctx: _Ctx,
    target: np.ndarray,
    jaw: float,
    finger_dir: np.ndarray | None = None,
    straight: bool = False,
) -> Iterator[np.ndarray]:
    """手先（pinch_L）を target へ動かす。

    straight=True のときは手先が直線上を 1cm 刻みで進む（物に横から当てないため）。
    False のときは関節角を直接目標へ動かす（速いが、手先の通り道は曲線になる）。
    """
    env = ctx.env
    if straight:
        start = env.data.site("pinch_L").xpos.copy()
        n = max(1, int(np.ceil(np.linalg.norm(target - start) / 0.01)))
        q = env._arm_target[TARGET_ARM_L][:5]
        for i in range(1, n + 1):
            q, _ = _solve(ctx, start + (target - start) * i / n, finger_dir, q_init=q)
            yield from _track(ctx, np.r_[q, jaw], max_steps=10, settle=False)
    else:
        q, _ = _solve(ctx, target, finger_dir)
    yield from _track(ctx, np.r_[q, jaw], max_steps=150)


def _track(ctx: _Ctx, goal: np.ndarray, max_steps: int, settle: bool = True) -> Iterator[np.ndarray]:
    """左腕の目標角（5 関節 + グリッパー）を goal まで動かす。settle=True なら腕が止まるまで待つ。"""
    env = ctx.env
    for _ in range(max_steps):
        delta = goal - env._arm_target[TARGET_ARM_L]
        if np.abs(delta).max() < 1e-3 and (not settle or _arm_settled(env)):
            return
        action = _hold_base(ctx)
        action[ACTION_ARM_L] = np.clip(delta / env.max_joint_delta, -1, 1)
        yield action


def _move_jaw(ctx: _Ctx, jaw: float, steps: int) -> Iterator[np.ndarray]:
    """腕は止めたまま、グリッパーだけ動かして待つ。"""
    goal = ctx.env._arm_target[TARGET_ARM_L].copy()
    goal[5] = jaw
    yield from _track(ctx, goal, max_steps=steps, settle=False)
    for _ in range(10):  # 握る（離す）のを待つ
        yield _hold_base(ctx)


def _arm_settled(env: TableCleanEnv, tol: float = 0.05) -> bool:
    """腕の関節がほぼ止まったか（重力で少し垂れるので、角度ではなく速さで見る）。"""
    return bool(np.abs(env.data.qvel[env._arm_dadr[TARGET_ARM_L]]).max() < tol)


# ---------------------------------------------------------------- 台車


def _move_base_to(ctx: _Ctx, x: float, y: float, yaw: float, max_steps: int = 300) -> Iterator[np.ndarray]:
    """台車を目標の位置・向きへ動かす。腕とグリッパーはそのまま保つ。"""
    ctx.base_goal = np.array([x, y, yaw])
    for _ in range(max_steps):
        err = _base_error(ctx)
        if np.abs(err[:2]).max() < 0.005 and abs(err[2]) < 0.01:
            return
        yield _hold_base(ctx)


def _hold_base(ctx: _Ctx) -> np.ndarray:
    """台車を ctx.base_goal に向かわせる（とどめる）行動。腕の部分はゼロ（そのまま）。"""
    action = np.zeros(15)
    action[:3] = np.clip(3.0 * _base_error(ctx) / ctx.env.max_base_speed, -1, 1)
    return action


def _base_error(ctx: _Ctx) -> np.ndarray:
    """目標とのずれ（ロボットから見た 前, 左, 旋回）。"""
    x, y, yaw = ctx.env._base_pose()
    err_world = ctx.base_goal[:2] - [x, y]
    fwd = np.array([np.cos(yaw), np.sin(yaw)])
    left = np.array([-np.sin(yaw), np.cos(yaw)])
    return np.array([err_world @ fwd, err_world @ left, _wrap(ctx.base_goal[2] - yaw)])


# ---------------------------------------------------------------- 小道具


def _robot_point(env: TableCleanEnv, forward: float, left: float, z: float) -> np.ndarray:
    """台車から見た (前, 左) の位置をワールド座標にする。"""
    x, y, yaw = env._base_pose()
    return np.array(
        [x + forward * np.cos(yaw) - left * np.sin(yaw), y + forward * np.sin(yaw) + left * np.cos(yaw), z]
    )


def _tilted(horizontal, tilt_deg: float) -> np.ndarray:
    """水平な向きを tilt_deg 度だけ下に傾ける。"""
    t = np.deg2rad(tilt_deg)
    h = _horizontal(np.asarray(horizontal, dtype=float))
    return h * np.cos(t) + np.array([0, 0, -np.sin(t)])


def _horizontal(v: np.ndarray) -> np.ndarray:
    v = np.array([v[0], v[1], 0.0])
    return v / np.linalg.norm(v)


def _wrap(a: float) -> float:
    return (a + np.pi) % (2 * np.pi) - np.pi
