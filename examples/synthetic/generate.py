"""Regenerate the synthetic place-task episodes in this directory.

These episodes are SYNTHETIC. They exercise the oracle's decision paths; they are
not measurements from a real robot, camera or load cell.

    python examples/synthetic/generate.py
"""

from __future__ import annotations

import json
import random
from pathlib import Path

HERE = Path(__file__).parent
DT = 0.1
DURATION = 4.0
MASS_G = 52.0
ZONE = {"x_min": 0.30, "x_max": 0.40, "y_min": -0.05, "y_max": 0.05}
TARGET_XY = (0.35, 0.0)
START_XY = (0.10, 0.20)


def ticks(end: float = DURATION) -> list[float]:
    return [round(i * DT, 2) for i in range(int(round(end / DT)) + 1)]


def approach(t: float, arrive: float = 2.0) -> list[float]:
    a = min(t / arrive, 1.0)
    return [round(START_XY[0] + a * (TARGET_XY[0] - START_XY[0]), 4), round(START_XY[1] + a * (TARGET_XY[1] - START_XY[1]), 4)]


def episode(eid: str, description: str, load, gripper_open_at, video, label: str, note: str, load_end=DURATION):
    rng = random.Random(eid)
    load_cell = [{"t": t, "grams": round(max(load(t) + rng.gauss(0, 0.3), 0.0), 2)} for t in ticks(load_end)]
    gripper = [{"t": t, "state": "open" if gripper_open_at is not None and t >= gripper_open_at else "closed"} for t in ticks()]
    frames = []
    for t in ticks():
        xy, conf = video(t)
        frames.append({"t": t, "object_xy": xy, "confidence": round(conf, 3)})
    return {
        "schema": "taskwitness.episode/v0",
        "episode_id": eid,
        "description": description,
        "synthetic": True,
        "task": {"type": "place", "object": {"name": "red_block", "mass_g": MASS_G}, "target_zone": ZONE},
        "claim": {"source": "policy_self_report", "success": True},
        "video": frames,
        "sensors": {"load_cell": load_cell, "gripper": gripper},
        "label": {"verdict": label, "note": note},
    }


SCENARIOS = [
    episode(
        "01_clean_success",
        "Block is lowered onto the target plate at t=2.0s and released at t=2.2s.",
        load=lambda t: MASS_G if t >= 2.0 else 0.0,
        gripper_open_at=2.2,
        video=lambda t: (approach(t), 0.9),
        label="PASS",
        note="Synthetic ground truth: object resting in zone, gripper open.",
    ),
    episode(
        "02_not_released",
        "Block touches the plate but the gripper never opens; the robot holds it.",
        load=lambda t: 18.0 if t >= 2.0 else 0.0,
        gripper_open_at=None,
        video=lambda t: (approach(t), 0.92),
        label="FAIL",
        note="Synthetic ground truth: video shows the block in the zone, but it was never released.",
    ),
    episode(
        "03_bounced_off",
        "Block is dropped from height, lands on the plate and bounces off behind a fixture; the tracker stays locked on the zone.",
        load=lambda t: MASS_G if 2.0 <= t < 2.5 else 0.0,
        gripper_open_at=2.0,
        video=lambda t: (approach(t), 0.85),
        label="FAIL",
        note="Synthetic ground truth: object left the zone; video tracker is stale.",
    ),
    episode(
        "04_sensor_dropout",
        "Load-cell stream drops at t=1.5s (e.g. USB disconnect) before the placement happens.",
        load=lambda t: MASS_G if t >= 2.0 else 0.0,
        gripper_open_at=2.2,
        video=lambda t: (approach(t), 0.9),
        label="UNKNOWN",
        note="Synthetic ground truth: object was placed, but without physical evidence the oracle must not decide.",
        load_end=1.5,
    ),
    episode(
        "05_evidence_conflict",
        "Plate reads the object's mass but the camera sees the block outside the zone (e.g. a look-alike object on the plate or camera calibration drift).",
        load=lambda t: MASS_G if t >= 2.0 else 0.0,
        gripper_open_at=2.2,
        video=lambda t: ([0.46, 0.02] if t >= 2.0 else approach(t), 0.88),
        label="UNKNOWN",
        note="Synthetic ground truth: independent evidence disagrees; needs human review.",
    ),
]


def main() -> None:
    for ep in SCENARIOS:
        path = HERE / f"{ep['episode_id']}.json"
        path.write_text(json.dumps(ep, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
