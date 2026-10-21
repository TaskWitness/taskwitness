"""ButtonPressOracle: sensor-grounded verification of "press the button" tasks.

Primary evidence is the button's own contact switch, sampled on the shared clock.
A press counts only if contact is made after an open state, held at least
`min_hold_s` and released again. Contact bounce is merged and ignored.

Video of the tool (gripper / finger) is secondary: it can veto a PASS when the
switch fired but the tool was never seen at the button (something else may have
pressed it), but it can never create a PASS. "Hovering over the button" is the
classic false success of a vision-only judge, and the switch rules it out.

Absence of a press is only concluded (FAIL) when the switch stream covers the
whole episode without gaps; otherwise the press could have happened unobserved,
and the verdict is UNKNOWN.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from taskwitness.core import (
    FAIL,
    PASS,
    UNKNOWN,
    EpisodeError,
    OracleResult,
    build_bundle,
    episode_bounds,
    in_zone,
    require,
    stream,
    strip_label,
    validate_common,
    validate_zone,
)

SENSORS = ("button",)


@dataclass(frozen=True)
class ButtonPressConfig:
    # Contact runs, and open gaps between them, shorter than this are switch bounce.
    debounce_s: float = 0.02
    # A press must keep contact at least this long to count.
    min_hold_s: float = 0.05
    # Gaps between switch samples (and at the episode edges) longer than this are unobserved time.
    max_gap_s: float = 0.5
    # Video frames below this confidence are ignored.
    video_min_confidence: float = 0.6
    # Confident frames needed before video may say anything.
    video_min_frames: int = 3
    # Frames with the tool inside the button zone needed to say "tool at button".
    video_min_frames_in_zone: int = 2


def validate_episode(episode: dict[str, Any]) -> None:
    validate_common(episode, "button_press", "tool_xy")
    button = require(episode["task"], "button", "task")
    if not isinstance(button, dict):
        raise EpisodeError("task.button must be an object")
    expected = button.get("expected_presses", 1)
    if isinstance(expected, bool) or not isinstance(expected, int) or expected < 1:
        raise EpisodeError("task.button.expected_presses must be an integer >= 1")
    if "max_presses" in button:
        maximum = button["max_presses"]
        if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < expected:
            raise EpisodeError("task.button.max_presses must be an integer >= expected_presses")
    if "zone" in button:
        validate_zone(button["zone"], "task.button.zone")
    elif episode.get("video"):
        raise EpisodeError("video is present but task.button.zone is missing; cannot place the tool")


def _contact_runs(samples: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    """Turn switch samples into contact runs. Returns (runs, pressed_at_first_sample)."""
    runs: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    prev_pressed: bool | None = None
    for s in samples:
        if s["pressed"] and not prev_pressed:
            current = {"start": s["t"], "end": None, "rising_edge": prev_pressed is False}
            runs.append(current)
        elif not s["pressed"] and prev_pressed and current is not None:
            current["end"] = s["t"]
            current = None
        prev_pressed = s["pressed"]
    return runs, bool(samples and samples[0]["pressed"])


def _merge_bounce(runs: list[dict[str, Any]], debounce_s: float) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for run in runs:
        prev = merged[-1] if merged else None
        if prev is not None and prev["end"] is not None and run["start"] - prev["end"] < debounce_s:
            prev["end"] = run["end"]
        else:
            merged.append(dict(run))
    return merged


def switch_oracle(episode: dict[str, Any], cfg: ButtonPressConfig, bounds: tuple[float, float] | None) -> OracleResult:
    samples = stream(episode, "button")
    button = episode["task"]["button"]
    expected = button.get("expected_presses", 1)
    maximum = button.get("max_presses")
    if not samples or bounds is None:
        return OracleResult("switch", "NO_DATA", "no button switch samples", {"expected_presses": expected})

    times = [bounds[0]] + [s["t"] for s in samples] + [bounds[1]]
    max_gap = max(b - a for a, b in zip(times, times[1:]))
    runs, pressed_at_start = _contact_runs(samples)
    runs = _merge_bounce(runs, cfg.debounce_s)
    presses, short, bounces, held = [], [], 0, None
    for run in runs:
        if not run["rising_edge"]:
            continue  # already pressed when observation began: not a press we saw happen
        if run["end"] is None:
            held = run  # contact still open when observation ended: the press never completed
            continue
        duration = run["end"] - run["start"]
        if duration < cfg.debounce_s:
            bounces += 1
        elif duration < cfg.min_hold_s:
            short.append(round(duration, 4))
        else:
            presses.append({"start_s": run["start"], "end_s": run["end"], "duration_s": round(duration, 4)})

    m: dict[str, Any] = {
        "expected_presses": expected,
        "max_presses": maximum,
        "valid_presses": len(presses),
        "presses": presses,
        "short_contacts_s": short,
        "bounces_ignored": bounces,
        "pressed_at_first_sample": pressed_at_start,
        "max_unobserved_gap_s": round(max_gap, 4),
        "samples": len(samples),
    }
    n = len(presses)
    if held is not None:
        m["held_since_s"] = held["start"]
        return OracleResult("switch", "STILL_PRESSED", f"button still pressed at end of episode (since t={held['start']}s)", m)
    if maximum is not None and n > maximum:
        return OracleResult("switch", "TOO_MANY", f"{n} presses, at most {maximum} allowed", m)
    if n >= expected:
        return OracleResult("switch", "PRESSED", f"{n} complete press(es), {expected} required", m)
    if max_gap > cfg.max_gap_s:
        return OracleResult(
            "switch", "UNOBSERVED", f"{n} of {expected} presses seen, but the switch was unobserved for {max_gap:.2f}s", m
        )
    detail = f"{n} of {expected} required presses"
    if short:
        detail += f"; contact only {max(short) * 1000:.0f} ms (< {cfg.min_hold_s * 1000:.0f} ms hold)"
    return OracleResult("switch", "NOT_PRESSED" if n == 0 else "TOO_FEW", detail, m)


def video_oracle(episode: dict[str, Any], cfg: ButtonPressConfig) -> OracleResult:
    frames = episode.get("video", [])
    zone = episode["task"]["button"].get("zone")
    if not frames or zone is None:
        return OracleResult("video", "NO_DATA", "no video observations of the tool")
    confident = [f for f in frames if f["confidence"] >= cfg.video_min_confidence]
    inside = sum(in_zone(f["tool_xy"], zone) for f in confident)
    m = {"frames": len(frames), "confident_frames": len(confident), "frames_tool_in_zone": inside}
    if len(confident) < cfg.video_min_frames:
        return OracleResult("video", "LOW_CONFIDENCE", f"only {len(confident)} confident frames", m)
    if inside >= cfg.video_min_frames_in_zone:
        return OracleResult("video", "TOOL_AT_BUTTON", f"tool seen at the button in {inside} frames", m)
    return OracleResult("video", "TOOL_ABSENT", "tool never seen at the button", m)


def fuse(switch: OracleResult, video: OracleResult) -> tuple[str, list[str]]:
    s = switch.state
    if s == "NO_DATA":
        return UNKNOWN, ["no usable switch evidence; refusing to judge from video alone"]
    if s == "UNOBSERVED":
        return UNKNOWN, ["switch stream has gaps; a press may have happened unobserved"]
    if s == "STILL_PRESSED":
        return UNKNOWN, ["button is still held down at the end; the press was never completed"]
    if s == "TOO_MANY":
        return FAIL, [f"button pressed more often than allowed ({switch.detail})"]
    if s in ("NOT_PRESSED", "TOO_FEW"):
        reasons = [f"switch never registered the required press ({switch.detail})"]
        if video.state == "TOOL_AT_BUTTON":
            reasons.append("video shows the tool at the button, but the switch never closed: hover or too little force")
        return FAIL, reasons
    if s == "PRESSED":
        if video.state == "TOOL_ABSENT":
            return UNKNOWN, ["switch fired but the tool was never seen at the button; something else may have pressed it"]
        reasons = [f"switch registered {switch.detail}"]
        if video.state == "TOOL_AT_BUTTON":
            reasons.append("video independently shows the tool at the button")
        else:
            reasons.append(f"video evidence unavailable ({video.state}); verdict rests on the switch")
        return PASS, reasons
    raise AssertionError(f"unhandled switch state {s}")


def vision_only_verdict(video: OracleResult) -> str:
    return {"TOOL_AT_BUTTON": PASS, "TOOL_ABSENT": FAIL}.get(video.state, UNKNOWN)


def _timeline(switch: OracleResult) -> list[dict[str, Any]]:
    events = []
    for p in switch.measurements.get("presses", []):
        events.append({"t": p["start_s"], "source": "switch", "event": "press"})
        events.append({"t": p["end_s"], "source": "switch", "event": "release"})
    if "held_since_s" in switch.measurements:
        events.append({"t": switch.measurements["held_since_s"], "source": "switch", "event": "press_held"})
    return events


def verify_button_press(episode: dict[str, Any], cfg: ButtonPressConfig | None = None) -> dict[str, Any]:
    """Verify one button-press episode and return a deterministic evidence bundle."""
    cfg = cfg or ButtonPressConfig()
    validate_episode(episode)
    evidence = strip_label(episode)
    bounds = episode_bounds(evidence, SENSORS)
    switch = switch_oracle(evidence, cfg, bounds)
    video = video_oracle(evidence, cfg)
    verdict, reasons = fuse(switch, video)
    return build_bundle(
        episode,
        evidence,
        oracle="ButtonPressOracle",
        verdict=verdict,
        reasons=reasons,
        results=[switch, video],
        vision_only=vision_only_verdict(video),
        timeline=_timeline(switch),
        config=cfg,
    )
