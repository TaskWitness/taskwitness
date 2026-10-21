"""Command-line interface. Run `taskwitness --help` for the list of commands."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

from taskwitness import __version__
from taskwitness.adapters import (
    AdapterError,
    build_episode,
    button_samples,
    file_sha256,
    gripper_samples,
    load_cell_samples,
    read_json,
    read_series,
    video_frames,
)
from taskwitness.api import verify_episode
from taskwitness.calibration import CameraCalibration, LoadCellCalibration, fit_homography, fit_load_cell
from taskwitness.config import config_digest, load_config
from taskwitness.core import FAIL, PASS, UNKNOWN, VERDICTS, verify_bundle_integrity
from taskwitness.evaluate import Row, judge_audit, success_rate_estimate, summarize
from taskwitness.thresholds import calibrate_thresholds, window_stats

EXIT_CODES = {PASS: 0, FAIL: 1, UNKNOWN: 2}
EXIT_ERROR = 3


def _load(path: Path | str) -> Any:
    with Path(path).open(encoding="utf-8") as fh:
        return json.load(fh)


def _write(obj: Any, out: str | None) -> None:
    text = json.dumps(obj, indent=2, ensure_ascii=False) + "\n"
    if out:
        Path(out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def _say(message: str) -> None:
    print(message, file=sys.stderr)


def _episode_files(directories: list[str]) -> list[Path]:
    paths = []
    for d in directories:
        found = sorted(Path(d).glob("*.json"))
        if not found:
            raise AdapterError(f"no episode files (*.json) in {d}")
        paths += found
    return paths


def _run_all(directories: list[str], configs: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Verify every episode file; collect (episode, bundle, path) results and per-file errors."""
    results, errors = [], []
    for path in _episode_files(directories):
        try:
            episode = _load(path)
            results.append({"path": path, "episode": episode, "bundle": verify_episode(episode, configs)})
        except (ValueError, OSError) as exc:  # JSON, validation and I/O problems of one file
            errors.append({"file": str(path), "error": str(exc)})
            _say(f"ERROR    {path.name}  ({exc})")
    return results, errors


def _label(episode: dict[str, Any]) -> str | None:
    label = episode.get("label", {}).get("verdict") if isinstance(episode.get("label"), dict) else None
    return label if label in VERDICTS else None


def _rows(results: list[dict[str, Any]], by: str | None) -> list[Row]:
    rows = []
    for r in results:
        episode, bundle = r["episode"], r["bundle"]
        stratum = str(episode.get("tags", {}).get(by, "(none)")) if by else "(all)"
        verdicts = {"taskwitness": bundle["verdict"], "vision_only": bundle["comparison"]["vision_only_verdict"]}
        rows.append(Row(bundle["episode_id"], _label(episode), verdicts, stratum))
    return rows


# ----------------------------------------------------------------------------- verification


def cmd_verify(args: argparse.Namespace) -> int:
    bundle = verify_episode(_load(args.episode), load_config(args.config))
    _write(bundle, args.out)
    _say(f"{bundle['episode_id']}: {bundle['verdict']} - {bundle['reasons'][0]}")
    return EXIT_CODES[bundle["verdict"]]


