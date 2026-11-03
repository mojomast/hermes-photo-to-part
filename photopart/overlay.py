"""Silhouette outline for a reference photo.

The line is the outer contour of the z-buffer mask, not the mesh's facet edges.
``center`` places that mask on the image center. ``auto`` scales, rotates,
and optionally mirrors it onto the part. It tries front, side, and top,
searching rotation at 15° and then 1°. An angled photo still gets an IoU,
labelled ``guide_only``. An ROI that cuts the silhouette is expanded.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image

_MAGENTA = np.array([255.0, 0.0, 210.0])
_ALPHA = 0.62


def paint_overlay(
    points: np.ndarray,
    faces: np.ndarray,
    photo: Path,
    destination: Path,
    diff_destination: Path,
    *,
    photo_scale: float,
    origin: tuple[float, float] | None,
    fit: str,
    roi: tuple[float, float, float, float] | None = None,
    seed: tuple[float, float] | None = None,
    exclude: list | None = None,
    angled: bool = False,
    view: str = "front",
) -> dict:
    """Draw the front silhouette on a copy of ``photo`` and write a diff image.

    ``roi`` is ``x, y, w, h`` in image pixels. ``seed`` is one pixel on the part.
    ``exclude`` drops rectangles (the coin or ruler) before the largest blob is chosen.
    """
    if fit not in ("center", "auto"):
        raise ValueError("overlay fit must be center or auto")
    image = np.array(Image.open(photo).convert("RGB"))
    height, width = image.shape[:2]
    model, minimum, maximum = raster_model(points, faces, photo_scale)
    note = None
    used = fit
    blob = None
    foreground = None
    rotation = 0.0
    mirror = False
    roi_warnings: list[str] = []
    roi_expanded = False
    hints = bool(roi or seed or exclude)
    if origin is not None:
        placed = _blit_origin(model, (height, width), minimum, maximum, photo_scale, origin)
        used = "origin"
        foreground, blob, roi_warnings, roi_expanded = _foreground_for_overlay(
            image, roi=roi, seed=seed, exclude=exclude, hints=hints
        )
    elif fit == "auto":
        foreground, blob, roi_warnings, roi_expanded = _foreground_for_overlay(
            image, roi=roi, seed=seed, exclude=exclude, hints=True
        )
        if foreground is None:
            placed = _blit_center(model, (height, width), minimum, maximum, photo_scale, points)
            used = "center"
            note = (
                "Could not segment a part from the photo, so the outline stayed centered. "
                "Pass roi or seed on the part, and exclude the coin."
            )
        else:
            pose = _select_pose(model, foreground, image, roi)
            placed = pose["placed"]
            note = pose["note"]
            rotation = pose["rotation_deg"]
            mirror = pose["mirror"]
            used = "auto"
    else:
        placed = _blit_center(model, (height, width), minimum, maximum, photo_scale, points)
        foreground, blob, roi_warnings, roi_expanded = _foreground_for_overlay(
            image, roi=roi, seed=seed, exclude=exclude, hints=hints
        )
    iou = None if foreground is None else _iou(placed, foreground)
    alignment = _alignment(image, placed, foreground, roi, seed, exclude)
    if alignment["confidence"] == "low":
        iou = None
        unreliable = "overlay unreliable: pass roi= or a seed; do not iterate geometry on it"
        note = f"{note} {unreliable}".strip() if note else unreliable
    poses = []
    if used == "auto" and iou is not None:
        poses = [
            {
                "view": view,
                "rotation_deg": float(rotation),
                "mirror": bool(mirror),
                "iou": round(float(iou), 4),
            }
        ]
    return _write_overlay(
        image,
        placed,
        foreground,
        blob,
        destination,
        diff_destination,
        fit=used,
        note=note,
        iou=iou,
        warnings=_overlay_warnings(
            iou,
            blob,
            angled=angled,
            missed=foreground is None and (fit == "auto" or hints),
            extra=roi_warnings,
        ),
        rotation=rotation,
        mirror=mirror,
        view=view,
        poses=poses,
        roi_expanded=roi_expanded,
        angled=angled,
        alignment=alignment,
    )


def paint_auto_views(
    views: list,
    photo: Path,
    destination: Path,
    diff_destination: Path,
    *,
    photo_scale: float,
    roi: tuple[float, float, float, float] | None = None,
    seed: tuple[float, float] | None = None,
    exclude: list | None = None,
    angled: bool = False,
) -> dict:
    """Try front, side, and top. Keep the pose with the best overlap.

    ``views`` is ``(name, points, faces)`` in preference order. Each view is
    searched at 15°, then at 1°, including a mirror. Within 0.01 IoU the
    earlier view wins, so a rectangle does not flip to top. ``overlay_poses``
    lists every view's best pose, winner first. An angled photo is still
    scored; its IoU is labelled ``guide_only``.
    """
    if not views:
        raise ValueError("overlay auto needs at least one view")
    image = np.array(Image.open(photo).convert("RGB"))
    foreground, blob, roi_warnings, roi_expanded = _foreground_for_overlay(
        image, roi=roi, seed=seed, exclude=exclude, hints=True
    )
    chosen = None
    found = []
    if foreground is not None:
        for index, (name, points, faces) in enumerate(views):
            model, _minimum, _maximum = raster_model(points, faces, photo_scale)
            pose = _select_pose(model, foreground, image, roi)
            row = {
                "pose": pose,
                "name": name,
                "index": index,
                "iou": pose["iou"],
                "rotation_deg": pose["rotation_deg"],
                "mirror": pose["mirror"],
            }
            found.append(row)
            if chosen is None or _prefer_pose(pose["iou"], index, chosen["iou"], chosen["index"]):
                chosen = row
    poses = []
    if chosen is None:
        name, points, faces = views[0]
        model, minimum, maximum = raster_model(points, faces, photo_scale)
        placed = _blit_center(model, image.shape[:2], minimum, maximum, photo_scale, points)
        note = (
            "Could not segment a part from the photo, so the outline stayed centered. "
            "Pass roi or seed on the part, and exclude the coin."
        )
        rotation = 0.0
        mirror = False
        view_name = name
        iou = None if foreground is None else _iou(placed, foreground)
    else:
        placed = chosen["pose"]["placed"]
        note = chosen["pose"]["note"]
        rotation = chosen["rotation_deg"]
        mirror = chosen["mirror"]
        view_name = chosen["name"]
        iou = chosen["iou"]
        note = f"{note} View {view_name}."
        rest = [row for row in found if row is not chosen]
        rest.sort(key=lambda row: (-row["iou"], row["index"]))
        poses = [
            {
                "view": row["name"],
                "rotation_deg": float(row["rotation_deg"]),
                "mirror": bool(row["mirror"]),
                "iou": round(float(row["iou"]), 4),
            }
            for row in (chosen, *rest)
        ]
    alignment = _alignment(image, placed, foreground, roi, seed, exclude)
    if alignment["confidence"] == "low":
        iou = None
        for row in poses:
            row["iou"] = None
        unreliable = "overlay unreliable: pass roi= or a seed; do not iterate geometry on it"
        note = f"{note} {unreliable}".strip() if note else unreliable
    warnings = _overlay_warnings(
        iou, blob, angled=angled, missed=foreground is None, extra=roi_warnings
    )
    return _write_overlay(
        image,
        placed,
        foreground,
        blob,
        destination,
        diff_destination,
        fit="auto",
        note=note,
        iou=iou,
        warnings=warnings,
        rotation=rotation,
        mirror=mirror,
        view=view_name,
        poses=poses,
        roi_expanded=roi_expanded,
        angled=angled,
        alignment=alignment,
    )


def search_alignment(model: np.ndarray, foreground: np.ndarray) -> dict:
    """Coarse 15° search, then ±15° at 1°, including a mirror.

    The search runs on masks no wider than 160 px. The reported IoU is the
    full-resolution overlap of the winning pose. Ties within 0.01 IoU prefer
    no mirror and the angle closer to 0, so an axis-aligned part stays put.
    """
    long_side = max(max(model.shape), max(foreground.shape))
    factor = 1.0 if long_side <= 160 else 160.0 / long_side
    small_model = _resize_by(model, factor)
    small_foreground = _resize_by(foreground, factor)
    best: dict | None = None

    def consider(angle: float, mirror: bool) -> None:
        nonlocal best
        placed = _place(small_model, small_foreground, angle, mirror, close=False)
        score = _iou(placed, small_foreground)
        key = _pose_key(angle, mirror)
        if best is None or score > best["score"] + 0.01 or (score >= best["score"] - 0.01 and key < best["key"]):
            best = {"score": score, "angle": angle % 360.0, "mirror": mirror, "key": key}

    for mirror in (False, True):
        for step in range(0, 360, 15):
            consider(float(step), mirror)
    assert best is not None
    center = best["angle"]
    for mirror in (False, True):
        for delta in range(-15, 16, 1):
            consider(center + delta, mirror)
    angle = float(best["angle"])
    mirror = bool(best["mirror"])
    placed = _place(model, foreground, angle, mirror, close=True)
    full = _iou(placed, foreground)
    # A symmetric silhouette ties under a mirror. Prefer the unmirrored pose
    # when the full-resolution scores are within 0.01.
    other = _place(model, foreground, angle, not mirror, close=True)
    other_iou = _iou(other, foreground)
    if other_iou + 0.01 >= full and (not mirror) is False:
        # other is mirrored; keep the current one when it is already unmirrored
        pass
    if (not mirror) and other_iou > full + 0.01:
        placed, full, mirror = other, other_iou, True
    elif mirror and other_iou + 0.01 >= full:
        placed, full, mirror = other, other_iou, False
    angle = round(angle, 2)
    note = f"Aligned at {angle:g} deg, mirror {'on' if mirror else 'off'}."
    return {
        "placed": placed,
        "rotation_deg": angle,
        "mirror": mirror,
        "iou": full,
        "note": note,
    }


def _select_pose(model: np.ndarray, foreground: np.ndarray, image: np.ndarray, roi) -> dict:
    """Chamfer picks the pose when image edges exist. IoU search is the fallback."""
    iou_pose = search_alignment(model, foreground)
    chamfer = _search_chamfer(model, image, foreground, roi)
    iou_metrics = _chamfer_of_placed(iou_pose["placed"], image, roi)
    if chamfer is None:
        iou_pose.update(iou_metrics)
        return iou_pose
    # A rectangle matches at 180°. When the chamfer scores are that close,
    # keep the pose nearer to 0°, which is what the IoU search already picks.
    iou_px = iou_metrics.get("chamfer_px")
    if iou_px is not None and float(chamfer["chamfer_px"]) + 0.35 >= float(iou_px):
        if _pose_key(float(iou_pose["rotation_deg"]), bool(iou_pose["mirror"])) <= _pose_key(
            float(chamfer["rotation_deg"]), bool(chamfer["mirror"])
        ):
            iou_pose.update(iou_metrics)
            return iou_pose
    if float(chamfer.get("chamfer_norm") or 1.0) <= 0.05 or float(chamfer["iou"]) + 0.08 >= float(iou_pose["iou"]):
        return chamfer
    iou_pose.update(iou_metrics)
    return iou_pose


def _search_chamfer(model: np.ndarray, image: np.ndarray, foreground: np.ndarray, roi) -> dict | None:
    """Truncated chamfer on Canny edges. Scale stays at the known px/mm raster."""
    try:
        import cv2
    except ImportError:
        return None
    edges, dist, tau, diagonal = _edge_field(image, roi)
    if edges is None or int(np.count_nonzero(edges)) < 20 or diagonal <= 1.0:
        return None
    contour = _contour_points(model)
    if contour is None:
        return None
    center = _mask_center(model)
    photo = _mask_center(foreground)
    if center is None or photo is None:
        return None

    def score(angle: float, mirror: bool) -> float:
        samples = _rotated_samples(contour, center, photo, angle, mirror, dist)
        if samples is None:
            return 1e6
        return float(np.mean(np.minimum(samples, tau)))

    ranked = []
    for mirror in (False, True):
        for step in range(0, 360, 15):
            ranked.append((score(float(step), mirror), float(step) % 360.0, mirror))
    ranked.sort(key=lambda item: (item[0], _pose_key(item[1], item[2])))
    coarse = ranked[0]
    fine = []
    for mirror in (False, True):
        for delta in range(-15, 16):
            angle = (coarse[1] + delta) % 360.0
            fine.append((score(angle, mirror), angle, mirror))
    fine.sort(key=lambda item: (item[0], _pose_key(item[1], item[2])))
    top = fine[:3]
    chamfer_px, angle, mirror = top[0]
    placed = _place(model, foreground, angle, mirror, close=True, scale_mode="fixed")
    full = _iou(placed, foreground)
    norm = float(chamfer_px) / float(diagonal)
    note = f"Aligned at {angle:g} deg, mirror {'on' if mirror else 'off'}. chamfer {chamfer_px:.2f} px."
    return {
        "placed": placed,
        "rotation_deg": round(float(angle), 2),
        "mirror": bool(mirror),
        "iou": full,
        "note": note,
        "chamfer_px": round(float(chamfer_px), 4),
        "chamfer_norm": round(norm, 4),
        "top": [
            {"rotation_deg": round(float(item[1]), 2), "mirror": bool(item[2]), "chamfer_px": round(float(item[0]), 4)}
            for item in top
        ],
    }


def _edge_field(image: np.ndarray, roi):
    import cv2

    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if image.ndim == 3 else image
    edges = cv2.Canny(gray, 40, 120)
    height, width = edges.shape
    diagonal = math.hypot(width, height)
    if roi is not None:
        x, y, w, h = (int(roi[0]), int(roi[1]), int(roi[2]), int(roi[3]))
        x = max(0, min(width - 1, x))
        y = max(0, min(height - 1, y))
        w = max(1, min(width - x, w))
        h = max(1, min(height - y, h))
        gate = np.zeros_like(edges)
        gate[y : y + h, x : x + w] = edges[y : y + h, x : x + w]
        edges = gate
        diagonal = math.hypot(w, h)
    inv = np.where(edges > 0, np.uint8(0), np.uint8(255))
    dist = cv2.distanceTransform(inv, cv2.DIST_L2, 3)
    tau = 0.03 * float(diagonal)
    return edges, dist, tau, float(diagonal)


def _contour_points(model: np.ndarray):
    import cv2

    mask = (model.astype(np.uint8)) * 255
    contours, _hierarchy = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    points = np.vstack([item.reshape(-1, 2) for item in contours]).astype(float)
    if len(points) > 500:
        points = points[:: max(1, len(points) // 500)]
    return points


def _mask_center(mask: np.ndarray):
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return None
    return float(xs.mean()), float(ys.mean())


def _rotated_samples(points, center, photo, angle: float, mirror: bool, dist: np.ndarray):
    mcx, mcy = center
    pcx, pcy = photo
    dx = points[:, 0] - mcx
    dy = points[:, 1] - mcy
    if mirror:
        dx = -dx
    rad = math.radians(float(angle))
    cos_a = math.cos(rad)
    sin_a = math.sin(rad)
    rx = cos_a * dx - sin_a * dy
    ry = sin_a * dx + cos_a * dy
    qx = np.rint(pcx + rx).astype(np.int32)
    qy = np.rint(pcy + ry).astype(np.int32)
    height, width = dist.shape
    keep = (qx >= 0) & (qy >= 0) & (qx < width) & (qy < height)
    if int(np.count_nonzero(keep)) < 8:
        return None
    return dist[qy[keep], qx[keep]]


def _chamfer_of_placed(placed: np.ndarray, image: np.ndarray, roi) -> dict:
    try:
        edges, dist, _tau, diagonal = _edge_field(image, roi)
    except Exception:
        return {"chamfer_px": None, "chamfer_norm": None}
    if edges is None or diagonal <= 1.0 or int(np.count_nonzero(edges)) < 20:
        return {"chamfer_px": None, "chamfer_norm": None}
    points = _contour_points(placed)
    if points is None:
        return {"chamfer_px": None, "chamfer_norm": None}
    height, width = dist.shape
    qx = np.rint(points[:, 0]).astype(np.int32)
    qy = np.rint(points[:, 1]).astype(np.int32)
    keep = (qx >= 0) & (qy >= 0) & (qx < width) & (qy < height)
    if int(np.count_nonzero(keep)) < 8:
        return {"chamfer_px": None, "chamfer_norm": None}
    samples = dist[qy[keep], qx[keep]]
    tau = 0.03 * diagonal
    chamfer_px = float(np.mean(np.minimum(samples, tau)))
    return {"chamfer_px": round(chamfer_px, 4), "chamfer_norm": round(chamfer_px / diagonal, 4)}


def _alignment(image, placed, foreground, roi, seed, exclude) -> dict:
    gate = _segmentation_gate(image, foreground, roi, seed, exclude)
    metrics = _chamfer_of_placed(placed, image, roi) if placed is not None else {"chamfer_px": None, "chamfer_norm": None}
    iou = None
    if gate["confidence"] != "low" and foreground is not None and placed is not None:
        iou = round(float(_iou(placed, foreground)), 4)
    return {
        "chamfer_px": metrics.get("chamfer_px"),
        "chamfer_norm": metrics.get("chamfer_norm"),
        "iou": iou,
        "stability": gate["stability"],
        "confidence": gate["confidence"],
        "reason": gate["reason"],
    }


def _segmentation_gate(image, foreground, roi, seed, exclude) -> dict:
    """Stability of the part mask. Low confidence drops the IoU headline."""
    color_masks = []
    for scale in (0.85, 1.0, 1.15):
        raw = color_mask(image, threshold_scale=scale)
        if raw is None:
            continue
        chosen = _gate_mask(raw, roi, seed, exclude)
        if chosen is not None and int(chosen.sum()) >= 16:
            color_masks.append(chosen)
    grab = []
    if roi is not None or seed is not None:
        for iterations in (1, 3, 5):
            cut = grabcut_mask(image, roi=roi, seed=seed, iterations=iterations)
            if cut is not None and int(np.count_nonzero(cut)) >= 16:
                grab.append(cut.astype(bool))
    color_stability = _mean_pairwise_iou(color_masks)
    grab_stability = _mean_pairwise_iou(grab)
    if grab and grab_stability >= 0.85:
        stability = grab_stability
    elif color_masks:
        stability = color_stability
    else:
        stability = 0.0
    touches, fraction = _roi_stats(foreground, image.shape, roi)
    reasons = []
    low = foreground is None
    if foreground is None:
        reasons.append("no part mask")
    else:
        if stability < 0.85:
            reasons.append(f"stability {stability:.2f} is under 0.85")
            low = True
        # The 5% floor applies inside an explicit roi. A part that is small in
        # the full frame is still a real segmentation; cropping it out of the
        # roi is what should drop confidence.
        if roi is not None and fraction < 0.05:
            reasons.append(f"mask area {fraction:.2f} of the roi is under 5%")
            low = True
        if fraction > 0.90 and touches >= 2:
            reasons.append(f"mask area {fraction:.2f} of the roi and it touches two borders")
            low = True
        elif touches >= 2 and roi is not None and fraction > 0.5:
            reasons.append("mask touches two or more roi borders")
            low = True
    if low:
        confidence = "low"
    elif stability >= 0.92 and touches == 0:
        confidence = "high"
    else:
        confidence = "medium"
    reason = "; ".join(reasons) if reasons else "segmentation stable"
    return {"stability": round(float(stability), 4), "confidence": confidence, "reason": reason}


def _gate_mask(mask, roi, seed, exclude):
    chosen = mask.copy()
    for rect in exclude or []:
        _zero_rect(chosen, rect)
    if roi is not None:
        gated = np.zeros_like(chosen)
        _copy_rect(chosen, gated, roi)
        chosen = gated
    if seed is not None:
        component = _component_at(chosen, seed)
    else:
        component = _largest_component(chosen)
    if component is None or int(component.sum()) < 16:
        return None
    return component


def _mean_pairwise_iou(masks: list) -> float:
    if len(masks) < 2:
        return 1.0 if masks else 0.0
    scores = []
    for index, left in enumerate(masks):
        for right in masks[index + 1 :]:
            scores.append(_iou(left, right))
    if not scores:
        return 0.0
    return float(sum(scores) / len(scores))


def _roi_stats(mask, shape, roi) -> tuple[int, float]:
    if mask is None:
        return 0, 0.0
    height, width = shape[:2]
    if roi is not None:
        x, y, w, h = (int(roi[0]), int(roi[1]), int(max(1, roi[2])), int(max(1, roi[3])))
        x = max(0, min(width - 1, x))
        y = max(0, min(height - 1, y))
        w = max(1, min(width - x, w))
        h = max(1, min(height - y, h))
        region = mask[y : y + h, x : x + w]
    else:
        region = mask
    if region.size == 0:
        return 0, 0.0
    fraction = float(np.count_nonzero(region)) / float(region.size)
    touches = 0
    if region[0].any():
        touches += 1
    if region[-1].any():
        touches += 1
    if region[:, 0].any():
        touches += 1
    if region[:, -1].any():
        touches += 1
    return touches, fraction


def _prefer_pose(new_iou: float, new_index: int, old_iou: float, old_index: int) -> bool:
    if new_iou > old_iou + 0.01:
        return True
    return abs(new_iou - old_iou) <= 0.01 and new_index < old_index


def _pose_key(angle: float, mirror: bool) -> tuple:
    wrapped = angle % 360.0
    distance = min(wrapped, 360.0 - wrapped)
    return (distance, 1 if mirror else 0, wrapped)


def _resize_by(mask: np.ndarray, factor: float) -> np.ndarray:
    if factor >= 0.999:
        return mask
    height, width = mask.shape
    resized_w = max(1, int(round(width * factor)))
    resized_h = max(1, int(round(height * factor)))
    image = Image.fromarray((mask.astype(np.uint8) * 255), mode="L")
    small = np.asarray(image.resize((resized_w, resized_h), Image.Resampling.NEAREST))
    return small > 127


def _place(
    model: np.ndarray,
    foreground: np.ndarray,
    angle_deg: float,
    mirror: bool,
    *,
    close: bool,
    scale_mode: str = "match",
) -> np.ndarray:
    model_box = _bbox(model)
    photo_box = _bbox(foreground)
    if model_box is None or photo_box is None:
        return np.zeros_like(foreground)
    mx0, my0, mx1, my1 = model_box
    px0, py0, px1, py1 = photo_box
    ys, xs = np.nonzero(model)
    pys, pxs = np.nonzero(foreground)
    model_pixels = int(xs.size)
    photo_pixels = int(pxs.size)
    if scale_mode == "fixed":
        scale = 1.0
    elif model_pixels > 0 and photo_pixels > 0:
        # Pixel area stays stable when the part is rotated. The axis-aligned
        # box of a rotated silhouette is larger than the part.
        scale = math.sqrt(photo_pixels / model_pixels)
    else:
        mw = max(1, mx1 - mx0)
        mh = max(1, my1 - my0)
        fw = max(1, px1 - px0)
        fh = max(1, py1 - py0)
        scale = math.sqrt((fw * fh) / (mw * mh))
    # Centroid, not the box centre. An L rotated 45° moves its box centre
    # and would otherwise miss the photo by a wide margin.
    mcx = float(xs.mean()) if model_pixels else (mx0 + mx1 - 1) / 2.0
    mcy = float(ys.mean()) if model_pixels else (my0 + my1 - 1) / 2.0
    pcx = float(pxs.mean()) if photo_pixels else (px0 + px1 - 1) / 2.0
    pcy = float(pys.mean()) if photo_pixels else (py0 + py1 - 1) / 2.0
    dx = (xs.astype(float) - mcx) * scale
    dy = (ys.astype(float) - mcy) * scale
    if mirror:
        dx = -dx
    rad = math.radians(float(angle_deg))
    cos_a = math.cos(rad)
    sin_a = math.sin(rad)
    rx = cos_a * dx - sin_a * dy
    ry = sin_a * dx + cos_a * dy
    placed_x = np.rint(pcx + rx).astype(np.int32)
    placed_y = np.rint(pcy + ry).astype(np.int32)
    placed = np.zeros(foreground.shape, dtype=bool)
    keep = (placed_x >= 0) & (placed_y >= 0) & (placed_x < placed.shape[1]) & (placed_y < placed.shape[0])
    placed[placed_y[keep], placed_x[keep]] = True
    if close:
        placed = _close(placed)
    return placed


def _write_overlay(
    image,
    placed,
    foreground,
    blob,
    destination,
    diff_destination,
    *,
    fit,
    note,
    iou,
    warnings,
    rotation,
    mirror,
    view,
    poses=None,
    roi_expanded=False,
    angled=False,
    alignment=None,
) -> dict:
    if warnings and note:
        note = note + " " + " ".join(warnings)
    elif warnings:
        note = " ".join(warnings)
    painted = _draw_contour(image, placed)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(painted, mode="RGB").save(destination, format="PNG")
    diff = _diff_image(image, placed, foreground)
    Image.fromarray(diff, mode="RGB").save(diff_destination, format="PNG")
    label = None
    if iou is not None:
        label = "guide_only" if angled else "measured"
    return {
        "overlay_fit": fit,
        "overlay_iou": None if iou is None else round(float(iou), 4),
        "overlay_iou_label": label,
        "overlay_diff": str(Path(diff_destination).resolve()),
        "overlay_fit_note": note,
        "overlay_blob": blob,
        "overlay_warnings": warnings,
        "overlay_rotation_deg": float(rotation),
        "overlay_mirror": bool(mirror),
        "overlay_view": view,
        "overlay_poses": list(poses or []),
        "overlay_top_poses": list(poses or [])[:3],
        "overlay_roi_expanded": bool(roi_expanded),
        "alignment": alignment,
    }


def raster_model(points: np.ndarray, faces: np.ndarray, photo_scale: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Boolean silhouette in a tight canvas at ``photo_scale`` pixels per millimetre."""
    if len(points) == 0 or len(faces) == 0:
        return np.zeros((1, 1), dtype=bool), np.zeros(2), np.zeros(2)
    minimum = points.min(axis=0)
    maximum = points.max(axis=0)
    span = np.maximum(maximum - minimum, 1e-6)
    width = int(math.ceil(float(span[0]) * photo_scale)) + 1
    height = int(math.ceil(float(span[1]) * photo_scale)) + 1
    if width < 2 or height < 2:
        raise ValueError("photo scale is too small to draw an outline")
    if width * height > 8_000_000:
        raise ValueError("overlay raster is too large. Lower photo_scale.")
    pixels = np.column_stack(
        (
            (points[:, 0] - minimum[0]) * photo_scale,
            (maximum[1] - points[:, 1]) * photo_scale,
        )
    )
    return _raster_mask(pixels, faces, width, height), minimum, maximum


