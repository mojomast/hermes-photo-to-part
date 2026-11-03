"""Local printability checks. No slicer and no network.

Wall thickness is the nearest inward ray hit. Overhang is face area whose
normal points down past ``overhang_deg`` from vertical, excluding the bed.
Bed contact is downward area on the lowest Z. The gap is the nearest distance
between separate shells.
"""

from __future__ import annotations

import math
import warnings

import numpy as np
import trimesh


def check_printability(
    mesh: trimesh.Trimesh,
    *,
    min_wall_mm: float = 0.8,
    overhang_deg: float = 45.0,
    max_overhang_fraction: float = 0.35,
    min_bed_mm2: float = 1.0,
    min_gap_mm: float = 0.3,
    samples: int = 48,
    face_tags: dict | None = None,
) -> dict:
    """Return measurements and warnings. Warnings do not change ``ok`` by themselves.

    Wall thickness is an SDF-lite median of 7 rays in a 60° cone, converted
    from path length to distance along the inward normal. A raw 30° path
    through a 0.70 mm plate is about 0.81 mm and would hide the warning.
    Thread, knurl, and tooth faces are not ray sources (they stay valid
    targets). The warning uses the 5th percentile and the thin-area fraction.
    ``min_wall_raw_mm`` is the old single-ray minimum, including those crests.
    """
    warnings: list[str] = []
    info: list[str] = []
    raw = _min_wall(mesh, samples)
    auto_regions: list[dict] = []
    # A sidecar with a cylinder region wins. Indices alone do not describe the
    # collar, so a periodic crest is detected and excluded as well.
    stored = face_tags if face_tags is not None else _stored_tags(mesh)
    if stored is None:
        try:
            auto_regions = detect_periodic_regions(mesh)
        except Exception:
            auto_regions = []
        excluded = _faces_in_regions(mesh, auto_regions) if auto_regions else set()
        tags_source = "detected" if auto_regions else "none"
    else:
        excluded = _excluded_sources(mesh, stored)
        if not _regions_of(mesh, stored):
            try:
                auto_regions = detect_periodic_regions(mesh)
            except Exception:
                auto_regions = []
            if auto_regions:
                excluded |= _faces_in_regions(mesh, auto_regions)
        tags_source = str(stored.get("tags_source") or "sidecar") if isinstance(stored, dict) else "sidecar"
    p5, thin_fraction = _sdf_wall(mesh, samples, min_wall_mm, excluded)
    wall = p5 if p5 is not None else raw
    overhang_area, overhang_fraction, bed_area = _faces(mesh, overhang_deg)
    gap = _min_gap(mesh, samples)
    if p5 is not None and p5 < min_wall_mm:
        warnings.append(
            f"min wall {p5:.3f} mm is under {min_wall_mm:g} mm. "
            "Thicken the wall or raise min_wall_mm."
        )
    elif thin_fraction is not None and thin_fraction > 0.01:
        warnings.append(
            f"thin area fraction {thin_fraction:.3f} is over 1% under {min_wall_mm:g} mm. "
            "Thicken the wall or raise min_wall_mm."
        )
    if overhang_fraction is not None and overhang_fraction > max_overhang_fraction:
        warnings.append(
            f"overhang fraction {overhang_fraction:.2f} is past {overhang_deg:g} deg "
            f"(limit {max_overhang_fraction:g}). Add support or split the part."
        )
    if bed_area is not None and bed_area < min_bed_mm2:
        warnings.append(
            f"bed contact {bed_area:.2f} mm^2 is under {min_bed_mm2:g} mm^2. "
            "Lay a face on the bed."
        )
    if gap is not None and gap < min_gap_mm:
        warnings.append(
            f"gap between bodies {gap:.3f} mm is under {min_gap_mm:g} mm per side. "
            "Open the clearance before a print-in-place part."
        )
    auto_feature = _auto_feature_label(auto_regions)
    wall_warned = any("wall" in item or "thin area" in item for item in warnings)
    if auto_feature and raw is not None and raw < min_wall_mm and not wall_warned:
        info.append(f"auto_feature: {auto_feature}; min_wall_raw_mm={raw:.3f}")
    return {
        "min_wall_mm": None if wall is None else round(wall, 4),
        "min_wall_p5_mm": None if p5 is None else round(p5, 4),
        "min_wall_raw_mm": None if raw is None else round(raw, 4),
        "thin_area_fraction": None if thin_fraction is None else round(thin_fraction, 4),
        "overhang_area_mm2": None if overhang_area is None else round(overhang_area, 3),
        "overhang_fraction": None if overhang_fraction is None else round(overhang_fraction, 4),
        "bed_contact_area_mm2": None if bed_area is None else round(bed_area, 3),
        "min_gap_mm": None if gap is None else round(gap, 4),
        "thresholds": {
            "min_wall_mm": min_wall_mm,
            "overhang_deg": overhang_deg,
            "max_overhang_fraction": max_overhang_fraction,
            "min_bed_mm2": min_bed_mm2,
            "min_gap_mm": min_gap_mm,
        },
        "warnings": warnings,
        "info": info,
        "auto_feature": auto_feature,
        "regions": auto_regions,
        "tags_source": tags_source,
    }


