"""Optional PyMeshFix pass when manifold repair still leaves a bad edge.

The import is local. If the package is absent the caller keeps the mesh it
already had and the report says so.
"""

from __future__ import annotations

import trimesh


def try_meshfix(mesh: trimesh.Trimesh) -> tuple[trimesh.Trimesh, dict]:
    """Repair with PyMeshFix when it is installed. Otherwise return ``mesh``."""
    try:
        import pymeshfix
    except ImportError:
        return mesh, {
            "meshfix_applied": False,
            "meshfix_available": False,
            "meshfix_note": "pymeshfix is not installed. The manifold repair stands.",
        }
    try:
        fixer = pymeshfix.MeshFix(mesh.vertices, mesh.faces)
        fixer.repair(verbose=False, joincomp=True)
        repaired = trimesh.Trimesh(vertices=fixer.points, faces=fixer.faces, process=False)
    except Exception as exc:
        return mesh, {
            "meshfix_applied": False,
            "meshfix_available": True,
            "meshfix_note": f"pymeshfix failed: {exc}",
        }
    if len(repaired.faces) == 0:
        return mesh, {
            "meshfix_applied": False,
            "meshfix_available": True,
            "meshfix_note": "pymeshfix returned an empty mesh.",
        }
    return repaired, {
        "meshfix_applied": True,
        "meshfix_available": True,
        "meshfix_note": "pymeshfix repaired non-manifold edges.",
    }
