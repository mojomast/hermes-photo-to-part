"""Compare a mesh to the dimensions the user asked for.

``spec.json`` holds bbox sizes, shell count, knuckle count, and hole count.
``--dim name=value±tol`` is the same check on one line. Lengths default to
the validate tolerance (0.3 mm). Counts default to an exact match.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import numpy as np

GENUS_NOTE = "genus counts handles, not bores. hole_count is the circular bore count."

_DIM = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([+-]?\d+(?:\.\d+)?)"
    r"(?:\s*(?:±|\+/-|\+-)\s*(\d+(?:\.\d+)?))?\s*$"
)
_AXES = {"x": 0, "y": 1, "z": 2}
_COUNTS = {"shells", "knuckles", "hole_count"}
_NAMES = set(_AXES) | _COUNTS


def parse_dim(text: str) -> tuple[str, float, float | None]:
    """``x=100±0.5``, ``y=50+/-0.4``, or ``shells=2``."""
    match = _DIM.match(str(text))
    if not match:
        raise ValueError(f"dim must look like x=100±0.5 or shells=2, got {text!r}")
    name = match.group(1).lower()
    if name not in _NAMES:
        known = ", ".join(sorted(_NAMES))
        raise ValueError(f"unknown dim {name!r}. Use one of: {known}")
    tol = None if match.group(3) is None else float(match.group(3))
    return name, float(match.group(2)), tol


def load_spec(source) -> dict:
    """A path, a JSON string, or a dict. Returns the object."""
    if source is None or source == "":
        return {}
    if isinstance(source, dict):
        return source
    text = str(source).strip()
    path = Path(text).expanduser()
    if path.is_file():
        text = path.read_text(encoding="utf-8")
    loaded = json.loads(text)
    if not isinstance(loaded, dict):
        raise ValueError("spec must be a JSON object")
    return loaded


def apply_spec(mesh, *, spec=None, dims=None, tolerance: float = 0.3) -> tuple[list[str], list[dict]]:
    """Return failure strings and one row per check. Rows go in the report as ``spec``."""
    checks = _collect(spec, dims, tolerance)
    if not checks and not _holes_of(spec):
        return [], []
    failures: list[str] = []
    rows: list[dict] = []
    extents = np.asarray(mesh.extents, dtype=float)
    for name, value, tol in checks:
        extra: dict = {}
        undetected = False
        explained = False
        if name in _AXES:
            actual = float(extents[_AXES[name]])
            source = _source_of(checks.raw, name)
            extra["source"] = source
            note = _assumed_dim_note(checks.raw, name, value, tol, actual)
            if note:
                extra["warning"] = note
                explained = True
        elif name == "shells":
            actual = float(len(mesh.split(only_watertight=False)))
        elif name == "knuckles":
            detected = detect_knuckles(mesh, axis_hint=str(checks.axis or "x"))
            rings = count_knuckles(mesh, axis=str(checks.axis or "x"))
            cylinders = int(detected.get("cylinders") or 0)
            actual = float(detected.get("knuckles") or 0)
            extra = {
                "rings": rings,
                "cylinders": cylinders,
                "segments": detected.get("segments") or [],
                "radius": detected.get("radius"),
                "axis": detected.get("axis"),
            }
            if cylinders == 0:
                explained = True
                extra["warning"] = (
                    f"knuckles={rings} by rings, 0 cylinders. "
                    "knuckle probe is unreliable here; the check is reported as a warning"
                )
                extra["status"] = "warning"
            elif rings != int(actual):
                extra["warning"] = (
                    f"knuckle ring count {rings} disagrees with {int(actual)} cylinders. "
                    "The ring count is a warning, not a failure."
                )
        elif name == "hole_count":
            found = openings(mesh)
            bores = found["bores"]
            recesses = found["recesses"]
            info = genus_report(mesh)
            actual = float(len(bores))
            genus = info.get("genus")
            extra = {
                "bores": bores,
                "genus": genus,
                "genus_reliable": bool(info.get("reliable")),
                "note": GENUS_NOTE,
            }
            if recesses:
                extra["recesses"] = recesses
                extra["recess_note"] = (
                    f"{len(recesses)} shallow dish(es) or recess(es) are not bores. "
                    "Do not add them to hole_count."
                )
            if info.get("reason") and not info.get("reliable"):
                extra["genus_reason"] = info["reason"]
            # Zero bores plus a positive genus, or a genus we cannot trust,
            # means the counter missed holes. Say so instead of failing.
            undetected = len(bores) == 0 and ((genus or 0) > 0 or not info.get("reliable"))
            if undetected:
                extra["status"] = "undetected"
                extra["note"] = "undetected. " + GENUS_NOTE
        else:
            raise ValueError(f"unknown spec field {name}")
        if undetected or explained:
            ok = True
        else:
            ok = abs(actual - value) <= tol + 1e-9
        rows.append(
            {
                "name": name,
                "value": value,
                "tol": tol,
                "actual": actual,
                "ok": ok,
                **extra,
            }
        )
        if not ok:
            shown = int(actual) if name in _COUNTS else round(actual, 3)
            failures.append(f"spec {name}: actual {shown} is outside {value:g}±{tol:g}")
    hole_specs = _holes_of(spec)
    if hole_specs:
        from photopart.holes import check_holes

        hole_failures, hole_rows = check_holes(mesh, hole_specs, tolerance=tolerance)
        for failure in hole_failures:
            failures.append(f"spec {failure}")
        for row in hole_rows:
            rows.append(
                {
                    "name": "hole",
                    "ok": row["ok"],
                    "warning": row.get("warning"),
                    "actual": row,
                }
            )
    return failures, rows


def count_knuckles(mesh, axis: str = "x") -> int:
    """Count knuckles along ``axis`` between the pin and the knuckle wall.

    A ring at the bbox centre sits inside a continuous pin and reports one
    solid run. Several radii are sampled, from just off the axis out to just
    under half the short cross-section (inside the knuckle, short of the
    leaves). A radius that is solid for the whole span is the pin core and is
    skipped. The count is the largest remaining run. Call this only when the
    spec asks for knuckles.
    """
    name = (axis or "x").lower()
    if name not in _AXES:
        raise ValueError("knuckle_axis must be x, y, or z")
    return len(_ring_spans(mesh, _AXES[name]))


def _ring_spans(mesh, axis: int) -> list[tuple[float, float]]:
    """Occupied runs between the pin and the knuckle wall, in axis coordinates.

    The chosen radius is the one with the most runs of at least three samples.
    A radius that is solid across the span is the pin and is skipped.
    """
    from photopart.holes import _inside

    bounds = np.asarray(mesh.bounds, dtype=float)
    span = float(bounds[1, axis] - bounds[0, axis])
    if span <= 0:
        return []
    others = [slot for slot in range(3) if slot != axis]
    cross = min(float(bounds[1, slot] - bounds[0, slot]) for slot in others)
    if cross <= 0:
        return []
    outer = 0.48 * cross
    if outer <= 0.55:
        radii = np.array([max(0.2, outer * 0.6)], dtype=float)
    else:
        radii = np.linspace(0.5, outer, 6)
    center = bounds.mean(axis=0)
    stations = int(np.clip(round(span / 0.15), 80, 360))
    angles = 8
    pad = min(0.15, 0.005 * span)
    coords = np.linspace(bounds[0, axis] + pad, bounds[1, axis] - pad, stations)
    turns = np.arange(angles, dtype=float) * (2.0 * np.pi / angles)
    n_radii = len(radii)
    points = np.empty((n_radii, stations, angles, 3), dtype=float)
    points[...] = center
    points[..., axis] = coords[None, :, None]
    points[..., others[0]] = center[others[0]] + radii[:, None, None] * np.cos(turns)[None, None, :]
    points[..., others[1]] = center[others[1]] + radii[:, None, None] * np.sin(turns)[None, None, :]
    inside = _inside(mesh, points.reshape(-1, 3)).reshape(n_radii, stations, angles)
    occupied = inside.any(axis=2)
    best: list[tuple[float, float]] = []
    for row in occupied:
        spans, fraction = _occupied_runs(row, coords)
        if len(spans) == 1 and fraction >= 0.97:
            continue
        if len(spans) > len(best):
            best = spans
    return best


def _occupied_runs(flags, coords=None) -> tuple[list[tuple[float, float]], float]:
    """Runs of at least three inside samples, as ``(start, end)`` along ``coords``."""
    row = np.asarray(flags, dtype=bool)
    if len(row) == 0:
        return [], 0.0
    padded = np.concatenate(([False], row, [False]))
    changes = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(changes == 1)
    ends = np.flatnonzero(changes == -1)
    axis_coords = np.arange(len(row), dtype=float) if coords is None else np.asarray(coords, dtype=float)
    spans: list[tuple[float, float]] = []
    for start, end in zip(starts, ends):
        if int(end - start) < 3:
            continue
        spans.append((float(axis_coords[start]), float(axis_coords[end - 1])))
    fraction = float(np.count_nonzero(row)) / float(len(row))
    return spans, fraction


def _unmerge_knuckles(mesh, found: dict) -> dict:
    """Split cylinders that the pin or a fillet has joined back into rings.

    Face intervals merge neighbouring knuckles when the pin or a teardrop
    bridge connects them. The ring probe still sees each barrel. When at
    least one cylinder exists and more rings overlap those cylinders than the
    merged count, the rings are the knuckle count. Zero cylinders stays zero,
    so a strap or a cap is not reported as a hinge.
    """
    cylinders = int(found.get("cylinders") or 0)
    if cylinders < 1:
        return found
    axis_name = str(found.get("axis") or "x")
    if axis_name not in _AXES:
        return found
    try:
        rings = _ring_spans(mesh, _AXES[axis_name])
    except Exception:
        return found
    if len(rings) < 2 or len(rings) <= cylinders:
        return found
    overlapping: list[tuple[float, float]] = []
    for start, end in rings:
        for segment in found.get("segments") or []:
            if not isinstance(segment, (list, tuple)) or len(segment) < 2:
                continue
            if float(end) >= float(segment[0]) - 1.0 and float(start) <= float(segment[1]) + 1.0:
                overlapping.append((float(start), float(end)))
                break
    if len(overlapping) < 2 or len(overlapping) <= cylinders:
        return found
    updated = dict(found)
    updated["knuckles"] = len(overlapping)
    updated["cylinders"] = len(overlapping)
    updated["segments"] = [[round(start, 4), round(end, 4)] for start, end in overlapping]
    return updated


def detect_knuckles(mesh, axis_hint=None) -> dict:
    """Coaxial cylinders with gaps. A flat link is not a knuckle.

    A knuckle is a connected run of faces on one circle: arc at least 240°,
    radius at least max(1 mm, 0.6 × leaf thickness), length at least 1.5 × r,
    and RMS radial residual under 3% of r. The count is that run only when at
    least two segments share an axis and a gap. One rod is reported as one
    segment and does not satisfy the gap rule, so ``knuckles`` stays 0 or 1.
    When those cylinders have been merged by a pin or a fillet, the individual
    ring spans along the same axis replace the merged count.
    ``count_knuckles`` remains the ring cross-check.
    """
    names = ("x", "y", "z")
    hint = str(axis_hint or "x").lower()
    empty = {"knuckles": 0, "axis": hint if hint in _AXES else "x", "radius": None, "segments": [], "cylinders": 0}
    if mesh is None or len(getattr(mesh, "faces", [])) < 12:
        return empty
    order = []
    if hint in _AXES:
        order.append(_AXES[hint])
    for slot in range(3):
        if slot not in order:
            order.append(slot)
    best = empty
    for axis in order:
        found = _knuckles_along(mesh, axis)
        if found["cylinders"] > best["cylinders"] or (
            found["cylinders"] == best["cylinders"] and found["knuckles"] > best["knuckles"]
        ):
            best = found
    return _unmerge_knuckles(mesh, best)


def _knuckles_along(mesh, axis: int) -> dict:
    """Cylinder axis from radial normals, then a circle fit on each radius band."""
    names = ("x", "y", "z")
    empty = {"knuckles": 0, "axis": names[axis], "radius": None, "segments": [], "cylinders": 0}
    normals = np.asarray(mesh.face_normals, dtype=float)
    if len(normals) == 0:
        return empty
    axis_vec = np.zeros(3, dtype=float)
    axis_vec[axis] = 1.0
    radial = np.abs(normals @ axis_vec) < 0.15
    if int(np.count_nonzero(radial)) < 12:
        return empty
    centers = np.asarray(mesh.triangles_center, dtype=float)
    vertices = np.asarray(mesh.vertices, dtype=float)
    faces = np.asarray(mesh.faces)
    indexes = np.flatnonzero(radial)
    points = centers[indexes]
    norms = normals[indexes]
    perp = [slot for slot in range(3) if slot != axis]
    xy = points[:, perp]
    normal_xy = norms[:, perp]
    center = _radial_center(xy, normal_xy)
    if center is None:
        return empty
    offset = xy - center
    dist = np.linalg.norm(offset, axis=1)
    usable = dist > 1e-6
    radial_dir = np.zeros_like(offset)
    radial_dir[usable] = offset[usable] / dist[usable, None]
    aligned = usable & (np.abs(np.einsum("ij,ij->i", normal_xy, radial_dir)) > 0.7)
    if int(np.count_nonzero(aligned)) < 12:
        return empty
    leaf = _plate_thickness(mesh)
    floor = 1.0 if leaf is None else max(1.0, 0.6 * float(leaf))
    segments = []
    for lo, hi in _radius_bands(dist[aligned]):
        members = aligned & (dist >= lo) & (dist <= hi)
        if int(np.count_nonzero(members)) < 12:
            continue
        fit = _kasa_circle(xy[members])
        if fit is None:
            continue
        fitted, radius = fit
        if radius < floor or radius > 80.0:
            continue
        residual = np.linalg.norm(xy[members] - fitted, axis=1) - radius
        rms = float(np.sqrt(np.mean(residual ** 2)))
        if rms > 0.03 * radius:
            continue
        segments.extend(
            _face_intervals(
                points[members],
                vertices,
                faces[indexes[members]],
                axis_vec,
                fitted,
                radius,
                perp,
            )
        )
    segments = _merge_coaxial_spans(segments)
    segments.sort(key=lambda item: item["span"][0])
    gapped = _gapped_segments(segments)
    chosen = gapped if len(gapped) >= 2 else segments[:1]
    knuckles = len(gapped) if len(gapped) >= 2 else (1 if len(segments) == 1 else 0)
    radius = None
    if chosen:
        radius = round(float(np.median([item["radius"] for item in chosen])), 4)
    return {
        "knuckles": int(knuckles),
        "axis": names[axis],
        "radius": radius,
        "segments": [[round(float(item["span"][0]), 4), round(float(item["span"][1]), 4)] for item in chosen],
        "cylinders": int(len(segments)),
    }


def _radial_center(xy: np.ndarray, normal_xy: np.ndarray):
    """Least-squares point where the radial normal lines meet."""
    length = np.linalg.norm(normal_xy, axis=1)
    usable = length > 0.5
    if int(np.count_nonzero(usable)) < 8:
        return None
    normals = normal_xy[usable] / length[usable, None]
    points = xy[usable]
    matrix = np.column_stack((normals[:, 1], -normals[:, 0]))
    rhs = points[:, 0] * normals[:, 1] - points[:, 1] * normals[:, 0]
    try:
        center, *_rest = np.linalg.lstsq(matrix, rhs, rcond=None)
    except np.linalg.LinAlgError:
        return None
    if not np.all(np.isfinite(center)):
        return None
    return np.asarray(center, dtype=float)


def _radius_bands(radii: np.ndarray) -> list[tuple[float, float]]:
    """One band per histogram peak. A valley keeps the pin off the bore."""
    values = np.asarray(radii, dtype=float)
    values = values[np.isfinite(values) & (values > 0.4) & (values < 80.0)]
    if len(values) < 12:
        return []
    width = 0.2
    low = float(np.floor(values.min() / width) * width)
    high = float(np.ceil(values.max() / width) * width + width)
    edges = np.arange(low, high + width, width)
    if len(edges) < 2:
        return []
    counts, edges = np.histogram(values, bins=edges)
    peaks = []
    index = 0
    while index < len(counts):
        if counts[index] < 8:
            index += 1
            continue
        end = index
        while end + 1 < len(counts) and counts[end + 1] >= 8:
            end += 1
        # Split a run where the count falls and then rises (pin, then bore).
        cursor = index
        while cursor <= end:
            peak = cursor
            while peak + 1 <= end and counts[peak + 1] >= counts[peak]:
                peak += 1
            valley = peak
            while valley + 1 <= end and counts[valley + 1] <= counts[valley]:
                valley += 1
            if valley < end and counts[valley] < 0.55 * max(int(counts[peak]), int(counts[valley + 1])):
                peaks.append((cursor, peak))
                cursor = valley + 1
                continue
            peaks.append((cursor, end))
            break
        index = end + 1
    bands = []
    for start, peak in peaks:
        stop = peak
        while stop + 1 < len(counts) and counts[stop + 1] >= 8 and counts[stop + 1] <= counts[stop]:
            # Keep the falling shoulder, but not the next peak's climb.
            if stop + 2 < len(counts) and counts[stop + 2] > counts[stop + 1]:
                break
            stop += 1
        lo = float(edges[start])
        hi = float(edges[stop + 1])
        bands.append((max(0.4, lo - 0.05), hi + 0.05))
    return bands


def _kasa_circle(points: np.ndarray):
    xy = np.asarray(points, dtype=float)
    if len(xy) < 3:
        return None
    matrix = np.column_stack((xy[:, 0], xy[:, 1], np.ones(len(xy))))
    rhs = -(xy[:, 0] ** 2 + xy[:, 1] ** 2)
    try:
        sol, *_rest = np.linalg.lstsq(matrix, rhs, rcond=None)
    except np.linalg.LinAlgError:
        return None
    cx = float(-sol[0] / 2.0)
    cy = float(-sol[1] / 2.0)
    r2 = cx * cx + cy * cy - float(sol[2])
    if r2 <= 1e-8:
        return None
    return np.array([cx, cy], dtype=float), math.sqrt(r2)


def _face_intervals(points, vertices, faces, direction, center, radius, perp) -> list[dict]:
    """Merge overlapping face extents along the axis. One knuckle is one interval."""
    if len(points) == 0 or len(faces) == 0:
        return []
    intervals = []
    for slot, face in enumerate(faces):
        axial = vertices[face] @ direction
        intervals.append((float(axial.min()), float(axial.max()), slot))
    intervals.sort(key=lambda item: item[0])
    groups = [[intervals[0]]]
    for item in intervals[1:]:
        if item[0] <= groups[-1][-1][1] + 0.35:
            groups[-1].append(item)
        else:
            groups.append([item])
    spans = []
    for group in groups:
        if len(group) < 12:
            continue
        start = min(item[0] for item in group)
        end = max(item[1] for item in group)
        length = end - start
        if length < 1.5 * radius:
            continue
        slots = [item[2] for item in group]
        flat = points[slots][:, perp] - center
        norms = np.linalg.norm(flat, axis=1)
        keep = norms > 1e-6
        if int(np.count_nonzero(keep)) < 12:
            continue
        angles = np.arctan2(flat[keep, 1], flat[keep, 0])
        bins = np.clip(np.floor((angles + math.pi) / (2.0 * math.pi) * 36.0).astype(int), 0, 35)
        covered = len(set(int(item) for item in bins)) * 10.0
        if covered < 240.0:
            continue
        spans.append(
            {
                "span": (float(start), float(end)),
                "radius": float(radius),
                "center": np.array(center, dtype=float),
            }
        )
    return spans


def _merge_coaxial_spans(segments: list[dict]) -> list[dict]:
    """Inner and outer walls of one barrel are one knuckle."""
    if not segments:
        return []
    ordered = sorted(segments, key=lambda item: item["span"][0])
    merged = [ordered[0]]
    for item in ordered[1:]:
        prev = merged[-1]
        same_center = float(np.linalg.norm(item["center"] - prev["center"])) < 0.2
        overlap = min(prev["span"][1], item["span"][1]) - max(prev["span"][0], item["span"][0])
        shorter = min(prev["span"][1] - prev["span"][0], item["span"][1] - item["span"][0])
        if same_center and shorter > 0 and overlap > 0.5 * shorter:
            merged[-1] = {
                "span": (min(prev["span"][0], item["span"][0]), max(prev["span"][1], item["span"][1])),
                "radius": max(float(prev["radius"]), float(item["radius"])),
                "center": (prev["center"] + item["center"]) / 2.0,
            }
            continue
        merged.append(item)
    return merged


def _gapped_segments(segments: list[dict]) -> list[dict]:
    if len(segments) < 2:
        return []
    for left, right in zip(segments, segments[1:]):
        gap = float(right["span"][0] - left["span"][1])
        center = float(np.linalg.norm(right["center"] - left["center"]))
        if gap < 0.15 or center > 0.2:
            return []
    return list(segments)


def _plate_thickness(mesh) -> float | None:
    """Thickness of the largest parallel-face pair, or None when no plate is clear."""
    try:
        normals = np.asarray(mesh.face_normals, dtype=float)
        centers = np.asarray(mesh.triangles_center, dtype=float)
        areas = np.asarray(mesh.area_faces, dtype=float)
    except Exception:
        return None
    total = float(np.sum(areas)) if len(areas) else 0.0
    floor = max(8.0, 0.04 * total)
    found = []
    for axis in range(3):
        aligned = np.abs(normals[:, axis]) >= 0.92
        if int(np.count_nonzero(aligned)) < 6:
            continue
        pos = centers[aligned, axis]
        weight = areas[aligned]
        keys = np.round(pos / 0.35) * 0.35
        buckets: dict[float, list[float]] = {}
        for key, position, mass in zip(keys, pos, weight):
            slot = buckets.setdefault(float(key), [0.0, 0.0])
            slot[0] += float(position) * float(mass)
            slot[1] += float(mass)
        slabs = []
        for total_pos, mass in buckets.values():
            if mass < floor:
                continue
            slabs.append(total_pos / mass)
        slabs.sort()
        extent = float(np.asarray(mesh.extents, dtype=float)[axis])
        for left, right in zip(slabs, slabs[1:]):
            gap = float(right - left)
            # A gap that is most of this axis is the body itself, not a leaf.
            if extent > 0 and gap > 0.55 * extent:
                continue
            if 0.6 <= gap <= 12.0:
                found.append(gap)
    if not found:
        return None
    return float(min(found))


def genus_report(mesh) -> dict:
    """Handle count and whether that count can be trusted.

    ``split`` can turn one watertight solid into shells that are no longer
    watertight, so a per-shell sum then reports 0 while the unsplit Euler
    characteristic still shows the holes. That result is not reliable.
    """
    try:
        whole_watertight = bool(mesh.is_watertight)
        whole_euler = int(mesh.euler_number)
    except Exception:
        return {
            "genus": None,
            "reliable": False,
            "reason": "euler characteristic could not be computed",
        }
    whole_genus = (2 - whole_euler) / 2.0
    whole_integer = abs(whole_genus - round(whole_genus)) < 1e-6 and whole_genus >= -1e-6
    whole_value = int(round(whole_genus)) if whole_integer else None
    try:
        shells = list(mesh.split(only_watertight=False))
    except Exception:
        shells = []
    if not shells:
        if whole_watertight and whole_value is not None:
            return {"genus": whole_value, "reliable": True, "reason": None}
        return {
            "genus": whole_value,
            "reliable": False,
            "reason": "mesh is not watertight" if not whole_watertight else "genus is not an integer",
        }
    total = 0
    split_reliable = True
    reason = None
    for shell in shells:
        try:
            closed = bool(shell.is_watertight)
            euler = int(shell.euler_number)
        except Exception:
            split_reliable = False
            reason = "euler characteristic could not be computed"
            continue
        if not closed:
            split_reliable = False
            reason = "split shell is not watertight"
            continue
        genus = (2 - euler) / 2.0
        if abs(genus - round(genus)) > 1e-6 or genus < -1e-6:
            split_reliable = False
            reason = "genus is not a non-negative integer"
            continue
        if genus > 0:
            total += int(round(genus))
    if whole_watertight and whole_value is not None and (not split_reliable or total != whole_value):
        return {
            "genus": whole_value,
            "reliable": False,
            "reason": reason or "split genus does not match the whole mesh",
            "split_genus": total,
        }
    if not split_reliable:
        return {"genus": whole_value, "reliable": False, "reason": reason}
    return {"genus": total, "reliable": True, "reason": None}


def mesh_genus(mesh) -> int:
    """Handle count. Unreliable meshes still return the whole-mesh genus when it exists.

    This is information only. A shaft through several knuckles adds handles
    that are not separate bores, so ``hole_count`` uses :func:`count_bores`.
    """
    info = genus_report(mesh)
    genus = info.get("genus")
    if isinstance(genus, int):
        return genus
    return 0


def count_holes(mesh) -> int:
    """Bore count. ``mesh_genus`` is the handle count and is not this number."""
    return len(count_bores(mesh))


# A blind opening shallower than this fraction of its diameter is a recess.
# A 23.5 mm dish a couple of millimetres deep fails it. A pin-clearance bore
# and a real blind tap pass it. Through-holes are bores regardless of depth.
_RECESS_RATIO = 0.35
_OPEN_CACHE: list = [None, None]


def openings(mesh) -> dict:
    """Circular bores, and the shallow dishes that are not bores.

    Through-holes and blind bores whose depth is at least max(1 mm, 0.35 ×
    diameter) are bores. A blind dish shallower than that is a recess and is
    left out of ``hole_count``.
    """
    key = _openings_key(mesh)
    if key is not None and key == _OPEN_CACHE[0]:
        return _OPEN_CACHE[1]
    if mesh is None or len(getattr(mesh, "faces", [])) == 0:
        result = {"bores": [], "recesses": []}
    else:
        merged = _merge_bores(_bores_from_sections(mesh), _bores_from_rays(mesh))
        marked = _mark_through(mesh, merged)
        bores, recesses = _split_recesses(mesh, marked)
        result = {"bores": bores, "recesses": recesses}
    if key is not None:
        _OPEN_CACHE[0] = key
        _OPEN_CACHE[1] = result
    return result


def count_bores(mesh) -> list[dict]:
    """Circular bores from per-leg slices on all three axes, plus ray casting.

    Whole-part stations at 25, 50, and 75 percent stay, and each planar leg
    is also sliced at 30, 50, and 70 percent of its own thickness. An interior
    ring is accepted by a least-squares circle fit. Sections whose centres
    agree within 0.6 mm are the same bore. A sampled station between two
    sightings with no ring splits them, so two collinear knuckle bores stay
    two bores.

    Through-holes are also found by casting a grid of rays along each axis.
    A void column enclosed by material is a bore. A ray that never hits is
    through; a ray that hits the floor is blind. Ray bores that share an axis
    and a perpendicular centre with a section bore are not added again, so a
    pair of collinear knuckle bores is not collapsed into one tunnel.

    A blind opening whose depth is under max(1 mm, 0.35 × diameter) is a
    recess, not a bore. Decorative dishes fail that test. Through-holes and
    pin-clearance bores of meaningful depth stay.

    trimesh's ``section_multiplane`` needs scipy, which this plugin does not
    install. The slices are computed with numpy and shapely.
    """
    return openings(mesh)["bores"]


def _openings_key(mesh):
    try:
        bounds = np.round(np.asarray(mesh.bounds, dtype=float).ravel(), 3)
        return (id(mesh), int(len(mesh.faces)), tuple(float(value) for value in bounds))
    except Exception:
        return None


def _split_recesses(mesh, bores: list[dict]) -> tuple[list[dict], list[dict]]:
    kept: list[dict] = []
    recesses: list[dict] = []
    for bore in bores:
        if bore.get("through"):
            kept.append(bore)
            continue
        depth = _void_run_mm(mesh, bore)
        row = dict(bore)
        row["depth_mm"] = round(float(depth), 3)
        diameter = float(row.get("diameter") or 0.0)
        needed = max(1.0, _RECESS_RATIO * diameter) if diameter > 0 else 1.0
        if depth + 1e-9 >= needed:
            kept.append(row)
            continue
        row["kind"] = "recess"
        row["depth_ratio"] = round(float(depth) / diameter, 4) if diameter > 0 else 0.0
        recesses.append(row)
    return kept, recesses


def _void_run_mm(mesh, bore: dict) -> float:
    """Longest axial run where the opening is void and a wall sample is material."""
    axis = {"x": 0, "y": 1, "z": 2}[str(bore["axis"])]
    center = np.asarray(bore["center"], dtype=float)
    radius = float(bore.get("diameter") or 0.0) / 2.0
    if radius < 0.25:
        return 0.0
    bounds = np.asarray(mesh.bounds, dtype=float)
    start = float(bounds[0, axis]) + 0.2
    stop = float(bounds[1, axis]) - 0.05
    if stop <= start:
        return 0.0
    step = 0.45
    stations = np.arange(start, stop + 1e-6, step)
    if len(stations) == 0:
        return 0.0
    perp = [slot for slot in range(3) if slot != axis]
    # Pin clearance is the gap around the pin. An empty bore is open near the centre.
    frac = 0.90 if bore.get("kind") == "pin_clearance" else 0.45
    wall = 1.20
    # Offset from the cardinal axes so a sample does not ride a polygon edge.
    angles = tuple(0.37 + index * (math.pi / 2.0) for index in range(4))
    hole_pts = []
    wall_pts = []
    for position in stations:
        base = center.copy()
        base[axis] = float(position)
        for angle in angles:
            cosine = math.cos(angle)
            sine = math.sin(angle)
            hole = base.copy()
            hole[perp[0]] += frac * radius * cosine
            hole[perp[1]] += frac * radius * sine
            hole_pts.append(hole)
            outer = base.copy()
            outer[perp[0]] += wall * radius * cosine
            outer[perp[1]] += wall * radius * sine
            wall_pts.append(outer)
    hole_in = _points_inside(mesh, np.vstack(hole_pts), axis).reshape(len(stations), 4)
    wall_in = _points_inside(mesh, np.vstack(wall_pts), axis).reshape(len(stations), 4)
    # One ray through a shared edge flips parity. Three of four samples must agree.
    open_station = (np.sum(~hole_in, axis=1) >= 3) & (np.sum(wall_in, axis=1) >= 3)
    best = 0
    run = 0
    for flag in open_station:
        if flag:
            run += 1
            best = max(best, run)
        else:
            run = 0
    if best == 0:
        return 0.0
    return float(best) * step


def _points_inside(mesh, points: np.ndarray, axis: int) -> np.ndarray:
    hits = _hit_counts(mesh, points, axis)
    return (hits % 2) == 1


def _bores_from_sections(mesh) -> list[dict]:
    bounds = np.asarray(mesh.bounds, dtype=float)
    extents = np.asarray(mesh.extents, dtype=float)
    planes = _unique_planes(_section_planes(mesh, bounds, extents))
    bodies = _mesh_bodies(mesh)
    by_axis: dict[int, list[tuple[float, list[dict]]]] = {0: [], 1: [], 2: []}
    for axis, position in planes:
        origin = np.array(bounds[0], dtype=float)
        origin[axis] = float(position)
        normal = np.zeros(3, dtype=float)
        normal[axis] = 1.0
        rings = _rings_on_bodies(bodies, origin, normal, axis)
        by_axis[axis].append((float(position), rings))
    found: list[dict] = []
    names = ("x", "y", "z")
    for axis, samples in by_axis.items():
        samples.sort(key=lambda item: item[0])
        found.extend(_bores_from_stations(names[axis], samples))
    return found


def _section_planes(mesh, bounds: np.ndarray, extents: np.ndarray) -> list[tuple[int, float]]:
    """Whole-part stations plus several cuts through each planar leg."""
    planes: list[tuple[int, float]] = []
    for axis in range(3):
        span = float(extents[axis])
        if span <= 1e-6:
            continue
        for frac in (0.25, 0.50, 0.75):
            planes.append((axis, float(bounds[0, axis] + frac * span)))
    planes.extend(_slab_planes(mesh))
    return planes


def _slab_planes(mesh) -> list[tuple[int, float]]:
    """Mid-thickness cuts of each axis-aligned wall, including a thin leg."""
    triangles = np.asarray(mesh.triangles, dtype=float)
    if len(triangles) == 0:
        return []
    edge1 = triangles[:, 1] - triangles[:, 0]
    edge2 = triangles[:, 2] - triangles[:, 0]
    normals = np.cross(edge1, edge2)
    area = np.linalg.norm(normals, axis=1)
    keep = area > 1.0
    if not np.any(keep):
        return []
    normals = normals[keep] / area[keep, None]
    area = area[keep]
    centroids = triangles[keep].mean(axis=1)
    planes: list[tuple[int, float]] = []
    for axis in range(3):
        aligned = np.abs(normals[:, axis]) >= 0.92
        if int(np.count_nonzero(aligned)) < 4:
            continue
        pos = centroids[aligned, axis]
        weight = area[aligned]
        other = [slot for slot in range(3) if slot != axis]
        flat = centroids[aligned][:, other]
        keys = np.round(pos / 0.35) * 0.35
        clusters: dict[float, dict] = {}
        for key, position, mass, point in zip(keys, pos, weight, flat):
            bucket = clusters.get(float(key))
            if bucket is None:
                bucket = {
                    "pos": 0.0,
                    "mass": 0.0,
                    "min": np.array(point, dtype=float),
                    "max": np.array(point, dtype=float),
                    "count": 0,
                }
                clusters[float(key)] = bucket
            bucket["pos"] += float(position) * float(mass)
            bucket["mass"] += float(mass)
            bucket["min"] = np.minimum(bucket["min"], point)
            bucket["max"] = np.maximum(bucket["max"], point)
            bucket["count"] += 1
        slabs = []
        for bucket in clusters.values():
            if bucket["mass"] <= 0 or bucket["count"] < 4:
                continue
            slabs.append(
                {
                    "pos": bucket["pos"] / bucket["mass"],
                    "min": bucket["min"],
                    "max": bucket["max"],
                }
            )
        slabs.sort(key=lambda item: item["pos"])
        for left, right in zip(slabs, slabs[1:]):
            gap = float(right["pos"] - left["pos"])
            if gap < 0.4 or gap > 40.0:
                continue
            overlaps = bool(np.all(left["max"] + 1.5 >= right["min"]) and np.all(right["max"] + 1.5 >= left["min"]))
            if not overlaps:
                continue
            for frac in (0.30, 0.50, 0.70):
                planes.append((axis, float(left["pos"] + frac * gap)))
    return planes


def _unique_planes(planes: list[tuple[int, float]]) -> list[tuple[int, float]]:
    kept: list[tuple[int, float]] = []
    for axis, position in sorted(planes, key=lambda item: (item[0], item[1])):
        if any(other == axis and abs(found - position) < 0.15 for other, found in kept):
            continue
        kept.append((axis, position))
    return kept


def _bores_from_stations(axis_name: str, samples: list[tuple[float, list[dict]]]) -> list[dict]:
    """Group rings by perpendicular centre. A missed station between them splits the run."""
    positions = [position for position, _rings in samples]
    events: list[tuple[float, dict]] = []
    for position, rings in samples:
        for ring in rings:
            events.append((position, ring))
    groups: list[dict] = []
    for position, ring in events:
        placed = None
        for group in groups:
            if np.linalg.norm(np.asarray(group["perp"], dtype=float) - np.asarray(ring["perp"], dtype=float)) <= 0.6:
                placed = group
                break
        if placed is None:
            groups.append({"perp": list(ring["perp"]), "hits": [(position, ring)]})
            continue
        placed["hits"].append((position, ring))
        placed["perp"] = [(float(a) + float(b)) / 2.0 for a, b in zip(placed["perp"], ring["perp"])]
    bores = []
    for group in groups:
        hits = sorted(group["hits"], key=lambda item: item[0])
        run: list[tuple[float, dict]] = []
        for position, ring in hits:
            if run and _station_between(positions, run[-1][0], position):
                bores.append(_record_from_run(axis_name, run))
                run = []
            run.append((position, ring))
        if run:
            bores.append(_record_from_run(axis_name, run))
    return bores


def _station_between(positions: list[float], start: float, end: float) -> bool:
    """True when a sampled plane between two sightings missed this bore.

    A short gap is a thread or a tessellation miss, not a second bore.
    Knuckle bores sit tens of millimetres apart, so those still split.
    """
    low = min(start, end)
    high = max(start, end)
    if high - low <= 8.0:
        return False
    return any(low + 1e-6 < position < high - 1e-6 for position in positions)


def _record_from_run(axis_name: str, run: list[tuple[float, dict]]) -> dict:
    rings = [ring for _position, ring in run]
    centers = np.asarray([ring["center"] for ring in rings], dtype=float)
    diameters = [float(ring["diameter"]) for ring in rings]
    record = {
        "axis": axis_name,
        "center": [round(float(value), 4) for value in centers.mean(axis=0)],
        "diameter": round(float(np.median(diameters)), 4),
        "through": False,
    }
    kinds = [ring.get("kind") for ring in rings if ring.get("kind")]
    clearances = [float(ring["clearance_mm"]) for ring in rings if ring.get("clearance_mm") is not None]
    if kinds:
        record["kind"] = kinds[0]
    if clearances:
        record["clearance_mm"] = round(float(np.median(clearances)), 4)
    return record


def _bores_from_rays(mesh) -> list[dict]:
    """Enclosed void columns. Spacing stays near 1.5 mm so a Ø5 hole is hit."""
    bounds = np.asarray(mesh.bounds, dtype=float)
    extents = np.asarray(mesh.extents, dtype=float)
    found: list[dict] = []
    for axis in range(3):
        found.extend(_ray_axis(mesh, axis, bounds, extents))
    return found


def _ray_axis(mesh, axis: int, bounds: np.ndarray, extents: np.ndarray) -> list[dict]:
    perp = [slot for slot in range(3) if slot != axis]
    coords = []
    steps = []
    for slot in perp:
        span = float(extents[slot])
        if span <= 1e-6:
            return []
        count = int(np.clip(round(span / 1.5), 8, 40))
        step = span / count
        coords.append(bounds[0, slot] + (np.arange(count) + 0.5) * step)
        steps.append(step)
    first, second = np.meshgrid(coords[0], coords[1], indexing="ij")
    origins = np.zeros((first.size, 3), dtype=float)
    origins[:, perp[0]] = first.ravel()
    origins[:, perp[1]] = second.ravel()
    origins[:, axis] = float(bounds[0, axis]) - 1.0
    counts = _hit_counts(mesh, origins, axis).reshape(first.shape)
    names = ("x", "y", "z")
    bores = []
    for kind, through in ((counts == 0, True), (counts == 1, False)):
        for cells, touches in _mask_components(kind):
            if touches or len(cells) < 1:
                continue
            if not _enclosed(counts, cells):
                continue
            center2, diameter = _cell_circle(cells, coords[0], coords[1], steps)
            if diameter < 0.8 or diameter > 80.0:
                continue
            if not _round_enough(cells, coords[0], coords[1], steps):
                continue
            center = np.zeros(3, dtype=float)
            center[perp[0]] = center2[0]
            center[perp[1]] = center2[1]
            center[axis] = float(np.mean(bounds[:, axis]))
            bores.append(
                {
                    "axis": names[axis],
                    "center": [round(float(value), 4) for value in center],
                    "diameter": round(float(diameter), 4),
                    "through": through,
                }
            )
    confirmed = [bore for bore in _unique_ray_bores(bores) if _confirm_ray(mesh, bore)]
    return confirmed


def _confirm_ray(mesh, bore: dict) -> bool:
    """Keep a ray column only when some plane shows a circular ring there.

    A square through-hole is an enclosed void and would otherwise count.
    The confirming plane also places the centre inside a thin leg instead of
    at the middle of the whole part.
    """
    bounds = np.asarray(mesh.bounds, dtype=float)
    axis = {"x": 0, "y": 1, "z": 2}[str(bore["axis"])]
    span = float(bounds[1, axis] - bounds[0, axis])
    if span <= 1e-6:
        return False
    normal = np.zeros(3, dtype=float)
    normal[axis] = 1.0
    target = np.asarray(_perp_center(bore), dtype=float)
    for frac in (0.01, 0.04, 0.12, 0.25, 0.50, 0.75, 0.88, 0.96, 0.99):
        origin = np.array(bounds[0], dtype=float)
        origin[axis] = float(bounds[0, axis] + frac * span)
        for ring in _circular_interiors(mesh, origin, normal, axis):
            if np.linalg.norm(np.asarray(ring["perp"], dtype=float) - target) <= 1.0:
                bore["center"] = list(ring["center"])
                bore["diameter"] = ring["diameter"]
                return True
    return False


def _hit_counts(mesh, origins: np.ndarray, axis: int) -> np.ndarray:
    """Axis-aligned Möller–Trumbore, vectorised in ray chunks.

    The counts match the per-triangle test. A chunk's perpendicular bounds
    drop triangles the rays cannot meet.
    """
    triangles = np.asarray(mesh.triangles, dtype=float)
    origins = np.asarray(origins, dtype=float).reshape(-1, 3)
    hits = np.zeros(len(origins), dtype=np.int32)
    if len(triangles) == 0 or len(origins) == 0:
        return hits
    direction = np.zeros(3, dtype=float)
    direction[int(axis)] = 1.0
    v0 = triangles[:, 0, :]
    edge1 = triangles[:, 1, :] - v0
    edge2 = triangles[:, 2, :] - v0
    pvec = np.cross(direction, edge2)
    det = np.einsum("ij,ij->i", edge1, pvec)
    valid = np.abs(det) >= 1e-9
    if not np.any(valid):
        return hits
    inv = np.zeros(len(triangles), dtype=float)
    inv[valid] = 1.0 / det[valid]
    perp = [slot for slot in range(3) if slot != int(axis)]
    tri_min = triangles[:, :, perp].min(axis=1)
    tri_max = triangles[:, :, perp].max(axis=1)
    chunk = 64
    for start in range(0, len(origins), chunk):
        block = origins[start : start + chunk]
        span = block[:, perp]
        low = span.min(axis=0) - 1e-6
        high = span.max(axis=0) + 1e-6
        use = valid & np.all(tri_max >= low, axis=1) & np.all(tri_min <= high, axis=1)
        if not np.any(use):
            continue
        sel_v0 = v0[use]
        sel_e1 = edge1[use]
        sel_e2 = edge2[use]
        sel_p = pvec[use]
        sel_inv = inv[use]
        offset = block[:, None, :] - sel_v0[None, :, :]
        u = sel_inv * np.einsum("rti,ti->rt", offset, sel_p)
        qvec = np.cross(offset, sel_e1[None, :, :])
        v = sel_inv * np.einsum("rti,i->rt", qvec, direction)
        t = sel_inv * np.einsum("rti,ti->rt", qvec, sel_e2)
        mask = (u >= 0.0) & (v >= 0.0) & ((u + v) <= 1.0) & (t > 1e-9)
        hits[start : start + len(block)] = mask.sum(axis=1).astype(np.int32)
    return hits


def _mask_components(mask: np.ndarray) -> list[tuple[list[tuple[int, int]], bool]]:
    height, width = mask.shape
    seen = np.zeros(mask.shape, dtype=bool)
    found = []
    for y in range(height):
        for x in range(width):
            if not mask[y, x] or seen[y, x]:
                continue
            stack = [(y, x)]
            seen[y, x] = True
            cells: list[tuple[int, int]] = []
            touches = False
            while stack:
                cy, cx = stack.pop()
                cells.append((cy, cx))
                if cy in {0, height - 1} or cx in {0, width - 1}:
                    touches = True
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < height and 0 <= nx < width and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
            found.append((cells, touches))
    return found


def _enclosed(counts: np.ndarray, cells: list[tuple[int, int]]) -> bool:
    """A hole's neighbours are material. Exterior bays are not."""
    height, width = counts.shape
    occupied = set(cells)
    material = 0
    checked = 0
    for y, x in cells:
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if not (0 <= ny < height and 0 <= nx < width) or (ny, nx) in occupied:
                continue
            checked += 1
            if int(counts[ny, nx]) >= 2:
                material += 1
    if checked == 0:
        return False
    return material >= max(1, int(0.6 * checked))


