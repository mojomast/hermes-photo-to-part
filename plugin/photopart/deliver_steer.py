"""After a template mesh validates, steer the agent to deliver it.

Live r19 runs still burned turns on vision_analyze and extra scripted
refines after a spur-gear template had already passed validation, then
hit the 80% budget wall. Tool results and pre_tool_call hooks tell the
agent to deliver the validated file, or do at most one measured refine
(photo_part_measure, then one photo_part_build or a second template).
Vision loops and further CAD or refine calls are blocked.

This policy applies only after a *template* result has passed
``photo_part_validate``. Measure-only sessions and non-template fitting
paths are left alone.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

DELIVER_HINT = (
    "A template mesh passed validation ({file}). Deliver it now with "
    "photo_part_render final=true, or do at most one measured refine "
    "(photo_part_measure, then one photo_part_build as a new name_vN.stl). "
    "Do not start a vision loop. Do not overwrite the validated file."
)

HOOK_NOTE = (
    "[photo-to-part] A validated template already exists. Deliver it with "
    "photo_part_render final=true, or do at most one measured refine. "
    "Do not start a vision loop."
)

VISION_BLOCK = (
    "[photo-to-part] A validated template already exists ({file}). "
    "Vision loops are blocked. Deliver that file with photo_part_render "
    "final=true, or do at most one measured refine (photo_part_measure, "
    "then one photo_part_build as a new name_vN.stl)."
)

REFINE_BLOCK = (
    "[photo-to-part] A validated template already exists ({file}) and the "
    "one allowed measured refine has been used. Deliver the best validated "
    "file with photo_part_render final=true. Do not start another version."
)

_VISION = re.compile(r"(?:^|_)vision(?:_|$)|image_analyze|analyze_image|describe_image")
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
_CAD = re.compile(
    r"\b(?:cadquery|build123d|cq\.|FreeCAD|OpenSCAD|solidpython|"
    r"trimesh(?:\.creation)?|Workplane|extrude|revolve|mesh\.export|"
    r"write_stl|stl\.write)\b|\.stl\b",
    re.IGNORECASE,
)
_PATH_KEYS = (
    "path",
    "file_path",
    "file",
    "filename",
    "mesh",
    "stl",
    "script",
    "cwd",
    "workdir",
    "out_dir",
    "out",
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

_memory: dict[str, dict] = {}


def reset() -> None:
    """Drop in-memory steer state. Tests call this between cases."""
    _memory.clear()


def is_template_mesh(path) -> bool:
    """True when ``path`` has a ``.template.json`` sidecar from photo_part_template."""
    mesh = _as_path(path)
    if mesh is None:
        return False
    return _sidecar(mesh).is_file()


def deliver_hint(path) -> str:
    mesh = _as_path(path)
    name = mesh.name if mesh is not None else "the validated template"
    return DELIVER_HINT.format(file=name)


def note_validated(path, directory: Path | None = None) -> dict | None:
    """Record that a template mesh passed photo_part_validate."""
    mesh = _as_path(path)
    if mesh is None or not is_template_mesh(mesh):
        return None
    folder = _resolve_dir(directory, mesh)
    if folder is None:
        return None
    state = _load(folder)
    prior = state.get("file")
    state["template_validated"] = True
    state["file"] = str(mesh.resolve()) if mesh.exists() else str(mesh)
    if prior and _same_file(prior, state["file"]):
        pass
    state.setdefault("refines", 0)
    _save(folder, state)
    return state


def note_tool(
    tool_name: str,
    arguments: dict | None,
    session_id: str | None = None,
    result=None,
    directory: Path | None = None,
) -> None:
    """Mark a refine attempt, or a passing template validate, after a tool returns."""
    args = arguments if isinstance(arguments, dict) else {}
    folder = _resolve_dir(directory, _as_path(args.get("file") or args.get("mesh") or args.get("stl")))
    payload = _parse_result(result)
    mesh = _as_path(payload.get("file") or args.get("file") or args.get("mesh") or args.get("stl"))
    if tool_name == "photo_part_validate" and payload.get("ok") and mesh is not None:
        note_validated(mesh, folder)
        return
    state = _load(folder) if folder is not None else {}
    if not state.get("template_validated"):
        return
    if tool_name in {"photo_part_build", "photo_part_template"}:
        _count_refine(folder, mesh)
        return


def steer_pre_tool(
    tool_name: str,
    arguments: dict | None,
    session_id: str | None = None,
    directory: Path | None = None,
    cwd: Path | None = None,
) -> dict | None:
    """Return a block directive, or None when the call may proceed."""
    name = str(tool_name or "")
    args = arguments if isinstance(arguments, dict) else {}
    folder = _resolve_dir(
        directory,
        _as_path(args.get("file") or args.get("mesh") or args.get("stl") or args.get("cwd") or args.get("project")),
        cwd,
    )
    state = _load(folder) if folder is not None else {}
    if not state.get("template_validated"):
        return None
    target = Path(state["file"]).name if state.get("file") else "the validated template"
    if _is_vision(name):
        return {"action": "block", "message": VISION_BLOCK.format(file=target)}
    if name in {"photo_part_validate", "photo_part_render", "photo_part_measure", "photo_part_heal"}:
        return None
    if name.startswith("photo_part_") and name not in {"photo_part_build", "photo_part_template"}:
        return None
    refines = int(state.get("refines") or 0)
    if name in {"photo_part_build", "photo_part_template"}:
        if refines >= 1:
            return {"action": "block", "message": REFINE_BLOCK.format(file=target)}
        return None
    if refines >= 1 and _is_cad_or_script(name, args, folder):
        return {"action": "block", "message": REFINE_BLOCK.format(file=target)}
    return None


def _count_refine(folder: Path | None, mesh: Path | None) -> None:
    if folder is None:
        return
    state = _load(folder)
    if not state.get("template_validated"):
        return
    # A rebuild of the same already-validated file is not a new refine, but
    # the hook still counts a fresh template or build call as the one allow.
    state["refines"] = int(state.get("refines") or 0) + 1
    if mesh is not None:
        state["last_refine"] = str(mesh)
    _save(folder, state)


def _is_vision(name: str) -> bool:
    lowered = name.lower().strip()
    if lowered in {"vision_analyze", "vision_describe", "vision", "analyze_image"}:
        return True
    return bool(_VISION.search(lowered))


def _is_cad_or_script(name: str, arguments: dict, folder: Path | None) -> bool:
    lowered = name.lower()
    writing = name in _WRITE_TOOLS or "write_file" in lowered or "apply_patch" in lowered
    coding = name in _CODE_TOOLS or "terminal" in lowered or "execute_code" in lowered
    if not (writing or coding):
        return False
    text = " ".join(_texts(arguments))
    path = _target_path(arguments, folder)
    combined = text
    if path is not None:
        combined = f"{combined} {path}"
        if path.suffix.lower() in {".py", ".cq", ".scad", ".stl", ".3mf"}:
            return True
    return bool(_CAD.search(combined))


def _texts(arguments: dict) -> list[str]:
    found: list[str] = []
    for key in _TEXT_KEYS + _PATH_KEYS:
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            found.append(value)
    return found


def _target_path(arguments: dict, folder: Path | None) -> Path | None:
    for key in _PATH_KEYS:
        value = arguments.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        path = Path(value).expanduser()
        if not path.is_absolute() and folder is not None:
            path = folder / path
        return path
    return None


def _sidecar(mesh: Path) -> Path:
    return Path(str(mesh) + ".template.json")


def _as_path(value) -> Path | None:
    if isinstance(value, Path):
        return value
    if isinstance(value, str) and value.strip():
        return Path(value).expanduser()
    return None


def _same_file(left: str, right: str) -> bool:
    try:
        return Path(left).resolve() == Path(right).resolve()
    except OSError:
        return Path(left) == Path(right)


def _resolve_dir(*candidates) -> Path | None:
    for item in candidates:
        path = _as_path(item) if not isinstance(item, Path) else item
        if path is None:
            continue
        folder = path if path.is_dir() else path.parent
        try:
            folder = folder.resolve()
        except OSError:
            pass
        if folder.is_dir():
            return folder
    try:
        cwd = Path.cwd()
    except OSError:
        return None
    return cwd


def _state_path(folder: Path) -> Path:
    return folder / ".photopart" / "deliver.json"


def _load(folder: Path | None) -> dict:
    if folder is None:
        return {}
    key = str(folder)
    path = _state_path(folder)
    if path.is_file():
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            doc = {}
        if isinstance(doc, dict):
            _memory[key] = doc
            return dict(doc)
    return dict(_memory.get(key) or {})


def _save(folder: Path, state: dict) -> None:
    _memory[str(folder)] = dict(state)
    path = _state_path(folder)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        return


def _parse_result(result) -> dict:
    if isinstance(result, dict):
        return result
    if not isinstance(result, str) or not result.strip():
        return {}
    text = result.strip()
    start = text.find("{")
    if start < 0:
        return {}
    try:
        doc = json.loads(text[start:])
    except json.JSONDecodeError:
        return {}
    return doc if isinstance(doc, dict) else {}
