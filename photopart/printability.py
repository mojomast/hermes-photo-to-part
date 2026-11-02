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
) -> dict:
    """Return measurements and warnings. Warnings do not change ``ok`` by themselves."""
    warnings: list[str] = []
    wall = _min_wall(mesh, samples)
    overhang_area, overhang_fraction, bed_area = _faces(mesh, overhang_deg)
    gap = _min_gap(mesh, samples)
    if wall is not None and wall < min_wall_mm:
        warnings.append(
            f"min wall {wall:.3f} mm is under {min_wall_mm:g} mm. "
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
