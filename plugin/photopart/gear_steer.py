"""Hard-steer gear requests onto ``photo_part_template`` shape ``spur_gear``.

Live deepseek-v4.1-flash runs in r17 and r18 never called ``photo_part_*``.
They wrote an involute script with ``write_file`` and ran it from the
terminal until the 40-turn cap. This module is consulted from
``pre_tool_call``. It blocks that path until the spur-gear template has
been tried, including a failed call, then lifts the block.

Sessions that are not a photo-to-part gear request are left alone. The
plugin checkout and install directory are never blocked.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

BLOCK_MESSAGE = (
    "[photo-to-part] Call photo_part_template with shape spur_gear before "
    "writing or running a gear or involute script. The plugin already ships "
    "an involute spur-gear template. After that template has been tried, "
    "including a failure, you may script a refinement."
)

_GEAR_WORD = re.compile(
    r"\b(?:involute|sprockets?|spur|gears?|teeth|tooth)\b",
    re.IGNORECASE,
)
_P2P_WORD = re.compile(
    r"\b(?:photo|photos|printable|print|stl|3mf|recreate|scan|scans|"
    r"measurement|measure|overlay|part studio)\b",
    re.IGNORECASE,
)
_GEAR_MATH = re.compile(
    r"involute|spur[_\s-]?gear|gear_profile|build_gear|pressure_angle|"
    r"base[_\s-]?circle|pitch[_\s-]?circle|pitch[_\s-]?diameter|addendum|"
    r"dedendum|trochoid|tooth[_\s-]?profile|circular[_\s-]?pitch|"
    r"diametral[_\s-]?pitch|module_mm",
    re.IGNORECASE,
)
_CAD = re.compile(
    r"\b(?:cadquery|build123d|cq\.|FreeCAD|OpenSCAD|solidpython|"
    r"trimesh(?:\.creation)?|Workplane|extrude|revolve|mesh\.export|"
    r"write_stl|stl\.write)\b|\.stl\b",
    re.IGNORECASE,
)
_ANALYSIS = re.compile(
    r"\b(?:cv2|PIL|Pillow|Image\.open|imread|skimage)\b",
)
_WRITE_TOOLS = {
    "write_file",
    "create_file",
    "edit_file",
    "str_replace",
    "replace",
    "apply_patch",
    "patch",
    "search_replace",
}
_CODE_TOOLS = {
    "terminal",
    "execute_code",
    "code_execution",
    "bash",
    "shell",
    "python",
    "run_command",
}
_PATH_KEYS = (
    "path",
    "file_path",
    "file",
    "filename",
    "dest",
    "destination",
    "script",
    "cwd",
    "workdir",
    "out_dir",
    "project",
)
_TEXT_KEYS = (
    "content",
    "contents",
    "code",
    "command",
    "cmd",
    "script",
    "input",
    "new_string",
    "old_string",
    "patch",
    "diff",
    "text",
    "body",
    "file_text",
)
_SCRIPT_SUFFIXES = {".py", ".cq", ".scad", ".FCStd", ".fcstd"}

_gear_sessions: set[str] = set()
_p2p_sessions: set[str] = set()
_tried: set[str] = set()
_prompts: dict[str, str] = {}
_tried_dirs: set[str] = set()


def reset() -> None:
    """Drop in-memory steer state. Tests call this between cases."""
    _gear_sessions.clear()
    _p2p_sessions.clear()
    _tried.clear()
    _prompts.clear()
    _tried_dirs.clear()


def note_user_message(session_id: str | None, user_message) -> None:
    """Remember whether this session looks like a photo-to-part gear request."""
    sid = _sid(session_id)
    text, has_image = _message_parts(user_message)
    if not sid and not text and not has_image:
        return
    if text:
        if sid:
            existing = _prompts.get(sid, "")
            _prompts[sid] = (existing + "\n" + text).strip() if existing else text
        if _GEAR_WORD.search(text):
            if sid:
                _gear_sessions.add(sid)
        if has_image or _P2P_WORD.search(text):
            if sid:
                _p2p_sessions.add(sid)
    elif has_image and sid:
        _p2p_sessions.add(sid)


def note_tool(tool_name: str, arguments: dict | None, session_id: str | None = None) -> None:
    """Mark the spur-gear template as tried after a call, success or failure."""
    if not _is_spur_gear_template(tool_name, arguments if isinstance(arguments, dict) else {}):
        return
    sid = _sid(session_id)
    if sid:
        _tried.add(sid)
    directory = _project_dir(arguments if isinstance(arguments, dict) else {})
    if directory is not None:
        _mark_tried_dir(directory)


def template_tried(session_id: str | None, arguments: dict | None = None, directory: Path | None = None) -> bool:
    """True when ``photo_part_template`` shape ``spur_gear`` has already been attempted."""
    sid = _sid(session_id)
    if sid and sid in _tried:
        return True
    folders = []
    if directory is not None:
        folders.append(directory)
    if isinstance(arguments, dict):
        found = _project_dir(arguments)
        if found is not None:
            folders.append(found)
    cwd = _safe_cwd()
    if cwd is not None:
        folders.append(cwd)
    for folder in folders:
        if _dir_tried(folder):
            if sid:
                _tried.add(sid)
            return True
    return False


def steer_pre_tool(
    tool_name: str,
    arguments: dict | None,
    session_id: str | None = None,
    cwd: Path | None = None,
) -> dict | None:
    """Return a block directive, or None when the call may proceed."""
    name = str(tool_name or "")
    args = arguments if isinstance(arguments, dict) else {}
    here = cwd if cwd is not None else _safe_cwd()
    if _is_spur_gear_template(name, args):
        return None
    if name.startswith("photo_part_") and name != "photo_part_build":
        return None
    if name == "photo_part_build" and _is_help(args):
        return None
    if template_tried(session_id, args, here):
        return None
    if _in_plugin_tree(here, args):
        return None
    context = _photo_part_context(session_id, args, here)
    gearish = _gearish(session_id, args, here)
    payload = _payload_text(args)
    math = bool(_GEAR_MATH.search(payload) or _GEAR_MATH.search(_file_text(args, here)))
    if not context:
        return None
    if not (gearish or math):
        return None
    if _should_block(name, args, here, session_is_gear=gearish, math=math):
        return {"action": "block", "message": BLOCK_MESSAGE}
    return None


def _should_block(tool_name: str, arguments: dict, cwd: Path | None, *, session_is_gear: bool, math: bool) -> bool:
    if tool_name == "photo_part_build":
        return True
    lowered = tool_name.lower()
    writing = tool_name in _WRITE_TOOLS or "write_file" in lowered or "apply_patch" in lowered
    coding = tool_name in _CODE_TOOLS or "terminal" in lowered or "execute_code" in lowered
    if not (writing or coding):
        return False
    text = _payload_text(arguments)
    file_text = _file_text(arguments, cwd)
    combined = f"{text}\n{file_text}"
    path = _target_path(arguments, cwd)
    path_text = str(path) if path is not None else ""
    if math or _GEAR_MATH.search(combined) or _GEAR_MATH.search(path_text):
        return True
    if session_is_gear and _is_cad_script(tool_name, arguments, cwd, combined, path):
        return True
    return False


def _is_cad_script(tool_name: str, arguments: dict, cwd: Path | None, combined: str, path: Path | None) -> bool:
    if _is_analysis_only(combined):
        return False
    if _CAD.search(combined):
        return True
    if path is not None:
        name = path.name.lower()
        suffix = path.suffix
        if suffix in _SCRIPT_SUFFIXES and (
            "gear" in name or name.startswith("build_") or name.startswith("make_")
        ):
            return True
        if suffix in _SCRIPT_SUFFIXES and _CAD.search(combined or _read_small(path)):
            return True
    command = " ".join(str(arguments.get(key) or "") for key in ("command", "cmd", "code", "script", "input"))
    if re.search(r"\bpython(?:3)?\b", command, re.IGNORECASE) and re.search(
        r"\b(?:build_[A-Za-z0-9_]+\.py|[A-Za-z0-9_]*gear[A-Za-z0-9_]*\.py)\b",
        command,
        re.IGNORECASE,
    ):
        return True
    return False


def _is_analysis_only(text: str) -> bool:
    if not text or not _ANALYSIS.search(text):
        return False
    if _GEAR_MATH.search(text) or _CAD.search(text):
        return False
    return True


def _is_spur_gear_template(tool_name: str, arguments: dict) -> bool:
    if tool_name != "photo_part_template":
        return False
    shape = _shape_of(arguments)
    if not shape:
        return False
    folded = re.sub(r"[\s-]+", "_", shape.strip().lower())
    return folded in {"spur_gear", "gear", "involute_gear"}


def _shape_of(arguments: dict) -> str:
    for key in ("shape", "name", "template", "kind"):
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return value
    params = arguments.get("params")
    if isinstance(params, dict):
        for key in ("shape", "name", "template", "kind"):
            value = params.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return ""


def _photo_part_context(session_id: str | None, arguments: dict, cwd: Path | None) -> bool:
    sid = _sid(session_id)
    if sid and (sid in _p2p_sessions or sid in _gear_sessions):
        # A gear-marked session from a prompt that also mentioned a photo or
        # an attached image is enough. A gear-only mark still needs another
        # photo-to-part signal (image, prompt file, or project files).
        if sid in _p2p_sessions:
            return True
    text = _prompt_text(sid, cwd)
    if text and _P2P_WORD.search(text):
        return True
    if _has_project_markers(arguments, cwd):
        return True
    if sid:
        try:
            from photopart.hooks import session_project

            if session_project(sid) is not None:
                return True
        except Exception:
            pass
        try:
            from photopart.hooks import _active, _images

            if sid in _active or _images.get(sid):
                return True
        except Exception:
            pass
    return False


def _gearish(session_id: str | None, arguments: dict, cwd: Path | None) -> bool:
    sid = _sid(session_id)
    if sid and sid in _gear_sessions:
        return True
    text = _prompt_text(sid, cwd)
    if text and _GEAR_WORD.search(text):
        if sid:
            _gear_sessions.add(sid)
        return True
    payload = _payload_text(arguments)
    if payload and _GEAR_WORD.search(payload):
        return True
    return False


def _prompt_text(session_id: str | None, cwd: Path | None) -> str:
    chunks: list[str] = []
    sid = _sid(session_id)
    if sid and sid in _prompts:
        chunks.append(_prompts[sid])
    for folder in (cwd, _safe_cwd()):
        if folder is None:
            continue
        prompt = folder / "prompt.txt"
        if prompt.is_file():
            try:
                if prompt.stat().st_size <= 64_000:
                    chunks.append(prompt.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                continue
    return "\n".join(chunks)


def _has_project_markers(arguments: dict, cwd: Path | None) -> bool:
    folders: list[Path] = []
    if cwd is not None:
        folders.append(cwd)
    for key in _PATH_KEYS:
        value = arguments.get(key) if isinstance(arguments, dict) else None
        if isinstance(value, str) and value.strip():
            path = Path(value).expanduser()
            folders.append(path if path.suffix.lower() in {".py", ".stl", ".png", ".jpg", ".jpeg", ".webp"} else path)
            if path.suffix:
                folders.append(path.parent)
    image = arguments.get("image") if isinstance(arguments, dict) else None
    if isinstance(image, str) and image.strip():
        folders.append(Path(image).expanduser().parent)
        return True
    for folder in folders:
        try:
            root = folder if folder.is_dir() else folder.parent
        except OSError:
            continue
        if (root / ".photopart").is_dir():
            return True
        if (root / "prompt.txt").is_file() and _has_photo(root):
            return True
    return False


def _has_photo(folder: Path) -> bool:
    for name in ("photo.jpg", "photo.jpeg", "photo.png", "photo.webp"):
        if (folder / name).is_file():
            return True
    return False


def _payload_text(arguments: dict) -> str:
    parts: list[str] = []
    if not isinstance(arguments, dict):
        return ""

    def walk(value, depth=0):
        if depth > 6:
            return
        if isinstance(value, str):
            if value.strip():
                parts.append(value[:20_000])
            return
        if isinstance(value, dict):
            for item in value.values():
                walk(item, depth + 1)
            return
        if isinstance(value, (list, tuple)):
            for item in value[:40]:
                walk(item, depth + 1)

    for key in _TEXT_KEYS:
        if key in arguments:
            walk(arguments[key])
    walk(arguments)
    return "\n".join(parts)


def _file_text(arguments: dict, cwd: Path | None) -> str:
    path = _target_path(arguments, cwd)
    if path is None:
        return ""
    return _read_small(path)


def _target_path(arguments: dict, cwd: Path | None) -> Path | None:
    if not isinstance(arguments, dict):
        return None
    for key in _PATH_KEYS:
        value = arguments.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        path = Path(value).expanduser()
        if not path.is_absolute() and cwd is not None:
            path = cwd / path
        if path.suffix.lower() in _SCRIPT_SUFFIXES or path.suffix.lower() in {".py"}:
            return path
    command = " ".join(str(arguments.get(key) or "") for key in ("command", "cmd", "code"))
    match = re.search(r"([^\s\"']+\.py)\b", command)
    if match:
        path = Path(match.group(1)).expanduser()
        if not path.is_absolute() and cwd is not None:
            path = cwd / path
        return path
    return None


def _read_small(path: Path) -> str:
    try:
        if not path.is_file() or path.stat().st_size > 256_000:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _project_dir(arguments: dict) -> Path | None:
    if not isinstance(arguments, dict):
        return None
    try:
        from photopart.budget import project_dir

        if any(isinstance(arguments.get(key), str) and arguments.get(key).strip() for key in ("file", "mesh", "stl", "script", "image", "out_dir", "cwd", "out", "project")):
            return project_dir(arguments)
    except Exception:
        pass
    for key in ("out_dir", "cwd", "project", "workdir"):
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            path = Path(value).expanduser()
            return path if path.suffix == "" or path.is_dir() else path.parent
    return None


def _mark_tried_dir(directory: Path) -> None:
    try:
        path = Path(directory).expanduser().resolve()
    except OSError:
        return
    _tried_dirs.add(str(path))
    try:
        from photopart.paths import writable_project

        if writable_project(path) is None:
            return
    except Exception:
        return
    target = path / ".photopart" / "gear.json"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {"template_tried": True, "shape": "spur_gear"}
        target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        return


def _dir_tried(directory: Path) -> bool:
    try:
        path = Path(directory).expanduser().resolve()
    except OSError:
        return False
    if str(path) in _tried_dirs:
        return True
    target = path / ".photopart" / "gear.json"
    if not target.is_file():
        return False
    try:
        loaded = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return False
    if isinstance(loaded, dict) and loaded.get("template_tried"):
        _tried_dirs.add(str(path))
        return True
    return False


def _in_plugin_tree(cwd: Path | None, arguments: dict) -> bool:
    try:
        from photopart.paths import not_a_project, plugin_root, source_checkout_root
    except Exception:
        return False
    roots = [root for root in (plugin_root(), source_checkout_root()) if root is not None]
    candidates = []
    if cwd is not None:
        candidates.append(cwd)
    path = _target_path(arguments, cwd)
    if path is not None:
        candidates.append(path)
    for candidate in candidates:
        try:
            resolved = Path(candidate).expanduser().resolve()
        except OSError:
            continue
        if not_a_project(resolved):
            return True
        for root in roots:
            try:
                resolved.relative_to(root)
                return True
            except ValueError:
                continue
    return False


def _is_help(arguments: dict) -> bool:
    if arguments.get("help") or arguments.get("describe"):
        return True
    return str(arguments.get("mode") or "").strip().lower() in {"help", "describe"}


def _message_parts(user_message) -> tuple[str, bool]:
    if user_message is None:
        return "", False
    if isinstance(user_message, str):
        return user_message, False
    texts: list[str] = []
    has_image = False
    if isinstance(user_message, dict):
        items = [user_message]
    elif isinstance(user_message, (list, tuple)):
        items = list(user_message)
    else:
        return str(user_message), False
    for item in items:
        if isinstance(item, str):
            texts.append(item)
            continue
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or item.get("kind") or "").lower()
        if kind in {"image", "image_url", "input_image", "photo"} or item.get("image_url") or item.get("image"):
            has_image = True
        for key in ("text", "content", "prompt"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                texts.append(value)
            elif isinstance(value, list):
                nested, nested_image = _message_parts(value)
                if nested:
                    texts.append(nested)
                has_image = has_image or nested_image
    return "\n".join(texts), has_image


def _sid(session_id: str | None) -> str:
    return "" if session_id is None else str(session_id).strip()


def _safe_cwd() -> Path | None:
    try:
        return Path.cwd()
    except OSError:
        return None
