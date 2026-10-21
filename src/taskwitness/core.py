"""Shared building blocks: verdicts, errors, episode validation and evidence bundles.

Every oracle produces the same bundle shape (`taskwitness.evidence/v0`), so the
CLI, evaluation tools and integrations never need to know which oracle ran.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any

from taskwitness import __version__

EPISODE_SCHEMA = "taskwitness.episode/v0"
BUNDLE_SCHEMA = "taskwitness.evidence/v0"

PASS = "PASS"
FAIL = "FAIL"
UNKNOWN = "UNKNOWN"
VERDICTS = (PASS, FAIL, UNKNOWN)


class TaskWitnessError(ValueError):
    """Base class for every error TaskWitness raises on bad input."""


class EpisodeError(TaskWitnessError):
    """Raised when an episode document is malformed."""


@dataclass
class OracleResult:
    oracle: str
    state: str
    detail: str
    measurements: dict[str, Any] = field(default_factory=dict)


def canonical_json(obj: Any) -> bytes:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def sha256_of(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj)).hexdigest()


def is_number(value: Any) -> bool:
    """A finite int or float. Booleans and NaN/inf are rejected on purpose."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def require(mapping: Any, key: str, where: str) -> Any:
    if not isinstance(mapping, dict) or key not in mapping:
        raise EpisodeError(f"missing '{key}' in {where}")
    return mapping[key]


def require_number(mapping: Any, key: str, where: str) -> float:
    value = require(mapping, key, where)
    if not is_number(value):
        raise EpisodeError(f"{where}.{key} must be a finite number, got {value!r}")
    return value


def validate_zone(zone: Any, where: str) -> None:
    for key in ("x_min", "x_max", "y_min", "y_max"):
        require_number(zone, key, where)
    if zone["x_min"] >= zone["x_max"] or zone["y_min"] >= zone["y_max"]:
        raise EpisodeError(f"{where} min must be smaller than max")


def in_zone(xy: list[float], zone: dict[str, float]) -> bool:
    return zone["x_min"] <= xy[0] <= zone["x_max"] and zone["y_min"] <= xy[1] <= zone["y_max"]


def _validate_samples(samples: Any, where: str, check) -> None:
    if not isinstance(samples, list):
        raise EpisodeError(f"{where} must be a list")
    for i, sample in enumerate(samples):
        here = f"{where}[{i}]"
        if not isinstance(sample, dict):
            raise EpisodeError(f"{here} must be an object")
        require_number(sample, "t", here)
        check(sample, here)


def _check_load(sample: dict, here: str) -> None:
    require_number(sample, "grams", here)


def _check_gripper(sample: dict, here: str) -> None:
    state = require(sample, "state", here)
    if not isinstance(state, str) or state.lower() not in ("open", "closed"):
        raise EpisodeError(f"{here}.state must be 'open' or 'closed', got {state!r}")


def _check_width(sample: dict, here: str) -> None:
    if require_number(sample, "width_m", here) < 0:
        raise EpisodeError(f"{here}.width_m must not be negative")


def _check_button(sample: dict, here: str) -> None:
    if not isinstance(require(sample, "pressed", here), bool):
        raise EpisodeError(f"{here}.pressed must be true or false")


def _check_frame(key: str):
    def check(sample: dict, here: str) -> None:
        xy = require(sample, key, here)
        if not (isinstance(xy, list) and len(xy) == 2 and all(is_number(v) for v in xy)):
            raise EpisodeError(f"{here}.{key} must be [x, y] with finite numbers")
        conf = require_number(sample, "confidence", here)
        if not 0.0 <= conf <= 1.0:
            raise EpisodeError(f"{here}.confidence must be within [0, 1]")

    return check


SENSOR_CHECKS = {"load_cell": _check_load, "gripper": _check_gripper, "button": _check_button, "gripper_width": _check_width}


