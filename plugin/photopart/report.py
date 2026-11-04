"""Shared mesh measurements for the validator and the heal report."""

from __future__ import annotations

import numpy as np
import trimesh


def _edge_counts(mesh: trimesh.Trimesh) -> np.ndarray:
    if len(mesh.faces) == 0:
        return np.array([], dtype=int)
    inverse = np.asarray(mesh.edges_unique_inverse)
    if inverse.size == 0:
        return np.array([], dtype=int)
    return np.bincount(inverse)


def measure(mesh: trimesh.Trimesh) -> dict:
    """Measure a mesh without modifying it."""
    counts = _edge_counts(mesh)
    boundary = int(np.sum(counts == 1)) if counts.size else 0
    nonmanifold = int(np.sum(counts > 2)) if counts.size else 0
    try:
        degenerate = int(np.count_nonzero(~np.asarray(mesh.nondegenerate_faces())))
    except Exception:
        degenerate = None
    watertight = bool(mesh.is_watertight)
    winding = bool(mesh.is_winding_consistent)
    volume = None
    if watertight and winding:
        volume = float(mesh.volume)
    extents = np.asarray(mesh.extents, dtype=float)
    bounds = np.asarray(mesh.bounds, dtype=float)
    try:
        components = int(len(mesh.split(only_watertight=False)))
    except Exception:
        components = None
    return {
        "triangles": int(len(mesh.faces)),
        "vertices": int(len(mesh.vertices)),
        "watertight": watertight,
        "winding_consistent": winding,
        "volume_mm3": volume,
        "components": components,
        "boundary_edges": boundary,
        "nonmanifold_edges": nonmanifold,
        "degenerate_faces": degenerate,
        "extents_mm": {
            "x": float(extents[0]),
            "y": float(extents[1]),
            "z": float(extents[2]),
        },
        "bounds_mm": {
            "min": [float(v) for v in bounds[0]],
            "max": [float(v) for v in bounds[1]],
        },
    }
