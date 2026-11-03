"""Local printability checks. No slicer and no network.

Wall thickness is the nearest inward ray hit. Overhang is face area whose
normal points down past ``overhang_deg`` from vertical, excluding the bed.
Bed contact is downward area on the lowest Z. The gap is the nearest distance
between separate shells.
"""

from __future__ import annotations

import math

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
    raw = _min_wall(mesh, samples)
    p5, thin_fraction = _sdf_wall(mesh, samples, min_wall_mm, _excluded_sources(mesh, face_tags))
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
    }


def _excluded_sources(mesh: trimesh.Trimesh, face_tags: dict | None) -> set[int]:
    tags = face_tags
    if tags is None:
        meta = getattr(mesh, "metadata", None)
        if isinstance(meta, dict):
            tags = meta.get("face_tags")
    if not isinstance(tags, dict):
        return set()
    found: set[int] = set()
    for key in ("thread", "knurl", "teeth"):
        for item in tags.get(key) or []:
            try:
                found.add(int(item))
            except (TypeError, ValueError):
                continue
    return found


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
