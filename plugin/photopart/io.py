"""Load triangle meshes without repairing them on the way in."""

from __future__ import annotations

from pathlib import Path

import trimesh

DEFAULT_MAX_BYTES = 256 * 1024 * 1024


def resolve_file(path: str | Path, *, max_bytes: int, label: str) -> Path:
    """Resolve a user-supplied file and refuse empty or oversized inputs."""
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"{label} not found: {resolved}")
    size = resolved.stat().st_size
    if size == 0:
        raise ValueError(f"{label} is empty: {resolved}")
    if size > max_bytes:
        raise ValueError(
            f"{label} is {size} bytes, over the {max_bytes} byte limit. "
            "Pass --max-bytes to raise it."
        )
    return resolved


def load_mesh(path: str | Path, *, max_bytes: int = DEFAULT_MAX_BYTES) -> trimesh.Trimesh:
    """Load one triangle mesh. Scenes become a single concatenated mesh."""
    resolved = resolve_file(path, max_bytes=max_bytes, label="mesh")
    loaded = trimesh.load(resolved, force="mesh", process=False)
    if isinstance(loaded, trimesh.Scene):
        bodies = [
            geom
            for geom in loaded.geometry.values()
            if isinstance(geom, trimesh.Trimesh) and len(geom.faces)
        ]
        if not bodies:
            raise ValueError(f"no triangle meshes in {resolved}")
        loaded = bodies[0] if len(bodies) == 1 else trimesh.util.concatenate(bodies)
    if not isinstance(loaded, trimesh.Trimesh) or len(loaded.faces) == 0:
        raise ValueError(f"no triangle faces in {resolved}")
    # STL repeats vertices on every facet. Weld coincident points so shared
    # edges exist. This does not fill holes or drop broken faces.
    loaded.merge_vertices()
    loaded.remove_unreferenced_vertices()
    return loaded