def cmd_batch(args: argparse.Namespace) -> int:
    configs = load_config(args.config)
    results, errors = _run_all([args.directory], configs)
    counts = {PASS: 0, FAIL: 0, UNKNOWN: 0}
    rows, labeled, mismatches, vision_false_pass = [], 0, 0, 0
    for r in results:
        bundle, label = r["bundle"], _label(r["episode"])
        verdict = bundle["verdict"]
        counts[verdict] += 1
        row = {
            "file": r["path"].name,
            "episode_id": bundle["episode_id"],
            "oracle": bundle["oracle"],
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
        _say(f"{verdict:<8} {r['path'].name}  ({row['reason']})")

    report = {
        "taskwitness_version": __version__,
        "config_sha256": config_digest(configs),
        "episodes": len(rows),
        "verdicts": counts,
        "labeled": labeled,
        "label_mismatches": mismatches,
        "vision_only_false_pass": vision_false_pass,
        "errors": errors,
        "results": rows,
    }
    _write(report, args.out)
    _say(
        f"{len(rows)} episodes: {counts[PASS]} PASS, {counts[FAIL]} FAIL, {counts[UNKNOWN]} UNKNOWN; "
        f"{mismatches}/{labeled} labeled episodes disagree with their label"
        + (f"; {len(errors)} file(s) could not be verified" if errors else "")
    )
    if errors:
        return EXIT_ERROR
    return 1 if mismatches else 0


def cmd_check(args: argparse.Namespace) -> int:
    bundle = _load(args.bundle)
    episode = _load(args.episode) if args.episode else None
    ok = verify_bundle_integrity(bundle, episode)
    _say("OK: bundle integrity verified" if ok else "TAMPERED: bundle does not match its digests")
    return 0 if ok else 1


# ----------------------------------------------------------------------------- statistics


def _fmt_rate(m: dict[str, Any]) -> str:
    if m["rate"] is None:
        return "n/a"
    lo, hi = m["ci95"]
    return f"{m['count']}/{m['of']} = {m['rate']:.1%} [{lo:.1%}, {hi:.1%}]"


def _all_synthetic(results: list[dict[str, Any]]) -> bool:
    return bool(results) and all(r["episode"].get("synthetic") is True for r in results)


def cmd_evaluate(args: argparse.Namespace) -> int:
    configs = load_config(args.config)
    results, errors = _run_all(args.directories, configs)
    if args.order_by:
        results = _ordered(results, args.order_by)
    rows = _rows(results, args.by)
    report = {
        "taskwitness_version": __version__,
        "config_sha256": config_digest(configs),
        "all_synthetic": _all_synthetic(results),
        **summarize(rows, ["taskwitness", "vision_only"], compare=("vision_only", "taskwitness"), alpha=args.alpha),
        "episodes_evidence_sha256": {r["bundle"]["episode_id"]: r["bundle"]["integrity"]["evidence_sha256"] for r in results},
        "errors": errors,
    }
    _write(report, args.out)
    if report["all_synthetic"]:
        _say("NOTE: every episode is marked synthetic; these numbers are not measurements.")
    _say(f"audit coverage: {_fmt_rate(report['audit_coverage'])} of episodes carry a PASS/FAIL label")
    for judge, m in report["judges"].items():
        _say(
            f"{judge:<12} conditional miss {_fmt_rate(m['conditional_miss'])} | false fail {_fmt_rate(m['false_fail'])} "
            f"| unknown {_fmt_rate(m['unknown'])}"
        )
    p = report["paired_false_pass"]
    _say(f"paired false passes: vision-only only {p['vision_only_only']}, taskwitness only {p['taskwitness_only']}, "
         f"exact McNemar one-sided p = {p['p_one_sided']:.4g}")
    q = report["paired_false_pass_sequential"]
    verdict = f"rejects at discordant pair {q['stopped_at_pair']}" if q["rejected"] else "does not reject"
    _say(f"sequential test (anytime-valid, alpha {q['alpha']}): {verdict}; anytime p = {q['anytime_p']:.4g} "
         f"over {q['discordant_pairs']} discordant pairs")
    return EXIT_ERROR if errors else 0


def _ordered(results: list[dict[str, Any]], tag: str) -> list[dict[str, Any]]:
    """Sort episodes by a numeric tag (e.g. trial number) so sequential tests follow collection order."""
    def key(r: dict[str, Any]) -> float:
        try:
            return float(r["episode"].get("tags", {})[tag])
        except (KeyError, TypeError, ValueError):
            raise AdapterError(f"--order-by {tag}: episode {r['bundle']['episode_id']} has no numeric tag {tag!r}") from None

    return sorted(results, key=key)


def _read_judge(path: str) -> dict[str, Any]:
    if path.endswith(".json"):
        doc = _load(path)
        if not isinstance(doc, dict):
            raise AdapterError(f"{path}: expected an object mapping episode_id to score or verdict")
        items = doc.items()
    else:
        with open(path, encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            if not reader.fieldnames or not {"episode_id", "score"} <= set(reader.fieldnames):
                raise AdapterError(f"{path}: CSV needs 'episode_id' and 'score' columns")
            items = [(r["episode_id"], r["score"]) for r in reader]
    out: dict[str, Any] = {}
    for episode_id, value in items:
        text = str(value).strip()
        if text.upper() in VERDICTS:
            out[episode_id] = text.upper()
            continue
        try:
            score = float(text)
        except ValueError:
            raise AdapterError(f"{path}: {episode_id}: score must be a number in [0, 1] or PASS/FAIL/UNKNOWN") from None
        if not 0.0 <= score <= 1.0:
            raise AdapterError(f"{path}: {episode_id}: score {score} outside [0, 1]")
        out[episode_id] = score
    return out


def cmd_audit(args: argparse.Namespace) -> int:
    configs = load_config(args.config)
    results, errors = _run_all(args.episodes, configs)
    judgements = _read_judge(args.judge)
    reference, strata, tw = {}, {}, {}
    for r in results:
        episode, bundle = r["episode"], r["bundle"]
        eid = bundle["episode_id"]
        tw[eid] = bundle["verdict"]
        ref = _label(episode) if args.reference == "labels" else bundle["verdict"]
        if ref in (PASS, FAIL):
            reference[eid] = ref
        if args.by:
            strata[eid] = str(episode.get("tags", {}).get(args.by, "(none)"))
    report = {
        "taskwitness_version": __version__,
        "reference": args.reference,
        "all_synthetic": _all_synthetic(results),
        **judge_audit(judgements, reference, args.threshold, strata),
        "errors": errors,
    }
    if args.reference == "labels":
        # Same reference, same episodes: does physical evidence miss fewer failures than the judge?
        shared = sorted(set(judgements) & set(reference))
        rows = []
        for e in shared:
            j = judgements[e]
            jv = j if isinstance(j, str) else (PASS if j >= args.threshold else FAIL)
            rows.append(Row(e, reference[e], {"judge": jv, "taskwitness": tw[e]}))
        report["taskwitness_on_same_episodes"] = summarize(rows, ["taskwitness"])["judges"]["taskwitness"]
        report["paired_false_pass"] = summarize(rows, [], compare=("judge", "taskwitness"))["paired_false_pass"]
    else:
        report["note"] = "reference = TaskWitness decided verdicts, not human labels; measures agreement, not truth"
    _write(report, args.out)
    _say(f"matched {report['matched_episodes']} episodes; balanced accuracy {report['balanced_accuracy']}, "
         f"pass-rate bias {report['pass_rate_bias']}, ROC-AUC {report['roc_auc']}")
    return EXIT_ERROR if errors else 0


def cmd_estimate(args: argparse.Namespace) -> int:
    configs = load_config(args.config)
    results, errors = _run_all(args.directories, configs)
    rows = _rows(results, None)
    report = {
        "taskwitness_version": __version__,
        "config_sha256": config_digest(configs),
        "all_synthetic": _all_synthetic(results),
        "episodes": len(rows),
        **success_rate_estimate(rows, "taskwitness", args.unknown_as, args.confidence),
        "errors": errors,
    }
    _write(report, args.out)
    _say(f"labels only (Wilson):          {_fmt_rate(report['labels_only'])}")
    _say(f"labels only (finite-sample):   CI {report['labels_only_finite_sample']['ci']}")
    for key, name in (("prediction_powered", "prediction-powered (CLT):  "), ("prediction_powered_finite_sample", "prediction-powered (finite): ")):
        ppi = report[key]
        if "ci" in ppi:
            _say(f"{name} CI {ppi['ci']}")
        else:
            _say(f"{name} unavailable: {ppi['error']}")
    _say("choose which interval to report before looking; picking the narrowest afterwards voids its coverage")
    return EXIT_ERROR if errors else 0


# ----------------------------------------------------------------------------- data preparation


def _numbers(path: str) -> list[float]:
    rows, _ = read_series(Path(path).read_text(encoding="utf-8").splitlines(), path)
    try:
        return [float(v) for _, v in rows]
    except ValueError as exc:
        raise AdapterError(f"{path}: raw readings must be numbers ({exc})") from None


def cmd_calibrate_load_cell(args: argparse.Namespace) -> int:
    refs = []
    for spec in args.ref:
        mass, _, path = spec.partition("=")
        try:
            refs.append((float(mass), _numbers(path)))
        except ValueError:
            raise AdapterError(f"--ref must look like MASS_G=FILE, got {spec!r}") from None
    cal = fit_load_cell(_numbers(args.empty), refs)
    _write(cal.to_dict(), args.out)
    _say(f"slope {cal.counts_per_gram:.4f} counts/g, noise {cal.noise_std_g:.3f} g, "
         f"residual rms {cal.residual_rms_g:.3f} g, max error {cal.max_abs_error_g:.3f} g")
    return 0


def cmd_calibrate_camera(args: argparse.Namespace) -> int:
    doc = read_json(args.points)
    try:
        pixels = [tuple(p["pixel"]) for p in doc]
        plate = [tuple(p["plate"]) for p in doc]
    except (TypeError, KeyError):
        raise AdapterError(f"{args.points}: expected a list of {{\"pixel\": [u, v], \"plate\": [x, y]}}") from None
    cal = fit_homography(pixels, plate)
    _write(cal.to_dict(), args.out)
    _say(f"{cal.points} points, reprojection rms {cal.rms_error:.4g}, max {cal.max_error:.4g} (plate units)")
    return 0


def _grams_series(path: str, cal: LoadCellCalibration | None) -> list[tuple[float, float]]:
    rows, _ = read_series(Path(path).read_text(encoding="utf-8").splitlines(), path)
    try:
        values = [float(v) for _, v in rows]
    except ValueError as exc:
        raise AdapterError(f"{path}: readings must be numbers ({exc})") from None
    return [(t / 1000.0, cal.to_grams(v) if cal else v) for (t, _), v in zip(rows, values)]


def cmd_calibrate_thresholds(args: argparse.Namespace) -> int:
    cal = LoadCellCalibration.from_dict(read_json(args.load_cell_cal)) if args.load_cell_cal else None
    empty = [w for path in args.empty for w in window_stats(_grams_series(path, cal), args.window_s, args.min_samples)]
    objects: dict[float, list[tuple[float, float]]] = {}
    for spec in args.object or []:
        mass, _, path = spec.partition("=")
        try:
            mass_g = float(mass)
        except ValueError:
            raise AdapterError(f"--object must look like MASS_G=FILE, got {spec!r}") from None
        objects.setdefault(mass_g, []).extend(window_stats(_grams_series(path, cal), args.window_s, args.min_samples))
    report = calibrate_thresholds(empty, objects, args.alpha, args.window_s)
    config_doc = {"place": report["place_config"]}
    _write({**report, "config": config_doc}, args.out)
    _say(f"{report['windows']['empty']} empty windows, objects {report['windows']['object']}")
    _say("place config: " + json.dumps(report["place_config"]))
    for warning in report["warnings"]:
        _say(f"WARNING: {warning}")
    return 0


def _parse_bool(text: str) -> bool:
    if text.lower() in ("true", "yes", "1"):
        return True
    if text.lower() in ("false", "no", "0"):
        return False
    raise argparse.ArgumentTypeError("expected true or false")


def cmd_ingest(args: argparse.Namespace) -> int:
    task = read_json(args.task)
    if not isinstance(task, dict):
        raise AdapterError(f"{args.task}: task file must be a JSON object")
    logs = {"load_cell": args.load_cell, "gripper": args.gripper} if args.kind == "place" else {"button": args.button}
    if args.kind == "place" and not args.load_cell:
        raise AdapterError("a place episode needs --load-cell")
    if args.kind == "button_press" and not args.button:
        raise AdapterError("a button episode needs --button")

    series, sources = {}, {}
    for name, path in logs.items():
        if path:
            series[name] = read_series(Path(path).read_text(encoding="utf-8").splitlines(), path, strict=not args.lenient)
            sources[Path(path).name] = file_sha256(path)
    t0 = args.t0_ms if args.t0_ms is not None else min(rows[0][0] for rows, _ in series.values())

    cal = None
    if args.kind == "place" and args.load_cell_cal:
        cal = LoadCellCalibration.from_dict(read_json(args.load_cell_cal))
        sources[Path(args.load_cell_cal).name] = file_sha256(args.load_cell_cal)
    sensors, reports = {}, []
    for name, (rows, report) in series.items():
        if name == "load_cell":
            sensors[name] = load_cell_samples(rows, report, t0, cal, strict=not args.lenient)
        elif name == "gripper":
            sensors[name] = gripper_samples(rows, report, t0, strict=not args.lenient)
        else:
            sensors[name] = button_samples(rows, report, t0, strict=not args.lenient)
        reports.append(report.as_dict())

    video = None
    if args.video:
        camera = CameraCalibration.from_dict(read_json(args.camera_cal)) if args.camera_cal else None
        if args.camera_cal:
            sources[Path(args.camera_cal).name] = file_sha256(args.camera_cal)
        key = "object_xy" if args.kind == "place" else "tool_xy"
        video, info = video_frames(read_json(args.video), key, args.video_offset_s, camera)
        sources[Path(args.video).name] = file_sha256(args.video)
        reports.append({"source": args.video, **info})

    tags = {}
    for spec in args.tag or []:
        key, sep, value = spec.partition("=")
        if not sep or not key:
            raise AdapterError(f"--tag must look like KEY=VALUE, got {spec!r}")
        tags[key] = value
    episode = build_episode(args.kind, task, args.id, sensors, video, args.claim, args.label, args.note, tags, sources)
    episode["provenance"]["t0_ms"] = t0
    verify_episode(episode)  # validate before writing
    _write(episode, args.out)
    for rep in reports:
        _say(f"{rep['source']}: " + ", ".join(f"{k}={v}" for k, v in rep.items() if k != "source"))
    return 0


def cmd_track(args: argparse.Namespace) -> int:
    from taskwitness.vision import ColorBlobTracker, read_video, track_frames

    def ints(text: str, n: int, what: str) -> tuple[int, ...]:
        try:
            values = tuple(int(v) for v in text.split(","))
        except ValueError:
            values = ()
        if len(values) != n:
            raise AdapterError(f"{what} must be {n} comma-separated integers")
        return values

    tracker = ColorBlobTracker(
        target_rgb=ints(args.color, 3, "--color"),
        tolerance=args.tolerance,
        min_area_px=args.min_area,
        full_confidence_area_px=max(args.min_area, args.full_area),
        roi=ints(args.roi, 4, "--roi") if args.roi else None,
    )
    camera = CameraCalibration.from_dict(read_json(args.camera_cal)) if args.camera_cal else None
    doc = track_frames(read_video(args.video, stride=args.stride), tracker, camera)
    doc["source"] = {"file": Path(args.video).name, "sha256": file_sha256(args.video)}
    _write(doc, args.out)
    seen = sum(f["xy"] is not None for f in doc["frames"])
    _say(f"{len(doc['frames'])} frames, target detected in {seen}")
    return 0


# ----------------------------------------------------------------------------- signing


def cmd_keygen(args: argparse.Namespace) -> int:
    from taskwitness.signing import generate_keypair

    private, public = generate_keypair(args.dir, args.name)
    _say(f"wrote {private} (keep secret) and {public} (share)")
    return 0


def cmd_sign(args: argparse.Namespace) -> int:
    from taskwitness.signing import sign_bundle

    signature = sign_bundle(_load(args.bundle), Path(args.key).read_bytes())
    _write(signature, args.out)
    _say(f"signed {signature['episode_id']} with key {signature['key_id']}")
    return 0


def cmd_verify_signature(args: argparse.Namespace) -> int:
    from taskwitness.signing import verify_signature

    trusted = Path(args.public_key).read_bytes() if args.public_key else None
    result = verify_signature(_load(args.bundle), _load(args.signature), trusted)
    _say(("OK: " if result["ok"] else "INVALID: ") + f"{result['reason']} (key {result['key_id']})")
    return 0 if result["ok"] else 1


# ----------------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="taskwitness", description="Proof beyond perception.")
    parser.add_argument("--version", action="version", version=f"taskwitness {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def config_arg(p):
        p.add_argument("--config", help="oracle config JSON; freeze it before the experiment")

    p = sub.add_parser("verify", help="verify one episode; exit 0=PASS 1=FAIL 2=UNKNOWN")
    p.add_argument("episode", help="episode JSON file")
    p.add_argument("--out", help="write the evidence bundle here instead of stdout")
    config_arg(p)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("batch", help="verify every *.json episode in a directory")
    p.add_argument("directory")
    p.add_argument("--out", help="write the batch report here instead of stdout")
    config_arg(p)
    p.set_defaults(func=cmd_batch)

    p = sub.add_parser("check", help="check an evidence bundle has not been altered")
    p.add_argument("bundle", help="evidence bundle JSON file")
    p.add_argument("--episode", help="also check the bundle was produced from this episode file")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("evaluate", help="false-pass / false-fail statistics against human labels")
    p.add_argument("directories", nargs="+")
    p.add_argument("--by", help="break results down by this episode tag (e.g. failure_mode)")
    p.add_argument("--order-by", help="numeric tag giving the collection order for the sequential test (default: file name)")
    p.add_argument("--alpha", type=float, default=0.05, help="level of the sequential test")
    p.add_argument("--out")
    config_arg(p)
    p.set_defaults(func=cmd_evaluate)

    p = sub.add_parser("audit", help="audit an external success judge (VLM, reward model) on the same episodes")
    p.add_argument("--judge", required=True, help="CSV (episode_id,score) or JSON {episode_id: score|verdict}")
    p.add_argument("--episodes", nargs="+", required=True, help="episode directories")
    p.add_argument("--reference", choices=["labels", "taskwitness"], default="labels",
                   help="compare against human labels (default) or TaskWitness decided verdicts")
    p.add_argument("--threshold", type=float, default=0.5, help="score >= threshold counts as PASS")
    p.add_argument("--by", help="break results down by this episode tag")
    p.add_argument("--out")
    config_arg(p)
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("estimate", help="prediction-powered success-rate estimate from verdicts + a few labels")
    p.add_argument("directories", nargs="+")
    p.add_argument("--unknown-as", type=float, default=0.5, help="prediction used for UNKNOWN verdicts")
    p.add_argument("--confidence", type=float, default=0.95)
    p.add_argument("--out")
    config_arg(p)
    p.set_defaults(func=cmd_estimate)

    p = sub.add_parser("calibrate", help="fit load-cell or camera calibration")
    csub = p.add_subparsers(dest="target", required=True)
    c = csub.add_parser("load-cell", help="tare and scale from raw readings (t_ms,raw logs)")
    c.add_argument("--empty", required=True, help="log recorded with the plate empty")
    c.add_argument("--ref", action="append", required=True, help="MASS_G=FILE, repeat for each reference mass")
    c.add_argument("--out")
    c.set_defaults(func=cmd_calibrate_load_cell)
    c = csub.add_parser("thresholds", help="conformal PlaceOracle thresholds from known-good recordings")
    c.add_argument("--empty", nargs="+", required=True, help="logs recorded with the plate empty (t_ms,value)")
    c.add_argument("--object", action="append", help="MASS_G=FILE with the object resting on the plate; repeatable")
    c.add_argument("--load-cell-cal", help="load-cell calibration if the logs are raw counts")
    c.add_argument("--window-s", type=float, default=1.0, help="window length, = settle_window_s of the oracle")
    c.add_argument("--min-samples", type=int, default=5)
    c.add_argument("--alpha", type=float, default=0.05, help="a known-good window exceeds a threshold with probability <= alpha")
    c.add_argument("--out")
    c.set_defaults(func=cmd_calibrate_thresholds)
    c = csub.add_parser("camera", help="pixel-to-plate homography from >= 4 point pairs")
    c.add_argument("--points", required=True, help='JSON list of {"pixel": [u, v], "plate": [x, y]}')
    c.add_argument("--out")
    c.set_defaults(func=cmd_calibrate_camera)

    p = sub.add_parser("ingest", help="build an episode from raw sensor logs and tracker output")
    p.add_argument("kind", choices=["place", "button_press"])
    p.add_argument("--task", required=True, help="task JSON (object + target_zone, or button)")
    p.add_argument("--id", required=True, help="episode id")
    p.add_argument("--load-cell", help="t_ms,value log (raw counts with --load-cell-cal, else grams)")
    p.add_argument("--load-cell-cal", help="load-cell calibration from 'calibrate load-cell'")
    p.add_argument("--gripper", help="t_ms,open|closed log")
    p.add_argument("--button", help="t_ms,1|0 switch log")
    p.add_argument("--video", help="tracker output from 'taskwitness track'")
    p.add_argument("--camera-cal", help="camera calibration, when tracker output is in pixels")
    p.add_argument("--video-offset-s", type=float, default=0.0, help="add to video timestamps to reach sensor time")
    p.add_argument("--t0-ms", type=float, help="sensor time that becomes t=0 (default: earliest sample)")
    p.add_argument("--claim", type=_parse_bool, help="the robot's own success claim, if any")
    p.add_argument("--label", choices=list(VERDICTS), help="independent human label")
    p.add_argument("--note", help="note stored with the label")
    p.add_argument("--tag", action="append", help="KEY=VALUE tag, e.g. failure_mode=bounce; repeatable")
    p.add_argument("--lenient", action="store_true", help="skip malformed log lines instead of failing")
    p.add_argument("--out")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("track", help="track a coloured object or marker in a video (needs [vision] extra)")
    p.add_argument("video")
    p.add_argument("--color", required=True, help="target colour as R,G,B")
    p.add_argument("--tolerance", type=float, default=60.0, help="max RGB distance to the target colour")
    p.add_argument("--min-area", type=int, default=20, help="pixels needed to report a detection")
    p.add_argument("--full-area", type=int, default=200, help="pixels for full size confidence")
    p.add_argument("--roi", help="x0,y0,x1,y1: only look inside this pixel rectangle")
    p.add_argument("--stride", type=int, default=1, help="process every Nth frame")
    p.add_argument("--camera-cal", help="map detections to plate coordinates")
    p.add_argument("--out")
    p.set_defaults(func=cmd_track)

    p = sub.add_parser("keygen", help="create an Ed25519 key pair for signing bundles (needs [sign] extra)")
    p.add_argument("--dir", default=".")
    p.add_argument("--name", default="taskwitness")
    p.set_defaults(func=cmd_keygen)

    p = sub.add_parser("sign", help="sign an evidence bundle")
    p.add_argument("bundle")
    p.add_argument("--key", required=True, help="private key PEM from keygen")
    p.add_argument("--out")
    p.set_defaults(func=cmd_sign)

    p = sub.add_parser("verify-signature", help="verify a bundle signature")
    p.add_argument("bundle")
    p.add_argument("signature")
    p.add_argument("--public-key", help="pin this trusted public key PEM")
    p.set_defaults(func=cmd_verify_signature)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, OSError) as exc:  # TaskWitnessError and JSONDecodeError are ValueErrors
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