def _cell_circle(cells, xs, ys, steps) -> tuple[np.ndarray, float]:
    # cells are (row, col) into meshgrid(xs, ys, indexing="ij").
    points = np.array([[float(xs[row]), float(ys[col])] for row, col in cells], dtype=float)
    center = points.mean(axis=0)
    step = float(np.mean(steps))
    if len(points) == 1:
        return center, step
    radii = np.linalg.norm(points - center, axis=1)
    return center, float(2.0 * (radii.max() + 0.5 * step))


def _round_enough(cells, xs, ys, steps) -> bool:
    points = np.array([[float(xs[row]), float(ys[col])] for row, col in cells], dtype=float)
    if len(points) <= 2:
        return True
    span = points.max(axis=0) - points.min(axis=0)
    step = float(np.mean(steps))
    aspect = (float(span.max()) + step) / max(step, float(span.min()) + step)
    return aspect <= 1.85


def _unique_ray_bores(bores: list[dict]) -> list[dict]:
    kept: list[dict] = []
    for bore in bores:
        if any(_perp_close(bore, other) and bore.get("through") == other.get("through") for other in kept):
            continue
        kept.append(bore)
    return kept


def _merge_bores(sections: list[dict], rays: list[dict]) -> list[dict]:
    """Keep section bores. A ray bore is new only when no section shares its centre."""
    merged = list(sections)
    for ray in rays:
        if any(_perp_close(ray, existing) for existing in merged):
            continue
        merged.append(ray)
    return merged


