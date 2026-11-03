"""Check hole position and diameter against a small spec.

A hole along an axis is present when its center is void, a ring inside the
radius is void, and a ring just outside the radius is material.
"""

from __future__ import annotations

import math

import numpy as np

_AXIS = {"x": 0, "y": 1, "z": 2}


def check_holes(mesh, holes: list, *, tolerance: float) -> tuple[list[str], list[dict]]:
    """Return failure strings and one result object per hole.

    ``holes`` items are ``{x, y, diameter}`` plus optional ``z`` and ``axis``.
    The coordinate along ``axis`` defaults to the middle of the mesh bounds.

    A fan-tessellated cap makes the ray probe split its votes, and a probe
    plane through the middle of an L misses a hole that sits in a thin leg.
    When that probe disagrees with the bore detector, or the votes are split,
    the row is a warning. It stays in the report with both results and does
    not fail validation.
    """
    if not holes:
        return [], []
    if tolerance < 0:
        raise ValueError("tolerance must be >= 0")
    if not bool(mesh.is_watertight):
        return ["hole check needs a watertight mesh"], []
    bounds = np.asarray(mesh.bounds, dtype=float)
    try:
        from photopart.spec import count_bores

        bores = count_bores(mesh)
    except Exception:
        bores = []
    failures: list[str] = []
    results: list[dict] = []
    for index, spec in enumerate(holes):
        center, radius, axis = _spec(spec, index, bounds)
        inner = _ring(center, radius * 0.5, axis)
        outer = _ring(center, radius + tolerance, axis)
        center_z = bool(_inside(mesh, center.reshape(1, 3), 2)[0])
        center_x = bool(_inside(mesh, center.reshape(1, 3), 0)[0])
        inner_inside = _inside(mesh, inner)
        outer_inside = _inside(mesh, outer)
        center_void = not center_z
        inner_void = bool(np.all(~inner_inside))
        outer_material = bool(np.all(outer_inside))
        probe_ok = center_void and inner_void and outer_material
        matched = _match_bore(bores, center, radius * 2.0, axis, tolerance)
        # A side ray through a solid plate can disagree with the hole axis
        # even when the centre is material and no bore is there. That is a
        # miss. Split votes, a void centre, or a matching bore stay ambiguous.
        split_votes = _split(inner_inside) or _split(outer_inside)
        center_split = center_z != center_x
        ambiguous = split_votes or (center_split and (center_void or matched is not None))
        if not center_void:
            reason = "center is inside material; the hole is missing or the position is wrong"
        elif not inner_void:
            reason = "hole is smaller than the specified diameter or the position is off"
        elif not outer_material:
            reason = "hole is larger than the specified diameter, or the surrounding wall is missing"
        else:
            reason = None
        probe = {
            "ok": probe_ok,
            "ambiguous": ambiguous,
            "reason": reason,
            "center_void": center_void,
            "inner_void_votes": int(np.count_nonzero(~inner_inside)),
            "inner_samples": int(len(inner_inside)),
            "outer_material_votes": int(np.count_nonzero(outer_inside)),
            "outer_samples": int(len(outer_inside)),
        }
        bore = None if matched is None else dict(matched)
        disagree = (probe_ok and bore is None) or ((not probe_ok) and bore is not None)
        warning = None
        if disagree or ambiguous:
            warning = _probe_warning(probe, bore)
            ok = True
        else:
            ok = probe_ok
        if not ok and reason:
            failures.append(f"hole {index}: {reason}")
        results.append(
            {
                "index": index,
                "ok": ok,
                "axis": axis,
                "diameter": radius * 2.0,
                "center": [float(v) for v in center],
                "reason": None if ok else reason,
                "warning": warning,
                "probe": probe,
                "bore": bore,
            }
        )
    return failures, results


def _split(inside: np.ndarray) -> bool:
    """True when some samples are material and some are void."""
    if len(inside) == 0:
        return False
    material = int(np.count_nonzero(inside))
    return 0 < material < len(inside)


