"""PlaceOracle: sensor-grounded verification of "place object in target zone" tasks.

The oracle never controls a robot and never reads the robot's own success claim
when deciding a verdict. It combines three independent evidence streams:

* a load cell under the target zone (primary physical evidence),
* the gripper state reported by the hardware (used only to explain partial loads),
* video-derived object positions (secondary, can veto a PASS but never create one).

Every verdict is one of PASS / FAIL / UNKNOWN. UNKNOWN is a first-class outcome:
when evidence is missing, unstable or contradictory, the oracle says so instead
of guessing.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any

from taskwitness.core import (  # noqa: F401  (re-exported for backwards compatibility)
    BUNDLE_SCHEMA,
    EPISODE_SCHEMA,
    FAIL,
    PASS,
    UNKNOWN,
    EpisodeError,
    OracleResult,
    build_bundle,
    canonical_json,
    episode_bounds,
    in_zone,
    require,
    require_number,
    sha256_of,
    stream,
    strip_label,
    validate_common,
    validate_zone,
    verify_bundle_integrity,
)

SENSORS = ("load_cell", "gripper")


@dataclass(frozen=True)
class PlaceOracleConfig:
    # Load-cell samples inside the last `settle_window_s` seconds decide the final state.
    settle_window_s: float = 1.0
    min_settle_samples: int = 5
    # A load is "the object" if it is within max(abs, ratio * mass) of the expected mass.
    mass_tolerance_abs_g: float = 3.0
    mass_tolerance_ratio: float = 0.15
    # Below this the plate is considered empty.
    empty_threshold_g: float = 3.0
    # Population std-dev above this means the reading has not settled.
    stability_std_g: float = 2.0
    # Video frames below this confidence are ignored.
    video_min_confidence: float = 0.6
    video_final_window_s: float = 0.5


def validate_episode(episode: dict[str, Any]) -> None:
    validate_common(episode, "place", "object_xy")
    task = episode["task"]
    obj = require(task, "object", "task")
    if require_number(obj, "mass_g", "task.object") <= 0:
        raise EpisodeError("task.object.mass_g must be a positive number")
    validate_zone(require(task, "target_zone", "task"), "task.target_zone")


def sensor_oracle(episode: dict[str, Any], cfg: PlaceOracleConfig, t_end: float | None) -> OracleResult:
    samples = stream(episode, "load_cell")
    expected = float(episode["task"]["object"]["mass_g"])
    tolerance = max(cfg.mass_tolerance_abs_g, cfg.mass_tolerance_ratio * expected)
    base = {"expected_g": expected, "tolerance_g": round(tolerance, 3)}

    if expected - tolerance <= cfg.empty_threshold_g:
        return OracleResult(
            "load_cell",
            "UNRESOLVABLE",
            f"a {expected:.1f} g object cannot be told apart from an empty plate "
            f"(tolerance {tolerance:.1f} g, empty threshold {cfg.empty_threshold_g:.1f} g)",
            base,
        )
    if not samples or t_end is None:
        return OracleResult("load_cell", "NO_DATA", "no load-cell samples", base)

    window_start = t_end - cfg.settle_window_s
    window = [s["grams"] for s in samples if s["t"] >= window_start]
    m = dict(base, window_start_s=round(window_start, 3), window_end_s=round(t_end, 3), samples=len(window))
    if len(window) < cfg.min_settle_samples:
        return OracleResult(
            "load_cell",
            "NO_DATA",
            f"only {len(window)} samples in final {cfg.settle_window_s}s window "
            f"(need {cfg.min_settle_samples}); last sample at t={samples[-1]['t']}s",
            m,
        )

    mean = statistics.fmean(window)
    std = statistics.pstdev(window)
    m.update(mean_g=round(mean, 3), std_g=round(std, 3))
    if std > cfg.stability_std_g:
        return OracleResult("load_cell", "UNSTABLE", f"load not settled (std {std:.2f} g)", m)
    if mean < cfg.empty_threshold_g:
        return OracleResult("load_cell", "ABSENT", f"target plate empty ({mean:.1f} g)", m)
    if abs(mean - expected) <= tolerance:
        return OracleResult("load_cell", "PLACED", f"stable {mean:.1f} g matches {expected:.1f} g object", m)
    if mean < expected:
        return OracleResult(
            "load_cell", "PARTIAL_LOAD", f"stable {mean:.1f} g is below expected {expected:.1f} g", m
        )
    return OracleResult("load_cell", "OVERLOAD", f"stable {mean:.1f} g exceeds expected {expected:.1f} g", m)


def gripper_oracle(episode: dict[str, Any]) -> OracleResult:
    samples = stream(episode, "gripper")
    if not samples:
        return OracleResult("gripper", "NO_DATA", "no gripper state reported")
    last = samples[-1]
    state = last["state"].upper()
    opened = [s["t"] for s in samples if s["state"].upper() == "OPEN"]
    m = {"final_state": state, "final_t_s": last["t"]}
    if opened:
        m["first_open_t_s"] = opened[0]
    return OracleResult("gripper", state, f"gripper {state.lower()} at t={last['t']}s", m)


def video_oracle(episode: dict[str, Any], cfg: PlaceOracleConfig, t_end: float | None) -> OracleResult:
    frames = sorted(episode.get("video", []), key=lambda f: f["t"])
    if not frames or t_end is None:
        return OracleResult("video", "NO_DATA", "no video observations")
    window_start = t_end - cfg.video_final_window_s
    final = [f for f in frames if f["t"] >= window_start]
    confident = [f for f in final if f["confidence"] >= cfg.video_min_confidence]
    m = {"frames_in_window": len(final), "confident_frames": len(confident)}
    if not confident:
        return OracleResult("video", "LOW_CONFIDENCE", "no confident frames at end of episode", m)

    zone = episode["task"]["target_zone"]
    ratio = sum(in_zone(f["object_xy"], zone) for f in confident) / len(confident)
    m.update(in_zone_ratio=round(ratio, 3), final_object_xy=confident[-1]["object_xy"])
    if ratio >= 0.8:
        return OracleResult("video", "IN_ZONE", f"object in target zone in {ratio:.0%} of confident frames", m)
    if ratio <= 0.2:
        return OracleResult("video", "OUT_OF_ZONE", f"object outside target zone in {1 - ratio:.0%} of frames", m)
    return OracleResult("video", "LOW_CONFIDENCE", f"object position ambiguous ({ratio:.0%} in zone)", m)


def fuse(sensor: OracleResult, gripper: OracleResult, video: OracleResult) -> tuple[str, list[str]]:
    """Combine oracle states into a verdict. The load cell is authoritative; video can only veto."""
    s = sensor.state
    if s == "UNRESOLVABLE":
        return UNKNOWN, ["object too light for the configured load-cell thresholds; recalibrate or lower them"]
    if s == "NO_DATA":
        return UNKNOWN, ["no usable load-cell evidence; refusing to judge from video alone"]
    if s == "UNSTABLE":
        return UNKNOWN, ["load cell had not settled by end of episode"]
    if s == "OVERLOAD":
        return UNKNOWN, ["load exceeds the object's mass; another object may be on the target plate"]
    if s == "ABSENT":
        reasons = ["load cell shows the target plate is empty at end of episode"]
        if video.state == "IN_ZONE":
            reasons.append("video reports the object in zone, contradicted by physical evidence")
        return FAIL, reasons
    if s == "PARTIAL_LOAD":
        if gripper.state == "CLOSED":
            return FAIL, ["only part of the object's weight is on the plate while the gripper is still closed: object not released"]
        return UNKNOWN, ["partial load with gripper not confirmed closed; object may be resting on the zone edge"]
    if s == "PLACED":
        if video.state == "OUT_OF_ZONE":
            return UNKNOWN, ["load matches the object but video places it outside the zone; evidence conflict"]
        reasons = ["stable load on the target plate matches the object's mass"]
        if gripper.state == "CLOSED":
            return UNKNOWN, reasons + ["but the gripper is still closed; the robot may be pressing on the plate"]
        if video.state == "IN_ZONE":
            reasons.append("video independently confirms the object in the target zone")
        else:
            reasons.append(f"video evidence unavailable ({video.state}); verdict rests on load cell")
        return PASS, reasons
    raise AssertionError(f"unhandled sensor state {s}")


def vision_only_verdict(video: OracleResult) -> str:
    """What a judge that only looks at video would conclude. Reported for comparison only."""
    return {"IN_ZONE": PASS, "OUT_OF_ZONE": FAIL}.get(video.state, UNKNOWN)


def _timeline(episode: dict[str, Any], gripper: OracleResult) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if "first_open_t_s" in gripper.measurements:
        events.append({"t": gripper.measurements["first_open_t_s"], "source": "gripper", "event": "gripper_open"})
    samples = stream(episode, "load_cell")
    expected = float(episode["task"]["object"]["mass_g"])
    loaded = False
    for s in samples:
        now = s["grams"] >= 0.5 * expected
        if now != loaded:
            events.append({"t": s["t"], "source": "load_cell", "event": "load_on" if now else "load_off", "grams": s["grams"]})
            loaded = now
    if samples:
        events.append({"t": samples[-1]["t"], "source": "load_cell", "event": "last_sample", "grams": samples[-1]["grams"]})
    return events


def verify_place(episode: dict[str, Any], cfg: PlaceOracleConfig | None = None) -> dict[str, Any]:
    """Verify one place episode and return a self-describing evidence bundle.

    The bundle is deterministic: the same episode, config and TaskWitness version
    always produce byte-identical output, so bundles can be diffed and re-verified.
    """
    cfg = cfg or PlaceOracleConfig()
    validate_episode(episode)
    # The ground-truth label (if any) must never influence the verdict.
    evidence = strip_label(episode)
    bounds = episode_bounds(evidence, SENSORS)
    t_end = bounds[1] if bounds else None

    sensor = sensor_oracle(evidence, cfg, t_end)
    gripper = gripper_oracle(evidence)
    video = video_oracle(evidence, cfg, t_end)
    verdict, reasons = fuse(sensor, gripper, video)
    return build_bundle(
        episode,
        evidence,
        oracle="PlaceOracle",
        verdict=verdict,
        reasons=reasons,
        results=[sensor, gripper, video],
        vision_only=vision_only_verdict(video),
        timeline=_timeline(evidence, gripper),
        config=cfg,
    )
