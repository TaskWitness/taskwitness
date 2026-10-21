"""Physics-based episode simulator for place and button-press tasks. Pure Python.

Purpose: stress the verifier at scale against *known* ground truth, and show how
its error rates move with sensor noise, dropouts, tracker failures and clock
offsets, before any real hardware exists.

How it avoids grading its own homework
    Each episode is generated from a latent physical story (what really happened:
    object released and resting, bounced out, held by the gripper, wrong object,
    another object on the plate, ...). Sensor and video streams are produced from
    that story with realistic imperfections, and the label comes from the story,
    never from an oracle. The mix includes failures the oracles are *not* designed
    to catch, such as a foreign object of similar mass on the plate while the
    tracker is stale, so the reported false-pass rate is not trivially zero.

What it cannot tell you
    The failure modes and noise levels are the author's assumptions, not
    measurements. Results show how the method behaves under those assumptions.
    `docs/SIMULATION.en.md` lists what to replace with real data.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, fields, replace
from typing import Any

from taskwitness.core import EPISODE_SCHEMA, TaskWitnessError

ZONE = {"x_min": 0.30, "x_max": 0.40, "y_min": -0.05, "y_max": 0.05}
ZONE_CENTER = (0.35, 0.0)
BUTTON_ZONE = {"x_min": 0.50, "x_max": 0.56, "y_min": 0.10, "y_max": 0.16}
BUTTON_CENTER = (0.53, 0.13)
START_XY = (0.10, 0.25)
AWAY_XY = (0.30, 0.30)


class SimulationError(TaskWitnessError):
    """Raised for unknown presets, modes or overrides."""


@dataclass(frozen=True)
class SimConfig:
    object_mass_g: float = 52.0
    # load cell
    load_hz: float = 20.0
    load_noise_g: float = 0.4
    load_drift_g_per_sqrt_s: float = 0.05
    load_offset_sd_g: float = 0.0  # zero-point shift between trials (pose-dependent bias of a wrist sensor)
    load_spike_prob: float = 0.002  # per sample
    load_spike_g: float = 12.0  # typical spike size
    sample_drop_prob: float = 0.01
    # gripper and button switch
    gripper_hz: float = 10.0
    switch_hz: float = 100.0
    switch_glitch_prob: float = 0.05  # per episode: a 1-3 ms spurious contact
    # video tracker
    video_fps: float = 10.0
    video_noise_m: float = 0.004
    stale_tracker_prob: float = 0.6  # object left the target but the tracker keeps the last position
    occlusion_prob: float = 0.08  # per episode: low confidence over the last 40% of frames
    # clocks and robot behaviour
    clock_offset_s: float = 0.15  # video clock is off by up to +-this much
    claim_on_success: float = 0.97  # probability the robot claims success when it did succeed
    claim_on_failure: float = 0.75  # ... when it did not


PRESETS = {
    "clean": SimConfig(load_noise_g=0.1, load_drift_g_per_sqrt_s=0.01, load_spike_prob=0.0, sample_drop_prob=0.0, stale_tracker_prob=0.3, occlusion_prob=0.02, clock_offset_s=0.05),
    "lab": SimConfig(),
    # The robot's own wrist force/torque sensor used as the load cell. Noise and bias are measured
    # on REASSEMBLE (Franka): ~11.6 g median in-window noise, ~106 g between-trial offset (IQR 143 g).
    "wrist_ft": SimConfig(load_hz=30.0, load_noise_g=11.6, load_drift_g_per_sqrt_s=0.5, load_offset_sd_g=106.0, load_spike_prob=0.005, sample_drop_prob=0.0),
    "noisy": SimConfig(load_hz=10.0, load_noise_g=2.0, load_drift_g_per_sqrt_s=0.3, load_spike_prob=0.01, sample_drop_prob=0.05, stale_tracker_prob=0.8, occlusion_prob=0.2, clock_offset_s=0.3),
}

PLACE_MIX = {
    "success": 43, "slow_settle": 4, "late_placement": 3, "dropout_success": 3,
    "not_released": 8, "pressing": 5, "bounce_out": 8, "miss": 8, "edge": 6,
    "wrong_object": 4, "leftover_object": 2, "foreign_object": 3, "dropout_fail": 3,
}
PLACE_TRUE_PASS = {"success", "slow_settle", "late_placement", "dropout_success"}

BUTTON_MIX = {
    "success": 50, "slow_press": 3, "held_at_end": 4, "dropout_success": 3,
    "hover": 12, "light_brush": 8, "bounce_only": 4, "double_press": 5,
    "external_trigger": 4, "miss_button": 4, "dropout_fail": 3,
}
# held_at_end: the switch did close, so the button was actuated; the oracle abstains (UNKNOWN) because
# the press never completed, which is the behaviour we want to measure.
BUTTON_TRUE_PASS = {"success", "slow_press", "held_at_end", "dropout_success"}


def preset(name: str, **overrides: float) -> SimConfig:
    if name not in PRESETS:
        raise SimulationError(f"unknown preset {name!r}; known: {sorted(PRESETS)}")
    known = {f.name for f in fields(SimConfig)}
    unknown = set(overrides) - known
    if unknown:
        raise SimulationError(f"unknown setting(s) {sorted(unknown)}; known: {sorted(known)}")
    return replace(PRESETS[name], **overrides)


def _ring(t: float, t0: float, amplitude: float, tau: float, freq: float) -> float:
    if t < t0:
        return 0.0
    return amplitude * math.exp(-(t - t0) / tau) * math.cos(2 * math.pi * freq * (t - t0))


def _times(start: float, end: float, hz: float) -> list[float]:
    n = int((end - start) * hz)
    return [start + i / hz for i in range(n + 1)]


def _noisy_load(rng: random.Random, cfg: SimConfig, end: float, signal) -> list[dict[str, float]]:
    out, drift, dt = [], 0.0, 1.0 / cfg.load_hz
    offset = rng.gauss(0.0, cfg.load_offset_sd_g) if cfg.load_offset_sd_g > 0 else 0.0
    for t in _times(0.0, end, cfg.load_hz):
        drift += rng.gauss(0.0, cfg.load_drift_g_per_sqrt_s * math.sqrt(dt))
        if rng.random() < cfg.sample_drop_prob:
            continue
        value = signal(t) + offset + drift + rng.gauss(0.0, cfg.load_noise_g)
        if rng.random() < cfg.load_spike_prob:
            value += rng.choice((-1, 1)) * rng.uniform(0.5, 1.5) * cfg.load_spike_g
        out.append({"t": round(t + rng.uniform(-0.1, 0.1) * dt, 4), "grams": round(value, 3)})
    return out


def _video(rng, cfg, end, offset, position, tool_key, in_zone_view, stale_after=None, zone_center=ZONE_CENTER):
    """Tracker output. `position(t)` is the true position; after `stale_after` the tracker may freeze on its last good value."""
    occluded = rng.random() < cfg.occlusion_prob
    stale = stale_after is not None and rng.random() < cfg.stale_tracker_prob
    frames, frozen = [], None
    for t in _times(0.0, end, cfg.video_fps):
        x, y = position(t)
        conf = min(1.0, max(0.0, rng.gauss(0.9, 0.05)))
        if stale and t >= stale_after:
            frozen = frozen or (position(stale_after) if in_zone_view else zone_center)
            x, y = frozen
        if occluded and t >= 0.6 * end:
            conf = rng.uniform(0.1, 0.5)
        frames.append({"t": round(t + offset, 4), tool_key: [round(x + rng.gauss(0, cfg.video_noise_m), 5), round(y + rng.gauss(0, cfg.video_noise_m), 5)], "confidence": round(conf, 3)})
    return frames


def _lerp(a, b, s):
    s = min(1.0, max(0.0, s))
    return (a[0] + s * (b[0] - a[0]), a[1] + s * (b[1] - a[1]))


# ----------------------------------------------------------------------------- place


def simulate_place(index: int, mode: str, cfg: SimConfig, seed: int) -> dict[str, Any]:
    if mode not in PLACE_MIX:
        raise SimulationError(f"unknown place mode {mode!r}; known: {sorted(PLACE_MIX)}")
    rng = random.Random(seed * 1_000_003 + index)
    m = cfg.object_mass_g
    t_touch = rng.uniform(1.5, 3.0)
    t_rel = t_touch + rng.uniform(0.15, 0.4)
    end = t_rel + rng.uniform(2.0, 3.0)
    if mode == "late_placement":
        t_rel = end - rng.uniform(0.3, 0.8)
        t_touch = t_rel - rng.uniform(0.15, 0.4)
    support = rng.uniform(0.2, 0.9)  # fraction of the weight the plate carries while the gripper still holds
    amp, tau, freq = m * rng.uniform(0.05, 0.3), 0.15, 8.0
    if mode == "slow_settle":
        amp, tau = m * rng.uniform(0.3, 0.6), rng.uniform(0.6, 1.2)
    base_mode = {"dropout_success": "success", "dropout_fail": "bounce_out"}.get(mode, mode)
    t_leave = t_rel + rng.uniform(0.05, 0.3)  # when a bouncing object leaves the plate
    factor = rng.choice((0.5, 0.65, 1.45, 2.0))
    held_fraction = rng.uniform(0.0, 0.7)
    edge_fraction = rng.uniform(0.25, 0.75)
    foreign_mass = m * rng.uniform(0.9, 1.1)
    # leftover_object: something from the previous trial sits on the plate from the start.
    # foreign_object: another object lands on the plate during this trial.
    foreign_since = 0.0 if mode == "leftover_object" else rng.uniform(max(0.0, t_touch - 0.6), t_rel)

    def signal(t: float) -> float:
        if base_mode in ("success", "slow_settle", "late_placement"):
            return (m * support if t_touch <= t < t_rel else m if t >= t_rel else 0.0) + _ring(t, t_rel, amp, tau, freq)
        if base_mode == "not_released":
            return m * held_fraction if t >= t_touch else 0.0
        if base_mode == "pressing":
            return m * rng.uniform(0.97, 1.03) if t >= t_touch else 0.0
        if base_mode == "bounce_out":
            if t < t_touch:
                return 0.0
            return m * support if t < t_rel else (m if t < t_leave else 0.0)
        if base_mode == "edge":
            return m * support * edge_fraction if t_touch <= t < t_rel else m * edge_fraction if t >= t_rel else 0.0
        if base_mode == "wrong_object":
            return factor * m * support if t_touch <= t < t_rel else factor * m if t >= t_rel else 0.0
        if base_mode in ("foreign_object", "leftover_object"):
            return foreign_mass if t >= foreign_since else 0.0
        return 0.0  # miss

    holds = base_mode in ("not_released", "pressing")
    gripper = []
    for t in _times(0.0, end, cfg.gripper_hz):
        if rng.random() < cfg.sample_drop_prob:
            continue
        opened = (not holds) and t >= t_rel + 0.1
        gripper.append({"t": round(t, 4), "state": "open" if opened else "closed"})

    load = _noisy_load(rng, cfg, end, signal)
    if mode.startswith("dropout"):
        cut = rng.uniform(0.3 * end, end - 1.6)
        load = [s for s in load if s["t"] <= cut]

    leaves = base_mode in ("bounce_out", "miss", "foreign_object", "leftover_object")
    outside = (ZONE["x_max"] + rng.uniform(0.04, 0.15), rng.uniform(-0.1, 0.1))
    edge_xy = (ZONE["x_max"] + rng.uniform(-0.01, 0.01), rng.uniform(-0.03, 0.03))
    target = edge_xy if base_mode == "edge" else ZONE_CENTER

    def position(t: float) -> tuple[float, float]:
        if base_mode == "bounce_out" and t >= t_leave:
            return outside
        if base_mode in ("miss", "foreign_object", "leftover_object") and t >= t_touch:
            return outside
        return _lerp(START_XY, target, (t - 0.5) / max(t_touch - 0.5, 0.1))

    stale_after = (t_leave if base_mode == "bounce_out" else t_touch - 0.05) if leaves else None
    offset = rng.uniform(-cfg.clock_offset_s, cfg.clock_offset_s)
    video = _video(rng, cfg, end, offset, position, "object_xy", True, stale_after)

    truth_pass = mode in PLACE_TRUE_PASS
    claim = rng.random() < (cfg.claim_on_success if truth_pass else cfg.claim_on_failure)
    return {
        "schema": EPISODE_SCHEMA,
        "episode_id": f"sim-place-{seed}-{index:05d}",
        "synthetic": True,
        "task": {"type": "place", "object": {"name": "block", "mass_g": m}, "target_zone": dict(ZONE)},
        "claim": {"source": "simulated_policy", "success": claim},
        "video": video,
        "sensors": {"load_cell": load, "gripper": gripper},
        "tags": {"failure_mode": mode, "trial": index},
        "label": {"verdict": "PASS" if truth_pass else "FAIL", "note": f"latent story: {mode}"},
    }


# ----------------------------------------------------------------------------- button


def simulate_button(index: int, mode: str, cfg: SimConfig, seed: int) -> dict[str, Any]:
    if mode not in BUTTON_MIX:
        raise SimulationError(f"unknown button mode {mode!r}; known: {sorted(BUTTON_MIX)}")
    rng = random.Random(seed * 1_000_003 + index)
    end = rng.uniform(3.0, 4.0)
    start = rng.uniform(1.2, end - 1.0)
    base_mode = {"dropout_success": "success", "dropout_fail": "hover"}.get(mode, mode)
    contacts: list[tuple[float, float | None]] = []

    def press(s: float, duration: float, bounce: bool) -> None:
        if bounce:
            for k in range(rng.randint(1, 3)):
                b = s - 0.014 * (k + 1)
                contacts.append((b - 0.005, b))
        contacts.append((s, s + duration))

    duration = min(0.6, max(0.07, rng.gauss(0.18, 0.06)))
    if base_mode == "success":
        press(start, duration, rng.random() < 0.6)
    elif base_mode == "slow_press":
        press(start, rng.uniform(0.6, 1.0), rng.random() < 0.6)
    elif base_mode == "light_brush":
        press(start, rng.uniform(0.01, 0.045), False)
    elif base_mode == "bounce_only":
        for k in range(rng.randint(1, 3)):
            contacts.append((start + 0.03 * k, start + 0.03 * k + rng.uniform(0.003, 0.012)))
    elif base_mode == "double_press":
        press(start, duration, rng.random() < 0.6)
        press(start + duration + rng.uniform(0.3, 0.8), duration, rng.random() < 0.6)
    elif base_mode == "held_at_end":
        contacts.append((end - rng.uniform(0.2, 0.6), None))
    elif base_mode == "external_trigger":
        press(start, rng.uniform(0.1, 0.4), rng.random() < 0.6)
    if rng.random() < cfg.switch_glitch_prob:
        g = rng.uniform(0.2, end - 0.2)
        contacts.append((g, g + rng.uniform(0.001, 0.003)))

    cut = rng.uniform(0.3, max(0.31, start - 0.1)) if mode.startswith("dropout") else None
    switch = []
    for t in _times(0.0, end, cfg.switch_hz):
        if cut is not None and t > cut:
            break
        switch.append({"t": round(t, 4), "pressed": any(a <= t and (b is None or t < b) for a, b in contacts)})

    robot_at_button = base_mode not in ("external_trigger", "miss_button")
    target = BUTTON_CENTER if robot_at_button else AWAY_XY
    arrive = max(0.6, start - 0.4)
    leave = ((contacts[-1][1] or end) if contacts else start + 0.4) + 0.2

    def position(t: float) -> tuple[float, float]:
        if t <= arrive:
            return _lerp(START_XY, target, t / arrive)
        if t <= leave:
            return target
        return _lerp(target, START_XY, (t - leave) / 0.7)

    video = _video(rng, cfg, end, rng.uniform(-cfg.clock_offset_s, cfg.clock_offset_s), position, "tool_xy", True)
    truth_pass = mode in BUTTON_TRUE_PASS
    claim = rng.random() < (cfg.claim_on_success if truth_pass else cfg.claim_on_failure)
    return {
        "schema": EPISODE_SCHEMA,
        "episode_id": f"sim-button-{seed}-{index:05d}",
        "synthetic": True,
        "task": {"type": "button_press", "button": {"name": "start", "expected_presses": 1, "max_presses": 1, "zone": dict(BUTTON_ZONE)}},
        "claim": {"source": "simulated_policy", "success": claim},
        "video": video,
        "sensors": {"button": switch},
        "tags": {"failure_mode": mode, "trial": index},
        "label": {"verdict": "PASS" if truth_pass else "FAIL", "note": f"latent story: {mode}"},
    }


# ----------------------------------------------------------------------------- datasets


def _modes(kind: str, n: int, seed: int, mix: dict[str, float] | None) -> list[str]:
    mix = mix or (PLACE_MIX if kind == "place" else BUTTON_MIX)
    names, weights = list(mix), list(mix.values())
    if any(w < 0 for w in weights) or sum(weights) <= 0:
        raise SimulationError("mode weights must be non-negative with a positive sum")
    return random.Random(seed).choices(names, weights, k=n)


def simulate_dataset(kind: str, n: int, seed: int = 1, cfg: SimConfig | None = None, mix: dict[str, float] | None = None) -> list[dict[str, Any]]:
    """`n` independent episodes of `kind` ('place' or 'button_press') with latent-story labels."""
    if kind not in ("place", "button_press"):
        raise SimulationError("kind must be 'place' or 'button_press'")
    cfg = cfg or PRESETS["lab"]
    make = simulate_place if kind == "place" else simulate_button
    episodes = [make(i, mode, cfg, seed) for i, mode in enumerate(_modes(kind, n, seed, mix))]
    for ep in episodes:
        ep["tags"]["rig"] = "custom"
    return episodes


def simulate_load_recording(cfg: SimConfig, level_g: float, seconds: float, seed: int = 0) -> list[tuple[float, float]]:
    """A known-good recording on the simulated rig: a constant `level_g` on the plate, as (t_s, grams).

    Meant for `calibrate_thresholds`, so a study can calibrate on the same rig it then tests.
    """
    rng = random.Random(seed)
    return [(s["t"], s["grams"]) for s in _noisy_load(rng, cfg, seconds, lambda _t: level_g)]