def _perp_close(left: dict, right: dict) -> bool:
    if left.get("axis") != right.get("axis"):
        return False
    return float(np.linalg.norm(np.asarray(_perp_center(left)) - np.asarray(_perp_center(right)))) <= 0.8


def _perp_center(bore: dict) -> list[float]:
    axis = {"x": 0, "y": 1, "z": 2}[str(bore["axis"])]
    return [float(value) for index, value in enumerate(bore["center"]) if index != axis]


def _mark_through(mesh, bores: list[dict]) -> list[dict]:
    """A centre ray with no hit is a through-hole. A hit is the floor of a blind bore."""
    if not bores:
        return bores
    axis_index = {"x": 0, "y": 1, "z": 2}
    bounds = np.asarray(mesh.bounds, dtype=float)
    for bore in bores:
        axis = axis_index[str(bore["axis"])]
        origin = np.asarray(bore["center"], dtype=float).reshape(1, 3).copy()
        origin[0, axis] = float(bounds[0, axis]) - 1.0
        hits = int(_hit_counts(mesh, origin, axis)[0])
        bore["through"] = hits == 0
    return bores


def section_areas_mm2(mesh) -> dict:
    """Material area of horizontal sections at 25, 50, and 75 percent of the height."""
    empty = {"0.25": 0.0, "0.50": 0.0, "0.75": 0.0}
    if mesh is None or len(getattr(mesh, "faces", [])) == 0:
        return empty
    bounds = np.asarray(mesh.bounds, dtype=float)
    span = float(bounds[1, 2] - bounds[0, 2])
    if span <= 1e-6:
        return empty
    areas = {}
    normal = np.array([0.0, 0.0, 1.0])
    for label, frac in (("0.25", 0.25), ("0.50", 0.50), ("0.75", 0.75)):
        origin = np.array(bounds[0], dtype=float)
        origin[2] = float(bounds[0, 2] + frac * span)
        areas[label] = round(_material_area(mesh, origin, normal), 3)
    return areas


