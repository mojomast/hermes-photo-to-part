"""Session-scoped Hermes hooks for budget, skill ids, and photo probes.

Hermes v0.21.7 calls these for every tool, not only photo_part_*. Budget
and probe hooks act only after this plugin has been used in that
``session_id`` (a ``photo_part_*`` call or ``skill_view`` of this skill).
A photo-to-part gear request is also steered before the first plugin
call: handwritten gear or involute scripts are blocked until
``photo_part_template`` shape ``spur_gear`` has been tried. Unrelated
sessions are left untouched. Exceptions are swallowed so an unrelated
tool still runs. A read of an eval scoring file or ``tests/regression``
stays blocked when this hook raises. ``on_session_end`` settles the
Part studio pane so a CLI oneshot does not stay ``running``.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from photopart.canary import EVAL_CANARY
from photopart.skillref import rewrite_arguments, skill_id_status, touches_plugin

_PROBE = re.compile(r"\b(?:cv2|PIL|Image\.open|imread)\b")
_TERMINALS = {"terminal", "execute_code", "code_execution", "bash", "shell", "python"}
_PATH_KEYS = ("path", "file_path", "file", "image", "mesh", "script", "pattern", "command", "cmd", "code")
_LEVELS = ((0.60, "60"), (0.80, "80"), (0.95, "95"))
_NOTE = "[photo-to-part] {used} of {cap} tool calls used; {advice}"
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
    try:
        from photopart.gear_steer import reset as reset_gear_steer

        reset_gear_steer()
    except Exception:
        pass
    try:
        from photopart.deliver_steer import reset as reset_deliver_steer

        reset_deliver_steer()
    except Exception:
        pass


def session_project(session_id: str | None) -> Path | None:
    """Project directory remembered for ``session_id``, if this process has one."""
    if not session_id:
        return None
    return _projects.get(str(session_id))


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
        return _block_protected_read(args, kwargs)


def _block_protected_read(args, kwargs):
    """Fail closed for eval and regression paths. A normal read still proceeds."""
    try:
        from photopart.build_gate import eval_read_block

        fields = _fields(args, kwargs)
        return eval_read_block(fields.get("tool_name") or "", fields.get("args"))
    except Exception:
        try:
            from photopart.build_gate import BLOCK_MESSAGE, protected_read_text

            if protected_read_text(_raw_blob(args, kwargs)):
                return {"action": "block", "message": BLOCK_MESSAGE}
        except Exception:
            return None
        return None


def _raw_blob(args, kwargs) -> str:
    parts = [str(item) for item in args]
    parts.extend(f"{key} {value}" for key, value in kwargs.items())
    return "\n".join(parts)


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


def on_pre_llm_call(*args, **kwargs):
    """Remember a photo-to-part gear request. Never injects context."""
    try:
        return _pre_llm(*args, **kwargs)
    except Exception:
        return None


def on_session_end(*args, **kwargs):
    """Settle pane.json to Ready, Measured, or Incomplete when a turn ends."""
    try:
        return _session_end(*args, **kwargs)
    except Exception:
        return None


HOOKS = (
    ("pre_tool_call", on_pre_tool_call),
    ("post_tool_call", on_post_tool_call),
    ("transform_tool_result", on_transform_tool_result),
    ("pre_llm_call", on_pre_llm_call),
    ("on_session_end", on_session_end),
)


def _pre(*args, **kwargs):
    fields = _fields(args, kwargs)
    name = fields["tool_name"]
    arguments, was_string = _coerce_args(fields["args"])
    sid = fields["session_id"]
    updated, misses = rewrite_arguments(name, arguments)
    if sid and (touches_plugin(name, arguments) or misses):
        _mark_active(sid, updated if isinstance(updated, dict) else arguments)
        _remember_image(sid, arguments)
        _remember_wrapped_images(sid, arguments)
    if misses:
        if sid:
            for tool, original in misses:
                _log(sid, arguments, {"tool": tool, "rewrite_from": original, "paths": []})
        payload = json.dumps(updated) if was_string else updated
        return {"action": "modify", "args": payload}
    try:
        from photopart.gear_steer import steer_pre_tool

        steered = steer_pre_tool(name, arguments if isinstance(arguments, dict) else {}, sid)
        if steered:
            return steered
    except Exception:
        pass
    try:
        from photopart.deliver_steer import steer_pre_tool as steer_deliver

        directory = None
        if sid:
            try:
                directory = _directory(sid, arguments if isinstance(arguments, dict) else {})
            except Exception:
                directory = None
        steered = steer_deliver(
            name,
            arguments if isinstance(arguments, dict) else {},
            sid,
            directory=directory,
        )
        if steered:
            return steered
    except Exception:
        pass
    if name.startswith("photo_part_"):
        return None
    from photopart.build_gate import eval_read_block

    blocked = eval_read_block(name, arguments if arguments else fields["args"])
    if blocked:
        return blocked
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
    try:
        from photopart.gear_steer import note_tool

        note_tool(name, arguments, sid)
    except Exception:
        pass
    try:
        from photopart.deliver_steer import note_tool as note_deliver

        directory = None
        if sid:
            try:
                directory = _directory(sid, arguments if isinstance(arguments, dict) else {})
            except Exception:
                directory = None
        note_deliver(
            name,
            arguments,
            sid,
            result=fields.get("result"),
            directory=directory,
        )
    except Exception:
        pass
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
        highest = max(crossed, key=int)
        if highest == "95":
            advice = "deliver the best validated version now with photo_part_render final=true; do not start a new version."
        elif highest == "80":
            advice = "deliver now; stop exploring."
        else:
            advice = "deliver soon; prefer photo_part_template or photo_part_measure / photo_part_build, then validate."
        lines.append(_NOTE.format(used=used, cap=cap, advice=advice))
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


def _pre_llm(*args, **kwargs):
    sid = kwargs.get("session_id")
    if sid is None and args:
        sid = args[0]
    message = kwargs.get("user_message")
    if message is None and len(args) > 1:
        message = args[1]
    history = kwargs.get("conversation_history")
    if history is None and len(args) > 2:
        history = args[2]
    from photopart.gear_steer import note_user_message

    note_user_message(sid, message)
    if history and not message:
        note_user_message(sid, history)
    return None


def _session_end(*args, **kwargs):
    names = ("session_id", "completed", "interrupted", "model", "platform")
    fields = {name: kwargs.get(name) for name in names}
    for name, value in zip(names, args):
        if fields.get(name) is None:
            fields[name] = value
    sid = fields.get("session_id")
    sid = "" if sid is None else str(sid).strip()
    if not sid:
        return None
    extras = []
    remembered = _projects.get(sid)
    if remembered is not None:
        extras.append(remembered)
    try:
        cwd = Path.cwd()
    except OSError:
        cwd = None
    if cwd is not None and (cwd / ".photopart" / "pane.json").is_file():
        extras.append(cwd)
    from photopart.progress import settle_session

    settle_session(sid, directories=extras, ended=True)
    return None


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


def _coerce_args(raw) -> tuple[dict, bool]:
    """Return ``(arguments, was_json_string)``. A non-object stays an empty dict."""
    if isinstance(raw, dict):
        return raw, False
    if isinstance(raw, str):
        text = raw.strip()
        if text[:1] in "{[":
            try:
                loaded = json.loads(text)
            except json.JSONDecodeError:
                return {}, False
            if isinstance(loaded, dict):
                return loaded, True
    return {}, False


def _is_our_skill(arguments: dict) -> bool:
    skill = arguments.get("name") or arguments.get("skill") or arguments.get("skill_name")
    return isinstance(skill, str) and skill_id_status(skill) in {"exact", "miss"}


def _remember_wrapped_images(sid: str, arguments: dict) -> None:
    calls = arguments.get("calls") if isinstance(arguments, dict) else None
    if not isinstance(calls, list):
        return
    for call in calls:
        if not isinstance(call, dict):
            continue
        inner = call.get("arguments") if isinstance(call.get("arguments"), dict) else call.get("args")
        if isinstance(inner, dict):
            _remember_image(sid, inner)


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
    from photopart.paths import not_a_project

    return not_a_project(directory)


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
    line = json.dumps(body, sort_keys=True) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        pass
    _mirror_rewrite(path, line, row)


def _mirror_rewrite(written: Path, line: str, row: dict) -> None:
    """Copy a skill-id rewrite to ``$HERMES_HOME/.photopart`` for inspection.

    The scorer does not read that shared file. It reads the case directory's
    ``.photopart/calls.jsonl``, filtered to the session being scored.
    """
    if not row.get("rewrite_from"):
        return
    raw = os.environ.get("HERMES_HOME", "").strip()
    if not raw:
        return
    directory = Path(raw).expanduser()
    if _plugin_dir(directory):
        return
    path = _calls_path(directory)
    try:
        if path.resolve() == written.resolve():
            return
    except OSError:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
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
