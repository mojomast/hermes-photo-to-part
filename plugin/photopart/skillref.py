"""Exact skill id, and the misspellings agents actually send.

Hermes v0.21.7 calls ``skill_view`` and ``skills_list`` on their own, and also
inside the ``tool_call`` wrapper ``{calls: [{name, arguments}]}``. A slash, a
``plugin:`` prefix, or the bare skill name is still this skill. Another
plugin's id is not.
"""

from __future__ import annotations

import json
import re

from photopart.flow import SKILL_ID

_SKILL_TOOLS = {"skill_view", "skills_list"}
_ARG_KEYS = ("name", "skill", "skill_name", "id", "query", "skill_id")
_PREFIXES = (
    "plugin:",
    "plugins:",
    "skill:",
    "skills:",
    "plugin/",
    "plugins/",
    "skill/",
    "skills/",
)
_DROP = {"plugin", "plugins", "skill", "skills"}
_CALL = re.compile(
    r"(?:skill_view|skills_list)\(\s*(?:(?:name|skill|skill_name|id|query|skill_id)\s*=\s*)?([\"'])(.*?)\1",
    re.IGNORECASE,
)
_NAMED_JSON = re.compile(
    r"\b(skill_view|skills_list|tool_call)\b[^\n{\[]{0,80}(\{.*\}|\[.*\])",
    re.IGNORECASE,
)


def skill_id_status(value: str) -> str:
    """``exact``, ``miss`` (this skill, wrong spelling), or ``other``."""
    if not isinstance(value, str):
        return "other"
    text = value.strip().strip("\"'`").strip()
    if not text:
        return "other"
    if text == SKILL_ID:
        return "exact"
    folded = text.replace("\\", "/").strip().strip("/")
    if folded.lower().endswith(".md"):
        folded = folded[:-3].strip().strip("/")
    changed = True
    while changed and folded:
        changed = False
        low = folded.lower()
        for prefix in _PREFIXES:
            if low.startswith(prefix):
                folded = folded[len(prefix) :].lstrip("/:")
                changed = True
                break
    parts = [part for part in re.split(r"[:/]+", folded) if part]
    parts = [part for part in parts if part.lower() not in _DROP]
    if len(parts) == 1 and parts[0].lower() == "photo-to-printable-part":
        return "miss"
    if (
        len(parts) >= 2
        and parts[-2].lower() == "photo-to-part"
        and parts[-1].lower() == "photo-to-printable-part"
    ):
        return "miss"
    return "other"


def counts_as_wrong_skill(value: str) -> bool:
    """A skill_view/skills_list argument that is not the exact id.

    Misspellings of this skill count. So does any ``plugin:`` id, which is
    the form the scorer already treated as wrong when it was written as
    ``skill_view("...")``.
    """
    if skill_id_status(value) == "miss":
        return True
    if not isinstance(value, str):
        return False
    text = value.strip()
    return text.startswith("plugin:") and text != SKILL_ID


def rewrite_arguments(tool_name: str, arguments: dict) -> tuple[dict | None, list[tuple[str, str]]]:
    """Copy ``arguments`` with this skill's misspellings replaced.

    Returns ``(updated, [(tool, original), ...])``. ``updated`` is None when
    nothing changed. Inner ``calls`` of a ``tool_call`` wrapper are included.
    Other skills are left as they were.
    """
    if not isinstance(arguments, dict):
        return None, []
    import copy

    updated = copy.deepcopy(arguments)
    found = _rewrite_into(str(tool_name or ""), updated)
    if not found:
        return None, []
    return updated, found


def touches_plugin(tool_name: str, arguments: dict) -> bool:
    """True when this call is one of our tools or a view of this skill."""
    name = str(tool_name or "")
    if name.startswith("photo_part_"):
        return True
    if not isinstance(arguments, dict):
        return False
    if name in _SKILL_TOOLS and _dict_mentions_us(arguments):
        return True
    calls = arguments.get("calls")
    if isinstance(calls, list) and name in {None, "", "tool_call", * _SKILL_TOOLS}:
        for call in calls:
            if not isinstance(call, dict):
                continue
            inner = _call_name(call)
            args = _call_args(call)
            if inner and touches_plugin(inner, args if isinstance(args, dict) else {}):
                return True
    return False


def misspelled_skill_arguments(text: str) -> list[str]:
    """Wrong skill ids from ``skill_view("...")`` and from tool-call JSON.

    A string that appears both as ``skill_view("id")`` and inside a JSON
    argument is counted once. ``skills_list`` arguments and ids nested in
    ``tool_call`` ``calls`` are included. Prose that merely mentions the
    ``plugin:`` form is not.
    """
    if not text:
        return []
    regex_hits = [match.group(2) for match in _CALL.finditer(text) if counts_as_wrong_skill(match.group(2))]
    structured = [item for item in _structured_arguments(text) if counts_as_wrong_skill(item)]
    have: dict[str, int] = {}
    for item in regex_hits:
        have[item] = have.get(item, 0) + 1
    extra = []
    for item in structured:
        if have.get(item, 0):
            have[item] -= 1
            continue
        extra.append(item)
    return regex_hits + extra


def _dict_mentions_us(arguments: dict) -> bool:
    for key in _ARG_KEYS:
        value = arguments.get(key)
        if isinstance(value, str) and skill_id_status(value) in {"exact", "miss"}:
            return True
    return False