def _material_area(mesh, origin: np.ndarray, normal: np.ndarray) -> float:
    from shapely.geometry import Polygon

    polygons = _section_polygons(mesh, origin, normal)
    total = 0.0
    for poly in polygons:
        contained = any(
            other is not poly
            and float(other.area) > float(poly.area) + 1e-6
            and other.contains(poly.representative_point())
            for other in polygons
        )
        if contained:
            continue
        hole_area = sum(float(Polygon(ring).area) for ring in poly.interiors)
        total += max(0.0, float(poly.area) - hole_area)
    return total


def _mesh_bodies(mesh) -> list:
    """One entry per shell. A pin and its sleeve are sectioned apart."""
    try:
        bodies = [body for body in mesh.split(only_watertight=False) if len(getattr(body, "faces", [])) > 0]
    except Exception:
        bodies = []
    if len(bodies) <= 1:
        return [mesh]
    return bodies


def _rings_on_bodies(bodies, origin: np.ndarray, normal: np.ndarray, axis: int) -> list[dict]:
    sections = []
    for body in bodies:
        try:
            bounds = np.asarray(body.bounds, dtype=float)
        except Exception:
            bounds = None
        if bounds is not None and (
            float(bounds[1, axis]) < float(origin[axis]) - 1e-6 or float(bounds[0, axis]) > float(origin[axis]) + 1e-6
        ):
            sections.append([])
            continue
        sections.append(_section_polygons(body, origin, normal))
    rings = []
    for index, polygons in enumerate(sections):
        others = [poly for other_index, group in enumerate(sections) if other_index != index for poly in group]
        for ring in _circular_interiors_from(polygons, origin, normal, axis, mesh_grid=_snap_grid(bodies[index])):
            _tag_pin_clearance(ring, others)
            rings.append(ring)
    return _unique_rings(rings)


