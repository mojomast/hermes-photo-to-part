"""Session-scoped Hermes hooks for budget, skill ids, and photo probes.

Hermes v0.21.7 calls these for every tool, not only photo_part_*. Each hook
acts only after this plugin has been used in that ``session_id`` (a
``photo_part_*`` call or ``skill_view`` of this skill). Any other session is
left untouched. Exceptions are swallowed so an unrelated tool still runs.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from photopart.canary import EVAL_CANARY
from photopart.flow import SKILL_ID

_SKILL_MISSPELL = re.compile(
    r"^(?:plugin:|plugins:)?photo-to-part[:/]photo-to-printable-part$|^photo-to-printable-part$"
)
_PROBE = re.compile(r"\b(?:cv2|PIL|Image\.open|imread)\b")
_TERMINALS = {"terminal", "execute_code", "code_execution", "bash", "shell", "python"}
_PATH_KEYS = ("path", "file_path", "file", "image", "mesh", "script", "pattern", "command", "cmd", "code")
_LEVELS = ((0.60, "60"), (0.80, "80"), (0.95, "95"))
_NOTE = "[photo-to-part] {used} of {cap} tool calls used; next: photo_part_measure / photo_part_build."
_PROBE_NOTE = (
    "[photo-to-part] photo_part_measure already measures this photo: "
    "pass seed=[x,y] or roi=[x0,y0,x1,y1] to get the part size in mm."
)

_active: set[str] = set()
_projects: dict[str, Path] = {}
_images: dict[str, set[str]] = {}
_counts: dict[str, int] = {}
_notes: dict[str, set[str]] = {}
_probes: dict[str, int] = {}
_probe_noted: set[str] = set()


def reset_hooks() -> None:
    """Drop in-memory session state. Tests call this between cases."""
    _active.clear()
    _projects.clear()
    _images.clear()
    _counts.clear()
    _notes.clear()
    _probes.clear()
    _probe_noted.clear()


def hook_call_count(session_id: str | None, directory: Path | None = None) -> int | None:
    """Tool calls this process has counted for ``session_id``, or None if unknown."""
    if not session_id:
        return None
    sid = str(session_id)
    memory = _counts.get(sid)
    stored = _file_count(directory, sid) if directory is not None else None
    if memory is None and stored is None:
        return None
    return max(int(memory or 0), int(stored or 0))


def on_pre_tool_call(*args, **kwargs):
    """Rewrite our own misspelled skill id. Optionally block repeated photo probes."""
    try:
        return _pre(*args, **kwargs)
    except Exception:
        return None


def on_post_tool_call(*args, **kwargs):
    """Count every tool call in a session that has used this plugin."""
    try:
        return _post(*args, **kwargs)
    except Exception:
        return None


def on_transform_tool_result(*args, **kwargs):
    """Append one budget line at 60/80/95 percent, and a soft probe note."""
    try:
        return _transform(*args, **kwargs)
    except Exception:
        return None


HOOKS = (
    ("pre_tool_call", on_pre_tool_call),
    ("post_tool_call", on_post_tool_call),
    ("transform_tool_result", on_transform_tool_result),
)


def _pre(*args, **kwargs):
    fields = _fields(args, kwargs)
    name = fields["tool_name"]
    arguments = fields["args"] if isinstance(fields["args"], dict) else {}
    sid = fields["session_id"]
    if name == "skill_view":
        skill = arguments.get("name") or arguments.get("skill")
        if isinstance(skill, str) and _SKILL_MISSPELL.fullmatch(skill.strip()):
            if sid:
                _mark_active(sid, arguments)
            if skill.strip() != SKILL_ID:
                if sid:
                    _log(sid, arguments, {"tool": "skill_view", "rewrite_from": skill.strip(), "paths": []})
                updated = dict(arguments)
                updated["name"] = SKILL_ID
                return {"action": "modify", "args": updated}
            return None
        return None
    if name.startswith("photo_part_"):
        if sid:
            _mark_active(sid, arguments)
            _remember_image(sid, arguments)
        return None
    if not sid or sid not in _active:
        return None
    if _is_probe(name, arguments, sid):
        count = _probes.get(sid, 0) + 1
        _probes[sid] = count
        if _block_probes() and count >= 3:
            return {"action": "block", "message": _PROBE_NOTE}
    return None


def _post(*args, **kwargs):
    fields = _fields(args, kwargs)
    name = fields["tool_name"]
    arguments = fields["args"] if isinstance(fields["args"], dict) else {}
    sid = fields["session_id"]
    if not sid:
        return None
    if name.startswith("photo_part_") or (name == "skill_view" and _is_our_skill(arguments)):
        _mark_active(sid, arguments)
        _remember_image(sid, arguments)
    if sid not in _active:
        return None
    directory = _directory(sid, arguments)
    _counts[sid] = int(_counts.get(sid, 0)) + 1
    _write_budget(directory, sid, name)
    paths = _paths_of(arguments)
    row = {"tool": name or "other", "paths": paths}
    if paths and _paths_leak(paths):
        row["leak"] = True
    _log(sid, arguments, row)
    return None


def _transform(*args, **kwargs):
    fields = _fields(args, kwargs)
    name = fields["tool_name"]
    arguments = fields["args"] if isinstance(fields["args"], dict) else {}
    sid = fields["session_id"]
    result = fields["result"]
    if not sid or sid not in _active:
        return None
    if name.startswith("photo_part_"):
        return None
    lines: list[str] = []
    from photopart.budget import max_calls

    used = int(_counts.get(sid, 0))
    cap = max_calls()
    fraction = used / float(cap) if cap else 1.0
    sent = _notes.setdefault(sid, set())
    crossed = [label for level, label in _LEVELS if fraction + 1e-9 >= level and label not in sent]
    if crossed:
        for label in crossed:
            sent.add(label)
        _persist_notes(sid, sent)
        lines.append(_NOTE.format(used=used, cap=cap))
    if _is_probe(name, arguments, sid) and sid not in _probe_noted:
        _probe_noted.add(sid)
        lines.append(_PROBE_NOTE)
    if not lines:
        return None
    extra = "\n".join(lines)
    if isinstance(result, str):
        return result + ("\n" if result else "") + extra
    if result is None:
        return extra
    return str(result) + "\n" + extra


def _fields(args, kwargs) -> dict:
    names = ("tool_name", "args", "task_id", "session_id", "tool_call_id", "turn_id", "result")
    fields = {name: kwargs.get(name) for name in names}
    for name, value in zip(names, args):
        if fields.get(name) is None:
            fields[name] = value
    if fields.get("tool_name") is None and isinstance(kwargs.get("name"), str):
        fields["tool_name"] = kwargs["name"]
    tool = fields.get("tool_name")
    fields["tool_name"] = "" if tool is None else str(tool)
    session = fields.get("session_id")
    fields["session_id"] = "" if session is None else str(session)
    return fields


def _is_our_skill(arguments: dict) -> bool:
    skill = arguments.get("name") or arguments.get("skill")
    return isinstance(skill, str) and bool(_SKILL_MISSPELL.fullmatch(skill.strip()))


def _mark_active(sid: str, arguments: dict) -> None:
    _active.add(sid)
    if _has_project_path(arguments):
        from photopart.budget import project_dir

        _projects[sid] = project_dir(arguments)


def _remember_image(sid: str, arguments: dict) -> None:
    image = arguments.get("image")
    if not isinstance(image, str) or not image.strip():
        return
    path = Path(image).expanduser()
    names = _images.setdefault(sid, set())
    names.add(str(path))
    names.add(path.name)
    try:
        names.add(str(path.resolve()))
    except OSError:
        return


def _directory(sid: str, arguments: dict) -> Path:
    if _has_project_path(arguments):
        from photopart.budget import project_dir

        chosen = project_dir(arguments)
        _projects[sid] = chosen
        return chosen
    remembered = _projects.get(sid)
    if remembered is not None:
        return remembered
    return Path.cwd()


def _has_project_path(arguments: dict) -> bool:
    if not isinstance(arguments, dict):
        return False
    for key in ("file", "mesh", "stl", "script", "image", "out_dir", "cwd", "out", "project"):
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return True
    return False


def _budget_path(directory: Path) -> Path:
    return directory / ".photopart" / "budget.json"


def _calls_path(directory: Path) -> Path:
    return directory / ".photopart" / "calls.jsonl"


def _plugin_dir(directory: Path) -> bool:
    from photopart.paths import plugin_root

    root = plugin_root()
    if root is None:
        return False
    try:
        return directory.expanduser().resolve() == root
    except OSError:
        return False


def _write_budget(directory: Path, sid: str, tool_name: str) -> None:
    if _plugin_dir(directory):
        return
    path = _budget_path(directory)
    state = _read_json(path)
    sessions = state.get("sessions") if isinstance(state.get("sessions"), dict) else {}
    row = sessions.get(sid) if isinstance(sessions.get(sid), dict) else {}
    tools = row.get("tools") if isinstance(row.get("tools"), dict) else {}
    bucket = tool_name if tool_name else "other"
    tools[bucket] = int(tools.get(bucket) or 0) + 1
    if bucket != "other" and not str(tool_name).startswith("photo_part_"):
        tools["other"] = int(tools.get("other") or 0) + 1
    row = {
        "calls": int(_counts.get(sid) or 0),
        "tools": tools,
        "notes": sorted(_notes.get(sid) or []),
    }
    sessions[sid] = row
    state = {"sessions": sessions}
    _write_json(path, state)


def _persist_notes(sid: str, sent: set[str]) -> None:
    directory = _projects.get(sid, Path.cwd())
    if _plugin_dir(directory):
        return
    path = _budget_path(directory)
    state = _read_json(path)
    sessions = state.get("sessions") if isinstance(state.get("sessions"), dict) else {}
    row = sessions.get(sid) if isinstance(sessions.get(sid), dict) else {}
    row["notes"] = sorted(sent)
    row["calls"] = int(_counts.get(sid) or row.get("calls") or 0)
    sessions[sid] = row
    state["sessions"] = sessions
    _write_json(path, state)


def _file_count(directory: Path | None, sid: str) -> int | None:
    if directory is None:
        return None
    state = _read_json(_budget_path(directory))
    sessions = state.get("sessions") if isinstance(state.get("sessions"), dict) else {}
    row = sessions.get(sid)
    if not isinstance(row, dict) or "calls" not in row:
        return None
    try:
        return int(row["calls"])
    except (TypeError, ValueError):
        return None


def _log(sid: str, arguments: dict, row: dict) -> None:
    directory = _directory(sid, arguments) if sid in _projects or _has_project_path(arguments) else _projects.get(sid, Path.cwd())
    if _plugin_dir(directory):
        return
    path = _calls_path(directory)
    body = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session_id": sid,
        **row,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(body, sort_keys=True) + "\n")
    except OSError:
        return


def _paths_of(arguments: dict) -> list[str]:
    found: list[str] = []
    if not isinstance(arguments, dict):
        return found
    for key in _PATH_KEYS:
        value = arguments.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        if key in {"command", "cmd", "code"}:
            for match in re.findall(r"[^\s\"']+\.(?:py|json|md|stl|png|jpg|txt)", value):
                found.append(match[:300])
            folded = value.replace("\\", "/")
            if "evals/" in folded or EVAL_CANARY in value:
                found.append(folded[:300])
            continue
        found.append(value[:300])
    unique: list[str] = []
    for item in found:
        if item not in unique:
            unique.append(item)
    return unique[:12]


def _paths_leak(paths: list[str]) -> bool:
    for raw in paths:
        folded = raw.replace("\\", "/")
        if "evals/" in folded or EVAL_CANARY in raw:
            return True
        file = Path(raw).expanduser()
        try:
            if not file.is_file() or file.stat().st_size > 256_000:
                continue
            text = file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if EVAL_CANARY in text:
            return True
    return False


def _is_probe(tool_name: str, arguments: dict, sid: str) -> bool:
    if tool_name not in _TERMINALS and "terminal" not in tool_name:
        return False
    blob = " ".join(str(arguments.get(key) or "") for key in ("command", "cmd", "code", "script", "input"))
    if not _PROBE.search(blob):
        return False
    known = _images.get(sid) or set()
    if not known:
        return False
    folded = blob.replace("\\", "/")
    return any(item and item in blob or item in folded for item in known)


def _block_probes() -> bool:
    raw = os.environ.get("PHOTOPART_BLOCK_PROBES", "0").strip().lower()
    return raw not in {"", "0", "false", "no", "off"}


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _write_json(path: Path, payload: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        return
