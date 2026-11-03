"""Per-project tool-call budget.

Hermes stops a session at about 40 tool calls in total. Counting only this
plugin's calls never reaches that cap, so the hint never fired. ``calls_used``
is the session total when the agent passes it. When it is omitted, the used
count is estimated high (four session calls per plugin call) so ``remaining``
is conservative. ``next_step`` says deliver now at 60 percent and at 80
percent of the cap. ``PHOTO_PART_MAX_CALLS`` overrides the default of 40.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_MAX_CALLS = 40
_ESTIMATE_PER_PLUGIN_CALL = 4
_PHASE = {
    "photo_part_measure": "spec",
    "photo_part_template": "build",
    "photo_part_build": "build",
    "photo_part_heal": "build",
    "photo_part_validate": "validate",
    "photo_part_render": "deliver",
}


def max_calls() -> int:
    """Session cap. ``PHOTO_PART_MAX_CALLS`` overrides the default of 40."""
    raw = os.environ.get("PHOTO_PART_MAX_CALLS", "").strip()
    if not raw:
        return DEFAULT_MAX_CALLS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_CALLS
    if value < 1:
        return DEFAULT_MAX_CALLS
    return value


def attach_budget(payload: dict, tool_name: str, calls_used=None) -> dict:
    """Increment the project counter and attach ``budget``. Hint at 60% and 80%."""
    directory = project_dir(payload)
    state = _bump(directory, tool_name, _file_name(payload))
    cap = max_calls()
    plugin_calls = int(state["plugin_calls"])
    used, source = _resolve_used(plugin_calls, calls_used, cap)
    remaining = max(0, cap - used)
    phase = _PHASE.get(tool_name, "build")
    payload["budget"] = {
        "max_calls": cap,
        "calls_used": used,
        "remaining": remaining,
        "plugin_calls": plugin_calls,
        "calls_used_source": source,
        "phase": phase,
    }
    fraction = used / float(cap) if cap else 1.0
    if fraction >= 0.60 - 1e-9:
        hint = f"Budget: deliver now. {remaining} of {cap} tool calls remain."
        if fraction >= 0.80 - 1e-9:
            hint = f"{hint} Stop exploring."
        step = str(payload.get("next_step") or "")
        if not step.startswith("Budget:"):
            payload["next_step"] = f"{hint} {step}".rstrip()
    return payload


def project_dir(payload: dict) -> Path:
    if not isinstance(payload, dict):
        return Path.cwd()
    for key in ("file", "mesh", "stl", "script", "image"):
        value = payload.get(key)
        if not value or not isinstance(value, str):
            continue
        path = Path(value).expanduser()
        parent = path.parent if path.suffix else path
        if str(parent) not in {"", "."}:
            return parent
    for key in ("out_dir", "cwd", "out", "project"):
        value = payload.get(key)
        if not value or not isinstance(value, str):
            continue
        path = Path(value).expanduser()
        return path.parent if path.suffix else path
    return Path.cwd()


def _resolve_used(plugin_calls: int, provided, cap: int) -> tuple[int, str]:
    if provided is not None and provided != "":
        try:
            reported = int(provided)
        except (TypeError, ValueError):
            reported = None
        if reported is not None:
            if reported < 0:
                reported = 0
            return min(cap, max(plugin_calls, reported)), "argument"
    estimated = max(plugin_calls, plugin_calls * _ESTIMATE_PER_PLUGIN_CALL)
    return min(cap, estimated), "estimate"


def _file_name(payload: dict) -> str | None:
    for key in ("best_version", "file", "stl", "mesh"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return Path(value).name
    return None


def _bump(directory: Path, tool_name: str, last_file: str | None) -> dict:
    from photopart.paths import plugin_root

    path = directory / ".p2p_state.json"
    root = plugin_root()
    try:
        resolved = directory.expanduser().resolve()
    except OSError:
        resolved = directory
    if root is not None and resolved == root:
        # The install directory is not a project. Do not leave state there.
        return {
            "plugin_calls": 1,
            "calls": {tool_name: 1},
            "last_file": last_file,
        }
    state = _read(path)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    calls = state.get("calls") if isinstance(state.get("calls"), dict) else {}
    calls[tool_name] = int(calls.get(tool_name) or 0) + 1
    state = {
        "plugin_calls": int(state.get("plugin_calls") or 0) + 1,
        "first_call": state.get("first_call") or now,
        "calls": calls,
        "last_file": last_file or state.get("last_file"),
    }
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        return state
    return state


def _read(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}