def foreground_mask(image: np.ndarray) -> np.ndarray | None:
    """Largest region whose color differs from the border. None when that fails."""
    mask = color_mask(image)
    if mask is None:
        return None
    component = _largest_component(mask)
    fraction = float(component.mean())
    if fraction < 0.005 or fraction > 0.90:
        return None
    return component


def color_mask(image: np.ndarray, threshold_scale: float = 1.0) -> np.ndarray | None:
    """Pixels that differ from the border color, before a blob is chosen."""
    if image.ndim != 3 or image.shape[0] < 4 or image.shape[1] < 4:
        return None
    border = np.concatenate([image[0], image[-1], image[:, 0], image[:, -1]], axis=0).astype(np.float64)
    background = np.median(border, axis=0)
    distance = np.linalg.norm(image.astype(np.float64) - background, axis=2)
    spread = float(np.median(np.abs(border - background)))
    mask = distance > max(18.0, spread * 4.0 + 12.0) * float(threshold_scale)
    if int(mask.sum()) < 16:
        return None
    return mask


def select_foreground(
    image: np.ndarray,
    *,
    roi: tuple[float, float, float, float] | None = None,
    seed: tuple[float, float] | None = None,
    exclude: list | None = None,
) -> tuple[np.ndarray | None, dict | None]:
    """Pick one blob. Seed wins, then the region inside roi, otherwise the largest.

    Exclude rectangles are cleared first so a coin is not the largest object.
    A seed is flood-filled at full resolution. If that pixel is background, a
    small neighborhood is searched.
    """
    mask = color_mask(image)
    if mask is None:
        return None, None
    chosen = mask.copy()
    for rect in exclude or []:
        _zero_rect(chosen, rect)
    source = "largest"
    if roi is not None:
        gated = np.zeros_like(chosen)
        _copy_rect(chosen, gated, roi)
        chosen = gated
        source = "roi"
    if seed is not None:
        component = _component_at(chosen, seed)
        source = "seed"
    else:
        component = _largest_component(chosen)
    if component is None or int(component.sum()) < 16:
        return None, None
    fraction = float(component.mean())
    if seed is None and roi is None and (fraction < 0.005 or fraction > 0.90):
        return None, None
    if fraction > 0.90:
        return None, None
    box = _bbox(component)
    blob = None
    if box is not None:
        x0, y0, x1, y1 = box
        blob = {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0, "source": source}
    return component, blob


