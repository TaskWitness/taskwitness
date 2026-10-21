"""Real-data check: GraspOracle on REASSEMBLE Franka pick segments.

REASSEMBLE (Sliwowski et al., TU Wien 2025, CC-BY-4.0, arXiv 2502.05086) is a
contact-rich assembly dataset. This script uses the LeRobot v3 port
`robot-lev/reassemble`: per-frame gripper finger position and a per-segment human
success label. It tests one narrow claim: that the gripper's final finger position
separates successful picks from failed ones, with an UNKNOWN band, better than
trusting that the segment ended.

Protocol (fixed before looking at test results)
  * official split from meta/splits.json: bands are learned on train episodes only
  * per object, the width band is [min, max] of the final widths of train successes
  * objects with fewer than --min-train successes get no band and are skipped
  * judged on test episodes: GraspOracle, a band-free "gripper not fully open"
    check, and "trust that the segment ended" (always PASS)

Limits to keep in mind: the gripper width is the robot's own proprioception, not an
external sensor; labels come from the dataset's annotators; this is one dataset,
one robot, one task family.

Setup (about 450 MB, no videos needed):
    pip install "taskwitness[lerobot]"
    python examples/real_data/reassemble_grasp.py --download data/reassemble
    python examples/real_data/reassemble_grasp.py --root data/reassemble --out reassemble_grasp.json
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
import urllib.request
from pathlib import Path

from taskwitness import verify_episode
from taskwitness.evaluate import Row, judge_metrics, paired_false_pass, wilson
from taskwitness.grasp import GraspConfig

REPO = "https://huggingface.co/datasets/robot-lev/reassemble/resolve/main"
FILES = ["meta/info.json", "meta/tasks.parquet", "meta/splits.json", "meta/episodes/chunk-000/file-000.parquet"] + [f"data/chunk-000/file-{i:03d}.parquet" for i in range(10)]
FULLY_OPEN_M = 0.039  # the Franka gripper opens to 0.040 m per finger


def download(root: Path) -> None:
    for rel in FILES:
        target = root / rel
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        print(f"downloading {rel}", file=sys.stderr)
        urllib.request.urlretrieve(f"{REPO}/{rel}", target)


PICK_MAPPING = {
    # The band is a placeholder; main() sets each object's band from the training split.
    "task": {"type": "grasp", "object": {"name": "pick", "width_m_min": 0.0, "width_m_max": 0.05}},
    "sensors": {"gripper_width": {"column": "observation.state.gripper_position", "index": 0, "field": "width_m"}},
    "segments": {"column": "segment.index"},
    "label": {"column": "segment.success", "reduce": "last"},
    "task_prefix": "Pick ",
}


def load_pick_segments(root: Path):
    """Pick segments through TaskWitness's LeRobot adapter: one per annotated action, with its human label."""
    from taskwitness.integrations.lerobot import LeRobotDataset, episodes_from_lerobot

    splits = {int(k): v["split"] for k, v in json.loads((root / "meta/splits.json").read_text()).items()}
    segments = []
    for ep in episodes_from_lerobot(LeRobotDataset(root), PICK_MAPPING):
        samples = ep["sensors"]["gripper_width"]
        segments.append({
            "episode": ep["tags"]["lerobot_episode"], "segment": ep["tags"]["segment"],
            "object": ep["tags"]["task_text"][len("Pick "):].rstrip("."),
            "success": ep["label"]["verdict"] == "PASS", "split": splits.get(ep["tags"]["lerobot_episode"], "unassigned"),
            "t": [x["t"] for x in samples], "width": [x["width_m"] for x in samples],
        })
    return segments


