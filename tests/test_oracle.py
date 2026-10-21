import copy
import json
from pathlib import Path

import pytest

from taskwitness.cli import main
from taskwitness.oracle import EpisodeError, verify_bundle_integrity, verify_place

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "synthetic"
EPISODE_FILES = sorted(EXAMPLES.glob("*.json"))


def load(name):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def test_examples_present():
    assert len(EPISODE_FILES) == 5


@pytest.mark.parametrize("path", EPISODE_FILES, ids=lambda p: p.stem)
def test_synthetic_episode_matches_label(path):
    episode = json.loads(path.read_text(encoding="utf-8"))
    bundle = verify_place(episode)
    assert bundle["verdict"] == episode["label"]["verdict"], bundle["reasons"]


def test_label_does_not_influence_verdict():
    episode = load("02_not_released.json")
    flipped = copy.deepcopy(episode)
    flipped["label"]["verdict"] = "PASS"
    assert verify_place(episode) == verify_place(flipped)


def test_robot_claim_does_not_influence_verdict():
    episode = load("03_bounced_off.json")
    honest = copy.deepcopy(episode)
    honest["claim"]["success"] = False
    assert verify_place(episode)["verdict"] == verify_place(honest)["verdict"] == "FAIL"
    assert verify_place(episode)["claim"]["contradicted"] is True
    assert verify_place(honest)["claim"]["contradicted"] is False


def test_vision_only_false_pass_is_reported():
    bundle = verify_place(load("02_not_released.json"))
    assert bundle["verdict"] == "FAIL"
    assert bundle["comparison"]["vision_only_verdict"] == "PASS"


def test_bundle_is_deterministic_and_tamper_evident():
    episode = load("01_clean_success.json")
    bundle = verify_place(episode)
    assert verify_place(episode) == bundle
    assert verify_bundle_integrity(bundle, episode)

    edited = copy.deepcopy(bundle)
    edited["verdict"] = "FAIL"
    assert not verify_bundle_integrity(edited)

    other = load("03_bounced_off.json")
    assert not verify_bundle_integrity(bundle, other)


def test_gripper_closed_with_full_load_is_unknown():
    episode = load("01_clean_success.json")
    for s in episode["sensors"]["gripper"]:
        s["state"] = "closed"
    assert verify_place(episode)["verdict"] == "UNKNOWN"


def test_unsettled_load_is_unknown():
    episode = load("01_clean_success.json")
    for i, s in enumerate(episode["sensors"]["load_cell"]):
        if s["t"] >= 3.0:
            s["grams"] = 52.0 + (8.0 if i % 2 else -8.0)
    bundle = verify_place(episode)
    assert bundle["verdict"] == "UNKNOWN"
    assert bundle["oracles"][0]["state"] == "UNSTABLE"


def test_overload_is_unknown():
    episode = load("01_clean_success.json")
    for s in episode["sensors"]["load_cell"]:
        s["grams"] += 100.0
    assert verify_place(episode)["verdict"] == "UNKNOWN"


def test_no_video_still_passes_on_physical_evidence():
    episode = load("01_clean_success.json")
    episode["video"] = []
    bundle = verify_place(episode)
    assert bundle["verdict"] == "PASS"
    assert bundle["comparison"]["vision_only_verdict"] == "UNKNOWN"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda e: e.update(schema="other/v1"),
        lambda e: e["task"].update(type="press"),
        lambda e: e["task"]["object"].update(mass_g=0),
        lambda e: e["task"]["target_zone"].update(x_min=1.0),
        lambda e: e.pop("episode_id"),
    ],
)
def test_malformed_episode_rejected(mutate):
    episode = load("01_clean_success.json")
    mutate(episode)
    with pytest.raises(EpisodeError):
        verify_place(episode)


def test_cli_batch(tmp_path):
    out = tmp_path / "report.json"
    assert main(["batch", str(EXAMPLES), "--out", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["verdicts"] == {"PASS": 1, "FAIL": 2, "UNKNOWN": 2}
    assert report["label_mismatches"] == 0
    assert report["vision_only_false_pass"] == 2


def test_cli_verify_exit_codes_and_check(tmp_path):
    expected = {"01_clean_success": 0, "02_not_released": 1, "04_sensor_dropout": 2}
    for stem, code in expected.items():
        out = tmp_path / f"{stem}.bundle.json"
        episode = EXAMPLES / f"{stem}.json"
        assert main(["verify", str(episode), "--out", str(out)]) == code
        assert main(["check", str(out), "--episode", str(episode)]) == 0


def test_cli_reports_bad_input(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"schema": "nope"}', encoding="utf-8")
    assert main(["verify", str(bad)]) == 3