def _circular_interiors(mesh, origin: np.ndarray, normal: np.ndarray, axis: int) -> list[dict]:
    polygons = _section_polygons(mesh, origin, normal)
    return _unique_rings(_circular_interiors_from(polygons, origin, normal, axis, mesh_grid=_snap_grid(mesh)))


def _circular_interiors_from(polygons, origin, normal, axis: int, mesh_grid: float) -> list[dict]:
    from shapely.geometry import Polygon

    holes = []
    for outer in polygons:
        for interior in outer.interiors:
            holes.append(Polygon(interior))
    if not holes:
        # polygonize sometimes emits the hole as its own polygon instead of a ring.
        holes = _contained_polygons(polygons)
    rings = []
    for hole in holes:
        ok, radius, circ = _roundness(hole, mesh_grid)
        if not ok:
            continue
        center3 = _polygon_center_3d(hole, origin, normal)
        perp = [float(center3[i]) for i in range(3) if i != axis]
        rings.append(
            {
                "center": [round(float(value), 4) for value in center3],
                "perp": perp,
                "diameter": round(_diameter_of(hole), 4),
                "circularity": round(circ, 4),
                "radius": round(float(radius), 4),
                "_polygon": hole,
            }
        )
    return rings


def _tag_pin_clearance(ring: dict, other_polygons) -> None:
    """An interior that holds another shell's circle is a pin-clearance bore."""
    hole = ring.pop("_polygon", None)
    if hole is None or not other_polygons:
        ring.pop("_polygon", None)
        return
    radius = float(ring.get("radius") or 0.0)
    if radius <= 0:
        return
    for poly in other_polygons:
        try:
            if float(poly.area) >= float(hole.area) * 0.98:
                continue
            if not hole.buffer(0.05).contains(poly.representative_point()):
                continue
        except Exception:
            continue
        inner = _diameter_of(poly) / 2.0
        gap = radius - inner
        if gap >= 0.2:
            ring["kind"] = "pin_clearance"
            ring["clearance_mm"] = round(float(gap), 4)
            return


