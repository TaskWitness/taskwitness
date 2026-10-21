"""Simulation study: how TaskWitness behaves as the rig gets worse, against known ground truth.

    python examples/simulation/study.py            # all tables, a few minutes
    python examples/simulation/study.py --n 400    # quick look

Everything here is SYNTHETIC. The simulator's failure modes and noise levels are
assumptions (see docs/SIMULATION.en.md), so read the tables as "how the method
behaves under these assumptions", not as measurements of a real rig.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys

from taskwitness import verify_episode
from taskwitness.config import parse_config
from taskwitness.evaluate import Row, judge_metrics, wilson
from taskwitness.inference import sequential_paired_test
from taskwitness.oracle import PlaceOracleConfig
from taskwitness.simulation import PLACE_MIX, preset, simulate_dataset, simulate_load_recording
from taskwitness.thresholds import calibrate_thresholds, window_stats


def run(kind, cfg, n, seed, mix=None, configs=None):
    rows = []
    for e in simulate_dataset(kind, n, seed, cfg, mix):
        b = verify_episode(e, configs)
        rows.append(Row(e["episode_id"], e["label"]["verdict"], {"tw": b["verdict"], "vision": b["comparison"]["vision_only_verdict"]}, e["tags"]["failure_mode"]))
    return rows


def pct(m):
    if m["rate"] is None:
        return "n/a"
    lo, hi = m["ci95"]
    return f"{m['rate']:.1%} [{lo:.1%}, {hi:.1%}]"


def false_unknown_on_true_pass(rows, judge):
    passes = [r for r in rows if r.label == "PASS"]
    k = sum(r.verdicts[judge] == "UNKNOWN" for r in passes)
    return {"count": k, "of": len(passes), "rate": k / len(passes), "ci95": wilson(k, len(passes))}


def unknown_on_plain_success(rows, judge):
    """UNKNOWN among ordinary clean successes only, excluding the deliberately hard ones (late, slow, dropout)."""
    plain = [r for r in rows if r.stratum == "success"]
    k = sum(r.verdicts[judge] == "UNKNOWN" for r in plain)
    return {"count": k, "of": len(plain), "rate": k / len(plain), "ci95": wilson(k, len(plain))}


def table(title, header, lines):
    print(f"\n### {title}\n")
    print("| " + " | ".join(header) + " |")
    print("|" + "|".join(["---"] * len(header)) + "|")
    for line in lines:
        print("| " + " | ".join(str(c) for c in line) + " |")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2000, help="episodes per table cell")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--planning-runs", type=int, default=100, help="repeated runs for the trials-needed table")
    ap.add_argument("--planning-trials", type=int, default=600, help="trials per planning run")
    args = ap.parse_args()
    n, seed = args.n, args.seed
    out = {}

    # 1. rigs, with and without the plate-empty-at-start check
    lines = []
    for name in ("clean", "lab", "noisy"):
        cfg = preset(name)
        for label, pc in (("on", PlaceOracleConfig()), ("off", PlaceOracleConfig(baseline_window_s=0.0))):
            rows = run("place", cfg, n, seed, configs={"place": pc})
            tw, vi = judge_metrics(rows, "tw"), judge_metrics(rows, "vision")
            lines.append([name, label, pct(tw["conditional_miss"]), pct(vi["conditional_miss"]), pct(tw["false_fail"]), pct(tw["unknown"]), pct(unknown_on_plain_success(rows, "tw"))])
            out[f"place/{name}/baseline_{label}"] = {"tw": tw, "vision": vi}
    table("Place: rig quality and the plate-empty-at-start check",
          ["rig", "baseline check", "TaskWitness false passes (of real failures)", "vision-only false passes", "TaskWitness false fails", "TaskWitness UNKNOWN (all)", "TaskWitness UNKNOWN (of ordinary successes)"], lines)

    # 2. verdicts by latent failure mode (lab rig)
    rows = run("place", preset("lab"), n, seed)
    modes = sorted({r.stratum for r in rows})
    lines = []
    for mode in modes:
        group = [r for r in rows if r.stratum == mode]
        c = {v: sum(r.verdicts["tw"] == v for r in group) for v in ("PASS", "FAIL", "UNKNOWN")}
        vc = {v: sum(r.verdicts["vision"] == v for r in group) for v in ("PASS", "FAIL", "UNKNOWN")}
        lines.append([mode, group[0].label, len(group), f"{c['PASS']} / {c['FAIL']} / {c['UNKNOWN']}", f"{vc['PASS']} / {vc['FAIL']} / {vc['UNKNOWN']}"])
    table("Place, lab rig: verdicts by what really happened", ["latent mode", "truth", "episodes", "TaskWitness PASS / FAIL / UNKNOWN", "vision-only PASS / FAIL / UNKNOWN"], lines)

    # 3. load-cell noise: default vs conformally calibrated thresholds
    lines = []
    for sigma in (0.1, 0.4, 1.0, 2.0, 4.0):
        cfg = preset("lab", load_noise_g=sigma)
        try:
            empty = window_stats(simulate_load_recording(cfg, 0.0, 120, 11), 1.0)
            block = window_stats(simulate_load_recording(cfg, cfg.object_mass_g, 120, 12), 1.0)
            cal = calibrate_thresholds(empty, {cfg.object_mass_g: block})
            calibrated = parse_config({"place": cal["place_config"]})
        except Exception as exc:  # report, don't hide
            calibrated, cal = None, {"place_config": {"error": str(exc)}}
        for label, configs in (("default", None), ("calibrated", calibrated)):
            if configs is None and label == "calibrated":
                lines.append([sigma, label, "n/a", "n/a", "n/a", "n/a"])
                continue
            rows = run("place", cfg, n, seed, configs=configs)
            tw = judge_metrics(rows, "tw")
            th = (configs or {}).get("place", PlaceOracleConfig())
            lines.append([sigma, label, f"{th.stability_std_g:.2f} / {th.empty_threshold_g:.2f} / {th.mass_tolerance_abs_g:.2f}", pct(tw["conditional_miss"]), pct(unknown_on_plain_success(rows, "tw")), pct(tw["false_fail"])])
        out[f"noise/{sigma}"] = cal["place_config"]
    table("Place: load-cell noise, default thresholds vs conformal calibration",
          ["noise sd (g)", "thresholds", "stability / empty / tolerance (g)", "false passes", "UNKNOWN of ordinary successes", "false fails"], lines)

    # 3b. the robot's own wrist force sensor as the load cell (noise and offset measured on REASSEMBLE)
    lines = []
    for name in ("lab", "wrist_ft"):
        rows = run("place", preset(name), n, seed)
        tw, vi = judge_metrics(rows, "tw"), judge_metrics(rows, "vision")
        lines.append([name, pct(tw["conditional_miss"]), pct(tw["false_fail"]), pct(tw["unknown"]), pct(unknown_on_plain_success(rows, "tw")), pct(vi["conditional_miss"])])
    table("Place: a dedicated load cell vs the robot's own wrist force sensor (52 g block; wrist noise 11.6 g, offset sd 106 g, measured on REASSEMBLE)",
          ["sensor", "TaskWitness false passes", "false fails", "UNKNOWN (all)", "UNKNOWN (ordinary successes)", "vision-only false passes"], lines)

    # 4. stale tracker
    lines = []
    for p in (0.0, 0.3, 0.6, 0.9):
        rows = run("place", preset("lab", stale_tracker_prob=p), n, seed)
        tw, vi = judge_metrics(rows, "tw"), judge_metrics(rows, "vision")
        lines.append([p, pct(vi["conditional_miss"]), pct(tw["conditional_miss"])])
    table("Place: how often the video tracker freezes on a stale position", ["stale tracker prob", "vision-only false passes", "TaskWitness false passes"], lines)

    # 5. sampling
    lines = []
    for hz, min_samples in ((5.0, 5), (5.0, 2), (20.0, 5)):
        for drop in (0.0, 0.05, 0.2, 0.4):
            rows = run("place", preset("lab", load_hz=hz, sample_drop_prob=drop), n, seed, configs={"place": PlaceOracleConfig(min_settle_samples=min_samples)})
            tw = judge_metrics(rows, "tw")
            lines.append([hz, min_samples, drop, pct(tw["conditional_miss"]), pct(unknown_on_plain_success(rows, "tw")), pct(tw["unknown"])])
    table("Place: load-cell sample rate and dropped samples", ["load Hz", "min_settle_samples", "dropped samples", "false passes", "UNKNOWN of ordinary successes", "UNKNOWN (all)"], lines)

    # 6. clock offset
    lines = []
    for off in (0.0, 0.15, 0.5, 1.0):
        rows = run("place", preset("lab", clock_offset_s=off), n, seed)
        tw = judge_metrics(rows, "tw")
        lines.append([off, pct(tw["conditional_miss"]), pct(unknown_on_plain_success(rows, "tw"))])
    table("Place: video clock off by up to this many seconds", ["offset (s)", "false passes", "UNKNOWN of ordinary successes"], lines)

    # 7. residual risk: another object lands on the plate mid-trial
    lines = []
    for share in (0, 3, 10, 20):
        mix = dict(PLACE_MIX)
        mix["foreign_object"] = share
        rows = run("place", preset("lab"), n, seed, mix=mix)
        tw, vi = judge_metrics(rows, "tw"), judge_metrics(rows, "vision")
        lines.append([f"{share} / {sum(mix.values()):.0f}", pct(tw["conditional_miss"]), pct(vi["conditional_miss"])])
    table("Place: share of trials where another object lands on the plate mid-trial", ["foreign_object weight / total", "TaskWitness false passes", "vision-only false passes"], lines)

    # 8. button
    lines = []
    for name in ("clean", "lab", "noisy"):
        rows = run("button_press", preset(name), n, seed)
        tw, vi = judge_metrics(rows, "tw"), judge_metrics(rows, "vision")
        lines.append([name, pct(tw["conditional_miss"]), pct(vi["conditional_miss"]), pct(tw["false_fail"]), pct(tw["unknown"])])
    table("Button press: rig quality", ["rig", "TaskWitness false passes", "vision-only false passes", "TaskWitness false fails", "TaskWitness UNKNOWN (all)"], lines)
    lines = []
    for hz in (20.0, 50.0, 100.0, 500.0):
        rows = run("button_press", preset("lab", switch_hz=hz), n, seed)
        tw = judge_metrics(rows, "tw")
        brush = [r for r in rows if r.stratum == "light_brush"]
        brush_pass = sum(r.verdicts["tw"] == "PASS" for r in brush)
        brush_unknown = sum(r.verdicts["tw"] == "UNKNOWN" for r in brush)
        lines.append([hz, pct(tw["conditional_miss"]), f"{brush_pass} / {len(brush)}", f"{brush_unknown} / {len(brush)}", pct(tw["false_fail"]), pct(tw["unknown"])])
    table("Button press: switch sampling rate (a contact can only be bracketed between samples; an unresolvable hold is UNKNOWN)", ["switch Hz", "false passes", "light brushes counted as presses", "light brushes left UNKNOWN", "false fails", "UNKNOWN (all)"], lines)

    # 9. planning: how many trials until the sequential test decides?
    stops, trials = [], args.planning_trials
    for rep in range(args.planning_runs):
        rows = run("place", preset("lab"), trials, 1000 + rep)
        outcomes, index_of = [], []
        for i, r in enumerate(rows):
            if r.label == "FAIL":
                a, b = r.verdicts["vision"] == "PASS", r.verdicts["tw"] == "PASS"
                if a != b:
                    outcomes.append(int(a))
                    index_of.append(i + 1)
        stop = None
        for j in range(1, len(outcomes) + 1):
            if sequential_paired_test(outcomes[:j])["rejected"]:
                stop = index_of[j - 1]
                break
        stops.append(stop)
    decided = [s for s in stops if s]
    table("Planning: trials until the anytime-valid test says TaskWitness has fewer false passes than vision-only (lab rig, alpha 0.05)",
          ["runs", f"decided within {trials} trials", "median trials", "90th percentile"],
          [[len(stops), f"{len(decided)}/{len(stops)}", statistics.median(decided) if decided else "n/a",
            sorted(decided)[int(0.9 * len(decided)) - 1] if decided else "n/a"]])
    out["planning"] = {"decided": len(decided), "runs": len(stops), "median": statistics.median(decided) if decided else None}
    print("\n<!-- machine-readable -->", file=sys.stderr)
    json.dump(out, sys.stderr, default=str)


if __name__ == "__main__":
    main()
