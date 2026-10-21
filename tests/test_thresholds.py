import json
import random
import statistics
from pathlib import Path

import pytest

from taskwitness import judge
from taskwitness.cli import main
from taskwitness.config import parse_config
from taskwitness.thresholds import ThresholdError, calibrate_thresholds, window_stats

NOISE_G = 0.4


def noisy_windows(rng, mean_g, count, per_window=10):
    return [
        (statistics.fmean(v), statistics.pstdev(v))
        for v in ([rng.gauss(mean_g, NOISE_G) for _ in range(per_window)] for _ in range(count))
    ]


def test_window_stats_slices_and_drops_partial_window():
    samples = [(i / 10, 5.0 + (i % 2)) for i in range(35)]  # 3.5 s at 10 Hz
    windows = window_stats(samples, 1.0)
    assert len(windows) == 3  # the partial last window is dropped
    assert windows[0] == pytest.approx((5.5, 0.5))
    assert window_stats(samples, 1.0, min_samples=11) == []
    assert window_stats([], 1.0) == []
    with pytest.raises(ThresholdError):
        window_stats(samples, 0)


def test_thresholds_hold_on_fresh_known_good_windows():
    """The guarantee itself: new known-good windows exceed each threshold at most alpha of the time."""
    rng = random.Random(8)
    alpha, reps, exceed = 0.05, 40, {"std": 0, "empty": 0, "error": 0}
    fresh_per_rep = 100
    for _ in range(reps):
        report = calibrate_thresholds(noisy_windows(rng, 0.0, 60), {52.0: noisy_windows(rng, 52.0, 60)}, alpha)
        cfg = report["place_config"]
        for mean, std in noisy_windows(rng, 0.0, fresh_per_rep):
            exceed["std"] += std > cfg["stability_std_g"]
            exceed["empty"] += abs(mean) > cfg["empty_threshold_g"]
        for mean, _std in noisy_windows(rng, 52.0, fresh_per_rep):
            exceed["error"] += abs(mean - 52.0) > cfg["mass_tolerance_abs_g"]
    total = reps * fresh_per_rep
    assert exceed["empty"] / total <= alpha + 0.01
    assert exceed["error"] / total <= alpha + 0.01
    assert exceed["std"] / (2 * total) <= alpha + 0.01  # std threshold is shared by both kinds of window


def test_not_enough_windows_is_an_error_not_a_guess():
    rng = random.Random(1)
    with pytest.raises(ThresholdError, match="at least 19"):
        calibrate_thresholds(noisy_windows(rng, 0.0, 10), {}, alpha=0.05)
    with pytest.raises(ThresholdError):
        calibrate_thresholds([], {})
    report = calibrate_thresholds(noisy_windows(rng, 0.0, 10), {}, alpha=0.2)  # a looser alpha needs only 4
    assert report["warnings"] and "mass_tolerance_abs_g" not in report["place_config"]


def test_light_object_is_flagged():
    rng = random.Random(2)
    # A 3 g object is clearly separable from the 0.4 g sensor noise ...
    ok = calibrate_thresholds(noisy_windows(rng, 0.0, 40), {3.0: noisy_windows(rng, 3.0, 40)})
    assert not any("too close" in w for w in ok["warnings"])
    # ... a 0.5 g object is not.
    flagged = calibrate_thresholds(noisy_windows(rng, 0.0, 40), {0.5: noisy_windows(rng, 0.5, 40)})
    assert any("too close" in w for w in flagged["warnings"])


def write_log(path: Path, rng, mean_raw, scale_noise, seconds, hz=20):
    lines = ["t_ms,raw"] + [f"{int(i * 1000 / hz)},{rng.gauss(mean_raw, scale_noise):.2f}" for i in range(int(seconds * hz))]
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


