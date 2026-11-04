"""Pixel-to-millimetre scale from a coin or a ruler, with an optional homography.

No network. Coin diameters are nominal circulated sizes, not a measurement of
the coin in the photo. The scale is only valid for features in the same plane
as the reference, on a straight-on photo, unless a four-point quad rectifies it.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

from photopart.flow import attach_flow, failed, step_measure
from photopart.paths import default_output, new_output

# Nominal diameters in millimetres.
COIN_DIAMETERS_MM = {
    "euro_1": 23.25,
    "euro_2": 25.75,
    "euro_50c": 24.25,
    "us_quarter": 24.26,
    "us_penny": 19.05,
    "us_nickel": 21.21,
    "us_dime": 17.91,
    "us_half": 30.61,
    "gbp_1": 23.43,
    "cad_quarter": 23.88,
    # Royal Canadian Mint circulation one-dollar coin (loonie), 26.5 mm.
    "cad_loonie": 26.5,
}

_ALIASES = {
    "1euro": "euro_1",
    "euro1": "euro_1",
    "eur1": "euro_1",
    "1eur": "euro_1",
    "2euro": "euro_2",
    "euro2": "euro_2",
    "50c": "euro_50c",
    "50cent": "euro_50c",
    "euro50": "euro_50c",
    "quarter": "us_quarter",
    "usquarter": "us_quarter",
    "penny": "us_penny",
    "uspenny": "us_penny",
    "nickel": "us_nickel",
    "dime": "us_dime",
    "halfdollar": "us_half",
    "ushalf": "us_half",
    "pound": "gbp_1",
    "gbp1": "gbp_1",
    "1pound": "gbp_1",
    "cadquarter": "cad_quarter",
    "loonie": "cad_loonie",
    "cadloonie": "cad_loonie",
    "cad1": "cad_loonie",
}

_PLANE_NOTE = (
    "Scale assumes the reference and the feature lie on the same plane. "
    "Without a quad, the photo must be straight-on; an angled photo makes "
    "the far edge short. Pass quad (TL, TR, BR, BL) plus width_mm and height_mm "
    "to rectify a known rectangle first."
)


def resolve_coin(name: str) -> tuple[str, float]:
    """Return the canonical coin id and its nominal diameter in millimetres."""
    key = (
        name.strip()
        .lower()
        .replace("€", "euro")
        .replace("£", "gbp")
        .replace("-", "")
        .replace("_", "")
        .replace(" ", "")
    )
    canonical = _ALIASES.get(key)
    if canonical is None:
        underscored = name.strip().lower().replace(" ", "_").replace("-", "_")
        if underscored in COIN_DIAMETERS_MM:
            canonical = underscored
    if canonical is None:
        known = ", ".join(sorted(COIN_DIAMETERS_MM))
        raise ValueError(f"unknown coin {name!r}. Known coins: {known}")
    return canonical, COIN_DIAMETERS_MM[canonical]


def homography(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Map four source pixels onto four destination pixels. Returns a 3×3 H."""
    source = np.asarray(src, dtype=float).reshape(4, 2)
    target = np.asarray(dst, dtype=float).reshape(4, 2)
    rows = []
    values = []
    for (x, y), (u, v) in zip(source, target):
        rows.append([x, y, 1.0, 0.0, 0.0, 0.0, -u * x, -u * y])
        rows.append([0.0, 0.0, 0.0, x, y, 1.0, -v * x, -v * y])
        values.append(u)
        values.append(v)
    try:
        solution = np.linalg.solve(np.asarray(rows, dtype=float), np.asarray(values, dtype=float))
    except np.linalg.LinAlgError as exc:
        raise ValueError("quad is degenerate; the four points do not define a homography") from exc
    return np.array(
        [
            [solution[0], solution[1], solution[2]],
            [solution[3], solution[4], solution[5]],
            [solution[6], solution[7], 1.0],
        ],
        dtype=float,
    )


def apply_homography(matrix: np.ndarray, points: np.ndarray) -> np.ndarray:
    pts = np.asarray(points, dtype=float).reshape(-1, 2)
    hom = np.concatenate([pts, np.ones((len(pts), 1))], axis=1)
    mapped = (matrix @ hom.T).T
    return mapped[:, :2] / mapped[:, 2:3]


def _distance(a, b) -> float:
    return float(np.linalg.norm(np.asarray(a, dtype=float) - np.asarray(b, dtype=float)))


def _pair(value, label: str) -> np.ndarray:
    points = np.asarray(value, dtype=float).reshape(2, 2)
    if not np.isfinite(points).all():
        raise ValueError(f"{label} points must be finite")
    if _distance(points[0], points[1]) <= 0:
        raise ValueError(f"{label} points must be distinct")
    return points


def _quad(value) -> np.ndarray:
    points = np.asarray(value, dtype=float).reshape(4, 2)
    if not np.isfinite(points).all():
        raise ValueError("quad points must be finite")
    return points


