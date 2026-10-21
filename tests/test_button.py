import copy
import json
from pathlib import Path

import pytest

from taskwitness.button import ButtonPressConfig, verify_button_press
from taskwitness.core import EpisodeError

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "synthetic_button"
EPISODE_FILES = sorted(EXAMPLES.glob("*.json"))


def load(name):
    return json.loads((EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))


def switch_samples(contacts, end=3.0, dt=0.01):
    n = int(round(end / dt))
    out = []
    for i in range(n + 1):
        t = round(i * dt, 3)
        out.append({"t": t, "pressed": any(a <= t and (b is None or t < b) for a, b in contacts)})
    return out


def with_switch(contacts, **task_button):
    episode = load("b01_clean_press")
    episode["sensors"]["button"] = switch_samples(contacts)
    episode["task"]["button"].update(task_button)
    return episode


def test_examples_present():
    assert len(EPISODE_FILES) == 6


@pytest.mark.parametrize("path", EPISODE_FILES, ids=lambda p: p.stem)
def test_synthetic_episode_matches_label(path):
    episode = json.loads(path.read_text(encoding="utf-8"))
    bundle = verify_button_press(episode)
    assert bundle["verdict"] == episode["label"]["verdict"], bundle["reasons"]


def test_hover_is_a_vision_false_pass():
    bundle = verify_button_press(load("b02_hover_no_contact"))
    assert (bundle["verdict"], bundle["comparison"]["vision_only_verdict"]) == ("FAIL", "PASS")
    assert any("hover" in r for r in bundle["reasons"])


def test_bounce_on_make_counts_as_one_press():
    bundle = verify_button_press(load("b01_clean_press"))
    switch = bundle["oracles"][0]["measurements"]
    assert switch["valid_presses"] == 1
    assert switch["presses"][0]["start_s"] == 1.5


def test_isolated_bounce_is_ignored():
    bundle = verify_button_press(with_switch([(1.0, 1.01)]))
    assert bundle["verdict"] == "FAIL"
    assert bundle["oracles"][0]["measurements"]["bounces_ignored"] == 1


def test_two_presses_needed():
    assert verify_button_press(with_switch([(1.0, 1.2)], expected_presses=2))["verdict"] == "FAIL"
    assert verify_button_press(with_switch([(1.0, 1.2), (1.6, 1.8)], expected_presses=2))["verdict"] == "PASS"


def test_too_many_presses():
    bundle = verify_button_press(with_switch([(1.0, 1.2), (1.6, 1.8)], max_presses=1))
    assert bundle["verdict"] == "FAIL"
    assert bundle["oracles"][0]["state"] == "TOO_MANY"


def test_contact_open_at_end_is_unknown_even_if_short():
    bundle = verify_button_press(with_switch([(2.99, None)]))
    assert bundle["verdict"] == "UNKNOWN"
    assert bundle["oracles"][0]["state"] == "STILL_PRESSED"


def test_pressed_before_observation_is_not_a_press():
    # Contact is already closed at the first sample and released later: we never saw it go down.
    bundle = verify_button_press(with_switch([(0.0, 0.5)]))
    assert bundle["verdict"] == "FAIL"
    assert bundle["oracles"][0]["measurements"]["pressed_at_first_sample"] is True


def test_internal_gap_blocks_fail_but_not_pass():
    episode = with_switch([])
    episode["sensors"]["button"] = [s for s in episode["sensors"]["button"] if not 1.0 < s["t"] < 2.0]
    assert verify_button_press(episode)["verdict"] == "UNKNOWN"
    episode = with_switch([(0.5, 0.7)])
    episode["sensors"]["button"] = [s for s in episode["sensors"]["button"] if not 1.0 < s["t"] < 2.0]
    assert verify_button_press(episode)["verdict"] == "PASS"


def test_no_video_passes_on_switch():
    episode = load("b01_clean_press")
    episode["video"] = []
    bundle = verify_button_press(episode)
    assert bundle["verdict"] == "PASS"
    assert bundle["comparison"]["vision_only_verdict"] == "UNKNOWN"


