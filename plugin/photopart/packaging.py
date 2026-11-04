"""Files a Hermes subdirectory install of this plugin publishes.

``hermes plugins install mojomast/hermes-photo-to-part/plugin`` sparse-checks
out this directory only. ``evals/`` and ``tests/`` stay at the repository
root, so they are not in that install. A root install is refused by the
stub ``plugin.yaml`` next to those directories.
"""

from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    """Git root. This file lives at ``plugin/photopart/packaging.py``."""
    return Path(__file__).resolve().parents[2]


def plugin_dir(repo: Path | None = None) -> Path:
    root = repo_root() if repo is None else Path(repo)
    return root / "plugin"


def installed_files(repo: Path | None = None) -> list[str]:
    """Relative paths Hermes copies for the ``plugin/`` subdirectory."""
    root = plugin_dir(repo)
    found: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if "/__pycache__/" in f"/{relative}" or relative.endswith((".pyc", ".pyo")):
            continue
        found.append(relative)
    return sorted(found)