def quad_px_per_mm(quad: np.ndarray, width_mm: float, height_mm: float) -> float:
    """Average the two width edges and the two height edges of a TL,TR,BR,BL quad."""
    if width_mm <= 0 or height_mm <= 0:
        raise ValueError("width_mm and height_mm must be positive")
    top = _distance(quad[0], quad[1])
    bottom = _distance(quad[3], quad[2])
    left = _distance(quad[0], quad[3])
    right = _distance(quad[1], quad[2])
    return ((top + bottom) / 2.0 / width_mm + (left + right) / 2.0 / height_mm) / 2.0


def _warp(image: np.ndarray, matrix: np.ndarray, out_w: int, out_h: int) -> np.ndarray:
    """Inverse-map a rectified image with bilinear samples. Pixels outside are white."""
    inverse = np.linalg.inv(matrix)
    ys, xs = np.mgrid[0:out_h, 0:out_w]
    dest = np.stack([xs.ravel(), ys.ravel(), np.ones(out_w * out_h)], axis=0)
    source = inverse @ dest
    source = source[:2] / source[2]
    sx = source[0]
    sy = source[1]
    height, width = image.shape[:2]
    x0 = np.floor(sx).astype(np.int32)
    y0 = np.floor(sy).astype(np.int32)
    x1 = x0 + 1
    y1 = y0 + 1
    wx = sx - x0
    wy = sy - y0
    valid = (x0 >= 0) & (y0 >= 0) & (x1 < width) & (y1 < height)
    x0c = np.clip(x0, 0, width - 1)
    x1c = np.clip(x1, 0, width - 1)
    y0c = np.clip(y0, 0, height - 1)
    y1c = np.clip(y1, 0, height - 1)
    sample = image.astype(np.float64)
    top = sample[y0c, x0c] * (1.0 - wx)[:, None] + sample[y0c, x1c] * wx[:, None]
    bot = sample[y1c, x0c] * (1.0 - wx)[:, None] + sample[y1c, x1c] * wx[:, None]
    mixed = top * (1.0 - wy)[:, None] + bot * wy[:, None]
    mixed[~valid] = 255.0
    return mixed.reshape(out_h, out_w, 3).clip(0, 255).astype(np.uint8)


def _measurements(items, px_per_mm: float) -> list[dict]:
    found = []
    for index, item in enumerate(items or []):
        if not isinstance(item, dict):
            raise ValueError(f"measurement {index} must be an object")
        name = str(item.get("name") or f"m{index}")
        if item.get("length_px") is not None:
            pixels = float(item["length_px"])
        elif item.get("points") is not None:
            pixels = _distance(*_pair(item["points"], name))
        else:
            raise ValueError(f"measurement {name!r} needs points or length_px")
        if pixels <= 0 or not np.isfinite(pixels):
            raise ValueError(f"measurement {name!r} has an empty span")
        plane = str(item.get("plane") or "in_plane")
        if plane not in {"in_plane", "out_of_plane"}:
            raise ValueError(f"measurement {name!r} plane must be in_plane or out_of_plane")
        uncertainty = max(1.0, 0.02 * pixels) / px_per_mm
        if plane == "out_of_plane":
            uncertainty *= 3.0
        found.append(
            {
                "name": name,
                "px": pixels,
                "mm": pixels / px_per_mm,
                "plane": plane,
                "uncertainty_mm": uncertainty,
            }
        )
    return found


