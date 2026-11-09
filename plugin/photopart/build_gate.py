"""Approval for a photo-to-part build that bypasses ``photo_part_build``.

Hermes v0.21.7 asks for approval when a ``pre_tool_call`` hook returns
``{"action": "approve", "rule_key": "photo_part_build"}``. The same rule
covers the terminal and the code tool. ``PHOTOPART_BUILD_APPROVAL=allow``
(and the other off values used by the build tool) skips the prompt. Any
other value, including an empty one, still asks. Hermes blocks the command
when nobody can approve. Hermes ``--yolo`` (and ``HERMES_YOLO_MODE``)
auto-approves this action by Hermes design. The plugin still returns it.
That flag is separate from ``PHOTOPART_BUILD_APPROVAL``.

The check looks at the command text and, when a ``.py`` path is readable and
is not a test, at the first 64KB of that file. It does not execute the
script. A build whose command line and file text avoid these patterns is
not seen. ``SECURITY.md`` lists that limit.
"""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

APPROVAL_OFF = {"allow", "yes", "true", "1", "off", "skip"}

SHELL_TOOLS = frozenset(
    {
        "terminal",
        "shell",
        "bash",
        "sh",
        "zsh",
        "cmd",
        "powershell",
        "process",
        "run_command",
    }
)
CODE_TOOLS = frozenset(
    {
        "execute_code",
        "code_execution",
        "python",
        "python_exec",
        "repl",
    }
)
READ_TOOLS = frozenset({"read_file", "search_files", "read", "view_file", "get_file"})

_READONLY = frozenset(
    {
        "ls",
        "cat",
        "head",
        "tail",
        "less",
        "more",
        "rg",
        "grep",
        "egrep",
        "fgrep",
        "find",
        "stat",
        "file",
        "wc",
        "pwd",
        "echo",
        "printf",
        "which",
        "type",
        "true",
        "false",
        "cd",
        "git",
        "diff",
        "nl",
        "bat",
        "hexdump",
        "od",
        "strings",
        "sed",
        "awk",
        "cut",
        "sort",
        "uniq",
        "dirname",
        "basename",
        "realpath",
        "readlink",
        "whoami",
        "date",
        "printenv",
        ":",
        "[",
    }
)
_PREFIX = frozenset({"sudo", "command", "time", "nice", "nohup", "setsid", "stdbuf"})
_TEST_MODULES = frozenset({"pytest", "unittest", "nose", "nose2"})
_MESH = r"(?:stl|step|stp|3mf)"
_MESH_WRITE = re.compile(
    rf"(?:"
    rf"\.(?:export|export_stl|export_step)\s*\("
    rf"|exporters?\s*\."
    rf"|>\s*\S+\.{_MESH}\b"
    rf"|(?:--out(?:put)?|-o)\s+\S+\.{_MESH}\b"
    rf"|[\"'][^\"'\n]*\.{_MESH}[\"']"
    rf")",
    re.I,
)
_MESH_EXT = re.compile(rf"\.{_MESH}\b", re.I)
_CAD = re.compile(r"\b(?:cadquery|build123d|OCP)\b")
_FEATURES = re.compile(r"photopart\.(?:features|geometry|parts)\b")
_BUILD_MOD = re.compile(
    r"(?:"
    r"from\s+photopart\s+import\s+[^\n;]*\b(?:build_run|stamp)\b"
    r"|from\s+photopart\.(?:build_run|stamp)\b"
    r"|import\s+photopart\.(?:build_run|stamp)\b"
    r"|photopart[/\\](?:build_run|stamp)\.py"
    r"|\bphoto-part-build\b"
    r"|-m\s+photopart\.(?:build_run|stamp)\b"
    r")"
)
_EVAL_PATH = re.compile(
    r"(?:^|[^\w])evals[/\\](?:runner\.py|tasks\.json|meshes\.py|photos\.json|fixtures(?:[/\\]|$)|__init__\.py|README\.md)"
    r"|(?:^|[^\w])tests[/\\]regression(?:[/\\]|$)"
)
_EVAL_IMPORT = re.compile(
    r"(?:^|[^\w])(?:from\s+evals(?:\.|\s+import)|import\s+evals(?:\.|\s|$)|-m\s+evals\b)"
)
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SNIFF_CAP = 65_536
_SNIFF_MAX = 262_144

