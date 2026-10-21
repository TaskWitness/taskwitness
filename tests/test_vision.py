from pathlib import Path

import pytest

from taskwitness.calibration import fit_homography

np = pytest.importorskip("numpy")



def frame_with_block(u, v, size=16, shape=(120, 160)):
    frame = np.full((*shape, 3), (200, 200, 190), dtype=np.uint8)
    frame[v - size // 2 : v + size // 2, u - size // 2 : u + size // 2] = (220, 30, 30)
    return frame


def test_tracker_finds_block_and_respects_roi():
    from taskwitness.vision import ColorBlobTracker

    tracker = ColorBlobTracker((220, 30, 30), min_area_px=20, full_confidence_area_px=200)
    det = tracker.detect(frame_with_block(60, 40))
    assert det is not None and (det.u, det.v) == pytest.approx((59.5, 39.5), abs=1.0)
    assert det.confidence == 1.0
    assert tracker.detect(np.full((120, 160, 3), 200, dtype=np.uint8)) is None
    in_roi = ColorBlobTracker((220, 30, 30), roi=(40, 20, 100, 80)).detect(frame_with_block(60, 40))
    assert in_roi is not None and in_roi.u == pytest.approx(59.5, abs=1.0)
    assert ColorBlobTracker((220, 30, 30), roi=(100, 60, 160, 120)).detect(frame_with_block(60, 40)) is None


def test_tracker_confidence_drops_for_scattered_pixels():
    from taskwitness.vision import ColorBlobTracker

    frame = np.full((120, 160, 3), 200, dtype=np.uint8)
    rng = np.random.default_rng(0)
    ys, xs = rng.integers(0, 120, 300), rng.integers(0, 160, 300)
    frame[ys, xs] = (220, 30, 30)
    det = ColorBlobTracker((220, 30, 30), cluster_radius_px=10).detect(frame)
    assert det is not None and det.confidence < 0.2


def test_tracker_rejects_bad_parameters():
    from taskwitness.vision import ColorBlobTracker, VisionError

    with pytest.raises(VisionError):
        ColorBlobTracker((300, 0, 0))
    with pytest.raises(VisionError):
        ColorBlobTracker((1, 2, 3), roi=(10, 10, 5, 20))


def test_video_file_round_trip_through_tracker(tmp_path: Path):
    cv2 = pytest.importorskip("cv2")
    from taskwitness.vision import ColorBlobTracker, read_video, track_frames

    path = tmp_path / "clip.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (160, 120))
    positions = [(30 + 10 * i, 60) for i in range(10)]
    for u, v in positions:
        writer.write(frame_with_block(u, v)[:, :, ::-1].copy())  # OpenCV writes BGR
    writer.release()

    cam = fit_homography([(0, 0), (160, 0), (160, 120), (0, 120)], [(0, 0), (1.6, 0), (1.6, 1.2), (0, 1.2)])
    doc = track_frames(read_video(str(path)), ColorBlobTracker((220, 30, 30), tolerance=70), camera=cam)
    assert doc["coords"] == "plate" and len(doc["frames"]) == 10
    for frame, (u, v) in zip(doc["frames"], positions):
        assert frame["xy"] == pytest.approx([u / 100, v / 100], abs=0.02)
        assert frame["confidence"] > 0.9
    assert [f["t"] for f in doc["frames"]] == pytest.approx([i / 10 for i in range(10)])
