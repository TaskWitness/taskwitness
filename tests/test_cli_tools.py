import json
import shutil
from pathlib import Path

import pytest

from taskwitness.cli import main

ROOT = Path(__file__).resolve().parent.parent / "examples"


def write(path: Path, text: str) -> str:
    path.write_text(text, encoding="utf-8")
    return str(path)


def read(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_batch_continues_past_bad_files(tmp_path):
    shutil.copy(ROOT / "synthetic" / "01_clean_success.json", tmp_path)
    write(tmp_path / "broken.json", '{"schema": "taskwitness.episode/v0"')
    write(tmp_path / "wrong.json", '{"schema": "nope"}')
    out = tmp_path / "report" / "r.json"
    out.parent.mkdir()
    assert main(["batch", str(tmp_path), "--out", str(out)]) == 3
    report = read(out)
    assert report["episodes"] == 1 and len(report["errors"]) == 2


def test_verify_with_config(tmp_path):
    cfg = write(tmp_path / "cfg.json", json.dumps({"button_press": {"min_hold_s": 0.02}}))
    episode = str(ROOT / "synthetic_button" / "b03_light_brush.json")
    assert main(["verify", episode, "--out", str(tmp_path / "b.json")]) == 1
    assert main(["verify", episode, "--config", cfg, "--out", str(tmp_path / "b.json")]) == 0
    assert main(["verify", episode, "--config", write(tmp_path / "bad.json", '{"place": {"x": 1}}')]) == 3


def test_evaluate_report(tmp_path):
    out = tmp_path / "eval.json"
    assert main(["evaluate", str(ROOT / "synthetic"), str(ROOT / "synthetic_button"), "--out", str(out)]) == 0
    report = read(out)
    assert report["all_synthetic"] is True
    assert report["episodes"] == 11
    assert report["judges"]["taskwitness"]["conditional_miss"]["count"] == 0
    assert report["judges"]["vision_only"]["conditional_miss"]["count"] == 4
    assert report["paired_false_pass"]["p_one_sided"] == pytest.approx(0.0625)
    assert len(report["config_sha256"]) == 64


def test_audit_external_judge(tmp_path):
    judge = write(
        tmp_path / "judge.csv",
        "episode_id,score\n01_clean_success,0.92\n02_not_released,0.88\n03_bounced_off,0.71\n"
        "b01_clean_press,0.9\nb02_hover_no_contact,0.8\nb03_light_brush,0.3\n",
    )
    out = tmp_path / "audit.json"
    assert main(["audit", "--judge", judge, "--episodes", str(ROOT / "synthetic"), str(ROOT / "synthetic_button"), "--out", str(out)]) == 0
    report = read(out)
    assert report["matched_episodes"] == 6
    assert report["judges"]["judge"]["conditional_miss"]["count"] == 3
    assert report["taskwitness_on_same_episodes"]["conditional_miss"]["count"] == 0
    assert report["paired_false_pass"]["judge_only"] == 3
    bad = write(tmp_path / "bad.csv", "episode_id,score\n01_clean_success,1.7\n")
    assert main(["audit", "--judge", bad, "--episodes", str(ROOT / "synthetic")]) == 3


def test_calibrate_and_ingest_end_to_end(tmp_path):
    tare, k = 8_000_000, 400.0
    empty = write(tmp_path / "empty.csv", "t_ms,raw\n" + "\n".join(f"{i * 100},{tare + (i % 3) - 1}" for i in range(20)))
    r100 = write(tmp_path / "r100.csv", "\n".join(f"{i * 100},{tare + k * 100 + (i % 2)}" for i in range(20)))
    r500 = write(tmp_path / "r500.csv", "\n".join(f"{i * 100},{tare + k * 500 - (i % 2)}" for i in range(20)))
    cal = tmp_path / "lc.cal.json"
    assert main(["calibrate", "load-cell", "--empty", empty, "--ref", f"100={r100}", "--ref", f"500={r500}", "--out", str(cal)]) == 0
    assert read(cal)["load_cell"]["counts_per_gram"] == pytest.approx(k, rel=1e-3)

    points = write(tmp_path / "points.json", json.dumps([
        {"pixel": [0, 0], "plate": [0.0, 0.0]}, {"pixel": [640, 0], "plate": [0.64, 0.0]},
        {"pixel": [640, 480], "plate": [0.64, 0.48]}, {"pixel": [0, 480], "plate": [0.0, 0.48]},
    ]))
    cam = tmp_path / "cam.cal.json"
    assert main(["calibrate", "camera", "--points", points, "--out", str(cam)]) == 0

    load_log = write(tmp_path / "load.csv", "# WitnessNode\nt_ms,raw\n" + "\n".join(
        f"{10_000 + i * 50},{tare + (k * 52.0 if i >= 40 else 0) + (i % 2)}" for i in range(81)))
    grip_log = write(tmp_path / "grip.csv", "10000,closed\n12200,open\n")
    video = write(tmp_path / "video.json", json.dumps({
        "schema": "taskwitness.video/v0", "coords": "pixel",
        "frames": [{"t": 0.1 * i, "xy": [350, 10], "confidence": 0.9} for i in range(40)] + [{"t": 4.0, "xy": None, "confidence": 0.0}],
    }))
    task = write(tmp_path / "task.json", json.dumps({
        "object": {"name": "red_block", "mass_g": 52.0},
        "target_zone": {"x_min": 0.30, "x_max": 0.40, "y_min": -0.05, "y_max": 0.05},
    }))
    episode_path = tmp_path / "ep.json"
    args = ["ingest", "place", "--task", task, "--id", "real-001", "--load-cell", load_log, "--load-cell-cal", str(cal),
            "--gripper", grip_log, "--video", video, "--camera-cal", str(cam), "--video-offset-s", "0.2",
            "--claim", "true", "--label", "PASS", "--tag", "failure_mode=none", "--out", str(episode_path)]
    assert main(args) == 0
    episode = read(episode_path)
    assert episode["tags"] == {"failure_mode": "none"}
    assert set(episode["provenance"]["sources"]) == {"load.csv", "grip.csv", "video.json", "lc.cal.json", "cam.cal.json"}
    assert episode["video"][0]["t"] == pytest.approx(0.2)
    assert main(["verify", str(episode_path), "--out", str(tmp_path / "bundle.json")]) == 0

    # Without the camera calibration, pixel tracker output must be refused.
    args_no_cam = [a for a in args if a not in ("--camera-cal", str(cam))]
    assert main(args_no_cam) == 3
    # A malformed log line fails strict ingestion but passes with --lenient.
    write(tmp_path / "grip.csv", "10000,closed\nbroken line\n12200,open\n")
    assert main(args) == 3
    assert main(args + ["--lenient"]) == 0


def test_ingest_button(tmp_path):
    task = write(tmp_path / "task.json", json.dumps({"button": {"name": "start", "expected_presses": 1}}))
    log = write(tmp_path / "sw.csv", "\n".join(f"{i * 10},{1 if 100 <= i < 120 else 0}" for i in range(300)))
    out = tmp_path / "ep.json"
    assert main(["ingest", "button_press", "--task", task, "--id", "b-1", "--button", log, "--out", str(out)]) == 0
    assert main(["verify", str(out)]) == 0
    assert main(["ingest", "button_press", "--task", task, "--id", "b-1", "--out", str(out)]) == 3


def test_track_cli(tmp_path):
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    path = tmp_path / "clip.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 5.0, (160, 120))
    for i in range(5):
        frame = np.full((120, 160, 3), 200, dtype=np.uint8)
        frame[50:66, 20 + 20 * i : 36 + 20 * i] = (30, 30, 220)  # BGR red
        writer.write(frame)
    writer.release()
    out = tmp_path / "video.json"
    assert main(["track", str(path), "--color", "220,30,30", "--tolerance", "70", "--roi", "0,30,160,90", "--out", str(out)]) == 0
    doc = read(out)
    assert doc["coords"] == "pixel" and len(doc["frames"]) == 5
    assert all(f["xy"] is not None for f in doc["frames"])
    assert main(["track", str(path), "--color", "220,30,30", "--tolerance", "70", "--start-s", "0.4", "--end-s", "1.0", "--out", str(out)]) == 0
    sliced = read(out)
    assert len(sliced["frames"]) == 3 and sliced["frames"][0]["t"] == 0.0  # frames 2-4 of 5 fps, timed from the slice start
    assert sliced["source"]["start_s"] == 0.4 and sliced["source"]["end_s"] == 1.0
    assert main(["track", str(path), "--color", "1,2", "--out", str(out)]) == 3


def test_sign_and_verify_signature(tmp_path):
    pytest.importorskip("cryptography")
    assert main(["keygen", "--dir", str(tmp_path / "keys")]) == 0
    assert main(["keygen", "--dir", str(tmp_path / "keys")]) == 3  # never overwrite a key
    bundle = tmp_path / "bundle.json"
    main(["verify", str(ROOT / "synthetic" / "02_not_released.json"), "--out", str(bundle)])
    sig = tmp_path / "bundle.sig.json"
    assert main(["sign", str(bundle), "--key", str(tmp_path / "keys" / "taskwitness.key"), "--out", str(sig)]) == 0
    pub = str(tmp_path / "keys" / "taskwitness.pub")
    assert main(["verify-signature", str(bundle), str(sig), "--public-key", pub]) == 0

    tampered = read(bundle)
    tampered["verdict"] = "PASS"
    write(tmp_path / "tampered.json", json.dumps(tampered))
    assert main(["verify-signature", str(tmp_path / "tampered.json"), str(sig)]) == 1

    main(["keygen", "--dir", str(tmp_path / "other")])
    assert main(["verify-signature", str(bundle), str(sig), "--public-key", str(tmp_path / "other" / "taskwitness.pub")]) == 1