BLOCK_MESSAGE = (
    "photo-to-part blocks reading eval scoring files "
    "(evals/ runner, tasks, meshes, fixtures, and tests/regression). "
    "They are not part of the build. Use photo_part_template or photo_part_build."
)


def approval_skipped() -> bool:
    """True when a sealed eval or a test set ``PHOTOPART_BUILD_APPROVAL`` off."""
    return os.environ.get("PHOTOPART_BUILD_APPROVAL", "").strip().lower() in APPROVAL_OFF


def is_shell_tool(tool_name: str) -> bool:
    """Terminal, shell, and code-execution tools. ``read_terminal`` is not one."""
    name = str(tool_name or "").strip().lower()
    if not name or name.startswith("read_"):
        return False
    if name in SHELL_TOOLS or name in CODE_TOOLS:
        return True
    return name.endswith("_terminal") or name.endswith("_shell")


def terminal_build_approval(tool_name: str = "", args=None, *, session_id: str | None = None) -> dict | None:
    """Approve action when a shell or code tool runs a photo-to-part build.

    ``None`` means the command is not that kind of build, or approval is
    switched off. Hermes still fail-closes when this returns an approve
    action and nobody answers.
    """
    if not is_shell_tool(tool_name):
        return None
    if approval_skipped():
        return None
    command, workdir = _command_and_dir(args)
    if not command.strip():
        return None
    code_only = str(tool_name or "").strip().lower() in CODE_TOOLS and not _has_shell_field(args)
    if not _needs_approval(command, workdir=workdir, session_id=session_id, code_only=code_only):
        return None
    snippet = " ".join(command.split())
    if len(snippet) > 240:
        snippet = snippet[:237] + "..."
    where = workdir or "."
    return {
        "action": "approve",
        "message": f"Run {snippet} in {where}",
        "rule_key": "photo_part_build",
    }


def eval_read_block(tool_name: str = "", args=None) -> dict | None:
    """Block a tool that reads this repo's eval scorer or regression meshes.

    ``pytest`` and ``unittest`` are left alone. A plain ``ls`` or ``cat`` of
    some other file is left alone.
    """
    name = str(tool_name or "").strip().lower()
    if name.startswith("photo_part_") or name.startswith("read_terminal"):
        return None
    command, _workdir = _command_and_dir(args)
    if command and _command_is_tests(command):
        return None
    blob = command if isinstance(args, str) and not _as_dict(args) else _blob(args)
    if not blob:
        return None
    folded = blob.replace("\\", "/")
    if name in READ_TOOLS:
        path = _path_field(args)
        target = path.replace("\\", "/") if path else ""
        if target and (_EVAL_PATH.search(target) or "p2p-canary-" in target):
            return {"action": "block", "message": BLOCK_MESSAGE}
        return None
    if not is_shell_tool(name):
        return None
    if _EVAL_PATH.search(folded) or _EVAL_IMPORT.search(blob) or "p2p-canary-" in blob:
        return {"action": "block", "message": BLOCK_MESSAGE}
    return None


def protected_read_text(blob: str) -> bool:
    """True when raw tool text names a protected eval or regression path.

    Used only after the read check itself raises. ``pytest`` and
    ``unittest`` stay allowed. An ordinary README path does not match.
    """
    if not blob:
        return False
    if re.search(r"\b(?:pytest|py\.test|unittest|nose2?|tox)\b", blob):
        return False
    folded = blob.replace("\\", "/")
    return bool(_EVAL_PATH.search(folded) or _EVAL_IMPORT.search(blob) or "p2p-canary-" in blob)


def _needs_approval(command: str, *, workdir: str | None, session_id: str | None, code_only: bool) -> bool:
    if code_only:
        return python_source_is_build(command)
    if _command_is_tests(command):
        return False
    for segment in _segments(command):
        if _segment_is_build(segment, workdir=workdir, session_id=session_id):
            return True
    return False


