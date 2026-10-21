"""Command-line interface: `taskwitness verify`, `taskwitness batch`, `taskwitness check`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from taskwitness import __version__
from taskwitness.oracle import FAIL, PASS, UNKNOWN, EpisodeError, verify_bundle_integrity, verify_place

EXIT_CODES = {PASS: 0, FAIL: 1, UNKNOWN: 2}
EXIT_ERROR = 3


def _load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _write(obj: Any, out: str | None) -> None:
    text = json.dumps(obj, indent=2, ensure_ascii=False) + "\n"
    if out:
        Path(out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def cmd_verify(args: argparse.Namespace) -> int:
    bundle = verify_place(_load(Path(args.episode)))
    _write(bundle, args.out)
    print(f"{bundle['episode_id']}: {bundle['verdict']} - {bundle['reasons'][0]}", file=sys.stderr)
    return EXIT_CODES[bundle["verdict"]]


def cmd_batch(args: argparse.Namespace) -> int:
    paths = sorted(Path(args.directory).glob("*.json"))
    if not paths:
        print(f"no episode files (*.json) in {args.directory}", file=sys.stderr)
        return EXIT_ERROR

    rows = []
    counts = {PASS: 0, FAIL: 0, UNKNOWN: 0}
    labeled = mismatches = vision_false_pass = 0
    for path in paths:
        episode = _load(path)
        bundle = verify_place(episode)
        verdict = bundle["verdict"]
        counts[verdict] += 1
        label = episode.get("label", {}).get("verdict")
        row = {
            "file": path.name,
            "episode_id": bundle["episode_id"],
            "verdict": verdict,
            "vision_only_verdict": bundle["comparison"]["vision_only_verdict"],
            "claim_contradicted": bundle["claim"]["contradicted"],
            "label": label,
            "reason": bundle["reasons"][0],
            "bundle_sha256": bundle["integrity"]["bundle_sha256"],
        }
        if label is not None:
            labeled += 1
            row["matches_label"] = label == verdict
            mismatches += label != verdict
            vision_false_pass += label == FAIL and row["vision_only_verdict"] == PASS
        rows.append(row)
        print(f"{verdict:<8} {path.name}  ({row['reason']})", file=sys.stderr)

    report = {
        "taskwitness_version": __version__,
        "episodes": len(rows),
        "verdicts": counts,
        "labeled": labeled,
        "label_mismatches": mismatches,
        "vision_only_false_pass": vision_false_pass,
        "results": rows,
    }
    _write(report, args.out)
    print(
        f"{len(rows)} episodes: {counts[PASS]} PASS, {counts[FAIL]} FAIL, {counts[UNKNOWN]} UNKNOWN; "
        f"{mismatches}/{labeled} labeled episodes disagree with their label",
        file=sys.stderr,
    )
    return 1 if mismatches else 0


def cmd_check(args: argparse.Namespace) -> int:
    bundle = _load(Path(args.bundle))
    episode = _load(Path(args.episode)) if args.episode else None
    ok = verify_bundle_integrity(bundle, episode)
    print("OK: bundle integrity verified" if ok else "TAMPERED: bundle does not match its digests", file=sys.stderr)
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="taskwitness", description="Proof beyond perception.")
    parser.add_argument("--version", action="version", version=f"taskwitness {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("verify", help="verify one episode; exit 0=PASS 1=FAIL 2=UNKNOWN")
    p.add_argument("episode", help="episode JSON file")
    p.add_argument("--out", help="write the evidence bundle here instead of stdout")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("batch", help="verify every *.json episode in a directory")
    p.add_argument("directory")
    p.add_argument("--out", help="write the batch report here instead of stdout")
    p.set_defaults(func=cmd_batch)

    p = sub.add_parser("check", help="check an evidence bundle has not been altered")
    p.add_argument("bundle", help="evidence bundle JSON file")
    p.add_argument("--episode", help="also check the bundle was produced from this episode file")
    p.set_defaults(func=cmd_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (EpisodeError, OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
