import json
import math
from pathlib import Path

import pytest

from taskwitness import judge, verify_episode
from taskwitness.config import ConfigError, config_digest, load_config, parse_config
from taskwitness.core import EpisodeError
from taskwitness.oracle import PlaceOracleConfig, verify_place

ROOT = Path(__file__).resolve().parent.parent / "examples"


def load(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def test_dispatch_by_task_type():
    assert verify_episode(load("synthetic/01_clean_success.json"))["oracle"] == "PlaceOracle"
    assert verify_episode(load("synthetic_button/b01_clean_press.json"))["oracle"] == "ButtonPressOracle"
    with pytest.raises(EpisodeError, match="unsupported task type"):
        verify_episode({"task": {"type": "pour"}})


def test_judge_wraps_bundle():
    result = judge(load("synthetic/02_not_released.json"))
    assert result.failed and not result.passed and not result.unknown
    assert result.bundle["verdict"] == "FAIL"


def test_judge_accepts_config_document():
    episode = load("synthetic/01_clean_success.json")
    assert judge(episode).passed
    # Demanding more settle samples than the 1 s window holds makes the evidence insufficient.
    assert judge(episode, {"place": {"min_settle_samples": 50}}).unknown


@pytest.mark.parametrize("value", [math.nan, math.inf])
def test_non_finite_sensor_values_rejected(value):
    episode = load("synthetic/01_clean_success.json")
    episode["sensors"]["load_cell"][-1]["grams"] = value
    with pytest.raises(EpisodeError, match="finite"):
        verify_place(episode)


def test_nan_parsed_from_json_rejected():
    text = (ROOT / "synthetic/01_clean_success.json").read_text(encoding="utf-8")
    episode = json.loads(text.replace('"grams": 52.', '"grams": NaN, "x": 52.', 1))
    with pytest.raises(EpisodeError):
        verify_place(episode)


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda e: e["sensors"]["load_cell"][0].pop("grams"), r"sensors\.load_cell\[0\]"),
        (lambda e: e["sensors"]["gripper"][2].update(state="half"), r"sensors\.gripper\[2\]\.state"),
        (lambda e: e["video"][1].update(confidence=1.5), r"video\[1\]\.confidence"),
        (lambda e: e["claim"].update(success="yes"), "claim.success"),
        (lambda e: e.update(sensors=[]), "sensors must be an object"),
        (lambda e: e.update(episode_id=""), "episode_id"),
    ],
)
def test_validation_messages_point_at_the_problem(mutate, message):
    episode = load("synthetic/01_clean_success.json")
    mutate(episode)
    with pytest.raises(EpisodeError, match=message):
        verify_place(episode)


def test_object_too_light_for_thresholds_is_unknown():
    episode = load("synthetic/01_clean_success.json")
    episode["task"]["object"]["mass_g"] = 4.0
    bundle = verify_place(episode)
    assert bundle["verdict"] == "UNKNOWN"
    assert bundle["oracles"][0]["state"] == "UNRESOLVABLE"


def test_config_parsing_and_digest(tmp_path):
    configs = parse_config({"place": {"settle_window_s": 2, "min_settle_samples": 8}})
    assert configs["place"] == PlaceOracleConfig(settle_window_s=2.0, min_settle_samples=8)
    assert config_digest(configs) != config_digest(parse_config({}))
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps({"button_press": {"min_hold_s": 0.1}}), encoding="utf-8")
    assert load_config(path)["button_press"].min_hold_s == 0.1


@pytest.mark.parametrize(
    "doc",
    [
        {"pour": {}},
        {"place": {"nope": 1}},
        {"place": {"settle_window_s": "1"}},
        {"place": {"settle_window_s": -1}},
        {"place": {"min_settle_samples": 2.5}},
        {"place": {"settle_window_s": True}},
        [],
    ],
)
def test_bad_configs_rejected(doc):
    with pytest.raises(ConfigError):
        parse_config(doc)
