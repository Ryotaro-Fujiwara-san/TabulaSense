"""XLeRobot の MuJoCo モデル（simulation/mujoco）だけを sparse checkout で取得する。

Windows / macOS / Linux 共通。git が必要。

    python scripts/fetch_xlerobot.py

再現性のためコミットを固定している。更新するときは XLEROBOT_REF を書き換える。
"""

import os
import subprocess
from pathlib import Path

XLEROBOT_REPO = os.environ.get("XLEROBOT_REPO", "https://github.com/Vector-Wangel/XLeRobot.git")
XLEROBOT_REF = os.environ.get("XLEROBOT_REF", "749abc837d5d771f26aeff961009c290e574b024")

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "third_party" / "XLeRobot"


def git(*args: str) -> None:
    subprocess.run(["git", *args], check=True)


def main() -> None:
    if not (DEST / ".git").exists():
        git("clone", "--filter=blob:none", "--no-checkout", XLEROBOT_REPO, str(DEST))
        git("-C", str(DEST), "sparse-checkout", "set", "simulation/mujoco")
    git("-C", str(DEST), "fetch", "--depth", "1", "origin", XLEROBOT_REF)
    git("-C", str(DEST), "checkout", "--quiet", "FETCH_HEAD")
    print(f"XLeRobot MuJoCo model: {DEST / 'simulation' / 'mujoco' / 'xlerobot.xml'}")


if __name__ == "__main__":
    main()
