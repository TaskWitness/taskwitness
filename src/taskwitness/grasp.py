"""GraspOracle: did the gripper end up holding the object?

Evidence is the gripper's finger position over time (`sensors.gripper_width`,
metres). A successful grasp leaves the fingers stopped at the object's width; a
grasp that closed on nothing, or lost the object, leaves them closed past it; a
gripper that never closed (or reopened) leaves them wider than the object.

The width band comes from the task (`task.object.width_m_min` / `width_m_max`):
measure the object with calipers, or take the range of known-good grasps. Widths
within `margin_m` outside the band are UNKNOWN rather than FAIL, because sensor
resolution and object tolerance make the boundary uncertain.

Independence, honestly: the gripper width is reported by the robot itself, so it
is independent of the policy's success claim and of vision, but it is not an
external sensor. It cannot tell a held object from a different object of the same
width, and it says nothing about what happens after the segment (a dropped
object). Use it where an external sensor is not available.
"""

from __future__ import annotations

import statistics
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
    require,
    require_number,
    stream,
    strip_label,
    validate_common,
)

SENSORS = ("gripper_width",)


@dataclass(frozen=True)
class GraspConfig:
    # The last `settle_window_s` of finger positions decide the final state.
    settle_window_s: float = 0.5
    min_settle_samples: int = 5
    # Population std-dev above this means the fingers are still moving.
    stability_std_m: float = 0.0005
    # Widths this close outside the band are UNKNOWN, not FAIL.
    margin_m: float = 0.001


def validate_episode(episode: dict[str, Any]) -> None:
    validate_common(episode, "grasp", "object_xy")
    obj = require(episode["task"], "object", "task")
    low = require_number(obj, "width_m_min", "task.object")
    high = require_number(obj, "width_m_max", "task.object")
    if low < 0 or high <= low:
        raise EpisodeError("task.object needs 0 <= width_m_min < width_m_max")


def width_oracle(episode: dict[str, Any], cfg: GraspConfig, t_end: float | None) -> OracleResult:
    samples = stream(episode, "gripper_width")
    obj = episode["task"]["object"]
    low, high = float(obj["width_m_min"]), float(obj["width_m_max"])
    base = {"band_m": [low, high], "margin_m": cfg.margin_m}
    if not samples or t_end is None:
        return OracleResult("gripper_width", "NO_DATA", "no gripper width samples", base)
    start = t_end - cfg.settle_window_s
    window = [s["width_m"] for s in samples if s["t"] >= start]
    m = dict(base, window_start_s=round(start, 4), samples=len(window))
    if len(window) < cfg.min_settle_samples:
        return OracleResult("gripper_width", "NO_DATA", f"only {len(window)} samples in the final {cfg.settle_window_s}s (need {cfg.min_settle_samples})", m)
    median = statistics.median(window)
    std = statistics.pstdev(window)
    m.update(median_m=round(median, 6), std_m=round(std, 6))
    if std > cfg.stability_std_m:
        return OracleResult("gripper_width", "MOVING", f"fingers still moving (std {std * 1000:.2f} mm)", m)
    if low <= median <= high:
        return OracleResult("gripper_width", "HOLDING", f"fingers stopped at {median * 1000:.1f} mm, inside the object's {low * 1000:.1f}-{high * 1000:.1f} mm", m)
    if low - cfg.margin_m <= median < low or high < median <= high + cfg.margin_m:
        return OracleResult("gripper_width", "NEAR_BAND", f"fingers at {median * 1000:.1f} mm, within the margin of the {low * 1000:.1f}-{high * 1000:.1f} mm band", m)
    if median < low:
        return OracleResult("gripper_width", "TOO_CLOSED", f"fingers closed to {median * 1000:.1f} mm, past the object's width: nothing between them", m)
    return OracleResult("gripper_width", "TOO_OPEN", f"fingers at {median * 1000:.1f} mm, wider than the object: not gripping", m)


def fuse(width: OracleResult) -> tuple[str, list[str]]:
    s = width.state
    if s == "NO_DATA":
        return UNKNOWN, ["no usable gripper-width evidence"]
    if s == "MOVING":
        return UNKNOWN, ["fingers had not stopped by the end of the episode"]
    if s == "NEAR_BAND":
        return UNKNOWN, [width.detail]
    if s == "HOLDING":
        return PASS, [width.detail]
    if s in ("TOO_CLOSED", "TOO_OPEN"):
        return FAIL, [width.detail]
    raise AssertionError(f"unhandled width state {s}")


def verify_grasp(episode: dict[str, Any], cfg: GraspConfig | None = None) -> dict[str, Any]:
    """Verify one grasp episode and return a deterministic evidence bundle."""
    cfg = cfg or GraspConfig()
    validate_episode(episode)
    evidence = strip_label(episode)
    bounds = episode_bounds(evidence, SENSORS)
    width = width_oracle(evidence, cfg, bounds[1] if bounds else None)
    verdict, reasons = fuse(width)
    samples = stream(evidence, "gripper_width")
    timeline = [{"t": samples[-1]["t"], "source": "gripper_width", "event": "last_sample", "width_m": samples[-1]["width_m"]}] if samples else []
    return build_bundle(
        episode,
        evidence,
        oracle="GraspOracle",
        verdict=verdict,
        reasons=reasons,
        results=[width],
        vision_only=UNKNOWN,
        timeline=timeline,
        config=cfg,
    )
