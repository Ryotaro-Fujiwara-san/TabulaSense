"""シーンを各カメラから描画して PNG に保存する（環境構築の動作確認用）。

    MUJOCO_GL=egl python scripts/render_scene.py --seed 0 --out outputs/scene
"""

import argparse
from pathlib import Path

from PIL import Image

from tabulasense import TableCleanEnv
from tabulasense.perception.oracle import colorize, label_image


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, default=Path("outputs/scene"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    env = TableCleanEnv(render_mode="rgb_array")
    _, info = env.reset(seed=args.seed)
    print(info)
    for cam in ("overview_cam", "top_cam", "head_cam"):
        Image.fromarray(env.render_camera_image(cam)).save(args.out / f"{cam}.png")
    _, labels = label_image(env, "head_cam")
    Image.fromarray(colorize(labels)).save(args.out / "head_cam_labels.png")
    env.close()
    print(f"saved to {args.out}/")


if __name__ == "__main__":
    main()
