"""シミュレーションの真値から「片付ける物」と「拭く汚れ」のラベル画像を作る。

実機ではここを物体検出・セグメンテーションモデル（VLM など）に置き換える。
同じ出力形式にしておけば、学習データ作りと精度評価の両方に使える。
"""

from __future__ import annotations

from enum import IntEnum

import mujoco
import numpy as np

from tabulasense.sim.env import TableCleanEnv


class Label(IntEnum):
    BACKGROUND = 0
    OBJECT = 1  # アームで回収する物（食器など）
    STAIN = 2  # ワイパーで拭き取る汚れ
    TABLE = 3
    ROBOT = 4


def label_image(env: TableCleanEnv, camera: str = "head_cam") -> tuple[np.ndarray, np.ndarray]:
    """(RGB 画像, ラベル画像) を返す。ラベルは Label の値。

    ほぼ消えた汚れ（残り 5% 未満）は拭き取り済みとして TABLE 扱いにする。
    """
    m = env.model
    rgb = env.render_camera_image(camera)
    seg = env.render_camera_image(camera, segmentation=True)
    obj_id, obj_type = seg[..., 0], seg[..., 1]

    lut = np.full(m.ngeom + 1, Label.BACKGROUND, dtype=np.uint8)
    lut[env.model.geom(env.handles.table_geom).id] = Label.TABLE
    for name in env.handles.object_geoms:
        lut[m.geom(name).id] = Label.OBJECT
    for j, name in enumerate(env.handles.stain_geoms):
        lut[m.geom(name).id] = Label.STAIN if env.dirt[j] >= 0.05 else Label.TABLE
    robot_root = m.body("chassis").id
    robot_geoms = np.flatnonzero(m.body_rootid[m.geom_bodyid] == robot_root)
    lut[robot_geoms] = Label.ROBOT

    is_geom = (obj_type == mujoco.mjtObj.mjOBJ_GEOM) & (obj_id >= 0)
    labels = np.where(is_geom, lut[np.clip(obj_id, 0, m.ngeom)], Label.BACKGROUND).astype(np.uint8)
    return rgb, labels


def colorize(labels: np.ndarray) -> np.ndarray:
    """ラベル画像を見やすい色にする（保存・確認用）。"""
    palette = np.array(
        [[0, 0, 0], [230, 80, 60], [120, 70, 20], [210, 190, 150], [70, 110, 200]], dtype=np.uint8
    )
    return palette[labels]
