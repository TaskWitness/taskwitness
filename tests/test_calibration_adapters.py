import json
import math
import statistics

import pytest

from taskwitness import verify_episode
from taskwitness.adapters import (
    AdapterError,
    build_episode,
    button_samples,
    gripper_samples,
    load_cell_samples,
    read_series,
    video_frames,
)
from taskwitness.calibration import (
    CalibrationError,
    CameraCalibration,
    LoadCellCalibration,
    fit_homography,
    fit_load_cell,
)

TRUE_H = [[0.0012, 0.0001, -0.05], [0.00005, -0.0011, 0.42], [0.00002, 0.00001, 1.0]]


def project(h, x, y):
    w = h[2][0] * x + h[2][1] * y + h[2][2]
    return ((h[0][0] * x + h[0][1] * y + h[0][2]) / w, (h[1][0] * x + h[1][1] * y + h[1][2]) / w)


# ----------------------------------------------------------------------------- load cell


def test_load_cell_fit_recovers_scale_and_tare():
    tare, k = 8_400_000.0, -412.5  # inverted wiring gives a negative slope; must still work
    empty = [tare + d for d in (-3, 1, 2, -1, 0, 1)]
    refs = [(m, [tare + k * m + d for d in (-2, 0, 2)]) for m in (100.0, 200.0, 500.0)]
    cal = fit_load_cell(empty, refs)
    assert cal.counts_per_gram == pytest.approx(k)
    assert cal.to_grams(tare + k * 52.0) == pytest.approx(52.0, abs=1e-6)
    assert cal.residual_rms_g < 0.01
    assert cal.noise_std_g == pytest.approx(statistics.pstdev(empty) / 412.5)
    suggested = cal.suggested_place_config()
    assert suggested["stability_std_g"] == 2.0 and suggested["empty_threshold_g"] == 3.0


def test_load_cell_nonlinearity_shows_in_residuals():
    empty = [0.0, 0.0, 0.0]
    refs = [(100.0, [100.0]), (200.0, [200.0]), (500.0, [560.0])]  # 12% high at 500 g
    cal = fit_load_cell(empty, refs)
    assert cal.max_abs_error_g > 15 and cal.residual_rms_g > 10


@pytest.mark.parametrize(
    "empty, refs",
    [
        ([1.0], [(100.0, [2.0]), (200.0, [3.0])]),
        ([0.0, 0.0], [(100.0, [5.0])]),
        ([0.0, 0.0], [(100.0, [5.0]), (100.0, [5.0])]),
        ([0.0, 0.0], [(100.0, [0.0]), (200.0, [0.0])]),
        ([0.0, math.nan], [(100.0, [5.0]), (200.0, [9.0])]),
        ([0.0, 0.0], [(-1.0, [5.0]), (200.0, [9.0])]),
    ],
)
def test_load_cell_fit_rejects_bad_data(empty, refs):
    with pytest.raises(CalibrationError):
        fit_load_cell(empty, refs)


def test_load_cell_calibration_round_trip():
    cal = fit_load_cell([0.0, 2.0], [(100.0, [101.0]), (200.0, [201.0])])
    assert LoadCellCalibration.from_dict(json.loads(json.dumps(cal.to_dict()))) == cal
    with pytest.raises(CalibrationError):
        LoadCellCalibration.from_dict({"schema": "x"})


# ----------------------------------------------------------------------------- camera


def test_homography_recovers_projective_map():
    pixels = [(100, 80), (540, 90), (560, 420), (90, 400), (320, 240), (200, 300)]
    plate = [project(TRUE_H, x, y) for x, y in pixels]
    cal = fit_homography(pixels, plate)
    assert cal.rms_error < 1e-9
    for x, y in [(10, 10), (600, 470), (333, 222)]:
        assert cal.to_plate(x, y) == pytest.approx(project(TRUE_H, x, y), abs=1e-9)
    assert CameraCalibration.from_dict(json.loads(json.dumps(cal.to_dict()))).to_plate(5, 5) == pytest.approx(cal.to_plate(5, 5))


def test_homography_reports_click_error():
    pixels = [(100, 80), (540, 90), (560, 420), (90, 400), (320, 240)]
    plate = [project(TRUE_H, x, y) for x, y in pixels]
    plate[4] = (plate[4][0] + 0.01, plate[4][1])  # one point clicked 1 cm off
    cal = fit_homography(pixels, plate)
    assert 0.001 < cal.max_error < 0.02