def python_source_is_build(source: str) -> bool:
    """True when Python source imports the build modules or exports a mesh."""
    if not source or not source.strip():
        return False
    if _BUILD_MOD.search(source):
        return True
    write = _MESH_WRITE.search(source) or _MESH_EXT.search(source)
    if _CAD.search(source) and (write or re.search(r"\.(?:export|save)\s*\(|exporters", source)):
        return True
    if _FEATURES.search(source) and write:
        return True
    return False


def _segment_is_build(segment: str, *, workdir: str | None, session_id: str | None) -> bool:
    argv = _argv(segment)
    if not argv:
        return False
    if _is_readonly(argv) or _is_test_argv(argv):
        return False
    command = Path(argv[0]).name
    if command == "photo-part-build":
        return True
    if command in {"cadquery", "build123d", "cq"}:
        return True
    if _is_python(argv[0]):
        module = _option_value(argv, {"-m"})
        if module in {f"photopart.{name}" for name in ("build_run", "stamp")}:
            return True
        if module in _TEST_MODULES:
            return False
        code = _option_value(argv, {"-c"})
        if code and python_source_is_build(code):
            return True
        scripts = _script_args(argv)
        for script in scripts:
            if Path(script).name == "build.py":
                return True
            folded = script.replace("\\", "/")
            if folded.endswith("photopart/build_run.py") or folded.endswith("photopart/stamp.py"):
                return True
            if _script_text_is_build(script, workdir):
                return True
        if scripts and any(_MESH_EXT.search(token) for token in argv):
            return True
        if (_MESH_WRITE.search(segment) or _writes_into_project(segment, workdir, session_id)) and (
            _CAD.search(segment) or _FEATURES.search(segment) or scripts
        ):
            return True
        return False
    if _CAD.search(segment) and (_MESH_WRITE.search(segment) or _MESH_EXT.search(segment)):
        return True
    return False


def _script_text_is_build(script: str, workdir: str | None) -> bool:
    path = _resolve_script(script, workdir)
    if path is None:
        return False
    parts = set(path.parts)
    if "tests" in parts or "evals" in parts or path.name.startswith("test_"):
        return False
    try:
        if not path.is_file() or path.stat().st_size > _SNIFF_MAX:
            return False
        text = path.read_text(encoding="utf-8", errors="ignore")[:_SNIFF_CAP]
    except OSError:
        return False
    return python_source_is_build(text)


def _resolve_script(script: str, workdir: str | None) -> Path | None:
    if not script or script.startswith("-"):
        return None
    path = Path(script).expanduser()
    if not path.is_absolute():
        base = Path(workdir).expanduser() if workdir else Path.cwd()
        path = base / path
    try:
        return path.resolve()
    except OSError:
        return path


def _writes_into_project(segment: str, workdir: str | None, session_id: str | None) -> bool:
    if not session_id or not _MESH_EXT.search(segment):
        return False
    from photopart.hooks import session_project

    folder = session_project(session_id)
    if folder is None:
        return False
    folded = segment.replace("\\", "/")
    root = str(folder).replace("\\", "/")
    if root and root in folded:
        return True
    if not workdir:
        return False
    try:
        work = Path(workdir).expanduser().resolve()
        project = folder.expanduser().resolve()
    except OSError:
        return False
    return work == project or project in work.parents


def _command_is_tests(command: str) -> bool:
    segments = [segment for segment in _segments(command) if segment.strip()]
    if not segments:
        return False
    saw_test = False
    for segment in segments:
        argv = _argv(segment)
        if not argv:
            continue
        if _is_test_argv(argv):
            saw_test = True
            continue
        if _is_readonly(argv):
            continue
        return False
    return saw_test


def _is_test_argv(argv: list[str]) -> bool:
    command = Path(argv[0]).name
    if command in {"pytest", "py.test", "tox"}:
        return True
    if _is_python(argv[0]):
        module = _option_value(argv, {"-m"})
        return module in _TEST_MODULES
    return False


def _is_readonly(argv: list[str]) -> bool:
    return Path(argv[0]).name in _READONLY


def _is_python(token: str) -> bool:
    name = Path(token).name
    if name.endswith(".exe"):
        name = name[:-4]
    return name in {"python", "python3", "pypy", "pypy3"} or re.fullmatch(r"python\d+(?:\.\d+)?", name) is not None


