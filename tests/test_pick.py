import numpy as np

from tabulasense import TableCleanEnv
from tabulasense.control.ik import ARM_JOINTS_L, ArmIK
from tabulasense.control.pick_place import pick_and_place, pick_scene_config


def test_ik_reaches_point_in_front_of_shoulder():
    env = TableCleanEnv()
    env.reset(seed=0)
    ik = ArmIK(env.model, ARM_JOINTS_L, "pinch_L")
    shoulder = env.data.body("Rotation_Pitch").xpos
    target = shoulder + np.array([0.0, 0.30, -0.05])
    q, err = ik.solve_best(env.data, target, finger_dir=np.array([0, 1.0, 0]), side_dir=np.array([1.0, 0, 0]))
    assert err < 0.006
    assert (q >= ik.range[:, 0]).all() and (q <= ik.range[:, 1]).all()
    env.close()


def test_pick_and_place_puts_glass_in_bin():
    env = TableCleanEnv(pick_scene_config())
    env.reset(seed=1)
    for action in pick_and_place(env, "obj0_glass"):
        env.step(action)
    for _ in range(20):
        env.step(np.zeros(15))
    assert env._get_info()["objects_in_bin"] == 1
    env.close()
