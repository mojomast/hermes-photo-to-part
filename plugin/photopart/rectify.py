"""One metric coordinate frame for a photo, its masks, and its landmarks."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

import numpy as np


def image_hash(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def map_points(matrix, points):
    points = np.asarray(points, dtype=float).reshape(-1, 2)
    homogeneous = np.column_stack((points, np.ones(len(points))))
    mapped = homogeneous @ np.asarray(matrix, dtype=float).T
    if not np.isfinite(mapped).all() or np.any(np.abs(mapped[:, 2]) < 1e-9):
        raise ValueError("rectification maps a point to infinity; measure a less oblique reference")
    return mapped[:, :2] / mapped[:, 2, None]


def rectangle_points(rect):
    if isinstance(rect, dict):
        rect = [rect[key] for key in ("x", "y", "w", "h")]
    x, y, w, h = (float(value) for value in rect)
    return np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]])


def map_rect(matrix, rect):
    if rect is None:
        return None
    points = map_points(matrix, rectangle_points(rect))
    lo, hi = points.min(axis=0), points.max(axis=0)
    return [float(lo[0]), float(lo[1]), float(hi[0] - lo[0]), float(hi[1] - lo[1])]


def plan(image_path, shape, quad, width_mm, height_mm, px_per_mm) -> dict:
    """Rectify the full photo, retaining objects outside the reference rectangle.

    Reference landmarks have exact metric spans, independent of integer canvas
    rounding. Downsampling caps the whole canvas and updates the same scale.
    """
    from photopart.measure import homography

    width_mm, height_mm, scale = float(width_mm), float(height_mm), float(px_per_mm)
    if not all(np.isfinite(v) and v > 0 for v in (width_mm, height_mm, scale)):
        raise ValueError("rectification dimensions and pixels-per-mm must be finite and positive")
    height, width = shape[:2]
    dest = rectangle_points([0, 0, width_mm * scale, height_mm * scale])
    matrix = homography(np.asarray(quad), dest)
    corners = rectangle_points([0, 0, width - 1, height - 1])
    denominators = np.column_stack((corners, np.ones(4))) @ matrix[2]
    if not (np.all(denominators > 1e-9) or np.all(denominators < -1e-9)):
        raise ValueError("rectification horizon crosses the photo; crop the photo or use a less oblique view")
    mapped = map_points(matrix, corners)
    lo = mapped.min(axis=0)
    spans = mapped.max(axis=0) - lo
    if not np.isfinite(spans).all() or np.any(spans <= 0):
        raise ValueError("rectification has an empty or invalid canvas")
    factor = min(1.0, 3998.0 / float(max(spans)))
    shift = np.array([[factor, 0, -lo[0] * factor], [0, factor, -lo[1] * factor], [0, 0, 1]])
    matrix = shift @ matrix
    return {
        "version": 1,
        "source_image": str(Path(image_path).resolve()),
        "source_sha256": image_hash(image_path),
        "source_size": [width, height],
        "matrix": matrix.tolist(),
        "size": [max(2, math.ceil(float(span) * factor) + 1) for span in spans],
        "px_per_mm": scale * factor,
        "coordinate_frame": "rectified",
    }


def validate(record: dict):
    matrix = np.asarray(record.get("matrix"), dtype=float)
    size = np.asarray(record.get("size"), dtype=float)
    source_size = np.asarray(record.get("source_size"), dtype=float)
    scale = float(record.get("px_per_mm") or 0)
    if (record.get("version") != 1 or matrix.shape != (3, 3)
            or not np.isfinite(matrix).all() or abs(np.linalg.det(matrix)) < 1e-12
            or size.shape != (2,) or not np.isfinite(size).all()
            or np.any(size < 2) or np.any(size > 4000) or np.any(size != np.floor(size))
            or source_size.shape != (2,) or not np.isfinite(source_size).all()
            or np.any(source_size < 2) or np.any(source_size != np.floor(source_size))
            or not np.isfinite(scale) or scale <= 0):
        raise ValueError("invalid rectification record; run photo_part_measure again")
    return matrix, tuple(int(value) for value in size)


def warp_mask(mask, record):
    import cv2

    matrix, size = validate(record)
    return cv2.warpPerspective(mask.astype(np.uint8), matrix, size, flags=cv2.INTER_NEAREST) > 0


def valid_mask(record):
    matrix, size = validate(record)
    width, height = (int(v) for v in record["source_size"])
    # Inverse-map in strips: do not allocate an additional full-resolution source
    # image just to discover which output pixels have interpolation support.
    inverse = np.linalg.inv(matrix)
    valid = np.zeros((size[1], size[0]), dtype=bool)
    x = np.arange(size[0], dtype=float)[None, :]
    for start in range(0, size[1], 128):
        y = np.arange(start, min(start + 128, size[1]), dtype=float)[:, None]
        denominator = inverse[2, 0] * x + inverse[2, 1] * y + inverse[2, 2]
        with np.errstate(divide="ignore", invalid="ignore"):
            sx = (inverse[0, 0] * x + inverse[0, 1] * y + inverse[0, 2]) / denominator
            sy = (inverse[1, 0] * x + inverse[1, 1] * y + inverse[1, 2]) / denominator
        valid[start:start + len(y)] = (np.isfinite(sx) & np.isfinite(sy)
                                      & (sx >= -1e-7) & (sx <= width - 1 + 1e-7)
                                      & (sy >= -1e-7) & (sy <= height - 1 + 1e-7))
    return valid


def warp_image(image, record):
    import cv2

    matrix, size = validate(record)
    if [image.shape[1], image.shape[0]] != record["source_size"]:
        raise ValueError("photo dimensions changed; run photo_part_measure again")
    border = np.concatenate((image[0], image[-1], image[:, 0], image[:, -1]))
    background = tuple(float(v) for v in np.median(border, axis=0))
    warped = cv2.warpPerspective(image, matrix, size, borderValue=background)
    valid = valid_mask(record)
    warped[~valid] = np.asarray(background, dtype=np.uint8)
    return warped, valid