def _auto_feature_label(regions: list[dict]) -> str | None:
    for region in regions:
        if not isinstance(region, dict):
            continue
        if region.get("kind") == "thread" and region.get("pitch"):
            return f"thread pitch={float(region['pitch']):.2f}"
        if region.get("kind") == "knurl":
            periods = region.get("periods")
            if periods:
                return f"knurl periods={int(periods)}"
            return "knurl"
    return None


def _stored_tags(mesh: trimesh.Trimesh) -> dict | None:
    """Face tags or feature regions already on the mesh, or None."""
    meta = getattr(mesh, "metadata", None)
    if not isinstance(meta, dict):
        return None
    tags = meta.get("face_tags") if isinstance(meta.get("face_tags"), dict) else None
    regions = meta.get("feature_regions") if isinstance(meta.get("feature_regions"), list) else None
    if tags is None and not regions:
        return None
    resolved = dict(tags) if tags else {}
    if regions and not resolved.get("regions"):
        resolved["regions"] = list(regions)
    has_indices = any(resolved.get(key) for key in ("thread", "knurl", "teeth"))
    if not has_indices and not resolved.get("regions"):
        return None
    return resolved


def _excluded_sources(mesh: trimesh.Trimesh, face_tags: dict | None) -> set[int]:
    """Skip thread, knurl, and tooth faces. Regions are re-resolved; indices are the fallback."""
    regions = _regions_of(mesh, face_tags)
    if regions:
        geometric = _faces_in_regions(mesh, regions)
        if geometric:
            return geometric
    return _index_sources(mesh, face_tags)


def _regions_of(mesh: trimesh.Trimesh, face_tags: dict | None) -> list:
    if isinstance(face_tags, dict) and isinstance(face_tags.get("regions"), list) and face_tags["regions"]:
        return list(face_tags["regions"])
    meta = getattr(mesh, "metadata", None)
    if isinstance(meta, dict) and isinstance(meta.get("feature_regions"), list):
        return list(meta["feature_regions"])
    return []


def _index_sources(mesh: trimesh.Trimesh, face_tags: dict | None) -> set[int]:
    tags = face_tags
    if tags is None:
        meta = getattr(mesh, "metadata", None)
        if isinstance(meta, dict):
            tags = meta.get("face_tags")
    if not isinstance(tags, dict):
        return set()
    limit = len(mesh.faces)
    found: set[int] = set()
    for key in ("thread", "knurl", "teeth"):
        for item in tags.get(key) or []:
            try:
                slot = int(item)
            except (TypeError, ValueError):
                continue
            if 0 <= slot < limit:
                found.add(slot)
    return found