def validate_common(episode: Any, task_type: str, video_key: str) -> None:
    """Checks shared by every oracle: schema, identity, claim and all known streams."""
    if not isinstance(episode, dict):
        raise EpisodeError("episode must be a JSON object")
    schema = require(episode, "schema", "episode")
    if schema != EPISODE_SCHEMA:
        raise EpisodeError(f"unsupported schema '{schema}', expected '{EPISODE_SCHEMA}'")
    episode_id = require(episode, "episode_id", "episode")
    if not isinstance(episode_id, str) or not episode_id:
        raise EpisodeError("episode_id must be a non-empty string")
    task = require(episode, "task", "episode")
    if require(task, "type", "task") != task_type:
        raise EpisodeError(f"expected task type '{task_type}', got '{task['type']}'")

    if "claim" in episode:
        claim = episode["claim"]
        if not isinstance(claim, dict):
            raise EpisodeError("claim must be an object")
        if "success" in claim and claim["success"] is not None and not isinstance(claim["success"], bool):
            raise EpisodeError("claim.success must be true, false or null")
    if "tags" in episode and not isinstance(episode["tags"], dict):
        raise EpisodeError("tags must be an object")

    sensors = episode.get("sensors", {})
    if not isinstance(sensors, dict):
        raise EpisodeError("sensors must be an object")
    for name, samples in sensors.items():
        if name in SENSOR_CHECKS:
            _validate_samples(samples, f"sensors.{name}", SENSOR_CHECKS[name])
    if "video" in episode:
        _validate_samples(episode["video"], "video", _check_frame(video_key))


def strip_label(episode: dict[str, Any]) -> dict[str, Any]:
    """The evidence an oracle may look at: everything except the ground-truth label."""
    return {k: v for k, v in episode.items() if k != "label"}


def stream(episode: dict[str, Any], name: str) -> list[dict[str, Any]]:
    return sorted(episode.get("sensors", {}).get(name, []), key=lambda s: s["t"])


def episode_bounds(episode: dict[str, Any], sensor_names: Iterable[str]) -> tuple[float, float] | None:
    """(start, end) over the video and the named sensor streams, or None if all are empty."""
    times = [f["t"] for f in episode.get("video", [])]
    for name in sensor_names:
        times += [s["t"] for s in episode.get("sensors", {}).get(name, [])]
    return (min(times), max(times)) if times else None


def build_bundle(
    episode: dict[str, Any],
    evidence: dict[str, Any],
    oracle: str,
    verdict: str,
    reasons: list[str],
    results: list[OracleResult],
    vision_only: str,
    timeline: list[dict[str, Any]],
    config: Any,
) -> dict[str, Any]:
    """Assemble a deterministic, self-describing evidence bundle with integrity digests."""
    claim = episode.get("claim", {}).get("success")
    bundle: dict[str, Any] = {
        "schema": BUNDLE_SCHEMA,
        "taskwitness_version": __version__,
        "episode_id": episode["episode_id"],
        "oracle": oracle,
        "verdict": verdict,
        "reasons": reasons,
        "claim": {
            "robot_claimed_success": claim,
            "contradicted": (claim is True and verdict == FAIL) or (claim is False and verdict == PASS),
        },
        "comparison": {"vision_only_verdict": vision_only},
        "oracles": [asdict(r) for r in results],
        "timeline": sorted(timeline, key=lambda e: (e["t"], e["source"], e["event"])),
        "config": asdict(config),
        "integrity": {"evidence_sha256": sha256_of(evidence)},
    }
    bundle["integrity"]["bundle_sha256"] = sha256_of(bundle)
    return bundle


def verify_bundle_integrity(bundle: dict[str, Any], episode: dict[str, Any] | None = None) -> bool:
    """Check that a bundle has not been edited, and optionally that it belongs to `episode`."""
    integrity = bundle.get("integrity", {})
    body = dict(bundle, integrity={k: v for k, v in integrity.items() if k != "bundle_sha256"})
    if sha256_of(body) != integrity.get("bundle_sha256"):
        return False
    if episode is not None:
        return sha256_of(strip_label(episode)) == integrity.get("evidence_sha256")
    return True
