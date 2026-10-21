"""TaskWitness inside a real Inspect Robots evaluation loop (inspect-robots 0.60)."""

import pytest

inspect_robots = pytest.importorskip("inspect_robots")
np = pytest.importorskip("numpy")

from inspect_robots.mock.cubepick import CubePickEmbodiment  # noqa: E402
from inspect_robots.mock.policies import ScriptedPolicy  # noqa: E402
from inspect_robots.rollout import StepRecord, TrialRecord  # noqa: E402
from inspect_robots.scene import Scene, Target  # noqa: E402
from inspect_robots.task import Task  # noqa: E402
from inspect_robots.types import Action, Observation, StepResult  # noqa: E402

from taskwitness.core import EpisodeError  # noqa: E402
from taskwitness.integrations.inspect_robots import episode_from_trial, taskwitness_scorer  # noqa: E402

PLACE_SPEC = {
    "object": {"name": "cube", "mass_g": 52.0},
    "target_zone": {"x_min": 0.0, "x_max": 1.0, "y_min": 0.0, "y_max": 1.0},
}
TARGET = Target(kind="taskwitness.place", spec=PLACE_SPEC)


class PlaceRig(CubePickEmbodiment):
    """CubePick plus a load cell and gripper, as a physical rig would report them.

    The policy "succeeds" when the effector reaches the cube and dwells there for
    12 steps. In scenes with metadata drop=True the cube never lands on the
    plate, so the load cell stays empty although the episode ends in "success".
    """

    DWELL = 12

    def reset(self, scene, *, seed=None):
        self._drop = bool(scene.metadata.get("drop"))
        self._dwell = 0
        obs = super().reset(scene, seed=seed)
        return self._with_sensors(obs)

    def step(self, action):
        result = super().step(action)
        if result.terminated:
            self._dwell += 1
        terminated = self._dwell >= self.DWELL
        return StepResult(
            observation=self._with_sensors(result.observation),
            reward=result.reward,
            terminated=terminated,
            termination_reason="success" if terminated else None,
            truncated=False,
            info=result.info,
        )

    def _with_sensors(self, obs):
        loaded = self._dwell > 0 and not self._drop
        noise = 0.1 * np.sin(self.num_steps)
        state = dict(obs.state, load_cell_g=np.array([52.0 + noise if loaded else 0.05 + noise]),
                     gripper=np.array([1.0 if self._dwell > 0 else 0.0]))
        return Observation(images=obs.images, state=state, instruction=obs.instruction,
                           state_time=self.num_steps / 10.0)


def test_scorers_are_registered_through_entry_points():
    from inspect_robots.registry import registered, resolve

    assert {"taskwitness", "taskwitness_unknown"} <= set(registered("scorer"))
    assert resolve("scorer", "taskwitness").name == "taskwitness"


def test_full_eval_separates_claimed_from_physical_success(tmp_path):
    from inspect_robots import eval as run_eval

    task = Task(
        name="place_cube",
        scenes=[
            Scene(id="placed", instruction="put the cube on the plate", target=TARGET),
            Scene(id="dropped", instruction="put the cube on the plate", target=TARGET, metadata={"drop": True}),
        ],
        scorer=["success_at_end", "taskwitness", "taskwitness_unknown"],
        max_steps=60,
    )
    [log] = run_eval(task, ScriptedPolicy(), PlaceRig(), log_dir=str(tmp_path))
    assert log.status == "success", log.error
    metrics = log.results.metrics
    assert metrics["success_at_end"] == 1.0  # the robot claims success in both scenes
    assert metrics["taskwitness"] == 0.5  # physical evidence confirms only one
    assert metrics["taskwitness_unknown"] == 0.0
    by_scene = {s.scene_id: s.reduced for s in log.samples}
    assert by_scene["placed"]["taskwitness"] == 1.0 and by_scene["dropped"]["taskwitness"] == 0.0


def _record(states, times, termination="success"):
    obs = [Observation(state=s, state_time=t) for s, t in zip(states, times)]
    steps = [
        StepRecord(t=i, observation=obs[i], action=Action(data=np.zeros(2)),
                   result=StepResult(observation=obs[i + 1], terminated=i == len(obs) - 2,
                                     termination_reason=termination if i == len(obs) - 2 else None))
        for i in range(len(obs) - 1)
    ]
    return TrialRecord(scene_id="s", epoch=0, seed=1, steps=steps, terminated=True, termination_reason=termination)


def test_episode_from_trial_maps_state_and_claim():
    # An empty plate at the start, the object placed and released halfway through.
    states = [{"load_cell_g": np.array([0.0 if i < 5 else 52.0]), "gripper": np.array([0.0 if i < 5 else 0.9])} for i in range(30)]
    record = _record(states, [i / 10 for i in range(30)])
    episode = episode_from_trial(record, TARGET)
    assert episode["claim"] == {"source": "termination_reason", "success": True}
    assert episode["sensors"]["gripper"][0]["state"] == "closed"
    assert episode["sensors"]["gripper"][-1]["state"] == "open"
    score = taskwitness_scorer()(record, TARGET)
    assert score.value is True and score.metadata["verdict"] == "PASS"


def test_missing_clock_needs_dt():
    states = [{"button_pressed": np.array([1.0 if 3 <= i < 6 else 0.0])} for i in range(10)]
    record = _record(states, [0.0] * 10)
    target = Target(kind="taskwitness.button_press", spec={"button": {"expected_presses": 1}})
    with pytest.raises(EpisodeError, match="state_time"):
        episode_from_trial(record, target)
    score = taskwitness_scorer(dt_s=0.1)(record, target)
    assert score.metadata["verdict"] == "PASS"


def test_unknown_scorer_and_missing_spec():
    record = _record([{"load_cell_g": np.array([52.0])} for _ in range(3)], [0.0, 0.1, 0.2])
    from taskwitness.integrations.inspect_robots import taskwitness_unknown_scorer

    score = taskwitness_unknown_scorer()(record, TARGET)  # too few settle samples -> UNKNOWN
    assert score.value is True and score.metadata["verdict"] == "UNKNOWN"
    with pytest.raises(EpisodeError, match="no TaskWitness task spec"):
        taskwitness_scorer()(record, Target(kind="reach_object"))