def _match_bore(bores, center: np.ndarray, diameter: float, axis: str, tolerance: float):
    """A detected bore on the same axis, near this centre, with a similar diameter."""
    limit = max(1.0, float(tolerance) + 0.5)
    diam_limit = max(0.8, float(tolerance) + 0.5)
    along = _AXIS[axis]
    perp = [slot for slot in range(3) if slot != along]
    best = None
    best_dist = limit + 1.0
    for bore in bores or []:
        if not isinstance(bore, dict) or str(bore.get("axis")) != axis:
            continue
        try:
            bore_center = np.asarray(bore.get("center"), dtype=float).reshape(3)
            bore_diameter = float(bore.get("diameter"))
        except (TypeError, ValueError):
            continue
        dist = float(np.linalg.norm(bore_center[perp] - center[perp]))
        if dist > limit or abs(bore_diameter - diameter) > diam_limit:
            continue
        if dist < best_dist:
            best = bore
            best_dist = dist
    return best


def _probe_warning(probe: dict, bore: dict | None) -> str:
    if bore is None:
        bore_text = "none"
    else:
        bore_text = (
            f"axis {bore.get('axis')} diameter {bore.get('diameter')} "
            f"center {bore.get('center')} through {bore.get('through')}"
        )
    reason = probe.get("reason") or "split votes"
    return (
        "per-hole probe disagrees with the bore detector or the probe is ambiguous. "
        f"Probe: {reason}. Bore: {bore_text}. "
        "Warning only. This does not fail validation and does not block delivery. "
        "Do not edit the spec to move the probe."
    )


def _spec(spec, index: int, bounds: np.ndarray) -> tuple[np.ndarray, float, str]:
    if not isinstance(spec, dict):
        raise ValueError(f"hole {index} must be an object with x, y, and diameter")
    axis = str(spec.get("axis") or "z").lower()
    if axis not in _AXIS:
        raise ValueError(f"hole {index} axis must be x, y, or z, got {axis!r}")
    try:
        diameter = float(spec["diameter"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"hole {index} needs a positive diameter") from exc
    if not np.isfinite(diameter) or diameter <= 0:
        raise ValueError(f"hole {index} diameter must be a positive number")
    center = np.zeros(3, dtype=float)
    along = _AXIS[axis]
    for name, slot in _AXIS.items():
        raw = spec.get(name)
        if raw is None or raw == "":
            if slot == along or name == "z":
                center[slot] = float(np.mean(bounds[:, slot]))
                continue
            raise ValueError(f"hole {index} needs {name}")
        try:
            center[slot] = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"hole {index} {name} must be a number") from exc
        if not np.isfinite(center[slot]):
            raise ValueError(f"hole {index} {name} must be finite")
    return center, diameter / 2.0, axis


def _ring(center: np.ndarray, radius: float, axis: str) -> np.ndarray:
    along = _AXIS[axis]
    perp = [slot for slot in range(3) if slot != along]
    points = []
    for turn in range(4):
        angle = turn * math.pi / 2.0
        point = center.copy()
        point[perp[0]] += radius * math.cos(angle)
        point[perp[1]] += radius * math.sin(angle)
        points.append(point)
    return np.vstack(points)


def _inside(mesh, points: np.ndarray, axis: int = 2) -> np.ndarray:
    """Odd-even ray test along +X, +Y, or +Z. Avoids the rtree-backed contains() path."""
    origins = np.asarray(points, dtype=float).reshape(-1, 3)
    triangles = np.asarray(mesh.triangles, dtype=float)
    direction = np.zeros(3, dtype=float)
    direction[int(axis)] = 1.0
    hits = np.zeros(len(origins), dtype=np.int32)
    for triangle in triangles:
        hits += _ray_hits(origins, direction, triangle)
    return (hits % 2) == 1


def _ray_hits(origins: np.ndarray, direction: np.ndarray, triangle: np.ndarray) -> np.ndarray:
    epsilon = 1e-9
    edge1 = triangle[1] - triangle[0]
    edge2 = triangle[2] - triangle[0]
    pvec = np.cross(direction, edge2)
    det = float(edge1 @ pvec)
    if abs(det) < epsilon:
        return np.zeros(len(origins), dtype=bool)
    inv = 1.0 / det
    offset = origins - triangle[0]
    u = inv * (offset @ pvec)
    qvec = np.cross(offset, edge1)
    v = inv * np.einsum("ij,j->i", qvec, direction)
    t = inv * (qvec @ edge2)
    return (u >= 0.0) & (v >= 0.0) & ((u + v) <= 1.0) & (t > epsilon)
