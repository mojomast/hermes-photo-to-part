"""Per-project tool-call counter.

The count lives in ``.p2p_state.json`` next to the mesh or the output
directory. Every tool result includes it. At 14 calls, ``next_step`` leads
with a deliver hint so the agent stops exploring.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

SOFT_LIMIT = 20
_HINT_AT = 14
_PHASE = {
    "photo_part_measure": "spec",
    "photo_part_template": "build",
    "photo_part_build": "build",
    "photo_part_heal": "build",
    "photo_part_validate": "validate",
    "photo_part_render": "deliver",
}


def attach_budget(payload: dict, tool_name: str) -> dict:
    """Increment the project counter and attach ``budget``. Prepend the hint at 14."""
    directory = project_dir(payload)
    state = _bump(directory, tool_name, _file_name(payload))
    phase = _PHASE.get(tool_name, "build")
    payload["budget"] = {
        "plugin_calls": int(state["plugin_calls"]),
        "soft_limit": SOFT_LIMIT,
        "phase": phase,
    }
    if int(state["plugin_calls"]) >= _HINT_AT:
        target = state.get("last_file") or _file_name(payload) or "the best validated file"
        hint = f"Budget: deliver the best validated version now ({target})."
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
    for key in ("out_dir", "cwd", "out"):
        value = payload.get(key)
        if not value or not isinstance(value, str):
            continue
        path = Path(value).expanduser()
        return path.parent if path.suffix else path
    return Path.cwd()


def _file_name(payload: dict) -> str | None:
    for key in ("best_version", "file", "stl", "mesh"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return Path(value).name
    return None


def _bump(directory: Path, tool_name: str, last_file: str | None) -> dict:
    path = directory / ".p2p_state.json"
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
