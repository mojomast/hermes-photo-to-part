"""Facts a template or build already knows, so an agent does not probe the mesh."""

from __future__ import annotations

import numpy as np

from photopart.spec import openings, section_areas_mm2


def mesh_facts(mesh) -> dict:
    """Bodies, circular bores, and three horizontal section areas."""
    bodies = []
    try:
        parts = list(mesh.split(only_watertight=False))
    except Exception:
        parts = [mesh]
    if not parts:
        parts = [mesh]
    for body in parts:
        extents = np.asarray(body.extents, dtype=float)
        volume = None
        if getattr(body, "is_watertight", False):
            volume = round(float(body.volume), 3)
        bodies.append(
            {
                "bbox_mm": {
                    "x": round(float(extents[0]), 3),
                    "y": round(float(extents[1]), 3),
                    "z": round(float(extents[2]), 3),
                },
                "volume": volume,
            }
        )
    found = openings(mesh)
    return {
        "bodies": bodies,
        "bores": found["bores"],
        "recesses": found["recesses"],
        "cavities": found["cavities"],
        "sections_mm2": section_areas_mm2(mesh),
    }


def facts_for_stl(path) -> dict | None:
    from pathlib import Path

    from photopart.io import load_mesh

    stl = Path(path)
    if not stl.is_file() or stl.suffix.lower() not in {".stl", ".3mf", ".obj", ".ply"}:
        return None
    try:
        mesh = load_mesh(stl)
    except (OSError, ValueError):
        return None
    return mesh_facts(mesh)
