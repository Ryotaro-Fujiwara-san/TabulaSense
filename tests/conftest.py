import os

import mujoco
import pytest

os.environ.setdefault("MUJOCO_GL", "egl")


def _can_render() -> bool:
    try:
        model = mujoco.MjModel.from_xml_string("<mujoco><worldbody/></mujoco>")
        mujoco.Renderer(model, 8, 8).close()
        return True
    except Exception:
        return False


requires_render = pytest.mark.skipif(not _can_render(), reason="オフスクリーン描画（EGL/OSMesa）が使えない")


def pytest_collection_modifyitems(config, items):
    from tabulasense import paths

    try:
        paths.xlerobot_xml()
    except FileNotFoundError:
        skip = pytest.mark.skip(reason="XLeRobot 未取得。python scripts/fetch_xlerobot.py を実行")
        for item in items:
            item.add_marker(skip)