def _foreground_for_score(image, *, roi, seed, exclude, hints: bool):
    if hints:
        return select_foreground(image, roi=roi, seed=seed, exclude=exclude)
    mask = foreground_mask(image)
    if mask is None:
        return None, None
    box = _bbox(mask)
    blob = None
    if box is not None:
        x0, y0, x1, y1 = box
        blob = {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0, "source": "largest"}
    return mask, blob


def _overlay_warnings(iou, blob, *, angled: bool, missed: bool, extra: list | None = None) -> list[str]:
    warnings = list(extra or [])
    if iou is not None and iou < 0.5:
        where = ""
        if blob is not None and blob.get("source") == "largest":
            where = " The largest object in the photo was used."
        warnings.append(
            f"overlay IoU {iou:.2f} is below 0.5.{where} "
            "Pass roi or seed on the part, and exclude the coin with measure JSON or exclude_roi."
        )
    elif missed:
        warnings.append(
            "overlay could not find the part. Pass roi or seed, and exclude the coin. IoU was not computed."
        )
    if angled:
        warnings.append(
            "The photo was flagged as angled. overlay_iou_label is guide_only: "
            "the fit was still computed, but perspective can move the outline. "
            "Rectify with photo_part_measure before treating the IoU as a measurement."
        )
    return warnings


