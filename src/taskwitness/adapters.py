"""Turn raw logs into `taskwitness.episode/v0` files.

Sensor logs are plain text, one sample per line, as any serial logger can write:

    # comment lines and a header line are allowed
    t_ms,value
    120,8431992
    220,8432017

* load cell: value = raw ADC counts (with a load-cell calibration) or grams (without)
* gripper:   value = open | closed
* button:    value = 1/0, true/false, pressed/released

Logs that come from the same device must share one clock; `t0_ms` (by default
the earliest timestamp across those logs) becomes t = 0 s in the episode.

Video observations come from `taskwitness track` (`taskwitness.video/v0`). Their
timestamps are seconds from the start of the video; `video_offset_s` shifts them
onto the sensor clock (find it from the sync tap, see the experiment guide).

Every episode records the SHA-256 of each source file under `provenance`, so the
evidence digest of the resulting bundle covers the raw data it was built from.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from taskwitness import __version__
from taskwitness.calibration import CameraCalibration, LoadCellCalibration
from taskwitness.core import EPISODE_SCHEMA, VERDICTS, TaskWitnessError

VIDEO_SCHEMA = "taskwitness.video/v0"

_BUTTON_VALUES = {"1": True, "true": True, "pressed": True, "0": False, "false": False, "released": False}


class AdapterError(TaskWitnessError):
    """Raised when a raw log cannot be turned into episode data."""


@dataclass
class ParseReport:
    source: str
    rows: int = 0
    skipped: list[str] = field(default_factory=list)
    reordered: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"source": self.source, "rows": self.rows, "skipped": len(self.skipped), "first_skipped": self.skipped[:5], "reordered": self.reordered}


def read_series(lines: Iterable[str], source: str, strict: bool = True) -> tuple[list[tuple[float, str]], ParseReport]:
    """Parse `t_ms,value` lines into (t_ms, raw value) pairs sorted by time."""
    report = ParseReport(source)
    rows: list[tuple[float, str]] = []
    header_allowed = True
    for lineno, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        problem = None
        if len(parts) != 2 or not parts[1]:
            problem = "expected 't_ms,value'"
        else:
            try:
                t = float(parts[0])
                if not math.isfinite(t):
                    problem = "timestamp is not finite"
            except ValueError:
                if header_allowed:
                    header_allowed = False
                    continue
                problem = f"timestamp {parts[0]!r} is not a number"
        header_allowed = False
        if problem:
            message = f"{source}:{lineno}: {problem}: {line[:60]!r}"
            if strict:
                raise AdapterError(message)
            report.skipped.append(message)
            continue
        rows.append((t, parts[1]))
    if not rows:
        raise AdapterError(f"{source}: no samples found")
    report.reordered = any(b[0] < a[0] for a, b in zip(rows, rows[1:]))
    rows.sort(key=lambda r: r[0])
    report.rows = len(rows)
    return rows, report


def _convert(
    rows: list[tuple[float, str]], report: ParseReport, strict: bool, t0_ms: float, key: str, parse: Callable[[str], Any]
) -> list[dict[str, Any]]:
    out = []
    for t_ms, value in rows:
        try:
            parsed = parse(value)
        except (ValueError, KeyError):
            message = f"{report.source}: t={t_ms:g} ms: bad value {value!r}"
            if strict:
                raise AdapterError(message) from None
            report.skipped.append(message)
            continue
        out.append({"t": round((t_ms - t0_ms) / 1000.0, 6), key: parsed})
    report.rows = len(out)
    return out


def _finite(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(value)
    return number


def load_cell_samples(rows, report, t0_ms, calibration: LoadCellCalibration | None = None, strict=True):
    to_grams = (lambda v: round(calibration.to_grams(_finite(v)), 4)) if calibration else (lambda v: _finite(v))
    return _convert(rows, report, strict, t0_ms, "grams", to_grams)


def gripper_samples(rows, report, t0_ms, strict=True):
    def parse(v: str) -> str:
        v = v.lower()
        if v not in ("open", "closed"):
            raise ValueError(v)
        return v

    return _convert(rows, report, strict, t0_ms, "state", parse)


def button_samples(rows, report, t0_ms, strict=True):
    return _convert(rows, report, strict, t0_ms, "pressed", lambda v: _BUTTON_VALUES[v.lower()])


def video_frames(
    doc: dict[str, Any], key: str, offset_s: float = 0.0, camera: CameraCalibration | None = None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Convert tracker output to episode video frames in plate coordinates."""
    if not isinstance(doc, dict) or doc.get("schema") != VIDEO_SCHEMA:
        raise AdapterError(f"video observations must be a {VIDEO_SCHEMA} document")
    coords = doc.get("coords")
    if coords == "pixel" and camera is None:
        raise AdapterError("video observations are in pixels; pass a camera calibration to map them to the plate")
    if coords == "plate" and camera is not None:
        raise AdapterError("video observations are already in plate coordinates; do not pass a camera calibration")
    if coords not in ("pixel", "plate"):
        raise AdapterError(f"video coords must be 'pixel' or 'plate', got {coords!r}")
    frames, missing = [], 0
    for f in doc.get("frames", []):
        if f.get("xy") is None:
            missing += 1
            continue
        x, y = camera.to_plate(*f["xy"]) if camera else f["xy"]
        frames.append({"t": round(f["t"] + offset_s, 6), key: [round(x, 5), round(y, 5)], "confidence": f["confidence"]})
    return frames, {"frames": len(frames), "frames_without_detection": missing, "offset_s": offset_s, "coords": coords}


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_episode(
    task_type: str,
    task: dict[str, Any],
    episode_id: str,
    sensors: dict[str, list[dict[str, Any]]],
    video: list[dict[str, Any]] | None = None,
    claim: bool | None = None,
    label: str | None = None,
    note: str | None = None,
    tags: dict[str, Any] | None = None,
    sources: dict[str, str] | None = None,
) -> dict[str, Any]:
    if task.get("type", task_type) != task_type:
        raise AdapterError(f"task file says type {task.get('type')!r}, but this is a {task_type!r} episode")
    episode: dict[str, Any] = {
        "schema": EPISODE_SCHEMA,
        "episode_id": episode_id,
        "task": dict(task, type=task_type),
        "sensors": {k: v for k, v in sensors.items() if v},
        "provenance": {"tool": "taskwitness ingest", "taskwitness_version": __version__, "sources": sources or {}},
    }
    if video:
        episode["video"] = video
    if claim is not None:
        episode["claim"] = {"source": "operator_input", "success": claim}
    if tags:
        episode["tags"] = tags
    if label is not None:
        if label not in VERDICTS:
            raise AdapterError(f"label must be one of {VERDICTS}")
        episode["label"] = {"verdict": label, "note": note or ""}
    return episode


def read_json(path: str | Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AdapterError(f"{path}: invalid JSON: {exc}") from None
