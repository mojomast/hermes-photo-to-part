"""trimesh ↔ manifold3d conversions.

Imported only when a boolean or a union runs. The plugin does not shell out
and does not download anything from here.
"""

from __future__ import annotations

import numpy as np
import trimesh


def to_manifold(mesh: trimesh.Trimesh):
    """Build a Manifold from a triangle mesh. An open mesh may come back empty."""
    import manifold3d

    vertices = np.ascontiguousarray(mesh.vertices, dtype=np.float32)
    faces = np.ascontiguousarray(mesh.faces, dtype=np.uint32)
    return manifold3d.Manifold(manifold3d.Mesh(vert_properties=vertices, tri_verts=faces))


def from_manifold(manifold) -> trimesh.Trimesh:
    """Convert a Manifold back to a trimesh, welding coincident vertices."""
    raw = manifold.to_mesh()
    mesh = trimesh.Trimesh(
        vertices=np.asarray(raw.vert_properties, dtype=float),
        faces=np.asarray(raw.tri_verts, dtype=np.int64),
        process=False,
    )
    if len(mesh.faces) == 0:
        return mesh
    mesh.merge_vertices()
    mesh.remove_unreferenced_vertices()
    return mesh


def as_mesh(manifold) -> trimesh.Trimesh:
    """Return a trimesh, or raise if the boolean produced nothing."""
    if manifold.is_empty():
        raise ValueError("manifold boolean produced an empty solid")
    mesh = from_manifold(manifold)
    if len(mesh.faces) == 0:
        raise ValueError("manifold boolean produced an empty solid")
    return mesh


def union_components(mesh: trimesh.Trimesh) -> tuple[trimesh.Trimesh, bool]:
    """Boolean-union the connected components.

    Overlapping shells become one shell. Disjoint shells stay separate.
    Returns the mesh unchanged, with False, when there is nothing to union
    or the boolean fails.
    """
    import manifold3d

    parts = mesh.split(only_watertight=False)
    if len(parts) < 2:
        return mesh, False
    bodies = []
    for part in parts:
        if len(part.faces) == 0:
            continue
        try:
            body = to_manifold(part)
        except Exception:
            return mesh, False
        if body.is_empty():
            return mesh, False
        bodies.append(body)
    if len(bodies) < 2:
        return mesh, False
    try:
        merged = manifold3d.Manifold.batch_boolean(bodies, manifold3d.OpType.Add)
    except Exception:
        return mesh, False
    if merged.is_empty():
        return mesh, False
    result = from_manifold(merged)
    if len(result.faces) == 0:
        return mesh, False
    return result, True