def grabcut_mask(image: np.ndarray, roi=None, seed=None, iterations: int = 3) -> np.ndarray | None:
    """OpenCV GrabCut seeded by a rectangle or a point. None if OpenCV is absent."""
    try:
        import cv2
    except ImportError:
        return None
    height, width = image.shape[:2]
    if roi is not None:
        x, y, w, h = (int(roi[0]), int(roi[1]), int(roi[2]), int(roi[3]))
    elif seed is not None:
        # A tight window can sit entirely inside a flat silhouette, and GrabCut
        # then has no background sample. Use a wide window around the seed.
        span = max(48, int(min(width, height) * 0.7))
        x = int(seed[0]) - span // 2
        y = int(seed[1]) - span // 2
        w, h = span, span
    else:
        return None
    x = max(0, min(width - 2, x))
    y = max(0, min(height - 2, y))
    w = max(2, min(width - x, w))
    h = max(2, min(height - y, h))
    mask = np.full((height, width), cv2.GC_BGD, dtype=np.uint8)
    mask[y : y + h, x : x + w] = cv2.GC_PR_FGD
    mode = cv2.GC_INIT_WITH_RECT
    if seed is not None:
        sx = max(0, min(width - 1, int(seed[0])))
        sy = max(0, min(height - 1, int(seed[1])))
        mask[max(0, sy - 2) : sy + 3, max(0, sx - 2) : sx + 3] = cv2.GC_FGD
        mode = cv2.GC_INIT_WITH_MASK
    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(image, mask, (x, y, w, h), bgd, fgd, max(1, int(iterations)), mode)
    except cv2.error:
        return None
    foreground = (mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD)
    if int(foreground.sum()) < 16:
        return None
    return foreground