def measure(payload: dict) -> dict:
    """Return pixel scale, optional measurements, and an optional rectified image."""
    if not isinstance(payload, dict):
        raise ValueError("measure arguments must be an object")
    coin = payload.get("coin")
    diameter_mm = payload.get("diameter_mm")
    reference_name = None
    if coin:
        reference_name, coin_mm = resolve_coin(str(coin))
        if diameter_mm is None:
            diameter_mm = coin_mm
    if diameter_mm is not None:
        diameter_mm = float(diameter_mm)
        if not np.isfinite(diameter_mm) or diameter_mm <= 0:
            raise ValueError("diameter_mm must be positive")
    ruler_mm = payload.get("ruler_mm")
    if ruler_mm is not None:
        ruler_mm = float(ruler_mm)
        if not np.isfinite(ruler_mm) or ruler_mm <= 0:
            raise ValueError("ruler_mm must be positive")
    points = payload.get("points")
    diameter_px = payload.get("diameter_px")
    quad = payload.get("quad")
    width_mm = payload.get("width_mm")
    height_mm = payload.get("height_mm")

    kind = None
    px_per_mm = None
    reference_px = None
    marker = None
    coin_detect = None
    image_path = payload.get("image")
    want_part = bool(payload.get("auto")) or payload.get("part_seed") is not None or payload.get("part_roi") is not None
    if image_path and payload.get("marker_mm") is not None:
        marker = _marker_scale(str(image_path), float(payload["marker_mm"]))
        px_per_mm = marker["px_per_mm"]
        reference_px = marker["side_px"]
        kind = marker["kind"]
    elif ruler_mm is not None:
        if points is None:
            raise ValueError("ruler_mm needs points: two pixels the ruler_mm span covers")
        pair = _pair(points, "ruler")
        reference_px = _distance(pair[0], pair[1])
        px_per_mm = reference_px / ruler_mm
        kind = "ruler"
    elif diameter_mm is not None and (diameter_px is not None or points is not None):
        if diameter_px is not None:
            reference_px = float(diameter_px)
        else:
            pair = _pair(points, "reference")
            reference_px = _distance(pair[0], pair[1])
        if reference_px <= 0 or not np.isfinite(reference_px):
            raise ValueError("the reference span in pixels must be positive")
        px_per_mm = reference_px / diameter_mm
        kind = "coin" if reference_name else "diameter"
    elif diameter_mm is not None and image_path and (coin or want_part):
        coin_detect = _detect_coin_in_file(str(image_path))
        reference_px = float(coin_detect["coin_px"])
        px_per_mm = reference_px / diameter_mm
        kind = "coin" if reference_name else "diameter"
    elif quad is not None and width_mm is not None and height_mm is not None:
        px_per_mm = quad_px_per_mm(_quad(quad), float(width_mm), float(height_mm))
        kind = "quad"
    else:
        raise ValueError(
            "Pass a coin (or diameter_mm) with diameter_px or two points, "
            "or coin plus image to detect the circle, "
            "or ruler_mm with two points, or quad with width_mm and height_mm, "
            "or image plus marker_mm for an ArUco or AprilTag."
        )

    rectified = None
    rectified_px = None
    if quad is not None and payload.get("image") and width_mm is not None and height_mm is not None:
        rectified, rectified_px = _rectify(
            str(payload["image"]),
            _quad(quad),
            float(width_mm),
            float(height_mm),
            px_per_mm,
            payload.get("out"),
            overwrite=bool(payload.get("overwrite") or payload.get("force")),
        )
    bbox_pair = None
    if kind == "ruler" and points is not None:
        bbox_pair = _pair(points, "ruler")
    elif kind in ("coin", "diameter") and points is not None:
        bbox_pair = _pair(points, "reference")
    part = None
    if want_part and image_path and px_per_mm:
        part = _measure_part(
            str(image_path),
            float(px_per_mm),
            coin_detect,
            _point(payload.get("part_seed"), "part_seed"),
            _box(payload.get("part_roi"), "part_roi"),
            payload,
        )
    measurements = _measurements(payload.get("measurements"), float(px_per_mm))
    out_of_plane = [item["name"] for item in measurements if item.get("plane") == "out_of_plane"]
    warning = None
    if out_of_plane:
        warning = (
            "out_of_plane measurement is not valid from this single photo: "
            + ", ".join(out_of_plane)
            + ". Use a caliper or a second view. One pixel of scale error is "
            f"{1.0 / float(px_per_mm):.4f} mm."
        )
    report = {
        "ok": True,
        "kind": kind,
        "coin": reference_name,
        "diameter_mm": None if diameter_mm is None else float(diameter_mm),
        "ruler_mm": None if ruler_mm is None else float(ruler_mm),
        "reference_px": reference_px,
        "reference_bbox": None if payload.get("reference_is_part") else _reference_bbox(kind, bbox_pair, reference_px, coin_detect),
        "reference_is_part": bool(payload.get("reference_is_part")),
        "coin_px": None if coin_detect is None else coin_detect.get("coin_px"),
        "coin_detect": None if coin_detect is None else coin_detect.get("coin_detect"),
        "coin_ellipse": None if coin_detect is None else coin_detect.get("coin_ellipse"),
        "scale_uncertainty_pct": None if coin_detect is None else coin_detect.get("scale_uncertainty_pct"),
        "px_per_mm": float(px_per_mm),
        "mm_per_px": float(1.0 / px_per_mm),
        "scale_plane": "in_plane",
        "uncertainty_mm_per_px": float(1.0 / px_per_mm),
        "measurements": measurements,
        "out_of_plane_warning": warning,
        "marker": marker,
        "rectified": rectified,
        "rectified_px_per_mm": rectified_px,
        "angled": bool(payload.get("angled", False)),
        "note": _PLANE_NOTE,
        "part_bbox_mm": None if part is None else part.get("part_bbox_mm"),
        "part_px": None if part is None else part.get("part_px"),
        "angle_deg": None if part is None else part.get("angle_deg"),
        "mask_png": None if part is None else part.get("mask_png"),
        "same_plane_warning": None if part is None else part.get("same_plane_warning"),
    }
    if part is not None and part.get("part_bbox_mm"):
        standards = _standards_for_measure(payload, report)
        if standards is not None:
            report["standards"] = standards
    directory = _write_last_measure(report, payload)
    if directory is None:
        report["last_measure_warning"] = (
            "last_measure.json was not written. Pass out_dir or cwd as the project directory. "
            "The plugin install directory is not a project."
        )
    else:
        report["last_measure"] = str(directory / "last_measure.json")
    return attach_flow(report, step_measure())