@pytest.mark.parametrize(
    "pixels",
    [
        [(0, 0), (1, 1), (2, 2), (3, 3)],  # collinear
        [(0, 0), (10, 0), (20, 0), (5, 9)],  # three collinear of four
        [(0, 0), (1, 0), (0, 1)],  # too few
    ],
)
def test_homography_rejects_degenerate_points(pixels):
    with pytest.raises(CalibrationError):
        fit_homography(pixels, [(i, i * i) for i in range(len(pixels))])


# ----------------------------------------------------------------------------- adapters


def test_read_series_handles_header_comments_and_order():
    rows, report = read_series(["# node 7", "t_ms,raw", "200,5", "", "100,4"], "lc.csv")
    assert rows == [(100.0, "4"), (200.0, "5")]
    assert report.reordered


@pytest.mark.parametrize("bad", ["100", "abc,4", "nan,4", "100,"])
def test_read_series_strict_rejects_malformed(bad):
    with pytest.raises(AdapterError, match="lc.csv:3"):
        read_series(["t_ms,raw", "100,4", bad], "lc.csv")


def test_read_series_lenient_skips_and_reports():
    rows, report = read_series(["100,4", "oops", "200,5"], "lc.csv", strict=False)
    assert len(rows) == 2 and len(report.skipped) == 1


def test_converters_apply_calibration_and_clock():
    cal = fit_load_cell([1000.0, 1000.0], [(100.0, [2000.0]), (200.0, [3000.0])])
    rows, report = read_series(["5000,1000", "5100,1520"], "lc")
    samples = load_cell_samples(rows, report, t0_ms=5000, calibration=cal)
    assert samples == [{"t": 0.0, "grams": 0.0}, {"t": 0.1, "grams": 52.0}]
    rows, report = read_series(["5000,Closed", "5100,open"], "g")
    assert [s["state"] for s in gripper_samples(rows, report, 5000)] == ["closed", "open"]
    rows, report = read_series(["5000,0", "5010,pressed", "5020,TRUE"], "b")
    assert [s["pressed"] for s in button_samples(rows, report, 5000)] == [False, True, True]
    rows, report = read_series(["5000,inf"], "lc")
    with pytest.raises(AdapterError, match="bad value"):
        load_cell_samples(rows, report, 5000)
    rows, report = read_series(["5000,half"], "g")
    with pytest.raises(AdapterError):
        gripper_samples(rows, report, 5000)


def test_video_frames_need_matching_coordinates():
    doc = {"schema": "taskwitness.video/v0", "coords": "pixel", "frames": [{"t": 0.0, "xy": [1, 2], "confidence": 0.9}, {"t": 0.1, "xy": None, "confidence": 0.0}]}
    with pytest.raises(AdapterError, match="pixels"):
        video_frames(doc, "object_xy")
    cam = fit_homography([(0, 0), (10, 0), (10, 10), (0, 10)], [(0, 0), (1, 0), (1, 1), (0, 1)])
    frames, info = video_frames(doc, "object_xy", offset_s=0.25, camera=cam)
    assert frames == [{"t": 0.25, "object_xy": [0.1, 0.2], "confidence": 0.9}]
    assert info["frames_without_detection"] == 1
    with pytest.raises(AdapterError, match="already"):
        video_frames(dict(doc, coords="plate"), "object_xy", camera=cam)


def test_ingested_place_episode_verifies():
    lines = ["t_ms,grams"] + [f"{1000 + 100 * i},{0.2 if i < 20 else 52.1}" for i in range(41)]
    rows, report = read_series(lines, "lc.csv")
    load = load_cell_samples(rows, report, t0_ms=1000)
    rows, report = read_series(["1000,closed", "3200,open"], "g.csv")
    grip = gripper_samples(rows, report, t0_ms=1000)
    task = {"object": {"name": "block", "mass_g": 52.0}, "target_zone": {"x_min": 0, "x_max": 1, "y_min": 0, "y_max": 1}}
    episode = build_episode("place", task, "real-001", {"load_cell": load, "gripper": grip}, claim=True, label="PASS", sources={"lc.csv": "ab" * 32})
    bundle = verify_episode(episode)
    assert bundle["verdict"] == "PASS"
    assert episode["provenance"]["sources"] == {"lc.csv": "ab" * 32}


def test_build_episode_checks_type_and_label():
    with pytest.raises(AdapterError):
        build_episode("place", {"type": "button_press"}, "x", {})
    with pytest.raises(AdapterError):
        build_episode("place", {}, "x", {}, label="MAYBE")
