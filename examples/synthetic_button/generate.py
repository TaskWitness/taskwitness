"""Regenerate the synthetic button-press episodes in this directory.

These episodes are SYNTHETIC. They exercise ButtonPressOracle's decision paths;
they are not measurements from a real robot, switch or camera.

    python examples/synthetic_button/generate.py
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent
DURATION = 3.0
SWITCH_DT = 0.01  # 100 Hz contact sampling
VIDEO_DT = 0.1  # 10 fps tool tracking
ZONE = {"x_min": 0.50, "x_max": 0.56, "y_min": 0.10, "y_max": 0.16}
HOME = (0.20, 0.40)
BUTTON = (0.53, 0.13)
AWAY = (0.30, 0.30)


def ticks(dt: float, start: float = 0.0, end: float = DURATION) -> list[float]:
    n = int(round((end - start) / dt))
    return [round(start + i * dt, 3) for i in range(n + 1)]


def lerp(a, b, s):
    return [round(a[0] + s * (b[0] - a[0]), 4), round(a[1] + s * (b[1] - a[1]), 4)]


def tool_path(t: float, target=BUTTON, arrive: float = 1.3, leave: float | None = 1.9) -> list[float]:
    """Approach the target by `arrive`, dwell until `leave` (None: stay), then retreat over 0.7 s."""
    if t <= arrive:
        return lerp(HOME, target, t / arrive)
    if leave is None or t <= leave:
        return list(target)
    return lerp(target, HOME, min((t - leave) / 0.7, 1.0))


def switch(contacts, end: float = DURATION) -> list[dict]:
    """contacts: list of (start, end) closed intervals; end=None means still closed."""
    out = []
    for t in ticks(SWITCH_DT, end=end):
        pressed = any(a <= t and (b is None or t < b) for a, b in contacts)
        out.append({"t": t, "pressed": pressed})
    return out


def episode(eid, description, contacts, label, note, target=BUTTON, switch_end=DURATION, arrive=1.3, leave=1.9):
    return {
        "schema": "taskwitness.episode/v0",
        "episode_id": eid,
        "description": description,
        "synthetic": True,
        "task": {"type": "button_press", "button": {"name": "start_button", "expected_presses": 1, "zone": ZONE}},
        "claim": {"source": "policy_self_report", "success": True},
        "video": [{"t": t, "tool_xy": tool_path(t, target, arrive, leave), "confidence": 0.9} for t in ticks(VIDEO_DT)],
        "sensors": {"button": switch(contacts, end=switch_end)},
        "label": {"verdict": label, "note": note},
    }


# A real press: contact bounces twice on make (10 ms blips) before holding for 200 ms.
BOUNCY_PRESS = [(1.50, 1.51), (1.52, 1.53), (1.54, 1.74)]

SCENARIOS = [
    episode(
        "b01_clean_press",
        "Tool reaches the button and presses it for 200 ms; contact bounces on make.",
        BOUNCY_PRESS,
        "PASS",
        "Synthetic ground truth: one complete press.",
    ),
    episode(
        "b02_hover_no_contact",
        "Tool hovers over the button for 0.6 s but never pushes it down.",
        [],
        "FAIL",
        "Synthetic ground truth: video shows the tool at the button, the switch never closed.",
    ),
    episode(
        "b03_light_brush",
        "Tool brushes the button: contact for 30 ms, below the 50 ms hold needed to actuate.",
        [(1.50, 1.53)],
        "FAIL",
        "Synthetic ground truth: the button did not actuate.",
    ),
    episode(
        "b04_held_at_end",
        "Tool arrives late and presses at t=2.6 s; it is still holding the button when recording stops.",
        [(2.60, None)],
        "UNKNOWN",
        "Synthetic ground truth: the press never completed within the episode.",
        arrive=2.4,
        leave=None,
    ),
    episode(
        "b05_switch_dropout",
        "Switch stream stops at t=1.0 s (e.g. USB disconnect), before the tool arrives.",
        BOUNCY_PRESS,
        "UNKNOWN",
        "Synthetic ground truth: a press may have happened, but nothing observed it.",
        switch_end=1.0,
    ),
    episode(
        "b06_external_trigger",
        "Switch registers a press while the tool is at the other side of the table (e.g. a person pressed it).",
        BOUNCY_PRESS,
        "UNKNOWN",
        "Synthetic ground truth: the button was pressed, but not by the robot; needs review.",
        target=AWAY,
    ),
]


def main() -> None:
    for ep in SCENARIOS:
        path = HERE / f"{ep['episode_id']}.json"
        path.write_text(json.dumps(ep, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