def _project_directory(payload: dict) -> Path | None:
    """Where this project's scale file belongs. Never the plugin install or the source checkout."""
    from photopart.paths import not_a_project

    def _accept(path: Path) -> Path | None:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            return None
        if not_a_project(resolved):
            return None
        return resolved

    for key in ("out_dir", "cwd", "project"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            chosen = _accept(Path(value))
            if chosen is not None:
                return chosen
    out = payload.get("out")
    if isinstance(out, str) and out.strip():
        chosen = _accept(Path(out).parent)
        if chosen is not None:
            return chosen
    image = payload.get("image")
    if isinstance(image, str) and image.strip():
        chosen = _accept(Path(image).parent)
        if chosen is not None:
            return chosen
    return _accept(Path.cwd())


def _stored_homography(payload: dict):
    """3×3 homography for a TL,TR,BR,BL quad, or None when the quad is absent."""
    quad = payload.get("quad")
    if quad is None:
        return None
    try:
        source = _quad(quad)
        width = float(np.max(source[:, 0]) - np.min(source[:, 0]))
        height = float(np.max(source[:, 1]) - np.min(source[:, 1]))
        if width < 2 or height < 2:
            return None
        dest = np.array(
            [[0.0, 0.0], [width, 0.0], [width, height], [0.0, height]],
            dtype=float,
        )
        matrix = homography(source, dest)
    except (TypeError, ValueError):
        return None
    return [[round(float(value), 8) for value in row] for row in np.asarray(matrix, dtype=float)]


def _write_last_measure(report: dict, payload: dict) -> Path | None:
    """Remember px/mm and an optional part region, scoped to the project directory."""
    directory = _project_directory(payload)
    if directory is None:
        return None
    image = payload.get("image")
    body = {
        "px_per_mm": report.get("px_per_mm"),
        "roi": payload.get("roi") if payload.get("roi") is not None else _box(payload.get("part_roi"), "part_roi"),
        "seed": payload.get("seed") if payload.get("seed") is not None else payload.get("part_seed"),
        "reference_bbox": report.get("reference_bbox"),
        "reference_is_part": bool(report.get("reference_is_part")),
        "part_bbox_mm": report.get("part_bbox_mm"),
        "image": None if not image else str(Path(str(image)).expanduser().resolve()),
        "angled": bool(report.get("angled")),
        "project": str(directory),
        "quad": payload.get("quad"),
        "homography": _stored_homography(payload),
        "coin_ellipse": report.get("coin_ellipse") or payload.get("coin_ellipse"),
    }
    try:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "last_measure.json").write_text(
            json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except OSError:
        return None
    return directory


def load_last_measure(*dirs, image=None) -> dict | None:
    """Scale hint for one project. Skips the plugin install and the source checkout."""
    from photopart.paths import not_a_project

    for directory in dirs:
        if not directory:
            continue
        try:
            resolved = Path(directory).expanduser().resolve()
        except OSError:
            continue
        if not_a_project(resolved):
            continue
        path = resolved / "last_measure.json"
        if not path.is_file():
            continue
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            continue
        if not isinstance(loaded, dict) or not loaded.get("px_per_mm"):
            continue
        if image is not None:
            saved_image = loaded.get("image")
            if not saved_image or Path(saved_image).expanduser().resolve() != Path(image).expanduser().resolve():
                continue
        project = loaded.get("project")
        if isinstance(project, str) and project.strip():
            try:
                if Path(project).expanduser().resolve() != resolved:
                    continue
            except OSError:
                continue
        return loaded
    return None


def _marker_scale(image_path: str, marker_mm: float) -> dict:
    """Pixels per millimetre from an ArUco or AprilTag of known side length."""
    if marker_mm <= 0 or not np.isfinite(marker_mm):
        raise ValueError("marker_mm must be positive")
    try:
        import cv2
    except ImportError as exc:
        raise ValueError("opencv is not installed, so ArUco and AprilTag detection is unavailable") from exc
    image = np.array(Image.open(image_path).convert("RGB"))
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    found = _detect_marker(gray)
    if found is None:
        raise ValueError("no ArUco or AprilTag marker was found in the image")
    return {
        "kind": found["kind"],
        "side_px": found["side_px"],
        "px_per_mm": found["side_px"] / marker_mm,
        "id": found["id"],
        "plane": "in_plane",
        "uncertainty_mm": max(1.0, 0.02 * found["side_px"]) / (found["side_px"] / marker_mm),
    }


def _detect_marker(gray: np.ndarray) -> dict | None:
    import cv2

    dictionaries = []
    if hasattr(cv2.aruco, "DICT_4X4_50"):
        dictionaries.append(("aruco", cv2.aruco.DICT_4X4_50))
    if hasattr(cv2.aruco, "DICT_APRILTAG_36h11"):
        dictionaries.append(("apriltag", cv2.aruco.DICT_APRILTAG_36h11))
    for kind, code in dictionaries:
        dictionary = cv2.aruco.getPredefinedDictionary(code)
        if hasattr(cv2.aruco, "ArucoDetector"):
            detector = cv2.aruco.ArucoDetector(dictionary, cv2.aruco.DetectorParameters())
            corners, ids, _rejected = detector.detectMarkers(gray)
        else:
            corners, ids, _rejected = cv2.aruco.detectMarkers(gray, dictionary)
        if ids is None or len(ids) == 0:
            continue
        quad = np.asarray(corners[0], dtype=float).reshape(4, 2)
        edges = [float(np.linalg.norm(quad[i] - quad[(i + 1) % 4])) for i in range(4)]
        return {"kind": kind, "side_px": float(sum(edges) / 4.0), "id": int(ids[0][0])}
    return None


def load_measure_hints(payload: dict) -> tuple[list[tuple[float, float, float, float]], bool]:
    """Rectangles to keep out of an overlay, plus whether the photo was angled."""
    if not isinstance(payload, dict):
        raise ValueError("measure JSON must be an object")
    rects: list[tuple[float, float, float, float]] = []

    def add(value) -> None:
        if value is None:
            return
        if isinstance(value, dict):
            if not all(key in value for key in ("x", "y", "w", "h")):
                return
            rects.append((float(value["x"]), float(value["y"]), float(value["w"]), float(value["h"])))
            return
        if isinstance(value, (list, tuple)):
            if len(value) == 4 and not isinstance(value[0], (list, tuple, dict)):
                rects.append(tuple(float(item) for item in value))  # type: ignore[arg-type]
                return
            for item in value:
                add(item)

    add(payload.get("reference_bbox"))
    add(payload.get("exclude_roi"))
    add(payload.get("exclude_rois"))
    return rects, bool(payload.get("angled", False))


def _point(value, name: str):
    """One ``[x, y]`` pixel, or None."""
    if value is None:
        return None
    if isinstance(value, dict) and "x" in value and "y" in value:
        pair = (float(value["x"]), float(value["y"]))
    elif isinstance(value, (list, tuple)) and len(value) >= 2 and not isinstance(value[0], (list, tuple, dict)):
        pair = (float(value[0]), float(value[1]))
    else:
        raise ValueError(f"{name} must be [x, y]")
    if not all(math.isfinite(item) for item in pair):
        raise ValueError(f"{name} must be finite")
    return pair


def _box(value, name: str):
    """A part box as ``[x0, y0, x1, y1]`` or ``{x, y, w, h}``, returned as x, y, w, h."""
    if value is None:
        return None
    if isinstance(value, dict):
        if all(key in value for key in ("x0", "y0", "x1", "y1")):
            x0, y0, x1, y1 = (float(value[key]) for key in ("x0", "y0", "x1", "y1"))
            return _positive_box(x0, y0, x1 - x0, y1 - y0, name)
        if all(key in value for key in ("x", "y", "w", "h")):
            return _positive_box(
                float(value["x"]), float(value["y"]), float(value["w"]), float(value["h"]), name
            )
        raise ValueError(f"{name} must be [x0, y0, x1, y1] or {{x, y, w, h}}")
    if isinstance(value, (list, tuple)) and len(value) == 4 and not isinstance(value[0], (list, tuple, dict)):
        x0, y0, a, b = (float(item) for item in value)
        # The hook tells the agent to pass corners. A width/height list whose
        # third value is not to the right of the first is kept as x, y, w, h.
        if a > x0 and b > y0:
            return _positive_box(x0, y0, a - x0, b - y0, name)
        return _positive_box(x0, y0, a, b, name)
    raise ValueError(f"{name} must be [x0, y0, x1, y1]")


def _positive_box(x, y, w, h, name: str):
    if min(w, h) <= 0 or not all(math.isfinite(item) for item in (x, y, w, h)):
        raise ValueError(f"{name} must be a positive box")
    return (float(x), float(y), float(w), float(h))


def _detect_coin_in_file(image_path: str) -> dict:
    """Largest plausible circle in ``image_path``. Hough proposes it; a contour confirms it."""
    path = Path(image_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"image not found: {path}")
    image = np.array(Image.open(path).convert("RGB"))
    found = _detect_coin(image)
    if found is None:
        raise ValueError("no circular coin was found in the image")
    return found


def _detect_coin(image: np.ndarray) -> dict | None:
    try:
        import cv2
    except ImportError as exc:
        raise ValueError("opencv is not installed, so coin detection is unavailable") from exc
    if image.ndim != 3 or min(image.shape[:2]) < 16:
        return None
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 1.2)
    height, width = gray.shape[:2]
    min_side = min(height, width)
    min_r = max(6, int(round(min_side * 0.04)))
    max_r = max(min_r + 2, int(round(min_side * 0.48)))
    circles = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=float(min_r * 2),
        param1=100,
        param2=28,
        minRadius=min_r,
        maxRadius=max_r,
    )
    hough = None
    if circles is not None and len(circles):
        # OpenCV orders HoughCircles by accumulator strength. The largest
        # radius is often a false halo around the coin.
        best = circles[0][0]
        hough = (float(best[0]), float(best[1]), float(best[2]))
    refined = _round_contour(blurred, min_r, max_r, hough, cv2)
    if refined is None and hough is None:
        return None
    ellipse = None
    if refined is not None:
        cx, cy, radius = refined[:3]
        ellipse = refined[3] if len(refined) > 3 else None
        coin_px = radius * 2.0
        method = "hough" if hough is not None else "contour"
        uncertainty = 4.0 if hough is None else max(2.0, abs(hough[2] * 2.0 - coin_px))
    else:
        cx, cy, radius = hough
        coin_px = radius * 2.0
        method = "hough"
        uncertainty = 4.0
    if coin_px <= 0:
        return None
    return {
        "coin_px": float(coin_px),
        "center": [float(cx), float(cy)],
        "radius_px": float(coin_px / 2.0),
        "coin_detect": method,
        "scale_uncertainty_pct": float(uncertainty / coin_px * 100.0),
        "hough_px": None if hough is None else float(hough[2] * 2.0),
        "coin_ellipse": ellipse,
    }


