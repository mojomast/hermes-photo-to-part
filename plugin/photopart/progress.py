"""Structured progress for the optional Part studio pane.

Tools call ``note_start``, ``note_result``, and ``note_approval``. Each call
rewrites ``<project>/.photopart/pane.json`` and, when ``HERMES_HOME`` is set,
an index under ``$HERMES_HOME/.photopart/pane-index.json``. A desktop pane
reads that index through ``plugin_api.py``. Nothing here is a tool argument.

Failures are swallowed by the callers. A missing desktop, a missing
``broadcast_plugin_event``, or a project this plugin must not write (the
install directory, the source checkout, ``evals/``, ``tests/regression``)
leaves the tools' return values unchanged.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

_LOCK = threading.Lock()
_LAST = threading.local()
_VERSION_RE = re.compile(r"_v(\d+)$")
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
_DIR_KEYS = ("out_dir", "cwd", "project")
_FILE_KEYS = ("mesh", "file", "stl", "out", "image", "photo", "script", "spec")
_NEST_KEYS = ("render",)
_STAGE_FOR_TOOL = {
    "photo_part_measure": "ingest",
    "photo_part_heal": "ingest",
    "photo_part_template": "build",
    "photo_part_build": "build",
    "photo_part_validate": "spec",
    "photo_part_render": "render",
}
_APPROVAL_OFF = {"allow", "yes", "true", "1", "off", "skip"}


def note_start(tool: str, args: dict | None) -> None:
    """Mark a tool as running. No-op for help and describe."""
    try:
        if not isinstance(args, dict) or _is_help(args):
            return
        _update(tool, args, phase="start")
    except Exception:
        return


def note_result(tool: str, payload: dict | None) -> None:
    """Fold a tool result into the project pane state."""
    try:
        if not isinstance(payload, dict) or _is_help(payload):
            return
        directory = project_for(payload)
        if directory is None and getattr(_LAST, "tool", None) == tool:
            remembered = getattr(_LAST, "project", None)
            if isinstance(remembered, Path) and remembered.is_dir() and not _blocked(remembered):
                directory = remembered
        if directory is None:
            return
        with _LOCK:
            state = _load(directory)
            _apply_result(state, tool, payload)
            _save(directory, state)
    except Exception:
        return


def note_approval(project, message: str = "", rule_key: str = "photo_part_build") -> None:
    """Record that Hermes is waiting on the build approval gate."""
    try:
        directory = _directory(project)
        if directory is None:
            return
        with _LOCK:
            state = _load(directory)
            state["approval"] = {
                "status": "waiting",
                "message": _clip(message, 240),
                "rule_key": rule_key or "photo_part_build",
                "at": _now(),
            }
            state["stage"] = "approval"
            state["status"] = "waiting"
            state["message"] = _clip(message, 180) or "Waiting for approval before the build runs."
            state["tool"] = "photo_part_build"
            _event(state, "photo_part_build", "approval", state["message"], ok=True)
            _save(directory, state)
    except Exception:
        return


def _update(tool: str, payload: dict, *, phase: str) -> None:
    directory = project_for(payload)
    if directory is None:
        return
    _LAST.tool = tool
    _LAST.project = directory
    with _LOCK:
        state = _load(directory)
        if phase == "start":
            _apply_start(state, tool, payload)
        else:
            _apply_result(state, tool, payload)
        _save(directory, state)


def _apply_start(state: dict, tool: str, args: dict) -> None:
    stage = _STAGE_FOR_TOOL.get(tool, "build")
    if tool == "photo_part_build":
        approval = state.get("approval") if isinstance(state.get("approval"), dict) else {}
        if os.environ.get("PHOTOPART_BUILD_APPROVAL", "").strip().lower() in _APPROVAL_OFF:
            approval = {
                "status": "skipped",
                "message": "Build approval is skipped in this process.",
                "rule_key": "photo_part_build",
                "at": _now(),
            }
            _mark_done(state, "approval")
        elif approval.get("status") == "waiting":
            approval = {
                "status": "approved",
                "message": approval.get("message") or "Build approved.",
                "rule_key": approval.get("rule_key") or "photo_part_build",
                "at": _now(),
            }
            _mark_done(state, "approval")
        state["approval"] = approval
    iteration = _peek_iteration(state, args)
    if iteration >= 2 and stage in {"build", "render", "spec"}:
        state["refining"] = True
        state["iteration"] = iteration
        state["message"] = f"Refinement {iteration}. " + _start_message(tool)
    else:
        state["message"] = _start_message(tool)
    state["stage"] = "refine" if state.get("refining") and stage in {"build", "render"} else stage
    if state.get("status") != "error":
        state["status"] = "running"
    state["tool"] = tool
    state["title"] = _title(Path(state["project"]), args) or state.get("title")
    _event(state, tool, state["stage"], state["message"], ok=True)


def _apply_result(state: dict, tool: str, payload: dict) -> None:
    layers = _layers(payload)
    ok = payload.get("ok") is not False and not payload.get("error")
    _absorb_metrics(state, layers)
    _absorb_images(state, layers)
    _absorb_outputs(state, layers)
    warnings = _warnings(layers)
    kept = [item for item in state.get("warnings") or [] if isinstance(item, str)]
    if _iou(layers) is not None:
        kept = [item for item in kept if "overlay fit" not in item.lower()]
    if warnings or _iou(layers) is not None:
        state["warnings"] = _unique(kept + warnings)[:8]
    if ok:
        state["errors"] = []
    else:
        state["errors"] = _errors(payload)[:6]
    if tool in {"photo_part_measure", "photo_part_heal"} and ok:
        _mark_done(state, "ingest")
    if _has_scale(layers):
        _mark_done(state, "scale")
    if _has_segment(layers):
        _mark_done(state, "segment")
    if tool == "photo_part_validate":
        _mark_done(state, "spec")
        if ok:
            state["validated"] = True
    if tool == "photo_part_template" and ok:
        _mark_done(state, "build")
        approval = state.get("approval") if isinstance(state.get("approval"), dict) else {}
        if approval.get("status") in {None, "", "idle"}:
            state["approval"] = {
                "status": "not_required",
                "message": "This template writes a known solid. photo_part_build still asks before a script runs.",
                "rule_key": "photo_part_build",
                "at": _now(),
            }
    if tool == "photo_part_build" and ok:
        _mark_done(state, "build")
        _mark_done(state, "approval")
        approval = state.get("approval") if isinstance(state.get("approval"), dict) else {}
        if approval.get("status") in {None, "", "idle", "waiting"}:
            status = "skipped" if os.environ.get("PHOTOPART_BUILD_APPROVAL", "").strip().lower() in _APPROVAL_OFF else "approved"
            state["approval"] = {
                "status": status,
                "message": approval.get("message") or "Build finished.",
                "rule_key": "photo_part_build",
                "at": _now(),
            }
    if tool == "photo_part_render" or _nested_render(layers):
        _mark_done(state, "render")
        if _has_compare(layers):
            _mark_done(state, "compare")
    mesh = _mesh_path(layers)
    if mesh or _image_map(state):
        if tool in {"photo_part_render", "photo_part_template", "photo_part_build", "photo_part_heal"} or _nested_render(layers):
            _upsert_iteration(state, tool, payload, ok=ok)
    iteration = int(state.get("iteration") or 0)
    if iteration >= 2 and ok and tool in {"photo_part_render", "photo_part_validate", "photo_part_build", "photo_part_template"}:
        state["refining"] = True
    stage = _result_stage(state, tool, ok, layers)
    state["stage"] = stage
    state["tool"] = tool
    state["title"] = _title(Path(state["project"]), payload) or state.get("title")
    if not ok:
        state["status"] = "error"
        state["message"] = (state.get("errors") or ["The step failed."])[0]
    elif state.get("validated") and "compare" in (state.get("done_stages") or []) and tool in {
        "photo_part_validate",
        "photo_part_render",
    }:
        state["status"] = "ready"
        _mark_done(state, "refine" if iteration >= 2 else "")
        state["message"] = "Ready to deliver. The latest check passed."
        if iteration >= 2:
            state["refining"] = False
    else:
        state["status"] = "running"
        state["message"] = _result_message(tool, state, payload)
    _event(state, tool, stage, state["message"], ok=ok)


def _result_stage(state: dict, tool: str, ok: bool, layers: list[dict]) -> str:
    if not ok:
        return _STAGE_FOR_TOOL.get(tool, state.get("stage") or "build")
    done = set(state.get("done_stages") or [])
    if tool == "photo_part_render" or (tool == "photo_part_validate" and _nested_render(layers)):
        if "compare" in done:
            return "compare"
        return "render"
    if tool == "photo_part_measure":
        if "segment" in done:
            return "segment"
        if "scale" in done:
            return "scale"
        return "ingest"
    if int(state.get("iteration") or 0) >= 2 and state.get("refining"):
        return "refine"
    return _STAGE_FOR_TOOL.get(tool, state.get("stage") or "build")


def _result_message(tool: str, state: dict, payload: dict) -> str:
    iteration = int(state.get("iteration") or 0)
    if tool == "photo_part_measure":
        source = (state.get("metrics") or {}).get("scale_source")
        if source:
            return f"Scale from {source}."
        return "Photo read."
    if tool == "photo_part_render":
        if iteration >= 2:
            return f"Refinement {iteration} rendered."
        return "Render ready to compare with the photo."
    if tool == "photo_part_validate":
        if payload.get("spec") or payload.get("target_mm"):
            return "Checked against the spec."
        return "Mesh checked."
    if tool == "photo_part_build":
        return "Build finished."
    if tool == "photo_part_template":
        return "Template solid written."
    if tool == "photo_part_heal":
        return "Scan healed."
    return "Updated."


def _start_message(tool: str) -> str:
    return {
        "photo_part_measure": "Reading the photo and looking for a scale reference.",
        "photo_part_heal": "Healing the scan.",
        "photo_part_template": "Writing a template solid.",
        "photo_part_build": "Building the solid.",
        "photo_part_validate": "Checking the mesh against the spec.",
        "photo_part_render": "Rendering views and the photo overlay.",
    }.get(tool, "Working.")


def _absorb_metrics(state: dict, layers: list[dict]) -> None:
    metrics = state.setdefault("metrics", {})
    source = _scale_source(layers)
    if source:
        metrics["scale_source"] = source
    confidence = _confidence(layers)
    if confidence:
        metrics["scale_confidence"] = confidence
    px = _first_number(layers, "px_per_mm", "photo_scale", "photo_scale_px_per_mm")
    if px is not None:
        metrics["px_per_mm"] = px
    iou = _iou(layers)
    if iou is not None:
        metrics["iou"] = iou
    label = _first_text(layers, "overlay_iou_label")
    if label:
        metrics["iou_label"] = label
    trusted = _iou_trusted(layers)
    if trusted is not None:
        metrics["iou_trusted"] = trusted
    trust = _trust(layers, metrics)
    if trust:
        metrics["trust"] = trust
    dimensions = _dimensions(layers)
    if dimensions:
        metrics["dimensions"] = dimensions
    note = _first_text(layers, "photo_scale_note")
    if note:
        metrics["scale_note"] = _clip(note, 180)


def _absorb_images(state: dict, layers: list[dict]) -> None:
    project = Path(state["project"])
    images = state.setdefault("images", {})
    found = {
        "photo": _first_text(layers, "image", "photo"),
        "overlay": _first_text(layers, "overlay", "mask_png"),
        "compare": _first_text(layers, "compare_front"),
        "render": _front_view(layers),
        "rectified": _first_text(layers, "rectified"),
    }
    for key, raw in found.items():
        accepted = _accept_image(project, raw)
        if accepted:
            images[key] = accepted


def _absorb_outputs(state: dict, layers: list[dict]) -> None:
    project = Path(state["project"])
    current = state.setdefault("outputs", [])
    known = {item.get("path") for item in current if isinstance(item, dict)}
    for raw in _output_paths(layers):
        accepted = _accept_output(project, raw)
        if not accepted or accepted in known:
            continue
        known.add(accepted)
        current.append({"kind": _kind(accepted), "path": accepted})
    state["outputs"] = current[:12]


def _upsert_iteration(state: dict, tool: str, payload: dict, *, ok: bool) -> None:
    layers = _layers(payload)
    mesh = _mesh_path(layers)
    number = _version_number(mesh)
    iterations = state.setdefault("iterations", [])
    if number is None:
        number = max([int(item.get("n") or 0) for item in iterations] + [0]) + 1
    images = state.get("images") if isinstance(state.get("images"), dict) else {}
    metrics = state.get("metrics") if isinstance(state.get("metrics"), dict) else {}
    card = {
        "n": number,
        "label": f"v{number}",
        "tool": tool,
        "ok": bool(ok),
        "mesh": mesh,
        "iou": metrics.get("iou"),
        "trust": metrics.get("trust"),
        "photo": images.get("photo"),
        "overlay": images.get("overlay"),
        "render": images.get("render"),
        "compare": images.get("compare"),
        "at": _now(),
    }
    replaced = False
    for index, item in enumerate(iterations):
        if isinstance(item, dict) and item.get("n") == number:
            iterations[index] = card
            replaced = True
            break
    if not replaced:
        iterations.append(card)
    state["iterations"] = iterations[-12:]
    state["iteration"] = number


def _peek_iteration(state: dict, args: dict) -> int:
    mesh = _mesh_path(_layers(args))
    number = _version_number(mesh)
    if number is not None:
        return number
    current = max([int(item.get("n") or 0) for item in state.get("iterations") or []] + [0])
    return current + 1 if current else 1


def project_for(payload: dict) -> Path | None:
    """Project directory for a tool payload, or None when it must not be written."""
    if not isinstance(payload, dict):
        return None
    candidates: list[Path] = []
    for key in _DIR_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append(Path(value))
    for key in _FILE_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append(Path(value).expanduser().parent)
    outputs = payload.get("outputs")
    if isinstance(outputs, list):
        for item in outputs:
            if isinstance(item, str) and item.strip():
                candidates.append(Path(item).expanduser().parent)
                break
    for key in ("overlay", "compare_front", "sheet"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append(Path(value).expanduser().parent)
    render = payload.get("render")
    if isinstance(render, dict):
        for key in ("overlay", "sheet", "photo"):
            value = render.get(key)
            if isinstance(value, str) and value.strip():
                candidates.append(Path(value).expanduser().parent)
    for raw in candidates:
        directory = _directory(raw)
        if directory is not None:
            return directory
    return None


def _directory(raw) -> Path | None:
    from photopart.paths import not_a_project

    if raw is None:
        return None
    try:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        resolved = path.resolve()
    except OSError:
        return None
    if resolved.name in {"renders", ".photopart", ".p2p_history"}:
        resolved = resolved.parent
    if not resolved.exists() or not resolved.is_dir():
        return None
    if not_a_project(resolved) or _blocked(resolved):
        return None
    return resolved


def _blocked(path: Path) -> bool:
    """True for eval scoring trees and regression meshes. The pane must not read them."""
    try:
        parts = {part.lower() for part in path.resolve().parts}
    except OSError:
        return True
    if "evals" in parts:
        return True
    if "regression" in parts and "tests" in parts:
        return True
    return False


def _accept_image(project: Path, raw) -> str | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        path = Path(raw).expanduser().resolve()
    except OSError:
        return None
    if not path.is_file() or path.suffix.lower() not in _IMAGE_SUFFIXES:
        return None
    if _blocked(path) or _canary(path):
        return None
    try:
        path.relative_to(project)
    except ValueError:
        return None
    try:
        if path.stat().st_size > 12_000_000:
            return None
    except OSError:
        return None
    return str(path)


def _accept_output(project: Path, raw) -> str | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        path = Path(raw).expanduser().resolve()
    except OSError:
        return None
    if path.suffix.lower() not in {".stl", ".3mf", ".scad", ".step", ".stp"}:
        return None
    if not path.is_file() or _blocked(path):
        return None
    try:
        path.relative_to(project)
    except ValueError:
        return None
    return str(path)


def _canary(path: Path) -> bool:
    try:
        blob = path.read_bytes()[:65536]
    except OSError:
        return True
    return b"p2p-canary-" in blob


def _load(directory: Path) -> dict:
    path = directory / ".photopart" / "pane.json"
    state = _read_json(path)
    if state.get("project") != str(directory):
        state = {}
    state.setdefault("version", 1)
    state["id"] = run_id(directory)
    state["project"] = str(directory)
    state.setdefault("title", directory.name.replace("_", " "))
    state.setdefault("created", _now())
    state.setdefault("stage", "ingest")
    state.setdefault("status", "idle")
    state.setdefault("message", "")
    state.setdefault("tool", "")
    state.setdefault("done_stages", [])
    state.setdefault("metrics", {})
    state.setdefault("images", {})
    state.setdefault("iterations", [])
    state.setdefault("outputs", [])
    state.setdefault("warnings", [])
    state.setdefault("errors", [])
    state.setdefault("events", [])
    approval = state.get("approval")
    if not isinstance(approval, dict):
        state["approval"] = {"status": "idle", "message": "", "rule_key": "photo_part_build", "at": ""}
    return state


def _save(directory: Path, state: dict) -> None:
    state["updated"] = _now()
    path = directory / ".photopart" / "pane.json"
    _write_json(path, state)
    _touch_index(state)
    _broadcast(state)


def run_id(project: Path) -> str:
    return hashlib.sha256(str(project).encode("utf-8")).hexdigest()[:16]


def index_path() -> Path | None:
    raw = os.environ.get("HERMES_HOME", "").strip()
    if not raw:
        return None
    try:
        root = Path(raw).expanduser().resolve()
    except OSError:
        return None
    from photopart.paths import not_a_project

    if not_a_project(root) or _blocked(root):
        return None
    return root / ".photopart" / "pane-index.json"


def _touch_index(state: dict) -> None:
    path = index_path()
    if path is None:
        return
    data = _read_json(path)
    runs = [row for row in data.get("runs", []) if isinstance(row, dict)]
    runs = [row for row in runs if row.get("id") != state.get("id")]
    runs.append(
        {
            "id": state.get("id"),
            "project": state.get("project"),
            "updated": state.get("updated"),
            "title": state.get("title"),
            "stage": state.get("stage"),
            "status": state.get("status"),
        }
    )
    runs.sort(key=lambda row: str(row.get("updated") or ""), reverse=True)
    try:
        _write_json(path, {"runs": runs[:40]})
    except OSError:
        return


def _broadcast(state: dict) -> None:
    payload = {
        "run_id": state.get("id"),
        "stage": state.get("stage"),
        "status": state.get("status"),
        "updated": state.get("updated"),
    }
    try:
        from hermes_cli.plugin_events import broadcast_plugin_event
    except Exception:
        return
    try:
        broadcast_plugin_event("photo-to-part", "run.updated", payload)
    except Exception:
        return


def _layers(payload: dict) -> list[dict]:
    layers = [payload]
    for key in _NEST_KEYS:
        nested = payload.get(key)
        if isinstance(nested, dict):
            layers.append(nested)
    alignment = payload.get("alignment")
    if isinstance(alignment, dict):
        layers.append(alignment)
    render = payload.get("render")
    if isinstance(render, dict) and isinstance(render.get("alignment"), dict):
        layers.append(render["alignment"])
    return layers


def _nested_render(layers: list[dict]) -> bool:
    if len(layers) < 2:
        return False
    render = layers[1] if isinstance(layers[0].get("render"), dict) else None
    if not isinstance(render, dict):
        return False
    return bool(render.get("overlay") or render.get("sheet") or render.get("ok"))


def _has_scale(layers: list[dict]) -> bool:
    return _first_number(layers, "px_per_mm", "photo_scale", "photo_scale_px_per_mm") is not None


def _has_segment(layers: list[dict]) -> bool:
    if _first_text(layers, "overlay", "mask_png") or _iou(layers) is not None:
        return True
    for source in layers:
        bbox = source.get("part_bbox_mm")
        if isinstance(bbox, (dict, list, tuple)) and bbox:
            return True
    return False


def _has_compare(layers: list[dict]) -> bool:
    return bool(_first_text(layers, "overlay", "compare_front"))


def _mesh_path(layers: list[dict]) -> str | None:
    return _first_text(layers, "stl", "mesh", "file", "deliverable")


def _version_number(mesh: str | None) -> int | None:
    if not isinstance(mesh, str) or not mesh.strip():
        return None
    match = _VERSION_RE.search(Path(mesh).stem)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _image_map(state: dict) -> dict:
    images = state.get("images")
    return images if isinstance(images, dict) else {}


def _front_view(layers: list[dict]) -> str | None:
    for source in layers:
        views = source.get("views")
        if isinstance(views, list):
            for item in views:
                if isinstance(item, str) and item.replace("\\", "/").endswith("/front.png"):
                    return item
        for key in ("render", "front"):
            value = source.get(key)
            if isinstance(value, str) and value.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                return value
    return None


def _output_paths(layers: list[dict]) -> list[str]:
    found: list[str] = []
    for source in layers:
        for key in ("stl", "threemf", "scad", "step", "stp", "file", "mesh", "deliverable"):
            value = source.get(key)
            if isinstance(value, str):
                found.append(value)
        outputs = source.get("outputs")
        if isinstance(outputs, list):
            for item in outputs:
                if isinstance(item, str):
                    found.append(item)
    return found


def _kind(path: str) -> str:
    suffix = Path(path).suffix.lower()
    return {".stl": "STL", ".3mf": "3MF", ".scad": "SCAD", ".step": "STEP", ".stp": "STEP"}.get(suffix, "FILE")


def _scale_source(layers: list[dict]) -> str | None:
    for source in layers:
        if source.get("photo_scale_source") == "user_part_dimension" or source.get("reference_is_part") is True:
            return "user part dimension"
        coin = source.get("coin")
        if isinstance(coin, str) and coin.strip():
            return coin.replace("_", " ")
        kind = source.get("kind")
        if kind == "ruler":
            return "ruler"
        marker = source.get("marker")
        if kind == "marker" or isinstance(marker, dict):
            if isinstance(marker, dict) and marker.get("family"):
                return str(marker["family"])
            return "marker"
        if isinstance(kind, str) and kind.strip():
            return kind.replace("_", " ")
    return None


def _confidence(layers: list[dict]) -> str | None:
    pct = _first_number(layers, "scale_uncertainty_pct")
    if pct is not None:
        return f"±{pct:.1f}%"
    for source in layers:
        seg = source.get("segmentation_confidence")
        if isinstance(seg, (int, float)) and not isinstance(seg, bool):
            value = float(seg)
            if 0 <= value <= 1:
                return f"{round(value * 100)}% mask"
        overall = source.get("overall_confidence")
        if isinstance(overall, str) and overall.strip():
            return overall.strip()
    return None


def _iou(layers: list[dict]) -> float | None:
    for source in layers:
        for key in ("overlay_iou", "iou"):
            number = _as_float(source.get(key))
            if number is not None:
                return number
    return None


def _iou_trusted(layers: list[dict]) -> bool | None:
    for source in layers:
        value = source.get("iou_trusted")
        if isinstance(value, bool):
            return value
    return None


def _trust(layers: list[dict], metrics: dict) -> str | None:
    label = metrics.get("iou_label") or _first_text(layers, "overlay_iou_label")
    trusted = metrics.get("iou_trusted")
    if trusted is None:
        trusted = _iou_trusted(layers)
    if label == "guide_only":
        return "guide only"
    if trusted is False or label == "untrusted":
        return "untrusted"
    if trusted is True or label == "measured":
        return "trusted"
    return None


def _dimensions(layers: list[dict]) -> str | None:
    for source in layers:
        for key in ("extents_mm", "expected_extents_mm", "target_mm", "part_bbox_mm"):
            text = _format_box(source.get(key))
            if text:
                return text
    return None


def _format_box(value) -> str | None:
    if isinstance(value, dict):
        if all(key in value for key in ("x", "y", "z")):
            return f"{_mm(value['x'])} × {_mm(value['y'])} × {_mm(value['z'])} mm"
        width = value.get("width_mm", value.get("width"))
        height = value.get("height_mm", value.get("height"))
        depth = value.get("depth_mm", value.get("depth"))
        if width is not None and height is not None and depth is not None:
            return f"{_mm(width)} × {_mm(height)} × {_mm(depth)} mm"
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return f"{_mm(value[0])} × {_mm(value[1])} × {_mm(value[2])} mm"
    return None


def _warnings(layers: list[dict]) -> list[str]:
    found: list[str] = []

    def add(value) -> None:
        if isinstance(value, str) and value.strip():
            found.append(_clip(value.strip(), 240))
        elif isinstance(value, list):
            for item in value:
                add(item)
        elif isinstance(value, dict):
            for key in ("warning", "message"):
                if isinstance(value.get(key), str):
                    add(value[key])

    for source in layers:
        for key in (
            "warnings",
            "overlay_warnings",
            "probe_warnings",
            "out_of_plane_warning",
            "same_plane_warning",
            "last_measure_warning",
        ):
            add(source.get(key))
        printable = source.get("printability")
        if isinstance(printable, dict):
            add(printable.get("warnings"))
        standards = source.get("standards")
        if isinstance(standards, dict):
            add(standards.get("warnings"))
        if source.get("iou_trusted") is False and isinstance(source.get("iou_trust_reason"), str):
            add(source["iou_trust_reason"])
    return _unique(found)


def _errors(payload: dict) -> list[str]:
    found: list[str] = []
    if isinstance(payload.get("error"), str) and payload["error"].strip():
        found.append(_clip(payload["error"].strip(), 240))
    failures = payload.get("failures")
    if isinstance(failures, list):
        for item in failures:
            if isinstance(item, str) and item.strip():
                found.append(_clip(item.strip(), 240))
    return _unique(found) or ["The step failed."]


def _title(project: Path, payload: dict) -> str:
    for source in _layers(payload):
        mesh = _mesh_path([source])
        if mesh:
            stem = _VERSION_RE.sub("", Path(mesh).stem).replace("_", " ").strip()
            if stem:
                return stem
        for key in ("part", "shape"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().replace("_", " ")
    return project.name.replace("_", " ")


def _mark_done(state: dict, stage: str) -> None:
    if not stage:
        return
    done = [item for item in state.get("done_stages") or [] if isinstance(item, str)]
    if stage not in done:
        done.append(stage)
    state["done_stages"] = done


def _event(state: dict, tool: str, stage: str, message: str, *, ok: bool) -> None:
    events = [item for item in state.get("events") or [] if isinstance(item, dict)]
    events.append({"at": _now(), "tool": tool, "stage": stage, "message": _clip(message, 180), "ok": bool(ok)})
    state["events"] = events[-40:]


def _first_text(layers: list[dict], *keys: str) -> str | None:
    for source in layers:
        for key in keys:
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _first_number(layers: list[dict], *keys: str) -> float | None:
    for source in layers:
        for key in keys:
            number = _as_float(source.get(key))
            if number is not None:
                return number
    return None


def _as_float(value) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return round(number, 4)


def _mm(value) -> str:
    number = _as_float(value)
    if number is None:
        return "?"
    if number.is_integer():
        return str(int(number))
    text = f"{number:.2f}".rstrip("0").rstrip(".")
    return text


def _unique(items: list[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _is_help(payload: dict) -> bool:
    if payload.get("help") or payload.get("describe"):
        return True
    if str(payload.get("mode") or "").strip().lower() in {"help", "describe"}:
        return True
    return "example_script" in payload


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path: Path) -> dict:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _write_json(path: Path, body: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)
