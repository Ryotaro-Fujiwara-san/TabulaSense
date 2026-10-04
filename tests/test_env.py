import gymnasium as gym
import numpy as np
from conftest import requires_render

from tabulasense import TableCleanEnv
from tabulasense.perception.oracle import Label, label_image


def test_scene_compiles_with_expected_parts():
    env = TableCleanEnv()
    m = env.model
    for name in ("head_cam", "top_cam", "overview_cam"):
        assert m.camera(name).id >= 0
    assert m.nu == 18 + 2  # XLeRobot 18 + 頭 2
    env.close()


def test_reset_places_everything_on_table():
    env = TableCleanEnv()
    obs, info = env.reset(seed=0)
    assert env.observation_space.contains(obs)
    assert info["objects_on_table"] == len(env.cfg.object_types)
    assert info["dirt_remaining"] == env.cfg.n_stains
    env.close()


def test_reset_is_reproducible():
    env = TableCleanEnv()
    a, _ = env.reset(seed=123)
    b, _ = env.reset(seed=123)
    np.testing.assert_allclose(a["objects"], b["objects"])
    np.testing.assert_allclose(a["stains"], b["stains"])
    env.close()


def test_random_actions_run():
    env = gym.make("TabulaSense/TableClean-v0", max_episode_steps=20)
    env.reset(seed=0)
    for _ in range(20):
        obs, reward, terminated, truncated, info = env.step(env.action_space.sample())
        assert np.isfinite(reward)
        assert np.isfinite(obs["robot"]).all()
    assert truncated
    env.close()


def test_base_moves_in_robot_frame():
    env = TableCleanEnv()
    env.reset(seed=0)
    start = env._base_pose()
    action = np.zeros(15)
    action[0] = 1.0  # 前進
    for _ in range(10):
        env.step(action)
    end = env._base_pose()
    heading = np.array([np.cos(start[2]), np.sin(start[2])])
    assert (end[:2] - start[:2]) @ heading > 0.1
    env.close()


def test_wiping_removes_stain():
    env = TableCleanEnv()
    env.reset(seed=0)
    stain = env._stain_geom[0]
    env.model.geom_size[stain, 0] = 0.06
    env.model.geom_pos[stain, :2] = np.array([-0.15, 0.55]) - np.array(env.cfg.table_center)
    for other in env._stain_geom[1:]:  # ほかの汚れはスポンジの届かない奥に置く
        env.model.geom_pos[other, :2] = np.array([0.3, 0.9]) - np.array(env.cfg.table_center)
    target = np.r_[[0.0, 0.14, 1.096, -0.406, 0.0, 0.0], np.zeros(6)]
    for k in range(180):
        action = np.zeros(15)
        if k < 60:
            action[3:] = np.clip((target - env._arm_target) / env.max_joint_delta, -1, 1)
        else:
            action[1] = 0.3 * np.sign(np.sin(k / 4))
        env.step(action)
    assert env.dirt[0] < 0.1
    np.testing.assert_allclose(env.dirt[1:], 1.0)  # 触れていない汚れはそのまま
    env.close()


@requires_render
def test_oracle_labels_see_objects_and_stains():
    env = TableCleanEnv(render_size=(240, 320))
    env.reset(seed=0)
    rgb, labels = label_image(env, "top_cam")
    assert rgb.shape == (240, 320, 3)
    assert labels.shape == (240, 320)
    for label in (Label.OBJECT, Label.STAIN, Label.TABLE):
        assert (labels == label).any(), label
    env.close()