def _round_contour(blurred, min_r: int, max_r: int, hough, cv2):
    """minEnclosingCircle of the roundest contour near the Hough hit, if any."""
    edges = cv2.Canny(blurred, 40, 120)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    _ok, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    inverted = cv2.bitwise_not(binary)
    found = []
    for source in (edges, binary, inverted):
        contours, _hier = cv2.findContours(source, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
        found.extend(contours)
    best = None
    best_score = 1e9
    floor = math.pi * (min_r ** 2) * 0.35
    image_area = float(blurred.shape[0] * blurred.shape[1])
    for contour in found:
        area = float(cv2.contourArea(contour))
        if area < floor or area > image_area * 0.4:
            continue
        peri = float(cv2.arcLength(contour, True))
        if peri <= 1.0:
            continue
        circularity = 4.0 * math.pi * area / (peri * peri)
        if circularity < 0.85:
            continue
        (cx, cy), radius = cv2.minEnclosingCircle(contour)
        if radius < min_r or radius > max_r:
            continue
        if hough is not None and math.hypot(cx - hough[0], cy - hough[1]) > max(8.0, hough[2] * 0.45):
            continue
        # Prefer the contour that agrees with Hough. A dilated edge sits outside the disk.
        score = abs(float(radius) - (hough[2] if hough is not None else float(radius))) - circularity * 0.01
        if score < best_score:
            best_score = score
            ellipse = None
            if len(contour) >= 5:
                try:
                    _center, axes, eangle = cv2.fitEllipse(contour)
                    major = max(float(axes[0]), float(axes[1]))
                    minor = min(float(axes[0]), float(axes[1]))
                    ellipse = {
                        "major_px": round(major, 3),
                        "minor_px": round(minor, 3),
                        "angle_deg": round(float(eangle), 3),
                        "ratio": round(minor / major, 4) if major else None,
                    }
                except cv2.error:
                    ellipse = None
            best = (float(cx), float(cy), float(radius), ellipse)
    return best


def _measure_part(image_path, px_per_mm, coin_detect, seed, roi, payload) -> dict:
    """Part length and width in millimetres from a seed, a box, or the non-coin blob."""
    path = Path(image_path).expanduser()
    image = np.array(Image.open(path).convert("RGB"))
    if payload.get("reference_is_part"):
        coin_detect = None
    elif coin_detect is None:
        try:
            coin_detect = _detect_coin(image)
        except ValueError:
            coin_detect = None
    circle = None
    if isinstance(coin_detect, dict) and coin_detect.get("center") and coin_detect.get("coin_px"):
        center = coin_detect["center"]
        circle = (float(center[0]), float(center[1]), float(coin_detect["coin_px"]) / 2.0 + 4.0)
    component = _part_mask(image, seed, roi, circle)
    if component is None or int(np.count_nonzero(component)) < 16:
        raise ValueError("could not find the part in the photo; pass part_seed or part_roi")
    length_px, width_px, angle = _min_area_size(component)
    mask_png = _save_part_mask(component, payload, path)
    return {
        "part_bbox_mm": [round(length_px / float(px_per_mm), 4), round(width_px / float(px_per_mm), 4)],
        "part_px": [round(length_px, 3), round(width_px, 3)],
        "angle_deg": round(float(angle), 3),
        "mask_png": mask_png,
        "same_plane_warning": (
            "The part and the reference are assumed to lie on the same plane. "
            "A feature that stands off the plane is closer to the camera, so its "
            "millimetres run large by about standoff height divided by camera distance."
        ),
    }


def _part_mask(image, seed, roi, circle):
    from photopart.overlay import _component_at, _largest_component, color_mask, grabcut_mask

    component = None
    if seed is not None or roi is not None:
        cut = grabcut_mask(image, roi=roi, seed=seed)
        if cut is not None:
            component = np.asarray(cut, dtype=bool)
            # A seed a few pixels off the part marks that background pixel as
            # foreground, and GrabCut grows a halo. The border-color mask drops
            # the halo; the seed then snaps onto the part.
            colors = color_mask(image)
            if colors is not None:
                narrowed = component & np.asarray(colors, dtype=bool)
                if int(np.count_nonzero(narrowed)) >= 16:
                    component = narrowed
            if seed is not None:
                component = _component_at(component, seed)
    if component is None or int(np.count_nonzero(component)) < 16:
        raw = color_mask(image)
        if raw is None:
            return None
        raw = np.asarray(raw, dtype=bool).copy()
        if circle is not None:
            _zero_disk(raw, circle)
        if roi is not None:
            from photopart.overlay import _copy_rect

            gated = np.zeros_like(raw)
            _copy_rect(raw, gated, roi)
            raw = gated
        if seed is not None:
            component = _component_at(raw, seed)
        else:
            component = _largest_component(raw)
    else:
        component = np.asarray(component, dtype=bool).copy()
        if circle is not None:
            _zero_disk(component, circle)
            if seed is not None:
                component = _component_at(component, seed)
            else:
                component = _largest_component(component)
    return component


def _zero_disk(mask: np.ndarray, circle) -> None:
    import cv2

    painted = np.zeros(mask.shape[:2], dtype=np.uint8)
    cx, cy, radius = circle
    cv2.circle(painted, (int(round(cx)), int(round(cy))), max(1, int(round(radius))), 1, thickness=-1)
    mask[painted.astype(bool)] = False


def _min_area_size(mask: np.ndarray):
    """Longer side, shorter side, and angle. Pixel centers span n-1, so add one pixel."""
    import cv2

    ys, xs = np.nonzero(mask)
    points = np.stack([xs.astype(np.float32), ys.astype(np.float32)], axis=1)
    _center, (width, height), angle = cv2.minAreaRect(points)
    longer, shorter = sorted((float(width) + 1.0, float(height) + 1.0), reverse=True)
    return longer, shorter, float(angle)


def _save_part_mask(mask: np.ndarray, payload: dict, image_path: Path) -> str | None:
    directory = _project_directory(payload) or image_path.parent
    destination = directory / "part_mask.png"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        Image.fromarray(np.where(mask, np.uint8(255), np.uint8(0)), mode="L").save(destination, format="PNG")
    except OSError:
        return None
    return str(destination.resolve())


def _standards_for_measure(payload: dict, report: dict):
    """Warn-only fastener check. Returns None when the payload names no standard."""
    from photopart.standards import check_standard

    spec = payload.get("spec")
    body = dict(spec) if isinstance(spec, dict) else {}
    if isinstance(spec, str) and spec.strip():
        body["notes"] = spec
    for key in ("part", "name", "designation", "notes", "note", "title", "description"):
        value = payload.get(key)
        if key not in body and isinstance(value, str):
            body[key] = value
    if not body:
        return None
    measured = {
        "part_bbox_mm": report.get("part_bbox_mm"),
        "pitch_mm": payload.get("pitch_mm"),
        "across_mm": payload.get("across_mm"),
        "flange_mm": payload.get("flange_mm"),
        "extents_mm": payload.get("extents_mm"),
    }
    if payload.get("quad") is None:
        measured["width_mm"] = payload.get("width_mm")
    result = check_standard(body, measured)
    if not result.get("checked"):
        return None
    return result


def _reference_bbox(kind: str | None, pair, reference_px, coin_detect=None) -> dict | None:
    """Circle around a coin, or a padded box around a ruler span."""
    if isinstance(coin_detect, dict) and coin_detect.get("center") and coin_detect.get("coin_px"):
        center = coin_detect["center"]
        radius = float(coin_detect["coin_px"]) / 2.0
        pad = max(2.0, radius * 0.08)
        reach = radius + pad
        return {
            "x": float(center[0]) - reach,
            "y": float(center[1]) - reach,
            "w": float(2.0 * reach),
            "h": float(2.0 * reach),
        }
    if pair is None or reference_px is None:
        return None
    points = np.asarray(pair, dtype=float).reshape(2, 2)
    if kind == "ruler":
        pad = max(3.0, float(reference_px) * 0.08)
        x0 = float(points[:, 0].min()) - pad
        y0 = float(points[:, 1].min()) - pad
        x1 = float(points[:, 0].max()) + pad
        y1 = float(points[:, 1].max()) + pad
        return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}
    radius = float(reference_px) / 2.0
    mid = (points[0] + points[1]) / 2.0
    pad = max(2.0, radius * 0.08)
    reach = radius + pad
    return {
        "x": float(mid[0] - reach),
        "y": float(mid[1] - reach),
        "w": float(2.0 * reach),
        "h": float(2.0 * reach),
    }


