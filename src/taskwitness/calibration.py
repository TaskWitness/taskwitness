"""Calibration: load-cell tare/scale and camera-to-plate homography. Pure Python.

Load cell
    Record raw ADC counts with the plate empty, then with at least two reference
    masses. `fit_load_cell` estimates the tare offset and the counts-per-gram
    slope (least squares through the tare), and reports noise and residuals so
    you can tell whether the setup is good enough before running experiments.

Camera
    Click at least four points on the plate in the image and measure their
    positions in the plate frame. `fit_homography` estimates the 3x3 projective
    mapping (normalised DLT) and its reprojection error, so tracker output in
    pixels can be compared with `target_zone` in plate coordinates.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from itertools import combinations
from dataclasses import asdict, dataclass

from taskwitness.core import TaskWitnessError, is_number

CALIBRATION_SCHEMA = "taskwitness.calibration/v0"


class CalibrationError(TaskWitnessError):
    """Raised when calibration data is missing, degenerate or malformed."""


def _check_values(values: Sequence[float], what: str, minimum: int) -> None:
    if len(values) < minimum:
        raise CalibrationError(f"{what}: need at least {minimum} readings, got {len(values)}")
    if not all(is_number(v) for v in values):
        raise CalibrationError(f"{what}: readings must be finite numbers")


@dataclass(frozen=True)
class LoadCellCalibration:
    tare_raw: float
    counts_per_gram: float
    noise_std_g: float
    residual_rms_g: float
    max_abs_error_g: float
    references: list[dict]

    def to_grams(self, raw: float) -> float:
        return (raw - self.tare_raw) / self.counts_per_gram

    def suggested_place_config(self) -> dict[str, float]:
        """Starting points derived from measured noise and residuals.

        Heuristics, not guarantees: freeze the values you choose *before* the
        experiment (see `taskwitness evaluate --config`).
        """
        return {
            "stability_std_g": round(max(2.0, 4.0 * self.noise_std_g), 3),
            "empty_threshold_g": round(max(3.0, 6.0 * self.noise_std_g), 3),
            "mass_tolerance_abs_g": round(max(3.0, 3.0 * self.max_abs_error_g), 3),
        }

    def to_dict(self) -> dict:
        return {"schema": CALIBRATION_SCHEMA, "load_cell": asdict(self), "suggested_place_config": self.suggested_place_config()}

    @classmethod
    def from_dict(cls, doc: dict) -> LoadCellCalibration:
        try:
            if doc.get("schema") != CALIBRATION_SCHEMA:
                raise CalibrationError(f"not a {CALIBRATION_SCHEMA} document")
            cal = cls(**doc["load_cell"])
        except (KeyError, TypeError, AttributeError) as exc:
            raise CalibrationError(f"malformed load-cell calibration: {exc}") from None
        if not (is_number(cal.tare_raw) and is_number(cal.counts_per_gram) and cal.counts_per_gram != 0):
            raise CalibrationError("load-cell calibration needs a finite tare and a non-zero slope")
        return cal


def fit_load_cell(empty_raw: Sequence[float], references: Sequence[tuple[float, Sequence[float]]]) -> LoadCellCalibration:
    """Fit tare and slope from empty-plate readings and (mass_g, raw readings) pairs."""
    _check_values(empty_raw, "empty plate", 2)
    if len(references) < 2:
        raise CalibrationError("need at least two reference masses to check linearity")
    tare = statistics.fmean(empty_raw)
    pairs = []
    for mass, raws in references:
        if not is_number(mass) or mass <= 0:
            raise CalibrationError(f"reference mass must be a positive number, got {mass!r}")
        _check_values(raws, f"reference {mass} g", 1)
        pairs.append((float(mass), statistics.fmean(raws) - tare, len(raws)))
    if len({m for m, _, _ in pairs}) < 2:
        raise CalibrationError("reference masses must differ")

    slope = sum(m * d for m, d, _ in pairs) / sum(m * m for m, _, _ in pairs)
    if not math.isfinite(slope) or abs(slope) < 1e-12:
        raise CalibrationError("load cell does not respond to the reference masses (slope is zero)")
    refs = []
    for mass, delta, n in pairs:
        measured = delta / slope
        refs.append({"mass_g": mass, "measured_g": round(measured, 4), "error_g": round(measured - mass, 4), "readings": n})
    errors = [r["error_g"] for r in refs]
    return LoadCellCalibration(
        tare_raw=tare,
        counts_per_gram=slope,
        noise_std_g=statistics.pstdev(empty_raw) / abs(slope),
        residual_rms_g=math.sqrt(statistics.fmean(e * e for e in errors)),
        max_abs_error_g=max(abs(e) for e in errors),
        references=refs,
    )


# --------------------------------------------------------------------------- homography

Matrix = list[list[float]]


def _matmul(a: Matrix, b: Matrix) -> Matrix:
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _inverse3(m: Matrix) -> Matrix:
    (a, b, c), (d, e, f), (g, h, i) = m
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if abs(det) < 1e-15:
        raise CalibrationError("singular matrix")
    adj = [
        [e * i - f * h, c * h - b * i, b * f - c * e],
        [f * g - d * i, a * i - c * g, c * d - a * f],
        [d * h - e * g, b * g - a * h, a * e - b * d],
    ]
    return [[v / det for v in row] for row in adj]


def _normaliser(points: Sequence[tuple[float, float]]) -> Matrix:
    """Hartley normalisation: centroid to origin, mean distance sqrt(2)."""
    cx = statistics.fmean(p[0] for p in points)
    cy = statistics.fmean(p[1] for p in points)
    spread = statistics.fmean(math.hypot(p[0] - cx, p[1] - cy) for p in points)
    if spread < 1e-12:
        raise CalibrationError("calibration points must not all coincide")
    s = math.sqrt(2) / spread
    return [[s, 0.0, -s * cx], [0.0, s, -s * cy], [0.0, 0.0, 1.0]]


def _general_position(points: Sequence[tuple[float, float]]) -> bool:
    """True if some four points have no three collinear (needed for a unique homography)."""
    spread = max(math.dist(p, q) for p in points for q in points) or 1.0
    tol = 1e-6 * spread * spread

    def collinear(a, b, c) -> bool:
        return abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) <= tol

    for quad in combinations(points[:30], 4):
        if not any(collinear(*tri) for tri in combinations(quad, 3)):
            return True
    return False


def _apply(h: Matrix, x: float, y: float) -> tuple[float, float]:
    w = h[2][0] * x + h[2][1] * y + h[2][2]
    if abs(w) < 1e-12:
        raise CalibrationError("point maps to infinity under this homography")
    return ((h[0][0] * x + h[0][1] * y + h[0][2]) / w, (h[1][0] * x + h[1][1] * y + h[1][2]) / w)


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting; raises on (near-)singular systems."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    scale = max(abs(v) for row in a for v in row) or 1.0
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-10 * scale:
            raise CalibrationError("calibration points are degenerate (three or more collinear?)")
        m[col], m[pivot] = m[pivot], m[col]
        for r in range(col + 1, n):
            f = m[r][col] / m[col][col]
            for c in range(col, n + 1):
                m[r][c] -= f * m[col][c]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (m[r][n] - sum(m[r][c] * x[c] for c in range(r + 1, n))) / m[r][r]
    return x


@dataclass(frozen=True)
class CameraCalibration:
    homography: Matrix
    rms_error: float
    max_error: float
    points: int

    def to_plate(self, u: float, v: float) -> tuple[float, float]:
        return _apply(self.homography, u, v)

    def to_dict(self) -> dict:
        return {"schema": CALIBRATION_SCHEMA, "camera": asdict(self)}

    @classmethod
    def from_dict(cls, doc: dict) -> CameraCalibration:
        try:
            if doc.get("schema") != CALIBRATION_SCHEMA:
                raise CalibrationError(f"not a {CALIBRATION_SCHEMA} document")
            cal = cls(**doc["camera"])
        except (KeyError, TypeError, AttributeError) as exc:
            raise CalibrationError(f"malformed camera calibration: {exc}") from None
        h = cal.homography
        if not (isinstance(h, list) and len(h) == 3 and all(len(r) == 3 and all(is_number(v) for v in r) for r in h)):
            raise CalibrationError("camera homography must be a 3x3 matrix of finite numbers")
        return cal


def fit_homography(pixels: Sequence[tuple[float, float]], plate: Sequence[tuple[float, float]]) -> CameraCalibration:
    """Least-squares homography from >= 4 pixel/plate correspondences (normalised DLT)."""
    if len(pixels) != len(plate):
        raise CalibrationError("need the same number of pixel and plate points")
    if len(pixels) < 4:
        raise CalibrationError(f"need at least 4 point pairs, got {len(pixels)}")
    for p in list(pixels) + list(plate):
        if len(p) != 2 or not all(is_number(v) for v in p):
            raise CalibrationError(f"points must be [x, y] pairs of finite numbers, got {p!r}")

    for name, pts in (("pixel", pixels), ("plate", plate)):
        if not _general_position(pts):
            raise CalibrationError(f"{name} points are degenerate: need four points with no three on a line")

    t_src, t_dst = _normaliser(pixels), _normaliser(plate)
    rows, rhs = [], []
    for (x0, y0), (u0, v0) in zip(pixels, plate):
        x, y = _apply(t_src, x0, y0)
        u, v = _apply(t_dst, u0, v0)
        rows.append([x, y, 1.0, 0.0, 0.0, 0.0, -u * x, -u * y])
        rhs.append(u)
        rows.append([0.0, 0.0, 0.0, x, y, 1.0, -v * x, -v * y])
        rhs.append(v)
    ata = [[sum(r[i] * r[j] for r in rows) for j in range(8)] for i in range(8)]
    atb = [sum(r[i] * b for r, b in zip(rows, rhs)) for i in range(8)]
    h = _solve(ata, atb)
    h_norm = [[h[0], h[1], h[2]], [h[3], h[4], h[5]], [h[6], h[7], 1.0]]
    full = _matmul(_matmul(_inverse3(t_dst), h_norm), t_src)
    full = [[v / full[2][2] for v in row] for row in full]

    errors = []
    for (x, y), (u, v) in zip(pixels, plate):
        pu, pv = _apply(full, x, y)
        errors.append(math.hypot(pu - u, pv - v))
    return CameraCalibration(
        homography=full,
        rms_error=math.sqrt(statistics.fmean(e * e for e in errors)),
        max_error=max(errors),
        points=len(pixels),
    )
