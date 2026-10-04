"""シーンをウィンドウで表示する（ディスプレイのある PC 用）。

マウスで視点を回せる。--demo を付けるとデモの動きを繰り返す。

    python scripts/view.py              # 止まったまま表示
    python scripts/view.py --demo       # 拭き取りデモ
    python scripts/view.py --demo pick  # コップをつかんでビンに入れるデモ

macOS では python の代わりに mjpython で実行する（MuJoCo のビューアの制約）。
"""

import argparse
import time

import mujoco.viewer
import numpy as np

from tabulasense import TableCleanEnv
from tabulasense.control.pick_place import PickFailed, pick_and_place, pick_scene_config

WIPE_POSE_R = np.array([0.0, 0.14, 1.096, -0.406, 0.0, 0.0])


def wipe_demo(env: TableCleanEnv):
    """腕を下ろして、台車を左右に振る（200 ステップ）。"""
    target = np.r_[WIPE_POSE_R, np.zeros(6)]
    for k in range(200):
        action = np.zeros(15)
        if k < 60:
            action[3:] = np.clip((target - env._arm_target) / env.max_joint_delta, -1, 1)
        else:
            action[1] = 0.3 * np.sign(np.sin(k / 4))
        yield action


def pick_demo(env: TableCleanEnv):
    try:
        yield from pick_and_place(env, env.handles.object_bodies[0])
    except PickFailed as e:
        print(e)
    for _ in range(20):
        yield np.zeros(15)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--demo", nargs="?", const="wipe", choices=["wipe", "pick"], default=None)
    args = parser.parse_args()

    env = TableCleanEnv(pick_scene_config() if args.demo == "pick" else None)
    seed = args.seed
    env.reset(seed=seed)
    demo = {"wipe": wipe_demo, "pick": pick_demo}.get(args.demo)
    actions = demo(env) if demo else None
    step_time = env.model.opt.timestep * env.frame_skip

    with mujoco.viewer.launch_passive(env.model, env.data) as viewer:
        while viewer.is_running():
            start = time.time()
            action = np.zeros(15)
            if actions is not None:
                action = next(actions, None)
                if action is None:  # 1 回分が終わったら、配置を変えてもう一度
                    seed += 1
                    env.reset(seed=seed)
                    actions = demo(env)
                    action = np.zeros(15)
            env.step(action)
            viewer.sync()
            time.sleep(max(0.0, step_time - (time.time() - start)))


if __name__ == "__main__":
    main()
