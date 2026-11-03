"""Tool-call counts from Hermes v0.21.7 session records.

``PluginContext`` at that tag does not carry a call counter. The dispatcher
passes ``session_id`` into a handler that accepts it. The canonical store is
``$HERMES_HOME/state.db`` (table ``messages``, column ``tool_calls``). The
same home also keeps JSON and JSONL transcripts under ``sessions/``, and
``hermes sessions export`` writes one session object per JSONL line. A text
export uses ``<timestamp> TOOLCALL name {args}``.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path

_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_TOOLCALL = re.compile(r"\bTOOLCALL\s+([A-Za-z][A-Za-z0-9_]*)\b")
_DB_LABEL = "state.db"


def hermes_home() -> Path | None:
    """``HERMES_HOME`` when it is set, otherwise ``~/.hermes`` if that directory exists."""
    raw = os.environ.get("HERMES_HOME", "").strip()
    if raw:
        return Path(raw).expanduser()
    default = Path.home() / ".hermes"
    if default.is_dir():
        return default
    return None


def session_call_count(session_id: str | None, *, home: Path | None = None) -> int | None:
    """How many tool calls that session has recorded. None when no record exists."""
    loaded = load_session_calls(session_id, home=home)
    if loaded is None:
        return None
    names, _label = loaded
    return len(names)


def load_session_calls(source: str | None, *, home: Path | None = None) -> tuple[list[str], str] | None:
    """Return ``(tool names, label)`` for a session id or a session file.

    The label is ``state.db``, ``jsonl``, ``json``, or ``transcript``. None
    when nothing matching ``source`` is on disk.
    """
    if source is None or not str(source).strip():
        return None
    text = str(source).strip()
    path = Path(text).expanduser()
    if path.is_file():
        try:
            body = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        names = names_from_text(body)
        label = _file_label(path)
        return names, label
    root = home if home is not None else hermes_home()
    if root is None:
        return None
    candidates: list[tuple[str, list[str]]] = []
    db_names = _names_from_db(root / "state.db", text)
    if db_names is not None:
        candidates.append((_DB_LABEL, db_names))
    file_names: list[str] = []
    file_label = "jsonl"
    for session_file in _session_files(root, text):
        try:
            body = session_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        found = names_from_text(body)
        if found:
            file_names.extend(found)
            file_label = _file_label(session_file)
    if file_names:
        candidates.append((file_label, file_names))
    if not candidates:
        return None
    label, names = max(candidates, key=lambda item: len(item[1]))
    return names, label


def session_text(source: str | None, *, home: Path | None = None) -> str:
    """Concatenated JSON/JSONL/text records for leak and skill-id scoring."""
    if source is None or not str(source).strip():
        return ""
    text = str(source).strip()
    path = Path(text).expanduser()
    if path.is_file():
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
    root = home if home is not None else hermes_home()
    if root is None:
        return ""
    parts: list[str] = []
    for session_file in _session_files(root, text):
        try:
            parts.append(session_file.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return "\n".join(parts)


def names_from_text(text: str) -> list[str]:
    """Tool names in a session JSON document, JSONL export, or TOOLCALL transcript.

    JSONL is one message per line, or one session object per line. Assistant
    ``tool_calls`` and the matching ``role=tool`` rows are one call, not two.
    """
    stripped = text.strip()
    if stripped[:1] in "{[":
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            obj = None
        if obj is not None:
            names = names_from_json(obj)
            if names:
                return names
    messages: list[dict] = []
    structured: list[str] = []
    toolcalls: list[str] = []
    for line in text.splitlines():
        row = line.strip()
        if not row:
            continue
        if row[:1] in "{[":
            try:
                obj = json.loads(row)
            except json.JSONDecodeError:
                obj = None
            if isinstance(obj, dict) and isinstance(obj.get("messages"), list):
                structured.extend(
                    names_from_messages([item for item in obj["messages"] if isinstance(item, dict)])
                )
                continue
            if isinstance(obj, dict) and ("role" in obj or "tool_calls" in obj):
                messages.append(obj)
                continue
            if obj is not None:
                found = names_from_json(obj)
                if found:
                    structured.extend(found)
                    continue
        match = _TOOLCALL.search(row)
        if match:
            toolcalls.append(match.group(1))
    if messages:
        structured.extend(names_from_messages(messages))
    return structured + toolcalls


def names_from_json(obj) -> list[str]:
    """Tool names in one session object, a message, or a list of either."""
    messages = _flatten_messages(obj)
    if messages:
        return names_from_messages(messages)
    name = _call_name(obj)
    return [name] if name else []


def names_from_messages(messages: list) -> list[str]:
    """Assistant ``tool_calls`` when present, otherwise ``role=tool`` rows.

    Counting both would double-count a call and its result.
    """
    assistant: list[str] = []
    tools: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        calls = _parse_calls(message.get("tool_calls"))
        if calls:
            for call in calls:
                name = _call_name(call) if isinstance(call, dict) else None
                if name:
                    assistant.append(name)
            continue
        if message.get("role") == "tool":
            raw = message.get("tool_name") or message.get("name")
            if isinstance(raw, str) and _NAME.fullmatch(raw.strip()):
                tools.append(raw.strip())
    return assistant if assistant else tools


def _flatten_messages(obj) -> list[dict]:
    found: list[dict] = []
    if isinstance(obj, list):
        for item in obj:
            found.extend(_flatten_messages(item))
        return found
    if not isinstance(obj, dict):
        return found
    messages = obj.get("messages")
    if isinstance(messages, list):
        for item in messages:
            if isinstance(item, dict):
                found.append(item)
        return found
    if "role" in obj or "tool_calls" in obj:
        found.append(obj)
    return found


def _parse_calls(raw):
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if isinstance(raw, list):
        return raw
    return None


def _call_name(obj) -> str | None:
    if not isinstance(obj, dict):
        return None
    function = obj.get("function")
    if isinstance(function, dict):
        name = function.get("name")
        if isinstance(name, str) and _NAME.fullmatch(name.strip()):
            return name.strip()
    if obj.get("role") == "tool":
        return None
    name = obj.get("name") or obj.get("tool")
    if isinstance(name, str) and _NAME.fullmatch(name.strip()) and "messages" not in obj:
        return name.strip()
    return None


def _file_label(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        return "jsonl"
    if suffix == ".json":
        return "json"
    return "transcript"


def _session_files(root: Path, session_id: str) -> list[Path]:
    directory = root / "sessions"
    if not directory.is_dir():
        return []
    names = (
        f"{session_id}.jsonl",
        f"{session_id}.json",
        f"session_{session_id}.json",
        f"session_{session_id}.jsonl",
    )
    exact = [directory / name for name in names if (directory / name).is_file()]
    if exact:
        return exact
    matches = []
    try:
        children = list(directory.iterdir())
    except OSError:
        return []
    for child in children:
        if not child.is_file():
            continue
        if child.suffix.lower() not in {".json", ".jsonl"}:
            continue
        if session_id in child.name:
            matches.append(child)
    matches.sort(key=lambda item: item.name)
    return matches


def _names_from_db(db_path: Path, session_id: str) -> list[str] | None:
    """None when the database or the session row is absent. An empty list is a real zero."""
    if not db_path.is_file():
        return None
    uri = f"file:{db_path}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=0.3)
    except sqlite3.Error:
        return None
    try:
        try:
            rows = conn.execute(
                "SELECT role, tool_calls, tool_name FROM messages WHERE session_id = ?",
                (session_id,),
            ).fetchall()
        except sqlite3.Error:
            return None
    finally:
        conn.close()
    if not rows:
        return None
    messages = [
        {"role": role, "tool_calls": tool_calls, "tool_name": tool_name, "name": tool_name}
        for role, tool_calls, tool_name in rows
    ]
    return names_from_messages(messages)