def _unique_rings(rings: list[dict]) -> list[dict]:
    kept: list[dict] = []
    for ring in rings:
        ring.pop("_polygon", None)
        if any(np.linalg.norm(np.asarray(ring["perp"]) - np.asarray(other["perp"])) <= 0.3 for other in kept):
            continue
        kept.append(ring)
    return kept


def _contained_polygons(polygons) -> list:
    """Polygons that sit inside a larger section polygon and inside no tighter one."""
    holes = []
    for candidate in polygons:
        parents = [
            other
            for other in polygons
            if other is not candidate and float(other.area) > float(candidate.area) + 1e-6
            and other.contains(candidate.representative_point())
        ]
        if not parents:
            continue
        smallest = min(parents, key=lambda other: float(other.area))
        tighter = [
            other
            for other in parents
            if other is not smallest and float(other.area) < float(smallest.area) - 1e-6
            and other.contains(candidate.representative_point())
        ]
        if not tighter:
            holes.append(candidate)
    return holes


def _bores_from_levels(axis_name: str, levels: list[list[dict]]) -> list[dict]:
    """Match rings across the three slices. A missing slice splits a run."""
    groups: list[dict] = []
    for level, rings in enumerate(levels):
        for ring in rings:
            placed = None
            for group in groups:
                if np.linalg.norm(np.asarray(group["perp"], dtype=float) - np.asarray(ring["perp"], dtype=float)) <= 0.5:
                    placed = group
                    break
            if placed is None:
                groups.append({"perp": list(ring["perp"]), "levels": {level: ring}})
            else:
                # Keep the first ring if two interiors land on one slice.
                placed["levels"].setdefault(level, ring)
                placed["perp"] = [
                    (float(a) + float(b)) / 2.0 for a, b in zip(placed["perp"], ring["perp"])
                ]
    bores = []
    for group in groups:
        indexes = sorted(group["levels"])
        run: list[int] = []
        for index in indexes + [None]:
            if run and (index is None or index > run[-1] + 1):
                bores.append(_bore_record(axis_name, run, group["levels"]))
                run = []
            if index is not None:
                run.append(index)
    return bores