def _rectify(image_path, quad, width_mm, height_mm, px_per_mm, out, *, overwrite=False) -> tuple[str, float]:
    from PIL import Image

    path = Path(image_path).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.is_file():
        raise FileNotFoundError(f"image not found: {path}")
    image = np.array(Image.open(path).convert("RGB"))
    scale = float(px_per_mm)
    out_w = max(2, int(round(width_mm * scale)))
    out_h = max(2, int(round(height_mm * scale)))
    cap = 4000
    if max(out_w, out_h) > cap:
        factor = cap / max(out_w, out_h)
        out_w = max(2, int(round(out_w * factor)))
        out_h = max(2, int(round(out_h * factor)))
        scale *= factor
    dest = np.array([[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1], [0, out_h - 1]], dtype=float)
    matrix = homography(quad, dest)
    warped = _warp(image, matrix, out_w, out_h)
    fallback = path.stem + "_rectified.png"
    if out:
        destination = new_output(out, ".png", overwrite=overwrite)
    else:
        destination = new_output(default_output(path.with_name(fallback), fallback), ".png", overwrite=overwrite)
    destination.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(warped, mode="RGB").save(destination, format="PNG")
    return str(destination.resolve()), float(scale)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pixel-to-millimetre scale from a coin, a ruler, or a rectangle."
    )
    parser.add_argument("--coin", help="Denomination id, such as euro_1 or us_quarter.")
    parser.add_argument("--diameter-mm", type=float, help="Reference diameter when it is not a known coin.")
    parser.add_argument("--diameter-px", type=float, help="That diameter in pixels.")
    parser.add_argument("--reference-is-part", action="store_true", help="The known span belongs to the part; do not exclude it from the overlay.")
    parser.add_argument("--points", help="Two pixels x1,y1,x2,y2 spanning the coin or the ruler.")
    parser.add_argument("--ruler-mm", type=float, help="Real length between --points, in millimetres.")
    parser.add_argument("--quad", help="Four pixels TL,TR,BR,BL as x,y,x,y,x,y,x,y.")
    parser.add_argument("--width-mm", type=float)
    parser.add_argument("--height-mm", type=float)
    parser.add_argument("--image", help="Photo to rectify when --quad is set.")
    parser.add_argument("--out", help="Rectified PNG path. Default: the working directory, never HERMES_HOME/cache.")
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing --out PNG.")
    parser.add_argument("--angled", action="store_true", help="Record that this photo is not straight-on.")
    parser.add_argument(
        "--measure",
        action="append",
        default=[],
        help="name=x1,y1,x2,y2 span to convert with the same scale.",
    )
    parser.add_argument("--json", help="JSON object of the same fields. Flags override it.")
    args = parser.parse_args(argv)
    try:
        payload = json.loads(Path(args.json).read_text(encoding="utf-8")) if args.json else {}
        if not isinstance(payload, dict):
            raise ValueError("--json must contain an object")
        if args.coin:
            payload["coin"] = args.coin
        if args.diameter_mm is not None:
            payload["diameter_mm"] = args.diameter_mm
        if args.diameter_px is not None:
            payload["diameter_px"] = args.diameter_px
        if args.reference_is_part:
            payload["reference_is_part"] = True
        if args.ruler_mm is not None:
            payload["ruler_mm"] = args.ruler_mm
        if args.width_mm is not None:
            payload["width_mm"] = args.width_mm
        if args.height_mm is not None:
            payload["height_mm"] = args.height_mm
        if args.image:
            payload["image"] = args.image
        if args.out:
            payload["out"] = args.out
        if args.overwrite:
            payload["overwrite"] = True
        if args.angled:
            payload["angled"] = True
        if args.points:
            payload["points"] = _csv_pairs(args.points, 2)
        if args.quad:
            payload["quad"] = _csv_pairs(args.quad, 4)
        extra = []
        for item in args.measure:
            if "=" not in item:
                raise ValueError("--measure expects name=x1,y1,x2,y2")
            name, rest = item.split("=", 1)
            extra.append({"name": name.strip(), "points": _csv_pairs(rest, 2)})
        if extra:
            payload.setdefault("measurements", [])
            payload["measurements"].extend(extra)
        report = measure(payload)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps(failed(str(exc)), indent=2, sort_keys=True))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _csv_pairs(text: str, count: int):
    pieces = [part.strip() for part in text.split(",")]
    if len(pieces) != count * 2:
        raise ValueError(f"expected {count * 2} comma-separated numbers, got {text!r}")
    numbers = [float(part) for part in pieces]
    return [[numbers[i], numbers[i + 1]] for i in range(0, len(numbers), 2)]
