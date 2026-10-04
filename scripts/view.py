"""シーンをウィンドウで表示する（ディスプレイのある PC 用）。

マウスで視点を回せる。--demo を付けると拭き取りデモの動きを繰り返す。

    python scripts/view.py
    python scripts/view.py --demo

macOS では python の代わりに mjpython で実行する（MuJoCo のビューアの制約）。
"""

import argparse
import time

import mujoco.viewer
import numpy as np

from tabulasense import TableCleanEnv

WIPE_POSE_R = np.array([0.0, 0.14, 1.096, -0.406, 0.0, 0.0])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--demo", action="store_true", help="拭き取りデモの動きを繰り返す")
    args = parser.parse_args()

    env = TableCleanEnv()
    env.reset(seed=args.seed)
    target = np.r_[WIPE_POSE_R, np.zeros(6)]
    step_time = env.model.opt.timestep * env.frame_skip

    with mujoco.viewer.launch_passive(env.model, env.data) as viewer:
        k = 0
        while viewer.is_running():
            start = time.time()
            action = np.zeros(15)
            if args.demo:
                if k < 60:
                    action[3:] = np.clip((target - env._arm_target) / env.max_joint_delta, -1, 1)
                else:
                    action[1] = 0.3 * np.sign(np.sin(k / 4))
                if k >= 200:
                    env.reset(seed=args.seed)
                    k = -1
            env.step(action)
            viewer.sync()
            k += 1
            time.sleep(max(0.0, step_time - (time.time() - start)))


if __name__ == "__main__":
    main()