def _bore_record(axis_name: str, run: list[int], levels: dict) -> dict:
    chosen = [levels[index] for index in run]
    centers = np.asarray([ring["center"] for ring in chosen], dtype=float)
    diameters = [float(ring["diameter"]) for ring in chosen]
    return {
        "axis": axis_name,
        "center": [round(float(v), 4) for v in centers.mean(axis=0)],
        "diameter": round(float(np.median(diameters)), 4),
        "through": run == [0, 1, 2],
    }


def _circularity(polygon) -> float:
    area = float(polygon.area)
    perimeter = float(polygon.length)
    if area <= 1e-6 or perimeter <= 1e-6:
        return 0.0
    return float(4.0 * np.pi * area / (perimeter * perimeter))


def _roundness(polygon, grid: float) -> tuple[bool, float, float]:
    """Least-squares circle on a smoothed outline.

    Passes when the RMS radial residual is under max(0.03 mm, 4% of r) and
    the area matches πr² within 5%. 4πA/P² on the simplified ring is kept as
    a secondary score. A staircase circle passes; a square does not.
    """
    try:
        smooth = polygon.simplify(max(float(grid), 1e-4), preserve_topology=True)
    except Exception:
        smooth = polygon
    if float(getattr(smooth, "area", 0.0)) <= 1e-6:
        smooth = polygon
    fit = _fit_circle_xy(np.asarray(smooth.exterior.coords, dtype=float))
    if fit is None:
        fit = _fit_circle_xy(np.asarray(polygon.exterior.coords, dtype=float))
    if fit is None:
        return False, 0.0, _circularity(smooth)
    _cx, _cy, radius, rms = fit
    if radius < 0.3:
        return False, radius, _circularity(smooth)
    area = float(polygon.area)
    target = math.pi * radius * radius
    area_ok = abs(area - target) <= 0.05 * max(target, 1e-9)
    limit = max(0.03, 0.04 * radius)
    return bool(rms < limit and area_ok), float(radius), _circularity(smooth)


def _fit_circle_xy(coords: np.ndarray):
    xy = np.asarray(coords, dtype=float)
    if len(xy) >= 2 and np.allclose(xy[0], xy[-1]):
        xy = xy[:-1]
    if len(xy) < 6:
        return None
    matrix = np.column_stack((xy[:, 0], xy[:, 1], np.ones(len(xy))))
    rhs = -(xy[:, 0] ** 2 + xy[:, 1] ** 2)
    try:
        sol, *_rest = np.linalg.lstsq(matrix, rhs, rcond=None)
    except np.linalg.LinAlgError:
        return None
    cx = float(-sol[0] / 2.0)
    cy = float(-sol[1] / 2.0)
    r2 = cx * cx + cy * cy - float(sol[2])
    if not math.isfinite(r2) or r2 <= 1e-8:
        return None
    radius = math.sqrt(r2)
    radial = np.sqrt((xy[:, 0] - cx) ** 2 + (xy[:, 1] - cy) ** 2)
    rms = float(np.sqrt(np.mean((radial - radius) ** 2)))
    return cx, cy, radius, rms


def _snap_grid(mesh) -> float:
    """Snap no coarser than 0.05 mm, and finer on a small part."""
    try:
        extents = np.asarray(mesh.extents, dtype=float)
    except Exception:
        return 0.05
    positive = extents[np.isfinite(extents) & (extents > 1e-6)]
    if positive.size == 0:
        return 0.05
    return float(min(0.05, 0.01 * float(positive.min())))


def _diameter_of(polygon) -> float:
    area = float(polygon.area)
    if area <= 0:
        return 0.0
    return float(2.0 * np.sqrt(area / np.pi))


def _polygon_center_3d(polygon, origin: np.ndarray, normal: np.ndarray) -> np.ndarray:
    centroid = polygon.centroid
    # Centroid of a ring is the hole centre. representative_point can sit on the wall.
    u, v = _plane_basis(normal)
    return np.asarray(origin, dtype=float) + float(centroid.x) * u + float(centroid.y) * v


