import collections
import copy
import json

import pytest

from taskwitness import verify_episode
from taskwitness.cli import main
from taskwitness.core import EpisodeError
from taskwitness.evaluate import Row, judge_metrics
from taskwitness.grasp import GraspConfig, verify_grasp
from taskwitness.simulation import (
    BUTTON_MIX,
    PLACE_MIX,
    SimulationError,
    preset,
    simulate_dataset,
    simulate_load_recording,
)


# ----------------------------------------------------------------------------- GraspOracle


def grasp_episode(widths, low=0.004, high=0.008, hz=30):
    return {
        "schema": "taskwitness.episode/v0",
        "episode_id": "g",
        "task": {"type": "grasp", "object": {"name": "peg", "width_m_min": low, "width_m_max": high}},
        "sensors": {"gripper_width": [{"t": i / hz, "width_m": w} for i, w in enumerate(widths)]},
        "claim": {"source": "policy", "success": True},
        "label": {"verdict": "FAIL"},
    }


@pytest.mark.parametrize(
    "widths, verdict, state",
    [
        ([0.04] * 30 + [0.006] * 30, "PASS", "HOLDING"),
        ([0.04] * 30 + [0.0003] * 30, "FAIL", "TOO_CLOSED"),
        ([0.04] * 60, "FAIL", "TOO_OPEN"),
        ([0.04] * 30 + [0.0035] * 30, "UNKNOWN", "NEAR_BAND"),
        ([0.04] * 30 + [0.0085] * 30, "UNKNOWN", "NEAR_BAND"),
        ([0.04] * 30 + [0.006 + 0.002 * (i % 2) for i in range(30)], "UNKNOWN", "MOVING"),
        ([0.006] * 3, "UNKNOWN", "NO_DATA"),
    ],
)
def test_grasp_oracle_states(widths, verdict, state):
    bundle = verify_grasp(grasp_episode(widths))
    assert (bundle["verdict"], bundle["oracles"][0]["state"]) == (verdict, state)


def test_grasp_ignores_claim_and_label_and_is_dispatched():
    episode = grasp_episode([0.04] * 30 + [0.006] * 30)
    flipped = copy.deepcopy(episode)
    flipped["claim"]["success"] = False
    flipped["label"]["verdict"] = "PASS"
    a, b = verify_grasp(episode), verify_grasp(flipped)
    assert (a["verdict"], a["reasons"], a["oracles"]) == (b["verdict"], b["reasons"], b["oracles"])  # claim and label never decide
    assert verify_episode(episode) == a
    assert verify_grasp(episode)["claim"]["contradicted"] is False
    assert verify_grasp(grasp_episode([0.04] * 60))["claim"]["contradicted"] is True


def test_grasp_config_and_validation():
    narrow = grasp_episode([0.04] * 30 + [0.0075] * 30)
    assert verify_grasp(narrow)["verdict"] == "PASS"
    assert verify_grasp(narrow, GraspConfig())["verdict"] == "PASS"
    with pytest.raises(EpisodeError):
        verify_grasp(grasp_episode([0.006] * 20, low=0.01, high=0.005))
    bad = grasp_episode([0.006] * 20)
    bad["sensors"]["gripper_width"][3]["width_m"] = -0.001
    with pytest.raises(EpisodeError, match="gripper_width"):
        verify_grasp(bad)


# ----------------------------------------------------------------------------- simulation


@pytest.mark.parametrize("kind", ["place", "button_press"])
def test_simulation_is_deterministic_and_labelled_from_the_latent_story(kind):
    a = simulate_dataset(kind, 60, 7)
    assert a == simulate_dataset(kind, 60, 7)
    assert a != simulate_dataset(kind, 60, 8)
    for ep in a:
        mode = ep["tags"]["failure_mode"]
        assert ep["label"]["note"] == f"latent story: {mode}"
        assert ep["label"]["verdict"] in ("PASS", "FAIL")  # real labels are binary; UNKNOWN is the verifier's, not the truth's
        assert ep["synthetic"] is True
        verify_episode(ep)  # every generated episode is valid input