def _foreground_for_overlay(image, *, roi, seed, exclude, hints: bool):
    """Segment the part. A roi or seed tries GrabCut before the colour mask."""
    if hints and (roi is not None or seed is not None):
        cut = grabcut_mask(image, roi=roi, seed=seed)
        if cut is not None:
            for rect in exclude or []:
                _zero_rect(cut, rect)
            if seed is not None:
                component = _component_at(cut, seed)
            elif roi is not None:
                gated = np.zeros_like(cut)
                _copy_rect(cut, gated, roi)
                component = _largest_component(gated)
            else:
                component = cut
            if component is not None and int(component.sum()) >= 16:
                box = _bbox(component)
                blob = None
                if box is not None:
                    x0, y0, x1, y1 = box
                    blob = {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0, "source": "grabcut"}
                return component, blob, [], False
    if not hints:
        mask, blob = _foreground_for_score(image, roi=None, seed=None, exclude=None, hints=False)
        return mask, blob, [], False
    if roi is None:
        mask, blob = select_foreground(image, roi=None, seed=seed, exclude=exclude)
        return mask, blob, [], False
    current = (float(roi[0]), float(roi[1]), float(roi[2]), float(roi[3]))
    mask, blob = select_foreground(image, roi=current, seed=seed, exclude=exclude)
    warnings = []
    grew = False
    for _ in range(4):
        if mask is None or not _mask_meets_roi_edge(mask, current):
            break
        grown = _grow_roi(current, image.shape)
        if _roi_same(grown, current):
            warnings.append(
                "ROI crops the silhouette and meets the image edge, so it cannot expand further. "
                "The IoU may score only the visible band."
            )
            break
        current = grown
        grew = True
        mask, blob = select_foreground(image, roi=current, seed=seed, exclude=exclude)
    if grew:
        x, y, w, h = current
        warnings.append(
            "ROI cropped the silhouette (the mask meets the ROI edge). "
            f"Expanded the ROI to x={x:.0f}, y={y:.0f}, w={w:.0f}, h={h:.0f}."
        )
    if (
        mask is not None
        and _mask_meets_roi_edge(mask, current)
        and not any("image edge" in item for item in warnings)
    ):
        warnings.append(
            "ROI still crops the silhouette after expanding. The IoU may score only part of the part."
        )
    return mask, blob, warnings, grew