def _plane_basis(normal: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    axis = np.asarray(normal, dtype=float)
    axis = axis / np.linalg.norm(axis)
    helper = np.array([1.0, 0.0, 0.0]) if abs(float(axis[0])) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = np.cross(axis, helper)
    u = u / np.linalg.norm(u)
    v = np.cross(axis, u)
    return u, v


def _section_polygons(mesh, origin: np.ndarray, normal: np.ndarray) -> list:
    """Closed section polygons on a plane. Outer and hole loops are separate polygons."""
    from shapely.geometry import LineString
    from shapely.ops import polygonize, unary_union

    segments = _plane_segments(mesh, origin, normal)
    if len(segments) < 3:
        return []
    u, v = _plane_basis(normal)
    # set_precision closes tessellated loops. The grid scales with the part
    # so a small bore is not turned into a 0.05 mm staircase before the fit.
    grid = _snap_grid(mesh)
    lines = []
    for start, end in segments:
        a = start - origin
        b = end - origin
        p = (float(a @ u), float(a @ v))
        q = (float(b @ u), float(b @ v))
        if (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 < 1e-18:
            continue
        lines.append(LineString((p, q)))
    if not lines:
        return []
    try:
        merged = unary_union(lines)
        try:
            from shapely import set_precision

            merged = set_precision(merged, grid, mode="pointwise")
        except Exception:
            pass
        polygons = [poly for poly in polygonize(merged) if float(poly.area) > 0.05]
    except Exception:
        return []
    return polygons


def _plane_segments(mesh, origin: np.ndarray, normal: np.ndarray) -> list[tuple[np.ndarray, np.ndarray]]:
    """One segment per triangle the plane cuts. Numpy only."""
    vertices = np.asarray(mesh.vertices, dtype=float)
    faces = np.asarray(mesh.faces)
    if len(faces) == 0:
        return []
    axis = np.asarray(normal, dtype=float)
    axis = axis / np.linalg.norm(axis)
    signed = (vertices - np.asarray(origin, dtype=float)) @ axis
    corner = signed[faces]
    tri = vertices[faces]
    pairs = ((0, 1), (1, 2), (2, 0))
    hits: dict[int, list[np.ndarray]] = {}
    for a, b in pairs:
        da = corner[:, a]
        db = corner[:, b]
        cross = (da * db <= 0.0) & ((np.abs(da) + np.abs(db)) > 1e-8)
        index = np.flatnonzero(cross)
        if len(index) == 0:
            continue
        denom = da[index] - db[index]
        safe = np.abs(denom) > 1e-12
        index = index[safe]
        denom = denom[safe]
        if len(index) == 0:
            continue
        weight = np.clip(da[index] / denom, 0.0, 1.0)
        points = tri[index, a] + (tri[index, b] - tri[index, a]) * weight[:, None]
        for face_index, point in zip(index.tolist(), points):
            hits.setdefault(int(face_index), []).append(point)
    segments = []
    for points in hits.values():
        if len(points) < 2:
            continue
        # A triangle meets a plane in at most one segment. Extra hits are duplicates.
        start = points[0]
        end = max(points[1:], key=lambda other: float(np.linalg.norm(other - start)))
        if float(np.linalg.norm(end - start)) < 1e-6:
            continue
        segments.append((start, end))
    return segments


class _Checks(list):
    axis: str | None = None
    raw: dict | None = None


def _source_of(spec, name: str) -> str:
    """A plain spec number is the user's value. ``source`` can mark it assumed."""
    if not isinstance(spec, dict):
        return "user"
    item = spec.get(name)
    nested = spec.get("dims") if isinstance(spec.get("dims"), dict) else {}
    if item is None and isinstance(nested, dict):
        item = nested.get(name)
    if isinstance(item, dict) and item.get("source"):
        return str(item["source"])
    return "user"


def _assumed_dim_note(spec, name: str, value: float, tol: float, actual: float) -> str | None:
    """Warn when an assumed feature pushes a user dimension out of tolerance."""
    if not isinstance(spec, dict) or _source_of(spec, name) != "user":
        return None
    features = spec.get("assumed_features")
    if not isinstance(features, list):
        features = spec.get("assumed")
    if not isinstance(features, list) or abs(actual - value) <= tol + 1e-9:
        return None
    added = 0.0
    labels = []
    for item in features:
        if not isinstance(item, dict):
            continue
        axis = str(item.get("axis") or "").lower()
        if axis != name:
            continue
        try:
            adds = float(item.get("adds_mm"))
        except (TypeError, ValueError):
            continue
        added += adds
        labels.append(str(item.get("name") or item.get("feature") or "feature"))
    if not labels:
        return None
    if abs(actual - (value + added)) > max(float(tol), 0.3) + 1e-9:
        return None
    if actual <= value + tol + 1e-9:
        return None
    return (
        f"{name} {actual:.1f} > user {value:.1f}; assumed {', '.join(labels)} adds {added:.1f}. "
        "Put the hub within the face width."
    )


def _collect(spec, dims, tolerance: float) -> _Checks:
    raw = load_spec(spec) if spec else {}
    axis = raw.get("knuckle_axis") or raw.get("axis") or "x"
    default_tol = float(raw.get("tolerance", tolerance))
    if default_tol < 0:
        raise ValueError("spec tolerance must be >= 0")
    found: dict[str, tuple[float, float]] = {}
    nested = raw.get("dims") if isinstance(raw.get("dims"), dict) else {}
    for name in _NAMES:
        item = raw.get(name, nested.get(name) if isinstance(nested, dict) else None)
        if item is None:
            continue
        value, tol = _value_tol(name, item, default_tol)
        found[name] = (value, tol)
    if isinstance(dims, str):
        dims = [dims]
    for item in dims or []:
        name, value, tol = parse_dim(item)
        if tol is None:
            tol = 0.0 if name in _COUNTS else default_tol
        found[name] = (value, tol)
    checks = _Checks((name, found[name][0], found[name][1]) for name in sorted(found))
    checks.axis = str(axis)
    checks.raw = raw if isinstance(raw, dict) else {}
    return checks


def _value_tol(name: str, item, default_tol: float) -> tuple[float, float]:
    if isinstance(item, dict):
        if "value" not in item:
            raise ValueError(f"spec {name} needs value")
        value = float(item["value"])
        tol = float(item.get("tol", 0.0 if name in _COUNTS else default_tol))
    else:
        value = float(item)
        tol = 0.0 if name in _COUNTS else default_tol
    if tol < 0:
        raise ValueError(f"spec {name} tolerance must be >= 0")
    return value, tol


def _holes_of(spec) -> list | None:
    if not spec:
        return None
    raw = load_spec(spec)
    holes = raw.get("holes")
    if not holes:
        return None
    if not isinstance(holes, list):
        raise ValueError("spec holes must be a list of {x, y, diameter}")
    return holes


_TEMPLATE_CHECKS = ("x", "y", "z", "shells", "knuckles", "hole_count")
_VERSION_STEM = re.compile(r"^(?P<prefix>.+)_v\d+$")
SPEC_NUDGE = (
    "No spec.json in the working directory. Write the user's bbox and key features "
    "to spec.json before photo_part_validate."
)


def find_template_spec(mesh_path) -> dict | None:
    """Spec checks a template wrote beside this mesh, or beside its unversioned name."""
    path = Path(mesh_path).expanduser()
    if path.exists():
        path = path.resolve()
    stems = [path.stem]
    match = _VERSION_STEM.match(path.stem)
    if match:
        stems.append(match.group("prefix"))
    candidates = []
    for stem in stems:
        candidates.append(path.parent / f"{stem}.template.json")
        candidates.append(path.parent / f"{stem}.stl.template.json")
    if match:
        try:
            candidates.extend(sorted(path.parent.glob(f"{match.group('prefix')}_v*.stl.template.json")))
        except OSError:
            pass
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        loaded = _read_object(candidate)
        if loaded is None:
            continue
        checks = loaded.get("spec_checks")
        if isinstance(checks, dict):
            return checks
    return None


def template_omissions(mesh_path, spec, dims) -> list[str]:
    """Failures for checks the template emitted that the user spec dropped."""
    checks = find_template_spec(mesh_path)
    if not checks:
        return []
    present = _present_names(spec, dims)
    missing = []
    for name in _TEMPLATE_CHECKS:
        if name not in checks or name in present:
            continue
        missing.append(
            f"spec dropped template check {name} (template expected {checks[name]}). "
            "Do not remove a check the template emitted."
        )
    return missing


def note_missing_spec(report: dict, *dirs) -> dict:
    """Warn when none of ``dirs`` contains ``spec.json``. Does not fail the tool."""
    for raw in dirs:
        if raw is None or raw == "":
            continue
        if (Path(raw).expanduser() / "spec.json").is_file():
            return report
    report["spec_warning"] = SPEC_NUDGE
    step = str(report.get("next_step") or "")
    if SPEC_NUDGE not in step:
        report["next_step"] = f"{SPEC_NUDGE} {step}".strip()
    return report


def _present_names(spec, dims) -> set[str]:
    names: set[str] = set()
    raw = load_spec(spec) if spec else {}
    nested = raw.get("dims") if isinstance(raw.get("dims"), dict) else {}
    for name in _NAMES:
        if raw.get(name) is not None or (isinstance(nested, dict) and nested.get(name) is not None):
            names.add(name)
    if isinstance(dims, str):
        dims = [dims]
    for item in dims or []:
        name, _value, _tol = parse_dim(item)
        names.add(name)
    return names


def _read_object(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    if not isinstance(loaded, dict):
        return None
    return loaded
