"""Conformal calibration of the load-cell thresholds from known-good recordings.

The PlaceOracle compares the last `settle_window_s` of load-cell data with three
thresholds. Instead of guessing them, record states you know are good and let
split conformal prediction set each threshold so that a new known-good window
exceeds it with probability at most alpha:

* `stability_std_g`      window standard deviation, from windows of settled states
* `empty_threshold_g`    |window mean| on the empty plate
* `mass_tolerance_abs_g` |window mean - mass| with the correct object on the plate

Each guarantee is per window and holds if calibration and future windows are
exchangeable: same rig, same conditions, no drift. Windows are non-overlapping
slices of the recordings; record on different days and with the rig in its real
condition if you want the guarantee to mean something.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from typing import Any

from taskwitness.core import TaskWitnessError
from taskwitness.inference import conformal_upper, min_scores_needed

THRESHOLDS_SCHEMA = "taskwitness.thresholds/v0"


class ThresholdError(TaskWitnessError):
    """Raised when there is not enough known-good data for the requested guarantee."""


def window_stats(samples: Sequence[tuple[float, float]], window_s: float, min_samples: int = 5) -> list[tuple[float, float]]:
    """Non-overlapping windows of (t_s, grams) samples -> [(mean, population std)].

    The last, possibly partial, window is dropped; windows with fewer than
    `min_samples` samples are skipped.
    """
    if window_s <= 0:
        raise ThresholdError("window length must be positive")
    if not samples:
        return []
    ordered = sorted(samples)
    t0 = ordered[0][0]
    buckets: dict[int, list[float]] = {}
    for t, grams in ordered:
        buckets.setdefault(int((t - t0) // window_s), []).append(grams)
    last = max(buckets)
    return [
        (statistics.fmean(values), statistics.pstdev(values))
        for index, values in sorted(buckets.items())
        if index != last and len(values) >= min_samples
    ]


def calibrate_thresholds(
    empty_windows: Sequence[tuple[float, float]],
    object_windows: dict[float, Sequence[tuple[float, float]]],
    alpha: float = 0.05,
    window_s: float = 1.0,
) -> dict[str, Any]:
    needed = min_scores_needed(alpha)
    if not empty_windows:
        raise ThresholdError("need recordings of the empty plate")

    def bound(scores: list[float], what: str) -> float:
        value = conformal_upper(scores, alpha)
        if value is None:
            raise ThresholdError(
                f"{what}: only {len(scores)} windows, but alpha = {alpha} needs at least {needed}; "
                "record longer or use a larger alpha"
            )
        return value

    stds = [s for _, s in empty_windows] + [s for ws in object_windows.values() for _, s in ws]
    thresholds = {
        "stability_std_g": bound(stds, "stability (settled windows)"),
        "empty_threshold_g": bound([abs(m) for m, _ in empty_windows], "empty plate"),
    }
    warnings = []
    errors = [abs(m - mass) for mass, ws in object_windows.items() for m, _ in ws]
    if object_windows:
        thresholds["mass_tolerance_abs_g"] = bound(errors, "object windows")
        for mass in object_windows:
            if mass - max(thresholds["mass_tolerance_abs_g"], 0.15 * mass) <= thresholds["empty_threshold_g"]:
                warnings.append(f"a {mass:g} g object is too close to the empty threshold to tell apart; the oracle will return UNKNOWN")
    else:
        warnings.append("no object recordings: mass_tolerance_abs_g keeps its default")
    if thresholds["stability_std_g"] == 0:
        warnings.append("zero-noise recordings: check the data is real before using a zero stability threshold")
    return {
        "schema": THRESHOLDS_SCHEMA,
        "alpha": alpha,
        "window_s": window_s,
        "windows": {"empty": len(empty_windows), "object": {f"{m:g}": len(w) for m, w in object_windows.items()}},
        "place_config": {k: round(v, 6) for k, v in thresholds.items()} | {"settle_window_s": window_s},
        "guarantee": (
            f"A new known-good window exceeds each threshold with probability at most {alpha}, "
            "provided calibration and future windows are exchangeable (same rig, no drift)."
        ),
        "warnings": warnings,
    }