def _mask_meets_roi_edge(mask: np.ndarray, rect) -> bool:
    y0, y1, x0, x1 = _rect_bounds(mask.shape, rect)
    if y1 - y0 < 2 or x1 - x0 < 2:
        return False
    return bool(
        mask[y0, x0:x1].any()
        or mask[y1 - 1, x0:x1].any()
        or mask[y0:y1, x0].any()
        or mask[y0:y1, x1 - 1].any()
    )


def _grow_roi(rect, shape, fraction: float = 0.5):
    height, width = shape[:2]
    x, y, w, h = (float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3]))
    x0 = max(0.0, x - w * fraction)
    y0 = max(0.0, y - h * fraction)
    x1 = min(float(width), x + w + w * fraction)
    y1 = min(float(height), y + h + h * fraction)
    return (x0, y0, max(1.0, x1 - x0), max(1.0, y1 - y0))


def _roi_same(left, right) -> bool:
    return all(abs(float(left[index]) - float(right[index])) < 0.5 for index in range(4))


def _zero_rect(mask: np.ndarray, rect) -> None:
    y0, y1, x0, x1 = _rect_bounds(mask.shape, rect)
    if y1 > y0 and x1 > x0:
        mask[y0:y1, x0:x1] = False


def _copy_rect(source: np.ndarray, dest: np.ndarray, rect) -> None:
    y0, y1, x0, x1 = _rect_bounds(source.shape, rect)
    if y1 > y0 and x1 > x0:
        dest[y0:y1, x0:x1] = source[y0:y1, x0:x1]


