"""Absolute output paths. Refuse the Hermes cache scratch directory and
paths that Hermes protects from writes."""

from __future__ import annotations

import os
from pathlib import Path

from photopart.flow import SKILL_ID


def plugin_root() -> Path | None:
    """Directory that holds ``plugin.yaml``. None when this file is not in a checkout."""
    here = Path(__file__).resolve()
    for candidate in (here.parents[1], here.parent):
        if (candidate / "plugin.yaml").is_file() and (candidate / "photopart").is_dir():
            return candidate
    return None


def source_checkout_root() -> Path | None:
    """Git root when this tree is the in-repo ``plugin/`` package.

    ``hermes plugins install .../plugin`` publishes that directory under a
    different name, so an install returns None. The test suite's working
    directory is this root. It is not a user project.
    """
    plugin = plugin_root()
    if plugin is None or plugin.name != "plugin":
        return None
    checkout = plugin.parent
    if (checkout / "plugin" / "plugin.yaml").is_file() and (checkout / "plugin.yaml").is_file():
        return checkout
    return None


def not_a_project(path: Path) -> bool:
    """True for the plugin install directory and the source checkout root."""
    try:
        resolved = Path(path).expanduser().resolve()
    except OSError:
        return False
    return any(root is not None and resolved == root for root in (plugin_root(), source_checkout_root()))


PLUGIN_ID = "photo-to-part"


def hermes_home() -> Path | None:
    """The active Hermes home from ``hermes_constants.get_hermes_home()``.

    Outside Hermes (a bare ``python`` run of a helper script, or the unit
    tests) this returns None. There is no ``~/.hermes`` fallback, so the
    plugin never guesses a profile.
    """
    try:
        from hermes_constants import get_hermes_home
    except ImportError:
        return None
    try:
        return Path(get_hermes_home()).expanduser().resolve()
    except Exception:
        return None


def state_dir() -> Path | None:
    """Shared plugin state: ``get_hermes_home()/plugin-data/photo-to-part``.

    Uses Hermes's ``plugins.plugin_storage.plugin_data_dir`` when it exists,
    which resolves the same path and follows the active profile. None outside
    Hermes, so nothing shared is written then.
    """
    try:
        from plugins.plugin_storage import plugin_data_dir
    except ImportError:
        plugin_data_dir = None
    if plugin_data_dir is not None:
        try:
            return Path(plugin_data_dir(PLUGIN_ID)).resolve()
        except Exception:
            pass
    home = hermes_home()
    if home is None:
        return None
    return home / "plugin-data" / PLUGIN_ID


def cache_root() -> Path | None:
    """``<hermes home>/cache``, the scratch tree no tool may write into.

    A helper script started by the terminal tool runs outside the Hermes
    process, so this write guard also honours an inherited ``HERMES_HOME``.
    It only refuses writes; no state is stored from that variable.
    """
    home = hermes_home()
    if home is None:
        raw = os.environ.get("HERMES_HOME", "").strip()
        if not raw:
            return None
        home = Path(raw).expanduser().resolve()
    return home / "cache"


def inside(path: Path, root: Path | None) -> bool:
    """True when ``path`` resolves to ``root`` or below it."""
    if root is None:
        return False
    try:
        Path(path).expanduser().resolve().relative_to(Path(root).resolve())
    except (OSError, ValueError):
        return False
    return True


def writable_project(path: Path | None) -> Path | None:
    """``path`` when the plugin may write ``<path>/.photopart`` there, else None.

    Refuses the install directory, the source checkout root, the Hermes cache,
    and any path Hermes's write denylist refuses.
    """
    if path is None:
        return None
    try:
        resolved = Path(path).expanduser().resolve()
    except OSError:
        return None
    if not resolved.is_dir() or not_a_project(resolved) or under_cache(resolved):
        return None
    if write_denied(resolved / ".photopart") or write_denied(resolved):
        return None
    return resolved


def under_cache(path: Path) -> bool:
    root = cache_root()
    if root is None:
        return False
    try:
        path.resolve().relative_to(root)
    except ValueError:
        return False
    return True


def write_denied(path: Path) -> str | None:
    """Hermes's write denylist verdict, or None outside Hermes."""
    try:
        from agent.file_safety import get_write_denied_error
    except ImportError:
        return None
    return get_write_denied_error(str(path))


def refuse_protected(path: Path) -> Path:
    """Raise ValueError when Hermes refuses writes to path."""
    denied = write_denied(path)
    if denied:
        raise ValueError(f"{denied} Skill id: {SKILL_ID}.")
    return path


def new_output(path: str | Path, suffix: str, *, overwrite: bool = False) -> Path:
    """An absolute output file with the expected suffix. Refuse an existing file unless overwrite."""
    resolved = absolute_path(path)
    if resolved.suffix.lower() != suffix:
        raise ValueError(f"output must end in {suffix}: {resolved}")
    if resolved.exists() and not overwrite:
        raise ValueError(f"refusing to overwrite {resolved}. Pass overwrite.")
    return resolved


def absolute_path(path: str | Path) -> Path:
    """Resolve a user path against the working directory. Never a cache or protected path."""
    raw = Path(path).expanduser()
    if not raw.is_absolute():
        raw = Path.cwd() / raw
    resolved = raw.resolve()
    if under_cache(resolved):
        raise ValueError(
            f"refusing to write {resolved} under HERMES_HOME/cache. "
            "Pass an absolute path in the user project, such as spur_gear_v1.stl. "
            f"Skill id: {SKILL_ID}."
        )
    return refuse_protected(resolved)


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
