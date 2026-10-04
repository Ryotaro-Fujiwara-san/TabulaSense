"""右腕のスポンジを天板に当て、台車を左右に振って汚れを拭き取るデモ。

学習済み方策の代わりの手書きスクリプト。拭き取りの仕組みが動くことの確認と、
模倣学習用のデモデータ作りの出発点に使う。

    MUJOCO_GL=egl python scripts/demo_wipe.py --video outputs/demo_wipe.mp4
"""

import argparse
from pathlib import Path

import numpy as np

from tabulasense import TableCleanEnv

# 右腕（スポンジ付き）を天板に下ろす関節角。順に Rotation, Pitch, Elbow, Wrist_Pitch, Wrist_Roll, Jaw
WIPE_POSE_R = np.array([0.0, 0.14, 1.096, -0.406, 0.0, 0.0])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--video", type=Path, default=None, help="mp4/gif で保存（imageio が必要）")
    args = parser.parse_args()

    env = TableCleanEnv(render_mode="rgb_array" if args.video else None)
    env.reset(seed=args.seed)

    # 汚れを一つ、スポンジの真下に置き直す
    stain = env._stain_geom[0]
    env.model.geom_size[stain, 0] = 0.06
    env.model.geom_pos[stain, :2] = np.array([-0.15, 0.55]) - np.array(env.cfg.table_center)

    target = np.r_[WIPE_POSE_R, np.zeros(6)]
    frames = []
    for k in range(200):
        action = np.zeros(15)
        if k < 60:  # 腕を下ろす
            action[3:] = np.clip((target - env._arm_target) / env.max_joint_delta, -1, 1)
        else:  # 台車を左右に振って拭く
            action[1] = 0.3 * np.sign(np.sin(k / 4))
        _, _, _, _, info = env.step(action)
        if args.video and k % 2 == 0:
            frames.append(env.render())
        if k % 40 == 0:
            print(k, info)
    print("final", info, "dirt per stain:", env.dirt.round(3))

    if args.video:
        import imageio.v3 as iio

        args.video.parent.mkdir(parents=True, exist_ok=True)
        iio.imwrite(args.video, frames, fps=10)
        print(f"saved {args.video}")
    env.close()


if __name__ == "__main__":
    main()