def test_config_changes_hold_threshold():
    episode = load("b03_light_brush")
    assert verify_button_press(episode)["verdict"] == "FAIL"
    assert verify_button_press(episode, ButtonPressConfig(min_hold_s=0.02))["verdict"] == "PASS"


def test_label_and_claim_do_not_influence_verdict():
    episode = load("b02_hover_no_contact")
    other = copy.deepcopy(episode)
    other["label"]["verdict"] = "PASS"
    other["claim"]["success"] = False
    a, b = verify_button_press(episode), verify_button_press(other)
    assert a["verdict"] == b["verdict"] == "FAIL"
    assert a["claim"]["contradicted"] and not b["claim"]["contradicted"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda e: e["task"]["button"].update(expected_presses=0),
        lambda e: e["task"]["button"].update(max_presses=0),
        lambda e: e["task"]["button"].pop("zone"),
        lambda e: e["sensors"]["button"][3].update(pressed=1),
        lambda e: e["video"][0].update(tool_xy=[0.1]),
        lambda e: e["task"].pop("button"),
    ],
)
def test_malformed_button_episode_rejected(mutate):
    episode = load("b01_clean_press")
    mutate(episode)
    with pytest.raises(EpisodeError):
        verify_button_press(episode)


def sampled_episode(contacts, hz):
    episode = load("b01_clean_press")
    n = int(3.0 * hz)
    episode["sensors"]["button"] = [
        {"t": round(i / hz, 4), "pressed": any(a <= i / hz < b for a, b in contacts)} for i in range(n + 1)
    ]
    return episode


def test_slow_switch_sampling_cannot_confirm_a_brush_as_a_press():
    # A 40 ms brush sampled at 20 Hz shows up as one closed sample: it may have lasted 0-100 ms.
    bundle = verify_button_press(sampled_episode([(1.49, 1.53)], hz=20))
    assert bundle["oracles"][0]["state"] == "UNRESOLVED_HOLD"
    assert bundle["verdict"] == "UNKNOWN"
    # The same brush sampled at 500 Hz is plainly too short.
    assert verify_button_press(sampled_episode([(1.49, 1.53)], hz=500))["verdict"] == "FAIL"


def test_real_press_is_confirmed_at_a_modest_rate_and_brush_is_not():
    assert verify_button_press(sampled_episode([(1.5, 1.8)], hz=20))["verdict"] == "PASS"
    assert verify_button_press(sampled_episode([(1.5, 1.8)], hz=100))["verdict"] == "PASS"
    brush = verify_button_press(sampled_episode([(1.5, 1.53)], hz=100))
    assert brush["verdict"] == "FAIL"


def test_a_press_elsewhere_still_passes_when_another_contact_is_unresolved():
    episode = sampled_episode([(0.5, 0.9), (1.49, 1.53)], hz=20)
    assert verify_button_press(episode)["verdict"] == "PASS"


def test_unresolved_second_contact_blocks_a_pass_when_presses_are_capped():
    # A confirmed 300 ms press, then a 40 ms contact seen by one 20 Hz sample: it might have been a second press.
    capped = sampled_episode([(0.5, 0.8), (1.49, 1.53)], hz=20)
    capped["task"]["button"]["max_presses"] = 1
    bundle = verify_button_press(capped)
    assert bundle["verdict"] == "UNKNOWN" and bundle["oracles"][0]["state"] == "UNRESOLVED_HOLD"
    # Without a cap the confirmed press is enough, and with a fast switch the second contact is plainly too short.
    uncapped = sampled_episode([(0.5, 0.8), (1.49, 1.53)], hz=20)
    assert verify_button_press(uncapped)["verdict"] == "PASS"
    fast = sampled_episode([(0.5, 0.8), (1.49, 1.53)], hz=500)
    fast["task"]["button"]["max_presses"] = 1
    assert verify_button_press(fast)["verdict"] == "PASS"
