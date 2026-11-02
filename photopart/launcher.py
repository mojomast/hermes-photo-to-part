"""Re-exec a helper script into the Hermes plugin environment.

Hermes installs trimesh into a private virtualenv. ``python <skill>/scripts/...``
uses the system interpreter, which does not see that env and, on PEP 668
hosts, cannot ``pip install`` into it. If this interpreter can already import
trimesh, it is the right one. Otherwise the script replaces itself with the
plugin env's Python and runs the same arguments again.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REEXEC_FLAG = "PHOTO_PART_PYTHON_REEXEC"

_MISSING = (
    "error: this Python cannot import trimesh, and no Hermes plugin environment "
    "was found under HERMES_HOME. Use the photo_part_validate, photo_part_render, "
    "photo_part_heal, or photo_part_template tools, which run inside the plugin "
    "environment. Do not pip install into the system Python."
)


def _can_import_trimesh() -> bool:
    try:
        import trimesh  # noqa: F401
    except ImportError:
        return False
    return True


def _python_in(venv: Path) -> Path | None:
    for relative in ("bin/python", "bin/python3", "Scripts/python.exe"):
        candidate = venv / relative
        if candidate.is_file():
            return candidate
    return None


def _from_facts(installs: Path) -> list[Path]:
    found: list[Path] = []
    if not installs.is_dir():
        return found
    for facts in sorted(installs.glob("*/facts.json")):
        try:
            data = json.loads(facts.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            continue
        env = data.get("packages", {}).get("venv", {}).get("environment")
        if not isinstance(env, str) or not env.strip():
            continue
        raw = Path(env.strip())
        roots = [raw] if raw.is_absolute() else []
        if not raw.is_absolute():
            roots.append((facts.parent / raw))
            roots.append(facts.parent / "environments" / raw.name / "venv")
            roots.append(facts.parent / "environments" / env.strip() / "venv")
        for root in roots:
            python = _python_in(root)
            if python is not None:
                found.append(python)
                break
    return found


def candidate_pythons(home: Path | None = None, *, include_virtualenv: bool = True) -> list[Path]:
    """Python interpreters that may hold the plugin's installed dependencies."""
    if home is None:
        raw_home = os.environ.get("HERMES_HOME", "").strip()
        home = Path(raw_home).expanduser() if raw_home else Path.home() / ".hermes"
    installs = home / "installs"
    found: list[Path] = []
    found.extend(_from_facts(installs))
    if installs.is_dir():
        for pattern in ("*/environments/*/venv", "*/venv"):
            for venv in sorted(installs.glob(pattern)):
                python = _python_in(venv)
                if python is not None:
                    found.append(python)
    if include_virtualenv:
        virtual = os.environ.get("VIRTUAL_ENV", "").strip()
        if virtual:
            python = _python_in(Path(virtual).expanduser())
            if python is not None:
                found.append(python)
    unique: list[Path] = []
    seen: set[str] = set()
    for path in found:
        key = str(path.resolve())
        if key not in seen:
            seen.add(key)
            unique.append(path.resolve())
    return unique


def pick_reexec(
    *,
    can_import: bool,
    already_reexec: bool,
    candidates: list[Path],
    current: Path,
) -> Path | None:
    """Return the interpreter to exec, or None when this process should continue.

    None with ``can_import`` or ``already_reexec`` means stay. None otherwise
    means no usable interpreter was found.
    """
    if already_reexec or can_import:
        return None
    try:
        current_resolved = current.resolve()
    except OSError:
        current_resolved = current
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        if resolved != current_resolved:
            return candidate
    return None


def ensure_plugin_python(
    *,
    can_import: bool | None = None,
    candidates: list[Path] | None = None,
    exec_fn=None,
    argv: list[str] | None = None,
    already: bool | None = None,
) -> Path | None:
    """Stay in this interpreter, re-exec into the plugin env, or exit 1.

    Tests pass ``exec_fn`` so they can observe the decision without replacing
    the process. The real scripts call this with no arguments.
    """
    if can_import is None:
        can_import = _can_import_trimesh()
    if candidates is None:
        candidates = candidate_pythons()
    if already is None:
        already = os.environ.get(REEXEC_FLAG) == "1"
    if exec_fn is None:
        exec_fn = os.execve
    if argv is None:
        argv = list(sys.argv)
    choice = pick_reexec(
        can_import=can_import,
        already_reexec=already,
        candidates=candidates,
        current=Path(sys.executable),
    )
    if can_import or already:
        return None
    if choice is None:
        print(_MISSING, file=sys.stderr, flush=True)
        raise SystemExit(1)
    env = os.environ.copy()
    env[REEXEC_FLAG] = "1"
    exec_fn(str(choice), [str(choice), *argv], env)
    return choice