def _faces_in_regions(mesh: trimesh.Trimesh, regions: list, eps: float = 0.15) -> set[int]:
    """Faces whose centroid sits in a feature cylinder and whose normal is radial.

    A thread also drops the collar around an external crest and the cylindrical
    wall around an internal crest. Those faces are the flange washer and the
    cap skirt, not a separate thin wall. A wide thin disk past that collar
    stays in the sample.
    """
    if len(mesh.faces) == 0 or not regions:
        return set()
    centers = np.asarray(mesh.triangles_center, dtype=float)
    normals = np.asarray(mesh.face_normals, dtype=float)
    found: set[int] = set()
    for region in regions:
        if not isinstance(region, dict):
            continue
        axis = np.asarray(region.get("axis") or [0.0, 0.0, 1.0], dtype=float)
        norm = float(np.linalg.norm(axis))
        if norm < 1e-8:
            continue
        axis = axis / norm
        origin = np.asarray(region.get("origin") or [0.0, 0.0, 0.0], dtype=float)
        relative = centers - origin
        height = relative @ axis
        radial_vec = relative - height[:, None] * axis
        radius = np.linalg.norm(radial_vec, axis=1)
        radial_dir = np.zeros_like(radial_vec)
        usable = radius > 1e-6
        radial_dir[usable] = radial_vec[usable] / radius[usable, None]
        radial_n = np.abs(np.einsum("ij,ij->i", normals, radial_dir))
        try:
            r_min = float(region.get("r_min"))
            r_max = float(region.get("r_max"))
            z0 = float(region.get("z0"))
            z1 = float(region.get("z1"))
        except (TypeError, ValueError):
            continue
        if region.get("kind") == "thread":
            mask = _thread_collar_mask(mesh, origin, axis, radius, height, r_min, r_max, z0, z1)
        else:
            mask = (
                (radius >= r_min - eps)
                & (radius <= r_max + eps)
                & (height >= z0 - eps)
                & (height <= z1 + eps)
                & (radial_n > 0.3)
            )
        found.update(int(slot) for slot in np.flatnonzero(mask))
    return found


def _thread_collar_mask(mesh, origin, axis, radius, height, r_min, r_max, z0, z1) -> np.ndarray:
    """External washer next to a crest, or the wall around an internal thread."""
    internal = _thread_is_internal(mesh, origin, axis, z0, z1, r_min)
    if internal:
        outer = float(np.nanmax(radius)) if len(radius) else r_max
        reach = max(2.5, outer - r_max)
        return (radius >= r_min - 0.4) & (radius <= r_max + reach) & (height >= z0 - 2.0) & (height <= z1 + 2.0)
    return (radius >= r_min - 0.15) & (radius <= r_max + 2.2) & (height >= z0 - 1.5) & (height <= z1 + 1.5)


def _thread_is_internal(mesh, origin, axis, z0, z1, r_min) -> bool:
    """True when the thread axis is hollow, as in a cap. A screw core is solid."""
    mid = np.asarray(origin, dtype=float) + np.asarray(axis, dtype=float) * ((float(z0) + float(z1)) / 2.0)
    try:
        inside = mesh.contains(mid.reshape(1, 3))
        if len(inside):
            return not bool(inside[0])
    except Exception:
        pass
    extents = np.asarray(getattr(mesh, "extents", [0.0, 0.0, 0.0]), dtype=float)
    max_r = 0.5 * float(np.max(extents)) if len(extents) else 0.0
    if max_r <= 1e-6:
        return False
    return (float(r_min) / max_r) > 0.55