def final_width(segment, window_s: float) -> float:
    t, w = segment["t"], segment["width"]
    end = t[-1]
    tail = sorted(x for tt, x in zip(t, w) if tt >= end - window_s)
    return tail[len(tail) // 2]


def window_std(segment, window_s: float) -> float:
    import statistics

    t, w = segment["t"], segment["width"]
    tail = [x for tt, x in zip(t, w) if tt >= t[-1] - window_s]
    return statistics.pstdev(tail)


def to_episode(segment, band, eid):
    return {
        "schema": "taskwitness.episode/v0", "episode_id": eid,
        "task": {"type": "grasp", "object": {"name": segment["object"], "width_m_min": band[0], "width_m_max": band[1]}},
        "sensors": {"gripper_width": [{"t": round(t, 5), "width_m": max(0.0, w)} for t, w in zip(segment["t"], segment["width"])]},
        "label": {"verdict": "PASS" if segment["success"] else "FAIL"},
    }


def pct(m):
    return "n/a" if m["rate"] is None else f"{m['count']}/{m['of']} = {m['rate']:.1%} [{m['ci95'][0]:.1%}, {m['ci95'][1]:.1%}]"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", help="directory with the downloaded dataset")
    ap.add_argument("--download", metavar="DIR", help="download the needed files (~450 MB) into DIR and exit")
    ap.add_argument("--margin-mm", type=float, default=1.0, help="UNKNOWN margin outside the band")
    ap.add_argument("--min-train", type=int, default=5, help="train successes needed to learn an object's band")
    ap.add_argument("--stability-alpha", type=float,
                    help="set the 'fingers stopped' threshold by conformal calibration on train successes, so that at most this "
                         "share of known-good windows is called MOVING (default: the oracle's fixed 0.5 mm)")
    ap.add_argument("--out", help="write the full results as JSON")
    args = ap.parse_args()
    if args.download:
        download(Path(args.download))
        return
    if not args.root:
        ap.error("pass --root DIR (or --download DIR first)")
    try:
        segments = load_pick_segments(Path(args.root))
    except ImportError:
        sys.exit("this script needs pyarrow: pip install 'taskwitness[lerobot]'")

    cfg = GraspConfig(margin_m=args.margin_mm / 1000)
    train = [s for s in segments if s["split"] == "train"]
    if args.stability_alpha is not None:
        from taskwitness.inference import conformal_upper

        stds = [window_std(s, cfg.settle_window_s) for s in train if s["success"]]
        threshold = conformal_upper(stds, args.stability_alpha)
        if threshold is None:
            sys.exit(f"alpha {args.stability_alpha} needs more train successes than the {len(stds)} available")
        cfg = GraspConfig(margin_m=cfg.margin_m, stability_std_m=threshold)
        print(f"conformal stability threshold from {len(stds)} train successes at alpha {args.stability_alpha}: {threshold * 1000:.2f} mm")
    test = [s for s in segments if s["split"] == "test"]
    finals = collections.defaultdict(list)
    for s in train:
        if s["success"]:
            finals[s["object"]].append(final_width(s, cfg.settle_window_s))
    bands = {obj: (min(v), max(v)) for obj, v in finals.items() if len(v) >= args.min_train}

    rows, skipped, detail = [], 0, []
    for i, s in enumerate(test):
        if s["object"] not in bands:
            skipped += 1
            continue
        bundle = verify_episode(to_episode(s, bands[s["object"]], f"test-{i}"), {"grasp": cfg})
        fw = final_width(s, cfg.settle_window_s)
        rows.append(Row(f"test-{i}", "PASS" if s["success"] else "FAIL", {
            "taskwitness": bundle["verdict"],
            "gripper_not_open": "PASS" if fw < FULLY_OPEN_M else "FAIL",
            "trust_segment_end": "PASS",
        }, s["object"]))
        detail.append((s, bundle, fw))

    print(f"segments: {len(segments)} picks; train {len(train)}, test {len(test)}; bands for {len(bands)} objects; test segments skipped (no band): {skipped}")
    print(f"test picks judged: {len(rows)} ({sum(r.label == 'PASS' for r in rows)} successes, {sum(r.label == 'FAIL' for r in rows)} failures)\n")
    results = {}
    for judge, name in (("trust_segment_end", "trust that the segment ended"), ("gripper_not_open", "band-free: gripper not fully open"), ("taskwitness", "TaskWitness GraspOracle")):
        m = judge_metrics(rows, judge)
        results[judge] = m
        print(f"{name}\n  false passes (of real failures): {pct(m['conditional_miss'])}\n  false fails (of real successes): {pct(m['false_fail'])}\n"
              f"  UNKNOWN: {pct(m['unknown'])}\n  accuracy when decided: {pct(m['accuracy_on_decided'])}\n")
    cmp = paired_false_pass(rows, "gripper_not_open", "taskwitness")
    print("paired false passes, band-free check vs GraspOracle:", cmp)
    results["paired_false_pass"] = cmp

    states = collections.Counter((("success" if seg["success"] else "failure"), b["oracles"][0]["state"]) for seg, b, _ in detail)
    print("oracle state by true outcome:")
    for (outcome, state), count in sorted(states.items()):
        print(f"  {outcome:8} {state:10} {count}")
    results["states"] = {f"{o}/{st}": c for (o, st), c in states.items()}
    print()

    missed = [(s, b, fw) for s, b, fw in detail if not s["success"] and b["verdict"] == "PASS"]
    print(f"\nfalse passes by object: {dict(collections.Counter(s['object'] for s, _, _ in missed))}")
    if missed:
        print("final widths (mm) of the missed failures:", sorted(round(fw * 1000, 1) for _, _, fw in missed)[:20])
    results["bands_mm"] = {k: [round(v[0] * 1000, 2), round(v[1] * 1000, 2)] for k, v in sorted(bands.items())}
    results["counts"] = {"picks": len(segments), "train": len(train), "test_judged": len(rows), "test_skipped_no_band": skipped, "objects_with_band": len(bands)}
    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=1, default=str))
    lo, hi = wilson(sum(r.label == "PASS" for r in rows), len(rows))
    print(f"\n(share of successes among judged test picks: Wilson [{lo:.1%}, {hi:.1%}])")


if __name__ == "__main__":
    main()
