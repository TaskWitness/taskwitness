"""TaskWitness scorers for Inspect Robots (https://github.com/robocurve/inspect-robots).

Built against inspect-robots 0.60's `Scorer` protocol. Installing TaskWitness
registers two scorers through the `inspect_robots.scorers` entry-point group:

* `taskwitness`          value 1.0 iff the physical verdict is PASS
* `taskwitness_unknown`  value 1.0 iff the verdict is UNKNOWN

Inspect Robots aggregates scores as a mean, so UNKNOWN cannot hide inside the
pass rate: run both scorers and report the unknown rate next to the pass rate.
The full verdict, reasons and bundle digests are kept in `Score.metadata`.

Where the evidence comes from
    The embodiment exposes sensor readings in `Observation.state`, stamped with
    `Observation.state_time` (seconds). By default the scorer reads
    `load_cell_g`, `gripper` (opening; > `gripper_open_above` means open) and
    `button_pressed` (> 0.5 means pressed). The task spec comes from the scene
    target (`Target(kind="taskwitness.place", spec={...})`), from
    `record.metadata["taskwitness_task"]`, or from the `task` argument.

Like Inspect Robots' own scorers, these only read the recorded trial, so
scoring is reproducible from a saved record.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from taskwitness.api import verify_episode
from taskwitness.config import parse_config
from taskwitness.core import EPISODE_SCHEMA, PASS, UNKNOWN, EpisodeError

TARGET_KINDS = {"taskwitness.place": "place", "taskwitness.button_press": "button_press"}


def _scalar(value: Any) -> float:
    import numpy as np

    flat = np.asarray(value, dtype=float).reshape(-1)
    if flat.size == 0:
        raise EpisodeError("empty state value")
    return float(flat[0])


def _task_spec(record: Any, target: Any, task: dict[str, Any] | None) -> dict[str, Any]:
    if task is not None:
        spec = dict(task)
    elif target is not None and getattr(target, "kind", None) in TARGET_KINDS:
        spec = dict(target.spec, type=TARGET_KINDS[target.kind])
    elif isinstance(getattr(record, "metadata", None), dict) and "taskwitness_task" in record.metadata:
        spec = dict(record.metadata["taskwitness_task"])
    else:
        raise EpisodeError(
            "no TaskWitness task spec: use Target(kind='taskwitness.place' or 'taskwitness.button_press'), "
            "record.metadata['taskwitness_task'], or the scorer's task argument"
        )
    if spec.get("type") not in TARGET_KINDS.values():
        raise EpisodeError(f"task spec needs type 'place' or 'button_press', got {spec.get('type')!r}")
    return spec


def episode_from_trial(
    record: Any,
    target: Any = None,
    task: dict[str, Any] | None = None,
    load_cell_key: str = "load_cell_g",
    gripper_key: str = "gripper",
    gripper_open_above: float = 0.5,
    button_key: str = "button_pressed",
    dt_s: float | None = None,
) -> dict[str, Any]:
    """Build a `taskwitness.episode/v0` document from an Inspect Robots TrialRecord."""
    spec = _task_spec(record, target, task)
    steps = list(record.steps)
    observations = ([steps[0].observation] if steps else []) + [s.result.observation for s in steps]
    if not observations:
        raise EpisodeError("trial has no observations")
    times = [float(o.state_time) for o in observations]
    if len(set(times)) < len(times) or any(b < a for a, b in zip(times, times[1:])):
        if dt_s is None:
            raise EpisodeError("observations lack increasing state_time; set it in the embodiment or pass dt_s")
        times = [i * dt_s for i in range(len(observations))]

    sensors: dict[str, list[dict[str, Any]]] = {"load_cell": [], "gripper": [], "button": []}
    for t, obs in zip(times, observations):
        state = obs.state
        if load_cell_key in state:
            sensors["load_cell"].append({"t": t, "grams": _scalar(state[load_cell_key])})
        if gripper_key in state:
            sensors["gripper"].append({"t": t, "state": "open" if _scalar(state[gripper_key]) > gripper_open_above else "closed"})
        if button_key in state:
            sensors["button"].append({"t": t, "pressed": _scalar(state[button_key]) > 0.5})

    claim = None
    if record.termination_reason == "success":
        claim = True
    elif record.terminated or record.truncated:
        claim = False
    episode: dict[str, Any] = {
        "schema": EPISODE_SCHEMA,
        "episode_id": f"{record.scene_id}-e{record.epoch}",
        "task": spec,
        "sensors": {k: v for k, v in sensors.items() if v},
        "provenance": {"source": "inspect_robots", "scene_id": record.scene_id, "epoch": record.epoch, "seed": record.seed},
    }
    if claim is not None:
        episode["claim"] = {"source": "termination_reason", "success": claim}
    return episode


@dataclass(frozen=True)
class TaskWitnessScorer:
    name: str = "taskwitness"
    count: str = PASS  # which verdict scores 1.0
    options: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] | None = None

    def __call__(self, record: Any, target: Any) -> Any:
        from inspect_robots.scorer import Score

        bundle = verify_episode(episode_from_trial(record, target, **self.options), parse_config(self.config or {}))
        return Score(
            value=bundle["verdict"] == self.count,
            explanation=f"{bundle['verdict']}: {bundle['reasons'][0]}",
            metadata={
                "verdict": bundle["verdict"],
                "reasons": bundle["reasons"],
                "oracle": bundle["oracle"],
                "claim_contradicted": bundle["claim"]["contradicted"],
                "evidence_sha256": bundle["integrity"]["evidence_sha256"],
                "bundle_sha256": bundle["integrity"]["bundle_sha256"],
            },
        )


def taskwitness_scorer(config: dict[str, Any] | None = None, **options: Any) -> TaskWitnessScorer:
    """Score 1.0 iff TaskWitness's physical verdict is PASS. Options go to `episode_from_trial`."""
    return TaskWitnessScorer("taskwitness", PASS, options, config)


def taskwitness_unknown_scorer(config: dict[str, Any] | None = None, **options: Any) -> TaskWitnessScorer:
    """Score 1.0 iff the verdict is UNKNOWN, so the unknown rate is reported next to the pass rate."""
    return TaskWitnessScorer("taskwitness_unknown", UNKNOWN, options, config)