def _sdf_wall(
    mesh: trimesh.Trimesh,
    samples: int,
    min_wall_mm: float,
    excluded: set[int],
) -> tuple[float | None, float | None]:
    """Area-weighted p5 of per-face median thickness, and the thin-area fraction.

    Seven rays leave each sampled face: one along the inward normal and six
    on a 60° cone (30° off the normal). A hit whose normal faces the same way
    as the source is ignored (Shapira, Gal, and Cohen-Or, 2008).
    """
    faces = len(mesh.faces)
    if faces == 0:
        return None, None
    normals = np.asarray(mesh.face_normals, dtype=float)
    centers = np.asarray(mesh.triangles_center, dtype=float)
    areas = np.asarray(mesh.area_faces, dtype=float)
    allowed = [slot for slot in range(faces) if slot not in excluded]
    if not allowed:
        return None, None
    step = max(1, len(allowed) // max(samples, 1))
    index = allowed[::step][:samples]
    index_arr = np.asarray(index, dtype=int)
    inward = -normals[index_arr]
    norms = np.linalg.norm(inward, axis=1)
    valid = norms > 1e-8
    if not np.any(valid):
        return None, None
    index_arr = index_arr[valid]
    inward = inward[valid] / norms[valid][:, None]
    origins = centers[index_arr] + inward * 1e-3
    directions = _cone_directions(inward)
    ray_origins = np.repeat(origins, directions.shape[1], axis=0)
    ray_dirs = directions.reshape(-1, 3)
    face_of_ray = np.repeat(index_arr, directions.shape[1])
    try:
        locations, ray_index, tri_index = mesh.ray.intersects_location(ray_origins, ray_dirs)
    except Exception:
        return None, None
    if len(locations) == 0:
        return None, None
    distance = np.linalg.norm(locations - ray_origins[ray_index], axis=1)
    hit_normals = normals[tri_index]
    source_normals = normals[face_of_ray[ray_index]]
    same_way = np.einsum("ij,ij->i", hit_normals, source_normals) > 0.0
    # The ray starts 0.001 mm inside the face. Path length times the cosine
    # of the angle from the inward normal is the wall thickness, plus that
    # offset. Cone rays otherwise read a 0.70 mm plate as 0.807 mm.
    inward = -source_normals
    cosine = np.einsum("ij,ij->i", ray_dirs[ray_index], inward)
    thickness = distance * np.clip(cosine, 0.0, 1.0) + 1e-3
    keep = (distance > 1e-3) & ~same_way & (cosine >= 0.5)
    per_face: dict[int, list[float]] = {int(slot): [] for slot in index_arr.tolist()}
    order = np.argsort(distance)
    seen_ray: set[int] = set()
    for slot in order:
        if not keep[slot]:
            continue
        ray = int(ray_index[slot])
        if ray in seen_ray:
            continue
        seen_ray.add(ray)
        per_face[int(face_of_ray[ray])].append(float(thickness[slot]))
    medians = []
    weights = []
    for slot, lengths in per_face.items():
        if not lengths:
            continue
        medians.append(float(np.median(lengths)))
        weights.append(float(areas[slot]))
    if not medians:
        return None, None
    medians_arr = np.asarray(medians, dtype=float)
    weights_arr = np.asarray(weights, dtype=float)
    total = float(weights_arr.sum())
    if total <= 0:
        return None, None
    order = np.argsort(medians_arr)
    cumulative = np.cumsum(weights_arr[order]) / total
    p5_index = int(np.searchsorted(cumulative, 0.05, side="left"))
    p5_index = min(p5_index, len(order) - 1)
    p5 = float(medians_arr[order[p5_index]])
    thin = float(weights_arr[medians_arr < min_wall_mm].sum() / total)
    return p5, thin


def _cone_directions(inward: np.ndarray) -> np.ndarray:
    """Seven unit directions per face: inward, plus a 60° cone. Shape (n, 7, 3)."""
    helper = np.tile(np.array([1.0, 0.0, 0.0]), (len(inward), 1))
    helper[np.abs(inward[:, 0]) > 0.9] = np.array([0.0, 1.0, 0.0])
    tangent = np.cross(inward, helper)
    tangent /= np.linalg.norm(tangent, axis=1)[:, None]
    bitangent = np.cross(inward, tangent)
    cos_a = math.cos(math.radians(30.0))
    sin_a = math.sin(math.radians(30.0))
    directions = [inward]
    for step in range(6):
        angle = step * math.pi / 3.0
        offset = math.cos(angle) * tangent + math.sin(angle) * bitangent
        directions.append(cos_a * inward + sin_a * offset)
    stacked = np.stack(directions, axis=1)
    stacked /= np.linalg.norm(stacked, axis=2)[:, :, None]
    return stacked


def _min_wall(mesh: trimesh.Trimesh, samples: int) -> float | None:
    faces = len(mesh.faces)
    if faces == 0:
        return None
    normals = np.asarray(mesh.face_normals, dtype=float)
    centers = np.asarray(mesh.triangles_center, dtype=float)
    step = max(1, faces // samples)
    index = np.arange(0, faces, step)[:samples]
    origins = centers[index] - normals[index] * 1e-3
    directions = -normals[index]
    try:
        locations, ray_index, _tri = mesh.ray.intersects_location(origins, directions)
    except Exception:
        return None
    if len(locations) == 0:
        return None
    distance = np.linalg.norm(locations - origins[ray_index], axis=1)
    nearest: dict[int, float] = {}
    for slot, length in zip(ray_index, distance):
        if length <= 1e-3:
            continue
        key = int(slot)
        nearest[key] = min(nearest.get(key, 1e9), float(length))
    if not nearest:
        return None
    return float(min(nearest.values()))


def _faces(mesh: trimesh.Trimesh, overhang_deg: float) -> tuple[float | None, float | None, float | None]:
    if len(mesh.faces) == 0:
        return None, None, None
    normals = np.asarray(mesh.face_normals, dtype=float)
    areas = np.asarray(mesh.area_faces, dtype=float)
    centers = np.asarray(mesh.triangles_center, dtype=float)
    total = float(areas.sum())
    if total <= 0:
        return 0.0, 0.0, 0.0
    downward = normals[:, 2]
    limit = -math.cos(math.radians(overhang_deg))
    zmin = float(np.asarray(mesh.bounds, dtype=float)[0, 2])
    bed = (downward < -0.85) & (centers[:, 2] <= zmin + 0.4)
    overhang = (downward < limit) & ~bed
    return float(areas[overhang].sum()), float(areas[overhang].sum() / total), float(areas[bed].sum())


def _min_gap(mesh: trimesh.Trimesh, samples: int) -> float | None:
    try:
        parts = mesh.split(only_watertight=False)
    except Exception:
        return None
    if len(parts) < 2:
        return None
    gaps = []
    for index, shell in enumerate(parts):
        others = [part for slot, part in enumerate(parts) if slot != index]
        try:
            other = trimesh.util.concatenate(others)
            points = np.asarray(shell.vertices, dtype=float)
            triangles = np.asarray(other.triangles, dtype=float)
        except Exception:
            return None
        if len(points) == 0 or len(triangles) == 0:
            continue
        if len(points) > samples:
            points = points[:: max(1, len(points) // samples)][:samples]
        distance = _distance_to_triangles(points, triangles)
        if distance is None:
            return None
        gaps.append(distance)
    if not gaps:
        return None
    return float(min(gaps))


def _distance_to_triangles(points: np.ndarray, triangles: np.ndarray) -> float | None:
    """Nearest point-to-triangle distance. Numpy only, so scipy is not required."""
    if len(triangles) > 6000:
        triangles = triangles[:: max(1, len(triangles) // 6000)][:6000]
    best = np.inf
    try:
        for point in points:
            repeated = np.repeat(point.reshape(1, 3), len(triangles), axis=0)
            closest = trimesh.triangles.closest_point(triangles, repeated)
            best = min(best, float(np.linalg.norm(closest - point, axis=1).min()))
    except Exception:
        return None
    if not np.isfinite(best):
        return None
    return float(best)


def detect_periodic_regions(mesh: trimesh.Trimesh) -> list[dict]:
    """Find a thread or knurl from radius samples when face tags were lost.

    A thread is a radius that repeats along an axis with a pitch in 0.35–3 mm.
    Crest amplitude is 0.12–2.2 mm so a coarse bottle thread still counts and a
    flat head does not. A knurl repeats around the axis at least 12 times.
    The naked M3 helper crests about 0.16 mm, but an M3 thread unioned with a
    hex head measures under 0.15 mm, so the floor stays 0.12 mm.
    """
    if mesh is None or len(getattr(mesh, "faces", [])) < 16:
        return []
    found: list[dict] = []
    for axis in _axis_order(mesh):
        region = _thread_on_axis(mesh, axis)
        if region is not None:
            found.append(region)
            break
    if found:
        return found
    knurl = _knurl_on_axis(mesh)
    if knurl is not None:
        return [knurl]
    return []


def _axis_order(mesh: trimesh.Trimesh) -> list[int]:
    extents = np.asarray(mesh.extents, dtype=float)
    return [int(slot) for slot in np.argsort(-extents)]


def _sample_axis(mesh: trimesh.Trimesh, axis: int, *, nz: int = 72, nt: int = 24, inset: float = 0.12):
    bounds = np.asarray(mesh.bounds, dtype=float)
    lo = float(bounds[0, axis])
    hi = float(bounds[1, axis])
    span = hi - lo
    if span < 2.0:
        return None
    zs = np.linspace(lo + 0.04 * span, hi - 0.04 * span, nz)
    mid = (bounds[0] + bounds[1]) / 2.0
    eye = np.eye(3)
    origins = []
    directions = []
    for z_value in zs:
        center = mid.copy()
        center[axis] = float(z_value)
        for step in range(nt):
            theta = 2.0 * math.pi * step / nt
            radial = math.cos(theta) * eye[(axis + 1) % 3] + math.sin(theta) * eye[(axis + 2) % 3]
            origins.append(center + inset * radial)
            directions.append(radial)
    origins_arr = np.asarray(origins, dtype=float)
    directions_arr = np.asarray(directions, dtype=float)
    try:
        locations, index, _tri = mesh.ray.intersects_location(
            origins_arr, directions_arr, multiple_hits=False
        )
    except Exception:
        return None
    radius = np.full(len(origins_arr), np.nan)
    if len(index):
        radius[index] = np.linalg.norm(locations - origins_arr[index], axis=1) + inset
    return radius.reshape(len(zs), nt), zs, mid


def _fill_column(column: np.ndarray):
    good = np.flatnonzero(np.isfinite(column))
    if len(good) < max(8, len(column) // 4):
        return None
    return np.interp(np.arange(len(column)), good, column[good])


def _best_period(filled: np.ndarray, dz: float):
    centered = filled - float(np.mean(filled))
    spectrum = np.abs(np.fft.rfft(centered))
    freqs = np.fft.rfftfreq(len(filled), d=dz)
    candidates = []
    for slot, (freq, amplitude) in enumerate(zip(freqs, spectrum)):
        if freq <= 0:
            continue
        period = 1.0 / float(freq)
        if 0.35 <= period <= 3.0:
            candidates.append((float(amplitude), period, slot))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    top = candidates[0]
    second = 0.0
    for amplitude, _period, slot in candidates[1:]:
        if abs(slot - top[2]) > 1:
            second = amplitude
            break
    return top[0], top[1], float(filled.max() - filled.min()), second


def _thread_on_axis(mesh: trimesh.Trimesh, axis: int) -> dict | None:
    sampled = _sample_axis(mesh, axis)
    if sampled is None:
        return None
    grid, zs, mid = sampled
    dz = float(zs[1] - zs[0])
    cleaned = _blank_radius_outliers(grid)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        median = np.nanmedian(cleaned, axis=1)
    runs = _candidate_runs(median)
    best = None
    columns = int(grid.shape[1])
    for begin, end in runs:
        window = cleaned[begin : end + 1]
        votes = []
        strong = []
        for column in range(columns):
            filled = _fill_column(window[:, column])
            if filled is None:
                continue
            result = _best_period(filled, dz)
            if result is None or not (0.12 <= result[2] <= 2.2):
                continue
            votes.append(result)
            if result[0] >= 1.15 * max(result[3], 1e-9):
                strong.append(result)
        if len(votes) < columns * 0.50:
            continue
        pitch = float(np.median([item[1] for item in votes]))
        agree = sum(1 for item in votes if abs(item[1] - pitch) <= max(0.08, 0.18 * pitch))
        helical = _helical_agreement(window, pitch, dz)
        # A real helix with a dominant spectral peak is a thread. A coarse
        # bottle crest has a strong second harmonic, so pitch agreement across
        # columns is enough when the helix test is weak.
        peak_helix = helical and len(strong) >= columns * 0.45 and agree >= len(votes) * 0.6
        agreed = agree >= columns * 0.65
        if not peak_helix and not agreed:
            continue
        span_mm = float(zs[end] - zs[begin])
        # A knuckle barrel repeats along a long flat hinge without a helix.
        # A bottle crest often fails the helix test, but it is not that shape:
        # at least one and a half pitches, on an axis that is not the long
        # direction of a plate, and a crest that is shallow relative to the radius.
        if span_mm < 1.5 * pitch:
            continue
        if not helical:
            cross = min(float(mesh.extents[slot]) for slot in range(3) if slot != axis)
            if cross <= 0 or span_mm > 2.5 * cross:
                continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            radius_typical = float(np.nanmedian(window))
        crest = float(np.median([item[2] for item in votes]))
        if not np.isfinite(radius_typical) or radius_typical <= 0.2 or crest > 0.35 * radius_typical:
            continue
        with np.errstate(all="ignore"):
            r_low = float(np.nanpercentile(window, 5))
            r_high = float(np.nanmax(window))
        if not np.isfinite(r_low) or not np.isfinite(r_high):
            continue
        axis_vec = [0.0, 0.0, 0.0]
        axis_vec[axis] = 1.0
        origin_axis = float(mid[axis])
        region = {
            "kind": "thread",
            "axis": axis_vec,
            "origin": [float(item) for item in mid],
            "r_min": r_low - 0.15,
            "r_max": r_high + 0.15,
            "z0": float(zs[begin]) - 0.3 - origin_axis,
            "z1": float(zs[end]) + 0.3 - origin_axis,
            "pitch": round(pitch, 3),
        }
        span = region["z1"] - region["z0"]
        if best is None or span > best["z1"] - best["z0"]:
            best = region
    return best


def _candidate_runs(median) -> list[tuple[int, int]]:
    """Loose, tight, and anchor-limited runs. The longest real crest wins.

    1.5 mm separates a screw head from the thread. 0.9 mm and a 0.45 mm drift
    from the run's first sample separate a knurl from a bottle crest that sits
    about 1 mm inward. A run that fails the pitch test is ignored.
    """
    found: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for run in (
        *_adjacent_runs(median, jump=1.5),
        *_adjacent_runs(median, jump=0.9),
        *_anchor_runs(median, drift=0.45),
    ):
        if run in seen:
            continue
        seen.add(run)
        found.append(run)
    return found


def _anchor_runs(median, min_len: int = 12, drift: float = 0.45) -> list[tuple[int, int]]:
    """Contiguous stations that stay within ``drift`` of the run's first sample."""
    runs: list[tuple[int, int]] = []
    start = None
    anchor = None
    series = list(median) + [np.nan]
    for index, value in enumerate(series):
        finite = bool(np.isfinite(value))
        drifted = finite and anchor is not None and abs(float(value) - float(anchor)) > drift
        if not finite or drifted:
            if start is not None and index - 1 - start >= min_len:
                runs.append((start, index - 1))
            if drifted:
                start = index
                anchor = float(value)
            else:
                start = None
                anchor = None
            continue
        if start is None:
            start = index
            anchor = float(value)
    return runs


def _blank_radius_outliers(grid: np.ndarray, limit: float = 1.2) -> np.ndarray:
    """Drop samples far from the station median before the pitch FFT.

    A knurl rib or a dome spike next to a thread otherwise splits the run or
    invents a second period. An M3 crest is about 0.16 mm, so 1.2 mm leaves it.
    """
    cleaned = np.array(grid, dtype=float, copy=True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        station = np.nanmedian(cleaned, axis=1)
    for index, med in enumerate(station):
        if not np.isfinite(med):
            continue
        row = cleaned[index]
        far = np.isfinite(row) & (np.abs(row - float(med)) > limit)
        row[far] = np.nan
    return cleaned


def _adjacent_runs(median, min_len: int = 12, jump: float = 1.5) -> list[tuple[int, int]]:
    """Contiguous stations whose radius changes by at most ``jump`` from the neighbour.

    The head-to-thread step on an M3 screw is about 1.9 mm, so 1.5 mm keeps the
    thread and leaves the head out. A first-sample anchor of 0.35 mm splits a
    bottle thread whose median drifts by less than a millimetre.
    """
    runs: list[tuple[int, int]] = []
    start = None
    prev = None
    series = list(median) + [np.nan]
    for index, value in enumerate(series):
        finite = bool(np.isfinite(value))
        jumped = finite and prev is not None and abs(float(value) - float(prev)) > jump
        if not finite or jumped:
            if start is not None and index - 1 - start >= min_len:
                runs.append((start, index - 1))
            if jumped:
                start = index
                prev = float(value)
            else:
                start = None
                prev = None
            continue
        if start is None:
            start = index
        prev = float(value)
    return runs


def _helical_agreement(window: np.ndarray, pitch: float, dz: float) -> bool:
    """True when shifting each column by the pitch matches the first column."""
    base = _fill_column(window[:, 0])
    if base is None or dz <= 0:
        return False
    ok = 0
    checked = 0
    for column in range(0, window.shape[1], 2):
        filled = _fill_column(window[:, column])
        if filled is None:
            continue
        checked += 1
        theta = 2.0 * math.pi * column / window.shape[1]
        matched = False
        for sign in (1.0, -1.0):
            shift = int(round(sign * (pitch * theta / (2.0 * math.pi)) / dz))
            rolled = np.roll(base, shift)
            if float(np.std(rolled)) < 1e-6 or float(np.std(filled)) < 1e-6:
                continue
            corr = float(np.corrcoef(rolled, filled)[0, 1])
            if np.isfinite(corr) and corr > 0.4:
                matched = True
                break
        if matched:
            ok += 1
    return checked > 0 and ok >= checked * 0.5


def _knurl_on_axis(mesh: trimesh.Trimesh) -> dict | None:
    axis = _axis_order(mesh)[0]
    sampled = _sample_axis(mesh, axis, nz=12, nt=72, inset=0.2)
    if sampled is None:
        return None
    grid, zs, mid = sampled
    finite_rows = [row for row in grid if np.isfinite(row).sum() > grid.shape[1] * 0.6]
    if not finite_rows:
        return None
    best_cycles = 0
    best_amp = 0.0
    for row in finite_rows:
        filled = _fill_column(row)
        if filled is None:
            continue
        p2p = float(filled.max() - filled.min())
        if p2p < 0.2:
            continue
        spectrum = np.abs(np.fft.rfft(filled - float(np.mean(filled))))
        if len(spectrum) < 13:
            continue
        cycles = int(np.argmax(spectrum[1:]) + 1)
        amplitude = float(spectrum[cycles])
        low = float(spectrum[1:12].max()) if len(spectrum) > 12 else 0.0
        if cycles >= 12 and amplitude > max(low * 1.5, 1e-6) and amplitude > best_amp:
            best_cycles = cycles
            best_amp = amplitude
    if best_cycles < 12:
        return None
    with np.errstate(all="ignore"):
        r_low = float(np.nanpercentile(grid, 20))
        r_high = float(np.nanmax(grid))
    if not np.isfinite(r_low) or not np.isfinite(r_high):
        return None
    axis_vec = [0.0, 0.0, 0.0]
    axis_vec[axis] = 1.0
    origin_axis = float(mid[axis])
    return {
        "kind": "knurl",
        "axis": axis_vec,
        "origin": [float(item) for item in mid],
        "r_min": max(0.0, r_low - 0.1),
        "r_max": r_high + 0.15,
        "z0": float(zs[0]) - origin_axis,
        "z1": float(zs[-1]) - origin_axis,
        "pitch": None,
        "periods": int(best_cycles),
    }