def _rect_bounds(shape, rect) -> tuple[int, int, int, int]:
    height, width = shape[:2]
    x, y, w, h = (float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3]))
    x0 = max(0, int(math.floor(x)))
    y0 = max(0, int(math.floor(y)))
    x1 = min(width, int(math.ceil(x + w)))
    y1 = min(height, int(math.ceil(y + h)))
    return y0, y1, x0, x1


def _component_at(mask: np.ndarray, seed, radius: int = 24) -> np.ndarray:
    height, width = mask.shape
    sx = int(round(float(seed[0])))
    sy = int(round(float(seed[1])))
    if sx < 0 or sy < 0 or sx >= width or sy >= height:
        raise ValueError("seed is outside the photo")
    if not mask[sy, sx]:
        found = None
        for ring in range(1, radius + 1):
            for dy in range(-ring, ring + 1):
                for dx in range(-ring, ring + 1):
                    if max(abs(dx), abs(dy)) != ring:
                        continue
                    ny = sy + dy
                    nx = sx + dx
                    if 0 <= nx < width and 0 <= ny < height and mask[ny, nx]:
                        found = (ny, nx)
                        break
                if found is not None:
                    break
            if found is not None:
                break
        if found is None:
            return np.zeros_like(mask)
        sy, sx = found
    return _flood(mask, sy, sx)


def _flood(mask: np.ndarray, y: int, x: int) -> np.ndarray:
    height, width = mask.shape
    out = np.zeros((height, width), dtype=bool)
    seen = np.zeros((height, width), dtype=bool)
    seen[y, x] = True
    stack = [(y, x)]
    while stack:
        cy, cx = stack.pop()
        out[cy, cx] = True
        for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
            if ny < 0 or nx < 0 or ny >= height or nx >= width or seen[ny, nx] or not mask[ny, nx]:
                continue
            seen[ny, nx] = True
            stack.append((ny, nx))
    return out


def _largest_component(mask: np.ndarray) -> np.ndarray:
    height, width = mask.shape
    scale = max(height, width) / 360.0
    if scale <= 1.0:
        small = mask
        scale = 1.0
    else:
        small_w = max(1, int(round(width / scale)))
        small_h = max(1, int(round(height / scale)))
        small = np.asarray(
            Image.fromarray(mask.astype(np.uint8) * 255).resize((small_w, small_h), Image.Resampling.NEAREST)
        ) > 127
    labeled = _walk_largest(small)
    if scale == 1.0:
        return labeled
    ys, xs = np.nonzero(labeled)
    if ys.size == 0:
        return np.zeros_like(mask)
    y0 = max(0, int(ys.min() * scale) - 2)
    y1 = min(height, int((ys.max() + 1) * scale) + 2)
    x0 = max(0, int(xs.min() * scale) - 2)
    x1 = min(width, int((xs.max() + 1) * scale) + 2)
    out = np.zeros_like(mask)
    out[y0:y1, x0:x1] = mask[y0:y1, x0:x1]
    return out


def _walk_largest(mask: np.ndarray) -> np.ndarray:
    height, width = mask.shape
    seen = np.zeros((height, width), dtype=bool)
    best: list[tuple[int, int]] = []
    ys, xs = np.nonzero(mask)
    for y, x in zip(ys.tolist(), xs.tolist()):
        if seen[y, x]:
            continue
        stack = [(y, x)]
        seen[y, x] = True
        comp: list[tuple[int, int]] = []
        while stack:
            cy, cx = stack.pop()
            comp.append((cy, cx))
            for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                if ny < 0 or nx < 0 or ny >= height or nx >= width or seen[ny, nx] or not mask[ny, nx]:
                    continue
                seen[ny, nx] = True
                stack.append((ny, nx))
        if len(comp) > len(best):
            best = comp
    out = np.zeros((height, width), dtype=bool)
    for y, x in best:
        out[y, x] = True
    return out


def _raster_mask(pixels: np.ndarray, faces: np.ndarray, width: int, height: int) -> np.ndarray:
    """Union of projected triangles. This is the silhouette, including holes in it."""
    mask = np.zeros((height, width), dtype=bool)
    for face in faces:
        tri = pixels[face]
        minx = max(int(math.floor(float(np.min(tri[:, 0])))), 0)
        maxx = min(int(math.ceil(float(np.max(tri[:, 0])))), width - 1)
        miny = max(int(math.floor(float(np.min(tri[:, 1])))), 0)
        maxy = min(int(math.ceil(float(np.max(tri[:, 1])))), height - 1)
        if minx > maxx or miny > maxy:
            continue
        xs = np.arange(minx, maxx + 1)
        ys = np.arange(miny, maxy + 1)
        xx, yy = np.meshgrid(xs, ys)
        x0, y0 = float(tri[0, 0]), float(tri[0, 1])
        x1, y1 = float(tri[1, 0]), float(tri[1, 1])
        x2, y2 = float(tri[2, 0]), float(tri[2, 1])
        denom = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(denom) < 1e-12:
            continue
        w0 = ((y1 - y2) * (xx - x2) + (x2 - x1) * (yy - y2)) / denom
        w1 = ((y2 - y0) * (xx - x2) + (x0 - x2) * (yy - y2)) / denom
        w2 = 1.0 - w0 - w1
        inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        mask[miny : maxy + 1, minx : maxx + 1] |= inside
    return mask


