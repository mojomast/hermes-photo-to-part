"""Copies of an STL or 3MF taken before a tool replaces it.

Snapshots live in ``.p2p_history/`` next to the file, named
``<filename>.<sha256-12>``. A second write of the same bytes does not
duplicate the copy. This module does not delete the file the tool is writing.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from photopart.stamp import mesh_hash

_VERSION = re.compile(r"^(?P<stem>.+)_v(?P<n>\d+)(?P<ext>\.[^.]+)$", re.IGNORECASE)


def snapshot(path: str | Path) -> str | None:
    """Copy ``path`` into ``.p2p_history`` when it already exists. Return the copy."""
    source = Path(path)
    if not source.is_file():
        return None
    if ".p2p_history" in source.parts:
        return None
    digest = mesh_hash(source)[:12]
    destination_dir = source.parent / ".p2p_history"
    destination = destination_dir / f"{source.name}.{digest}"
    if destination.is_file():
        return str(destination)
    destination_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return str(destination)


def missing_versions(path: str | Path) -> list[str]:
    """``name_vN`` whose ``name_v(N-1)`` is not beside it.

    An empty list means this path is not a later version, or the previous
    version is still on disk. The missing name is reported. Nothing is created.
    """
    source = Path(path)
    match = _VERSION.match(source.name)
    if not match:
        return []
    number = int(match.group("n"))
    if number <= 1:
        return []
    previous = f"{match.group('stem')}_v{number - 1}{match.group('ext')}"
    if (source.parent / previous).is_file():
        return []
    return [previous]
