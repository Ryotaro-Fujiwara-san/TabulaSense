"""細いコップ（glass）をつかんでビンに入れる手書きデモ。

    python scripts/demo_pick.py --seed 0
    python scripts/demo_pick.py --seeds 0-9                    # 成功率を測る
    python scripts/demo_pick.py --video outputs/demo_pick.mp4  # 動画で保存（imageio が必要）
"""

import argparse
from pathlib import Path

import numpy as np

from tabulasense import TableCleanEnv
from tabulasense.control.pick_place import PickFailed, pick_and_place, pick_scene_config


def run(seed: int, video: Path | None = None) -> str:
    env = TableCleanEnv(pick_scene_config(), render_mode="rgb_array" if video else None)
    env.reset(seed=seed)
    target = env.handles.object_bodies[0]  # obj0_glass
    frames = []
    try:
        for k, action in enumerate(pick_and_place(env, target)):
            env.step(action)
            if video and k % 2 == 0:
                frames.append(env.render())
        for _ in range(20):  # ビンの中で落ち着くのを待つ
            env.step(np.zeros(15))
        on_table, in_bin, dropped = env._object_status()[0]
        result = "成功（ビンに入った）" if in_bin else ("失敗（落とした）" if dropped else "失敗")
    except PickFailed as e:
        result = f"失敗（{e}）"
    if video:
        import imageio.v3 as iio

        video.parent.mkdir(parents=True, exist_ok=True)
        iio.imwrite(video, frames, fps=10)
        print(f"saved {video}")
    env.close()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--seeds", type=str, default=None, help="例: 0-9（範囲の乱数シードで繰り返して成功率を出す）")
    parser.add_argument("--video", type=Path, default=None)
    args = parser.parse_args()

    if args.seeds:
        lo, hi = (int(x) for x in args.seeds.split("-"))
        results = [run(s) for s in range(lo, hi + 1)]
        for s, r in zip(range(lo, hi + 1), results):
            print(f"seed {s}: {r}")
        ok = sum(r.startswith("成功") for r in results)
        print(f"成功率: {ok}/{len(results)}")
    else:
        print(f"seed {args.seed}: {run(args.seed, args.video)}")


if __name__ == "__main__":
    main()
