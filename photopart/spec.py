"""Compare a mesh to the dimensions the user asked for.

``spec.json`` holds bbox sizes, shell count, knuckle count, and hole count.
``--dim name=value±tol`` is the same check on one line. Lengths default to
the validate tolerance (0.3 mm). Counts default to an exact match.
"""

from __future__ import annotations

import json
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
        if name in _AXES:
            actual = float(extents[_AXES[name]])
        elif name == "shells":
            actual = float(len(mesh.split(only_watertight=False)))
        elif name == "knuckles":
            actual = float(count_knuckles(mesh, axis=str(checks.axis or "x")))
        elif name == "hole_count":
            bores = count_bores(mesh)
            info = genus_report(mesh)
            actual = float(len(bores))
            genus = info.get("genus")
            extra = {
                "bores": bores,
                "genus": genus,
                "genus_reliable": bool(info.get("reliable")),
                "note": GENUS_NOTE,
            }
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
        if undetected:
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
    from photopart.holes import _inside

    name = (axis or "x").lower()
    if name not in _AXES:
        raise ValueError("knuckle_axis must be x, y, or z")
    along = _AXES[name]
    bounds = np.asarray(mesh.bounds, dtype=float)
    span = float(bounds[1, along] - bounds[0, along])
    if span <= 0:
        return 0
    others = [slot for slot in range(3) if slot != along]
    cross = min(float(bounds[1, slot] - bounds[0, slot]) for slot in others)
    if cross <= 0:
        return 0
    outer = 0.48 * cross
    if outer <= 0.55:
        radii = np.array([max(0.2, outer * 0.6)], dtype=float)
    else:
        radii = np.linspace(0.5, outer, 6)
    center = bounds.mean(axis=0)
    stations = int(np.clip(round(span / 0.15), 80, 360))
    angles = 8
    pad = min(0.15, 0.005 * span)
    coords = np.linspace(bounds[0, along] + pad, bounds[1, along] - pad, stations)
    turns = np.arange(angles, dtype=float) * (2.0 * np.pi / angles)
    n_radii = len(radii)
    points = np.empty((n_radii, stations, angles, 3), dtype=float)
    points[...] = center
    points[..., along] = coords[None, :, None]
    points[..., others[0]] = center[others[0]] + radii[:, None, None] * np.cos(turns)[None, None, :]
    points[..., others[1]] = center[others[1]] + radii[:, None, None] * np.sin(turns)[None, None, :]
    inside = _inside(mesh, points.reshape(-1, 3)).reshape(n_radii, stations, angles)
    occupied = inside.any(axis=2)
    best = 0
    for row in occupied:
        runs, fraction = _occupied_runs(row)
        if runs == 1 and fraction >= 0.97:
            continue
        if runs == 0:
            continue
        if runs > best:
            best = runs
    return best


def _occupied_runs(flags) -> tuple[int, float]:
    """Runs of at least three inside samples, and the occupied fraction."""
    row = np.asarray(flags, dtype=bool)
    if len(row) == 0:
        return 0, 0.0
    padded = np.concatenate(([False], row, [False]))
    changes = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(changes == 1)
    ends = np.flatnonzero(changes == -1)
    runs = int(np.count_nonzero((ends - starts) >= 3))
    fraction = float(np.count_nonzero(row)) / float(len(row))
    return runs, fraction


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


def count_bores(mesh) -> list[dict]:
    """Circular bores from per-leg slices on all three axes, plus ray casting.

    Whole-part stations at 25, 50, and 75 percent stay, and each planar leg
    is also sliced at 30, 50, and 70 percent of its own thickness. An interior
    ring whose circularity (4πA/P²) is above 0.85 is a bore section. Sections
    whose centres agree within 0.6 mm are the same bore. A sampled station
    between two sightings with no ring splits them, so two collinear knuckle
    bores stay two bores.

    Through-holes are also found by casting a grid of rays along each axis.
    A void column enclosed by material is a bore. A ray that never hits is
    through; a ray that hits the floor is blind. Ray bores that share an axis
    and a perpendicular centre with a section bore are not added again, so a
    pair of collinear knuckle bores is not collapsed into one tunnel.

    trimesh's ``section_multiplane`` needs scipy, which this plugin does not
    install. The slices are computed with numpy and shapely.
    """
    if mesh is None or len(getattr(mesh, "faces", [])) == 0:
        return []
    section_bores = _bores_from_sections(mesh)
    ray_bores = _bores_from_rays(mesh)
    merged = _merge_bores(section_bores, ray_bores)
    return _mark_through(mesh, merged)


def _bores_from_sections(mesh) -> list[dict]:
    bounds = np.asarray(mesh.bounds, dtype=float)
    extents = np.asarray(mesh.extents, dtype=float)
    planes = _unique_planes(_section_planes(mesh, bounds, extents))
    by_axis: dict[int, list[tuple[float, list[dict]]]] = {0: [], 1: [], 2: []}
    for axis, position in planes:
        origin = np.array(bounds[0], dtype=float)
        origin[axis] = float(position)
        normal = np.zeros(3, dtype=float)
        normal[axis] = 1.0
        rings = _circular_interiors(mesh, origin, normal, axis)
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
    return {
        "axis": axis_name,
        "center": [round(float(value), 4) for value in centers.mean(axis=0)],
        "diameter": round(float(np.median(diameters)), 4),
        "through": False,
    }


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
    from photopart.holes import _ray_hits

    direction = np.zeros(3, dtype=float)
    direction[axis] = 1.0
    triangles = np.asarray(mesh.triangles, dtype=float)
    hits = np.zeros(len(origins), dtype=np.int32)
    for triangle in triangles:
        hits += _ray_hits(origins, direction, triangle).astype(np.int32)
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


def _circular_interiors(mesh, origin: np.ndarray, normal: np.ndarray, axis: int) -> list[dict]:
    from shapely.geometry import Polygon

    polygons = _section_polygons(mesh, origin, normal)
    holes = []
    for outer in polygons:
        for interior in outer.interiors:
            holes.append(Polygon(interior))
    if not holes:
        # polygonize sometimes emits the hole as its own polygon instead of a ring.
        holes = _contained_polygons(polygons)
    rings = []
    for hole in holes:
        circ = _circularity(hole)
        if circ <= 0.85:
            continue
        center3 = _polygon_center_3d(hole, origin, normal)
        perp = [float(center3[i]) for i in range(3) if i != axis]
        rings.append(
            {
                "center": [round(float(value), 4) for value in center3],
                "perp": perp,
                "diameter": round(_diameter_of(hole), 4),
                "circularity": round(circ, 4),
            }
        )
    return _unique_rings(rings)


def _unique_rings(rings: list[dict]) -> list[dict]:
    kept: list[dict] = []
    for ring in rings:
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
    # Snap to 0.05 mm so tessellated loops close. trimesh's own section
    # path needs scipy, which is not a plugin dependency.
    grid = 0.05
    lines = []
    for start, end in segments:
        a = start - origin
        b = end - origin
        p = (round(float(a @ u) / grid) * grid, round(float(a @ v) / grid) * grid)
        q = (round(float(b @ u) / grid) * grid, round(float(b @ v) / grid) * grid)
        if (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 < 1e-12:
            continue
        lines.append(LineString((p, q)))
    if not lines:
        return []
    try:
        merged = unary_union(lines)
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