def _rewrite_into(tool_name: str, arguments: dict) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if tool_name in _SKILL_TOOLS:
        found.extend((tool_name, original) for original in _rewrite_dict(arguments))
    calls = arguments.get("calls")
    if isinstance(calls, list) and tool_name in {None, "", "tool_call", *_SKILL_TOOLS}:
        for call in calls:
            if not isinstance(call, dict):
                continue
            inner = _call_name(call) or ""
            args = _call_args(call)
            string_args = isinstance(call.get("arguments"), str) or (
                isinstance(call.get("function"), dict) and isinstance(call["function"].get("arguments"), str)
            )
            if not isinstance(args, dict):
                if inner in _SKILL_TOOLS and isinstance(args, str) and skill_id_status(args) == "miss":
                    found.append((inner, args.strip()))
                    _write_args(call, SKILL_ID, string_args=True)
                continue
            if inner in _SKILL_TOOLS:
                misses = _rewrite_dict(args)
                if misses:
                    found.extend((inner, original) for original in misses)
                    _write_args(call, args, string_args=string_args)
            nested = args.get("calls")
            if isinstance(nested, list):
                found.extend(_rewrite_into("tool_call", args))
    return found


def _rewrite_dict(arguments: dict) -> list[str]:
    misses = []
    for key in _ARG_KEYS:
        value = arguments.get(key)
        if not isinstance(value, str):
            continue
        if skill_id_status(value) != "miss":
            continue
        misses.append(value.strip())
        arguments[key] = SKILL_ID
    return misses


def _write_args(call: dict, args, *, string_args: bool) -> None:
    payload = json.dumps(args) if string_args and not isinstance(args, str) else args
    function = call.get("function")
    if isinstance(function, dict) and ("arguments" in function or "name" in function):
        function["arguments"] = payload if string_args else args
        return
    if "arguments" in call or "args" not in call:
        call["arguments"] = payload if string_args else args
    else:
        call["args"] = payload if string_args else args


def _structured_arguments(text: str) -> list[str]:
    found: list[str] = []
    stripped = text.strip()
    if stripped[:1] in "{[":
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            obj = None
        if obj is not None:
            return _arguments_in(obj)
    for line in text.splitlines():
        row = line.strip()
        if row[:1] in "{[":
            try:
                obj = json.loads(row)
            except json.JSONDecodeError:
                obj = None
            if obj is not None:
                found.extend(_arguments_in(obj))
                continue
        found.extend(_named_json_arguments(row))
    return found


def _named_json_arguments(line: str) -> list[str]:
    """Skill ids in ``TOOLCALL skill_view {json}`` and ``TOOLCALL tool_call {calls:[...]}``."""
    found: list[str] = []
    for match in _NAMED_JSON.finditer(line):
        tool = match.group(1).lower()
        try:
            obj = json.loads(match.group(2))
        except json.JSONDecodeError:
            continue
        if tool == "tool_call":
            arguments = obj if isinstance(obj, dict) else {"calls": obj}
            found.extend(_from_call({"name": "tool_call", "arguments": arguments}))
            continue
        if isinstance(obj, dict):
            found.extend(_from_call({"name": tool, "arguments": obj}))
        elif isinstance(obj, str):
            found.extend(_from_call({"name": tool, "arguments": {"name": obj}}))
    return found


def _arguments_in(obj) -> list[str]:
    found: list[str] = []
    if isinstance(obj, list):
        for item in obj:
            found.extend(_arguments_in(item))
        return found
    if not isinstance(obj, dict):
        return found
    messages = obj.get("messages")
    if isinstance(messages, list):
        for item in messages:
            found.extend(_arguments_in(item))
    if obj.get("tool_calls") is not None:
        found.extend(_from_calls(obj.get("tool_calls")))
    if "messages" not in obj:
        found.extend(_from_call(obj))
    return found


def _from_calls(raw) -> list[str]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if isinstance(raw, dict):
        return _from_call(raw)
    if not isinstance(raw, list):
        return []
    found = []
    for item in raw:
        found.extend(_from_call(item))
    return found


def _from_call(call) -> list[str]:
    if not isinstance(call, dict):
        return []
    name = _call_name(call)
    args = _call_args(call)
    found: list[str] = []
    if name in _SKILL_TOOLS:
        if isinstance(args, dict):
            for key in _ARG_KEYS:
                value = args.get(key)
                if isinstance(value, str):
                    found.append(value)
        elif isinstance(args, str):
            found.append(args)
    calls = None
    if isinstance(args, dict) and isinstance(args.get("calls"), list) and name in {None, "tool_call", *_SKILL_TOOLS}:
        calls = args["calls"]
    elif isinstance(call.get("calls"), list) and name in {None, "tool_call", *_SKILL_TOOLS}:
        calls = call["calls"]
    if calls:
        for inner in calls:
            found.extend(_from_call(inner))
    return found


def _call_name(call: dict) -> str | None:
    function = call.get("function")
    if isinstance(function, dict) and isinstance(function.get("name"), str):
        return function["name"].strip()
    name = call.get("name") or call.get("tool")
    if isinstance(name, str):
        return name.strip()
    return None


def _call_args(call: dict):
    for key in ("arguments", "args"):
        if key in call:
            return _parse_args(call.get(key))
    function = call.get("function")
    if isinstance(function, dict):
        return _call_args(function)
    return None


def _parse_args(raw):
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if text[:1] in "{[":
            try:
                loaded = json.loads(text)
            except json.JSONDecodeError:
                return raw
            if isinstance(loaded, dict):
                return loaded
        return raw
    return None