def test_cli_calibrates_thresholds_that_make_the_oracle_work(tmp_path):
    rng = random.Random(3)
    tare, k = 8_000_000.0, 400.0  # counts, counts per gram
    noise_counts = NOISE_G * k
    empty = write_log(tmp_path / "empty.csv", rng, tare, noise_counts, 60)
    ref100 = write_log(tmp_path / "r100.csv", rng, tare + k * 100, noise_counts, 10)
    ref500 = write_log(tmp_path / "r500.csv", rng, tare + k * 500, noise_counts, 10)
    cal = tmp_path / "lc.cal.json"
    assert main(["calibrate", "load-cell", "--empty", empty, "--ref", f"100={ref100}", "--ref", f"500={ref500}", "--out", str(cal)]) == 0

    block = write_log(tmp_path / "block.csv", rng, tare + k * 52.0, noise_counts, 60)
    out = tmp_path / "thresholds.json"
    assert main(["calibrate", "thresholds", "--empty", empty, "--object", f"52={block}", "--load-cell-cal", str(cal), "--out", str(out)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["windows"]["empty"] == 59 and doc["windows"]["object"] == {"52": 59}
    assert 0.2 < doc["place_config"]["stability_std_g"] < 1.5  # sensor noise is 0.4 g
    configs = parse_config(doc["config"])  # the output is a ready-to-use config file

    from taskwitness.adapters import build_episode, load_cell_samples, read_series
    from taskwitness.calibration import LoadCellCalibration

    cell = LoadCellCalibration.from_dict(json.loads(cal.read_text(encoding="utf-8")))
    rows, report = read_series(Path(block).read_text(encoding="utf-8").splitlines(), "block")
    load = load_cell_samples(rows, report, t0_ms=0, calibration=cell)
    task = {"object": {"name": "block", "mass_g": 52.0}, "target_zone": {"x_min": 0, "x_max": 1, "y_min": 0, "y_max": 1}}
    episode = build_episode("place", task, "calibrated", {"load_cell": load})
    assert judge(episode, doc["config"]).passed
    assert configs["place"].settle_window_s == 1.0


def test_cli_thresholds_refuse_too_little_data(tmp_path):
    rng = random.Random(4)
    short = write_log(tmp_path / "short.csv", rng, 0.0, 1.0, 8)  # 7 windows < 19
    assert main(["calibrate", "thresholds", "--empty", short, "--out", str(tmp_path / "t.json")]) == 3
    assert main(["calibrate", "thresholds", "--empty", short, "--object", "oops", "--out", str(tmp_path / "t.json")]) == 3


def test_evaluate_sequential_follows_the_requested_order(tmp_path):
    root = Path(__file__).resolve().parent.parent / "examples"
    episodes = tmp_path / "eps"
    episodes.mkdir()
    # 12 copies of a failure that a vision-only judge passes (02_not_released), in a fixed trial order.
    base = json.loads((root / "synthetic" / "02_not_released.json").read_text(encoding="utf-8"))
    for i in range(12):
        ep = dict(base, episode_id=f"trial-{i:02d}", tags={"trial": str(i)})
        (episodes / f"z{12 - i:02d}.json").write_text(json.dumps(ep), encoding="utf-8")  # file order != trial order
    out = tmp_path / "eval.json"
    assert main(["evaluate", str(episodes), "--order-by", "trial", "--out", str(out)]) == 0
    seq = json.loads(out.read_text(encoding="utf-8"))["paired_false_pass_sequential"]
    assert seq["rejected"] and seq["discordant_pairs"] == 12 and seq["stopped_at_pair"] <= 10
    assert main(["evaluate", str(episodes), "--order-by", "missing_tag", "--out", str(out)]) == 3


def test_estimate_reports_every_interval(tmp_path):
    root = Path(__file__).resolve().parent.parent / "examples"
    base = json.loads((root / "synthetic" / "01_clean_success.json").read_text(encoding="utf-8"))
    fail = json.loads((root / "synthetic" / "03_bounced_off.json").read_text(encoding="utf-8"))
    rng = random.Random(6)
    for i in range(60):
        src = base if rng.random() < 0.6 else fail
        ep = {k: v for k, v in src.items() if k not in ("synthetic",)}
        ep["episode_id"] = f"e{i:02d}"
        if i >= 20:
            ep.pop("label")  # only the first 20 episodes carry a human label
        (tmp_path / f"e{i:02d}.json").write_text(json.dumps(ep), encoding="utf-8")
    out = tmp_path / "estimate.json"
    assert main(["estimate", str(tmp_path), "--out", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    for key in ("labels_only", "labels_only_finite_sample", "prediction_powered", "prediction_powered_finite_sample"):
        assert key in report
    lo, hi = report["labels_only_finite_sample"]["ci"]
    assert 0 <= lo < hi <= 1
