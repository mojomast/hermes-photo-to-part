"""Absolute output paths. Refuse the Hermes cache scratch directory."""

from __future__ import annotations

import os
from pathlib import Path

from photopart.flow import SKILL_ID


def cache_root() -> Path | None:
    raw = os.environ.get("HERMES_HOME", "").strip()
    if not raw:
        return None
    return (Path(raw).expanduser().resolve() / "cache")


def under_cache(path: Path) -> bool:
    root = cache_root()
    if root is None:
        return False
    try:
        path.resolve().relative_to(root)
    except ValueError:
        return False
    return True


def absolute_path(path: str | Path) -> Path:
    """Resolve a user path against the working directory. Never a cache path."""
    raw = Path(path).expanduser()
    if not raw.is_absolute():
        raw = Path.cwd() / raw
    resolved = raw.resolve()
    if under_cache(resolved):
        raise ValueError(
            f"refusing to write {resolved} under HERMES_HOME/cache. "
            "Pass an absolute path in the user project, such as name_v1.stl. "
            f"Skill id: {SKILL_ID}."
        )
    return resolved


def default_output(preferred: Path, fallback_name: str) -> Path:
    """Use preferred when it is outside the cache, otherwise the working directory."""
    chosen = preferred.resolve()
    if under_cache(chosen):
        chosen = (Path.cwd().resolve() / fallback_name).resolve()
    if under_cache(chosen):
        raise ValueError(
            "pass an absolute output path in the user project. "
            "The working directory is inside HERMES_HOME/cache, so a relative path "
            f"would be scratch. Skill id: {SKILL_ID}."
        )
    return chosen