def _blit_center(model, shape, minimum, maximum, photo_scale, points) -> np.ndarray:
    height, width = shape
    center = (points.min(axis=0) + points.max(axis=0)) / 2.0
    local_cx = (center[0] - minimum[0]) * photo_scale
    local_cy = (maximum[1] - center[1]) * photo_scale
    return _blit(model, shape, width / 2.0 - local_cx, height / 2.0 - local_cy)


def _blit_origin(model, shape, minimum, maximum, photo_scale, origin) -> np.ndarray:
    tight_h = (maximum[1] - minimum[1]) * photo_scale
    return _blit(model, shape, origin[0], origin[1] - tight_h)


def _blit(model: np.ndarray, shape: tuple[int, int], x0: float, y0: float) -> np.ndarray:
    out = np.zeros(shape, dtype=bool)
    src_h, src_w = model.shape
    height, width = shape
    ox = int(round(x0))
    oy = int(round(y0))
    dx0 = max(0, -ox)
    dy0 = max(0, -oy)
    dx1 = min(src_w, width - ox)
    dy1 = min(src_h, height - oy)
    if dx1 <= dx0 or dy1 <= dy0:
        return out
    out[oy + dy0 : oy + dy1, ox + dx0 : ox + dx1] = model[dy0:dy1, dx0:dx1]
    return out


def _align(model: np.ndarray, foreground: np.ndarray) -> tuple[np.ndarray, str | None]:
    model_box = _bbox(model)
    photo_box = _bbox(foreground)
    if model_box is None or photo_box is None:
        return np.zeros_like(foreground), "segmentation produced an empty mask"
    mx0, my0, mx1, my1 = model_box
    px0, py0, px1, py1 = photo_box
    mw = max(1, mx1 - mx0)
    mh = max(1, my1 - my0)
    fw = max(1, px1 - px0)
    fh = max(1, py1 - py0)
    scale = math.sqrt((fw * fh) / (mw * mh))
    rotate = _elongated(mw, mh) and _elongated(fw, fh) and ((mh > mw) != (fh > fw))
    mcx = (mx0 + mx1 - 1) / 2.0
    mcy = (my0 + my1 - 1) / 2.0
    pcx = (px0 + px1 - 1) / 2.0
    pcy = (py0 + py1 - 1) / 2.0
    ys, xs = np.nonzero(model)
    dx = (xs - mcx) * scale
    dy = (ys - mcy) * scale
    if rotate:
        dx, dy = -dy, dx
    placed_x = np.rint(pcx + dx).astype(np.int32)
    placed_y = np.rint(pcy + dy).astype(np.int32)
    placed = np.zeros_like(foreground)
    keep = (
        (placed_x >= 0)
        & (placed_y >= 0)
        & (placed_x < placed.shape[1])
        & (placed_y < placed.shape[0])
    )
    placed[placed_y[keep], placed_x[keep]] = True
    placed = _close(placed)
    note = None
    if rotate:
        note = "Rotated the outline 90 degrees so its long axis matches the part in the photo."
    return placed, note


def _elongated(width: int, height: int) -> bool:
    short = min(width, height)
    return short > 0 and max(width, height) / short >= 1.4


def _bbox(mask: np.ndarray):
    ys, xs = np.nonzero(mask)
    if ys.size == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _close(mask: np.ndarray) -> np.ndarray:
    return _erode(_dilate(mask, 1), 1)


def _dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    height, width = mask.shape
    ys, xs = np.nonzero(mask)
    out = np.zeros_like(mask)
    if ys.size == 0:
        return out
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx * dx + dy * dy > radius * radius + 0.1:
                continue
            yy = ys + dy
            xx = xs + dx
            keep = (yy >= 0) & (yy < height) & (xx >= 0) & (xx < width)
            out[yy[keep], xx[keep]] = True
    return out


def _erode(mask: np.ndarray, radius: int) -> np.ndarray:
    """Keep pixels whose full neighborhood is set. Walks the mask, not its inverse."""
    out = mask.copy()
    ys, xs = np.nonzero(mask)
    if ys.size == 0:
        return out
    height, width = mask.shape
    drop = np.zeros(ys.shape[0], dtype=bool)
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx * dx + dy * dy > radius * radius + 0.1:
                continue
            yy = ys + dy
            xx = xs + dx
            outside = (yy < 0) | (yy >= height) | (xx < 0) | (xx >= width)
            inside = ~outside
            missing = outside.copy()
            if np.any(inside):
                missing[inside] = ~mask[yy[inside], xx[inside]]
            drop |= missing
    out[ys[drop], xs[drop]] = False
    return out


def _iou(model: np.ndarray, foreground: np.ndarray) -> float:
    union = np.logical_or(model, foreground).sum()
    if union == 0:
        return 0.0
    return float(np.logical_and(model, foreground).sum()) / float(union)


def contour_ring(mask: np.ndarray) -> np.ndarray:
    """Pixels on the silhouette boundary, including holes in the mask."""
    if not np.any(mask):
        return np.zeros_like(mask)
    outer = _dilate(mask, 2) & ~mask
    inner = mask & ~_erode(mask, 1)
    return outer | inner


def _draw_contour(image: np.ndarray, mask: np.ndarray) -> np.ndarray:
    painted = image.copy()
    ring = contour_ring(mask)
    if not np.any(ring):
        return painted
    base = painted[ring].astype(np.float64)
    painted[ring] = np.clip(base * (1.0 - _ALPHA) + _MAGENTA * _ALPHA, 0, 255).astype(np.uint8)
    return painted


def _diff_image(image: np.ndarray, model: np.ndarray, foreground: np.ndarray | None) -> np.ndarray:
    """Model-only magenta, photo-only yellow, overlap green, on a dimmed photo."""
    canvas = (image.astype(np.float64) * 0.45 + 255.0 * 0.55).astype(np.uint8)
    photo = np.zeros_like(model) if foreground is None else foreground
    both = model & photo
    only_model = model & ~photo
    only_photo = photo & ~model
    canvas[only_model] = (230, 30, 190)
    canvas[only_photo] = (230, 200, 40)
    canvas[both] = (30, 170, 70)
    return canvas
