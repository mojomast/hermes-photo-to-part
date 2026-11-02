"""Silhouette outline for a reference photo.

The line is the outer contour of the z-buffer mask, not the mesh's facet edges.
``center`` places that mask on the image center. ``auto`` scales, rotates,
and optionally mirrors it onto the part, then picks the render view whose
silhouette overlaps the photo best.
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
    hints = bool(roi or seed or exclude)
    if origin is not None:
        placed = _blit_origin(model, (height, width), minimum, maximum, photo_scale, origin)
        used = "origin"
        foreground, blob = _foreground_for_score(image, roi=roi, seed=seed, exclude=exclude, hints=hints)
    elif fit == "auto":
        foreground, blob = _foreground_for_score(image, roi=roi, seed=seed, exclude=exclude, hints=True)
        if foreground is None:
            placed = _blit_center(model, (height, width), minimum, maximum, photo_scale, points)
            used = "center"
            note = (
                "Could not segment a part from the photo, so the outline stayed centered. "
                "Pass roi or seed on the part, and exclude the coin."
            )
        else:
            pose = search_alignment(model, foreground)
            placed = pose["placed"]
            note = pose["note"]
            rotation = pose["rotation_deg"]
            mirror = pose["mirror"]
            used = "auto"
    else:
        placed = _blit_center(model, (height, width), minimum, maximum, photo_scale, points)
        foreground, blob = _foreground_for_score(image, roi=roi, seed=seed, exclude=exclude, hints=hints)
    iou = None if foreground is None else _iou(placed, foreground)
    warnings = _overlay_warnings(iou, blob, angled=angled, missed=foreground is None and (fit == "auto" or hints))
    if warnings and note:
        note = note + " " + " ".join(warnings)
    elif warnings:
        note = " ".join(warnings)
    painted = _draw_contour(image, placed)
    destination.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(painted, mode="RGB").save(destination, format="PNG")
    diff = _diff_image(image, placed, foreground)
    Image.fromarray(diff, mode="RGB").save(diff_destination, format="PNG")
    return {
        "overlay_fit": used,
        "overlay_iou": None if iou is None else round(float(iou), 4),
        "overlay_diff": str(Path(diff_destination).resolve()),
        "overlay_fit_note": note,
        "overlay_blob": blob,
        "overlay_warnings": warnings,
        "overlay_rotation_deg": rotation,
        "overlay_mirror": bool(mirror),
        "overlay_view": view,
    }


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

    ``views`` is ``(name, points, faces)`` in preference order. Within 0.01
    IoU the earlier view wins, so a rectangle does not flip to top.
    """
    if not views:
        raise ValueError("overlay auto needs at least one view")
    image = np.array(Image.open(photo).convert("RGB"))
    foreground, blob = _foreground_for_score(image, roi=roi, seed=seed, exclude=exclude, hints=True)
    chosen = None
    if foreground is not None:
        for index, (name, points, faces) in enumerate(views):
            model, _minimum, _maximum = raster_model(points, faces, photo_scale)
            pose = search_alignment(model, foreground)
            if chosen is None or _prefer_pose(pose["iou"], index, chosen["iou"], chosen["index"]):
                chosen = {"pose": pose, "name": name, "index": index, "iou": pose["iou"]}
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
        rotation = chosen["pose"]["rotation_deg"]
        mirror = chosen["pose"]["mirror"]
        view_name = chosen["name"]
        iou = chosen["iou"]
        note = f"{note} View {view_name}."
    warnings = _overlay_warnings(iou, blob, angled=angled, missed=foreground is None)
    if warnings and note:
        note = note + " " + " ".join(warnings)
    elif warnings:
        note = " ".join(warnings)
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
    )


def search_alignment(model: np.ndarray, foreground: np.ndarray) -> dict:
    """Coarse 15° search, then ±12° at 3°, including a mirror.

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
        for delta in range(-12, 13, 3):
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


def _place(model: np.ndarray, foreground: np.ndarray, angle_deg: float, mirror: bool, *, close: bool) -> np.ndarray:
    model_box = _bbox(model)
    photo_box = _bbox(foreground)
    if model_box is None or photo_box is None:
        return np.zeros_like(foreground)
    mx0, my0, mx1, my1 = model_box
    px0, py0, px1, py1 = photo_box
    model_pixels = int(np.count_nonzero(model))
    photo_pixels = int(np.count_nonzero(foreground))
    if model_pixels > 0 and photo_pixels > 0:
        # Pixel area stays stable when the part is rotated. The axis-aligned
        # box of a rotated silhouette is larger than the part.
        scale = math.sqrt(photo_pixels / model_pixels)
    else:
        mw = max(1, mx1 - mx0)
        mh = max(1, my1 - my0)
        fw = max(1, px1 - px0)
        fh = max(1, py1 - py0)
        scale = math.sqrt((fw * fh) / (mw * mh))
    mcx = (mx0 + mx1 - 1) / 2.0
    mcy = (my0 + my1 - 1) / 2.0
    pcx = (px0 + px1 - 1) / 2.0
    pcy = (py0 + py1 - 1) / 2.0
    ys, xs = np.nonzero(model)
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
) -> dict:
    painted = _draw_contour(image, placed)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(painted, mode="RGB").save(destination, format="PNG")
    diff = _diff_image(image, placed, foreground)
    Image.fromarray(diff, mode="RGB").save(diff_destination, format="PNG")
    return {
        "overlay_fit": fit,
        "overlay_iou": None if iou is None else round(float(iou), 4),
        "overlay_diff": str(Path(diff_destination).resolve()),
        "overlay_fit_note": note,
        "overlay_blob": blob,
        "overlay_warnings": warnings,
        "overlay_rotation_deg": float(rotation),
        "overlay_mirror": bool(mirror),
        "overlay_view": view,
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


def color_mask(image: np.ndarray) -> np.ndarray | None:
    """Pixels that differ from the border color, before a blob is chosen."""
    if image.ndim != 3 or image.shape[0] < 4 or image.shape[1] < 4:
        return None
    border = np.concatenate([image[0], image[-1], image[:, 0], image[:, -1]], axis=0).astype(np.float64)
    background = np.median(border, axis=0)
    distance = np.linalg.norm(image.astype(np.float64) - background, axis=2)
    spread = float(np.median(np.abs(border - background)))
    mask = distance > max(18.0, spread * 4.0 + 12.0)
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


def _overlay_warnings(iou, blob, *, angled: bool, missed: bool) -> list[str]:
    warnings = []
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
            "The photo was flagged as angled. A flat overlay misses a tilted part. "
            "Rectify with photo_part_measure or skip the overlay."
        )
    return warnings


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
