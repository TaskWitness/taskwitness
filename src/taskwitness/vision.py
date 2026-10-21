"""Optional video front end: track a brightly coloured object or tool in raw video.

Install with `pip install taskwitness[vision]` (numpy + opencv-python-headless).

This is a deliberately simple, inspectable baseline, not a learned detector: it
finds pixels close to a target colour, takes their median position, and scores
confidence by blob size and compactness. It suits a saturated block or a
coloured marker on the gripper against a plain table. Restricting it to a
region of interest around the plate (`roi`) cuts false detections; outcome-region
cropping is also what helps VLM judges most (FailBench, arXiv 2609.03611).

Assumptions to respect in an experiment:
* frame timestamps are `index / fps`, i.e. constant frame rate. Phones often
  record variable frame rate; re-encode to constant rate first.
* lighting and white balance stay fixed; check detections on a few frames.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

from taskwitness.adapters import VIDEO_SCHEMA
from taskwitness.calibration import CameraCalibration
from taskwitness.core import TaskWitnessError


class VisionError(TaskWitnessError):
    """Raised for vision setup problems (missing extras, unreadable video, bad parameters)."""


def _numpy():
    try:
        import numpy
    except ImportError:  # pragma: no cover - exercised only without the extra
        raise VisionError("vision features need numpy: pip install 'taskwitness[vision]'") from None
    return numpy


@dataclass(frozen=True)
class Detection:
    u: float
    v: float
    area_px: int
    confidence: float


@dataclass(frozen=True)
class ColorBlobTracker:
    target_rgb: tuple[int, int, int]
    tolerance: float = 60.0
    min_area_px: int = 20
    full_confidence_area_px: int = 200
    cluster_radius_px: float = 40.0
    roi: tuple[int, int, int, int] | None = None  # x0, y0, x1, y1 in pixels

    def __post_init__(self) -> None:
        if len(self.target_rgb) != 3 or not all(0 <= c <= 255 for c in self.target_rgb):
            raise VisionError("target_rgb must be three values in 0..255")
        if self.tolerance <= 0 or self.min_area_px < 1 or self.full_confidence_area_px < self.min_area_px:
            raise VisionError("need tolerance > 0 and 1 <= min_area_px <= full_confidence_area_px")
        if self.roi is not None:
            x0, y0, x1, y1 = self.roi
            if x0 < 0 or y0 < 0 or x1 <= x0 or y1 <= y0:
                raise VisionError("roi must be x0,y0,x1,y1 with x1 > x0 >= 0 and y1 > y0 >= 0")

    def detect(self, frame: Any) -> Detection | None:
        """Detect the target in one RGB frame (H x W x 3, uint8). None if not found."""
        np = _numpy()
        if frame.ndim != 3 or frame.shape[2] != 3:
            raise VisionError(f"expected an H x W x 3 frame, got shape {frame.shape}")
        x_off = y_off = 0
        if self.roi is not None:
            x0, y0, x1, y1 = self.roi
            frame = frame[y0:y1, x0:x1]
            x_off, y_off = x0, y0
        diff = frame.astype(np.int32) - np.asarray(self.target_rgb, dtype=np.int32)
        mask = (diff * diff).sum(axis=2) <= self.tolerance**2
        ys, xs = np.nonzero(mask)
        area = int(xs.size)
        if area < self.min_area_px:
            return None
        u, v = float(np.median(xs)), float(np.median(ys))
        near = ((xs - u) ** 2 + (ys - v) ** 2) <= self.cluster_radius_px**2
        compactness = float(near.mean())
        confidence = min(1.0, area / self.full_confidence_area_px) * compactness
        return Detection(u + x_off, v + y_off, area, round(confidence, 4))


def track_frames(
    frames: Iterable[tuple[float, Any]], tracker: ColorBlobTracker, camera: CameraCalibration | None = None
) -> dict[str, Any]:
    """Run the tracker over (t_s, rgb_frame) pairs and return a `taskwitness.video/v0` document."""
    out = []
    for t, frame in frames:
        det = tracker.detect(frame)
        if det is None:
            out.append({"t": round(t, 6), "xy": None, "confidence": 0.0})
            continue
        xy = camera.to_plate(det.u, det.v) if camera else (det.u, det.v)
        out.append({"t": round(t, 6), "xy": [round(xy[0], 5), round(xy[1], 5)], "confidence": det.confidence, "area_px": det.area_px})
    return {
        "schema": VIDEO_SCHEMA,
        "coords": "plate" if camera else "pixel",
        "tracker": {
            "kind": "color_blob",
            "target_rgb": list(tracker.target_rgb),
            "tolerance": tracker.tolerance,
            "min_area_px": tracker.min_area_px,
            "full_confidence_area_px": tracker.full_confidence_area_px,
            "cluster_radius_px": tracker.cluster_radius_px,
            "roi": list(tracker.roi) if tracker.roi else None,
        },
        "frames": out,
    }


def read_video(path: str, stride: int = 1, max_frames: int | None = None) -> Iterator[tuple[float, Any]]:
    """Yield (t_s, rgb_frame) from a video file, assuming constant frame rate."""
    try:
        import cv2
    except ImportError:  # pragma: no cover - exercised only without the extra
        raise VisionError("reading video needs OpenCV: pip install 'taskwitness[vision]'") from None
    if stride < 1:
        raise VisionError("stride must be >= 1")
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise VisionError(f"cannot open video {path}")
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or not math.isfinite(fps) or fps <= 0:
        cap.release()
        raise VisionError(f"video {path} reports no frame rate")
    index = emitted = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if index % stride == 0:
                yield index / fps, frame[:, :, ::-1]
                emitted += 1
                if max_frames is not None and emitted >= max_frames:
                    break
            index += 1
    finally:
        cap.release()
