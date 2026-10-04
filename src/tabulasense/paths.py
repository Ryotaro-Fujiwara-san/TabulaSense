"""外部アセットの場所をまとめる。"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def xlerobot_xml() -> Path:
    """XLeRobot の MJCF のパス。環境変数 TABULASENSE_XLEROBOT_DIR で上書きできる。"""
    default = PROJECT_ROOT / "third_party" / "XLeRobot" / "simulation" / "mujoco"
    path = Path(os.environ.get("TABULASENSE_XLEROBOT_DIR", default)) / "xlerobot.xml"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} がありません。先に `python scripts/fetch_xlerobot.py` を実行してください。"
        )
    return path
