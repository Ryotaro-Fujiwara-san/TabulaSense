"""腕の逆運動学（IK）: 手先を目標の位置・向きに持っていく関節角を求める。

ヤコビアンを使った減衰最小二乗法（Damped Least Squares）。シミュレーションの状態は
書き換えず、コピーした MjData の上で計算する。
"""

from __future__ import annotations

import mujoco
import numpy as np

ARM_JOINTS_L = ["Rotation_L", "Pitch_L", "Elbow_L", "Wrist_Pitch_L", "Wrist_Roll_L"]
ARM_JOINTS_R = ["Rotation_R", "Pitch_R", "Elbow_R", "Wrist_Pitch_R", "Wrist_Roll_R"]


class ArmIK:
    def __init__(self, model: mujoco.MjModel, joints: list[str], site: str) -> None:
        self.model = model
        self.data = mujoco.MjData(model)
        self.site = model.site(site).id
        jids = [model.joint(n).id for n in joints]
        self.qadr = np.array([model.jnt_qposadr[j] for j in jids])
        self.dadr = np.array([model.jnt_dofadr[j] for j in jids])
        self.range = np.array([model.jnt_range[j] for j in jids])
        # 可動域がほぼ 1 周ある関節（手首の回転）は、端で止めずに反対側へ回り込ませる
        self.wraps = (self.range[:, 1] - self.range[:, 0]) > 2 * np.pi - 0.01

    def solve_best(self, data: mujoco.MjData, target_pos: np.ndarray, restarts: int = 8, **kwargs):
        """初期値を変えて何回か解き、誤差のいちばん小さい解を返す（局所解を避ける）。"""
        rng = np.random.default_rng(0)
        inits = [kwargs.pop("q_init", None)]
        inits += [rng.uniform(self.range[:, 0], self.range[:, 1]) for _ in range(restarts)]
        results = [self.solve(data, target_pos, q_init=q0, **kwargs) for q0 in inits]
        return min(results, key=lambda r: r[1])

    def solve(
        self,
        data: mujoco.MjData,
        target_pos: np.ndarray,
        finger_dir: np.ndarray | None = None,
        side_dir: np.ndarray | None = None,
        q_init: np.ndarray | None = None,
        iters: int = 200,
        damping: float = 1e-3,
        rot_weight: float = 0.1,
    ) -> tuple[np.ndarray, float]:
        """関節角とそのときの位置誤差 [m] を返す。

        finger_dir: 指先が向く方向（グリッパーのローカル -y 軸）のワールドでの向き
        side_dir:   グリッパーが開く方向（ローカル x 軸）のワールドでの向き
        """
        m, d = self.model, self.data
        d.qpos[:] = data.qpos
        if q_init is not None:
            d.qpos[self.qadr] = q_init
        jacp = np.zeros((3, m.nv))
        jacr = np.zeros((3, m.nv))
        for _ in range(iters):
            mujoco.mj_kinematics(m, d)
            mujoco.mj_comPos(m, d)
            err = [target_pos - d.site_xpos[self.site]]
            mujoco.mj_jacSite(m, d, jacp, jacr, self.site)
            jac = [jacp[:, self.dadr]]
            rot = d.site_xmat[self.site].reshape(3, 3)
            for local, want in ((-rot[:, 1], finger_dir), (rot[:, 0], side_dir)):
                if want is not None:
                    err.append(rot_weight * np.cross(local, want / np.linalg.norm(want)))
                    jac.append(rot_weight * jacr[:, self.dadr])
            e, j = np.concatenate(err), np.vstack(jac)
            dq = j.T @ np.linalg.solve(j @ j.T + damping * np.eye(len(e)), e)
            q = d.qpos[self.qadr] + dq
            q = np.where(self.wraps, (q + np.pi) % (2 * np.pi) - np.pi, q)
            q = np.clip(q, self.range[:, 0], self.range[:, 1])
            d.qpos[self.qadr] = q
            if np.linalg.norm(e) < 1e-4:
                break
        mujoco.mj_kinematics(m, d)
        return d.qpos[self.qadr].copy(), float(np.linalg.norm(target_pos - d.site_xpos[self.site]))
