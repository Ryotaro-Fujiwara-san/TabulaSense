"""TabulaSense: テーブルの片付けと拭き上げを行うロボットのシミュレーション環境。"""

import gymnasium as gym

from tabulasense.sim.env import TableCleanEnv
from tabulasense.sim.scene import SceneConfig, build_scene

__all__ = ["SceneConfig", "TableCleanEnv", "build_scene"]

gym.register(id="TabulaSense/TableClean-v0", entry_point="tabulasense.sim.env:TableCleanEnv")