def _script_args(argv: list[str]) -> list[str]:
    skip: set[int] = set()
    for index, token in enumerate(argv):
        if token in {"-c", "-m"} and index + 1 < len(argv):
            skip.add(index + 1)
    found = []
    for index, token in enumerate(argv):
        if index == 0 or index in skip or token.startswith("-"):
            continue
        if token.endswith(".py"):
            found.append(token)
    return found


def _option_value(argv: list[str], flags: set[str]) -> str | None:
    for index, token in enumerate(argv):
        if token in flags and index + 1 < len(argv):
            return argv[index + 1]
        for flag in flags:
            if token.startswith(flag + "="):
                return token.split("=", 1)[1]
    return None


def _argv(segment: str) -> list[str]:
    try:
        tokens = shlex.split(segment, posix=True)
    except ValueError:
        tokens = segment.split()
    tokens = _strip_prefix(tokens)
    return tokens


def _strip_prefix(argv: list[str]) -> list[str]:
    index = 0
    while index < len(argv):
        token = argv[index]
        if _ASSIGN.match(token):
            index += 1
            continue
        name = Path(token).name
        if name in _PREFIX:
            index += 1
            while index < len(argv) and argv[index].startswith("-") and argv[index] not in {"-c", "-m"}:
                index += 1
            continue
        if name == "env":
            index += 1
            while index < len(argv) and _ASSIGN.match(argv[index]):
                index += 1
            continue
        if name == "uv" and index + 1 < len(argv) and argv[index + 1] == "run":
            index += 2
            while index < len(argv) and argv[index].startswith("-") and argv[index] not in {"-c", "-m"}:
                index += 1
            continue
        break
    return argv[index:]


def _segments(command: str) -> list[str]:
    """Split on ``&&``, ``||``, ``|``, ``;``, and newlines, but not inside quotes.

    A ``python -c`` body may contain newlines. Splitting those would break
    the quotes and could also treat a later ``echo`` of a module name as
    Python source.
    """
    parts: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    index = 0
    length = len(command)
    while index < length:
        char = command[index]
        if quote:
            buf.append(char)
            if char == "\\" and quote == '"' and index + 1 < length:
                buf.append(command[index + 1])
                index += 2
                continue
            if char == quote:
                quote = None
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            buf.append(char)
            index += 1
            continue
        if command.startswith("&&", index) or command.startswith("||", index):
            parts.append("".join(buf).strip())
            buf = []
            index += 2
            continue
        if char in {";", "\n", "\r"}:
            parts.append("".join(buf).strip())
            buf = []
            index += 1
            continue
        if char == "|":
            parts.append("".join(buf).strip())
            buf = []
            index += 1
            continue
        buf.append(char)
        index += 1
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return [part for part in parts if part]


def _command_and_dir(args) -> tuple[str, str | None]:
    if isinstance(args, str) and not args.strip().startswith("{"):
        return args, None
    payload = _as_dict(args)
    if not payload:
        return args if isinstance(args, str) else "", None
    pieces = []
    for key in ("command", "cmd", "code", "script", "input"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            pieces.append(value)
        elif isinstance(value, (list, tuple)):
            pieces.append(" ".join(str(item) for item in value))
    workdir = None
    for key in ("workdir", "cwd", "working_directory"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            workdir = value.strip()
            break
    return "\n".join(pieces), workdir


def _has_shell_field(args) -> bool:
    payload = _as_dict(args)
    for key in ("command", "cmd"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return True
    return False


def _as_dict(args) -> dict:
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        text = args.strip()
        if text[:1] == "{":
            import json

            try:
                loaded = json.loads(text)
            except json.JSONDecodeError:
                return {}
            if isinstance(loaded, dict):
                return loaded
    return {}


def _blob(args) -> str:
    command, _workdir = _command_and_dir(args)
    if command:
        return command
    payload = _as_dict(args)
    parts = []
    for key in ("path", "file_path", "file", "pattern"):
        value = payload.get(key)
        if isinstance(value, str):
            parts.append(value)
    return "\n".join(parts)


def _path_field(args) -> str:
    payload = _as_dict(args)
    for key in ("path", "file_path", "file"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""