def test_simulation_covers_every_mode_in_the_mix():
    for kind, mix in (("place", PLACE_MIX), ("button_press", BUTTON_MIX)):
        seen = collections.Counter(ep["tags"]["failure_mode"] for ep in simulate_dataset(kind, 1500, 3))
        assert set(seen) == set(mix)


def test_simulation_rejects_bad_settings():
    with pytest.raises(SimulationError):
        preset("space")
    with pytest.raises(SimulationError):
        preset("lab", load_nose_g=1.0)
    with pytest.raises(SimulationError):
        simulate_dataset("pour", 3)
    with pytest.raises(SimulationError):
        simulate_dataset("place", 3, mix={"success": -1})


def evaluate(kind, name, n=700, seed=2, **overrides):
    rows = []
    for ep in simulate_dataset(kind, n, seed, preset(name, **overrides)):
        bundle = verify_episode(ep)
        rows.append(Row(ep["episode_id"], ep["label"]["verdict"], {"tw": bundle["verdict"], "vision": bundle["comparison"]["vision_only_verdict"]}, ep["tags"]["failure_mode"]))
    return rows


@pytest.mark.parametrize("kind", ["place", "button_press"])
def test_physical_evidence_beats_position_only_vision_on_simulated_rigs(kind):
    rows = evaluate(kind, "lab")
    tw, vision = judge_metrics(rows, "tw"), judge_metrics(rows, "vision")
    assert tw["conditional_miss"]["rate"] < 0.10
    assert vision["conditional_miss"]["rate"] > 0.35
    assert tw["false_fail"]["rate"] < 0.02  # it abstains rather than wrongly failing real successes


def test_oracle_abstains_instead_of_guessing_when_the_sensor_is_unusable():
    rows = evaluate("place", "wrist_ft", n=300)
    assert all(r.verdicts["tw"] == "UNKNOWN" for r in rows)  # zero-offset >> block weight: no verdict is defensible


def test_simulated_failures_that_fool_both_channels_are_not_hidden():
    """A foreign object on the plate with a frozen tracker is a false pass; the study must be able to show it."""
    rows = evaluate("place", "lab", n=1500)
    foreign = [r for r in rows if r.stratum == "foreign_object"]
    assert foreign and any(r.verdicts["tw"] == "PASS" for r in foreign)
    leftover = [r for r in rows if r.stratum == "leftover_object"]
    assert leftover and all(r.verdicts["tw"] == "UNKNOWN" for r in leftover)  # the plate-empty-at-start check catches these


def test_slow_switch_sampling_leaves_brushes_unknown_rather_than_pass():
    rows = evaluate("button_press", "lab", n=1000, switch_hz=20.0)
    brushes = [r for r in rows if r.stratum == "light_brush"]
    assert brushes and not any(r.verdicts["tw"] == "PASS" for r in brushes)


def test_simulated_load_recording_feeds_threshold_calibration():
    cfg = preset("lab", load_noise_g=1.0)
    samples = simulate_load_recording(cfg, 0.0, 30, seed=1)
    assert 500 < len(samples) <= 601
    assert abs(sum(g for _, g in samples) / len(samples)) < 1.0


def test_cli_simulate_then_evaluate(tmp_path):
    out = tmp_path / "sim"
    assert main(["simulate", "place", "--n", "120", "--seed", "4", "--preset", "lab", "--set", "load_noise_g=1.0", "--out", str(out)]) == 0
    files = sorted(out.glob("*.json"))
    assert len(files) == 120
    assert json.loads(files[0].read_text())["tags"]["rig"] == "lab"
    report = tmp_path / "eval.json"
    assert main(["evaluate", str(out), "--by", "failure_mode", "--order-by", "trial", "--out", str(report)]) == 0
    doc = json.loads(report.read_text())
    assert doc["all_synthetic"] and "by_stratum" in doc
    assert main(["simulate", "place", "--n", "5", "--set", "bogus=1", "--out", str(tmp_path / "x")]) == 3
    assert main(["simulate", "place", "--n", "5", "--set", "load_noise_g=abc", "--out", str(tmp_path / "x")]) == 3
