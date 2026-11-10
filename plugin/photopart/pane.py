"""Read-only Part studio API.

``dashboard/plugin_api.py`` mounts these functions at ``/api/plugins/photo-to-part/``.
The desktop pane polls them. Paths are confined to the project that wrote the
progress file. Eval trees and the canary string are refused.
"""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

from photopart.progress import _blocked, _canary, _read_json, index_path, run_id

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
_STAGES = (
    ("ingest", "Photo"),
    ("scale", "Scale"),
    ("segment", "Segment"),
    ("spec", "Spec"),
    ("approval", "Approval"),
    ("build", "Build"),
    ("render", "Render"),
    ("compare", "Compare"),
    ("refine", "Refine"),
)
_STAGE_LABELS = dict(_STAGES)


def health() -> dict:
    return {
        "ok": True,
        "pane": "photo-to-part",
        "min_hermes": "0.23.0",
        "optional": True,
    }


def list_runs() -> dict:
    rows = []
    for entry in _index_entries():
        state = _load_entry(entry)
        if state is None:
            continue
        rows.append(_summary(state))
    rows.sort(key=lambda row: str(row.get("updated") or ""), reverse=True)
    return {"ok": True, "runs": rows}


def get_run(run_id: str) -> dict:
    state = _state_by_id(run_id)
    if state is None:
        return {
            "ok": False,
            "error": "No part run with that id.",
            "fix": "Run a photo_part tool in a project folder, then refresh the pane.",
        }
    return {"ok": True, "run": view_state(state)}


def read_media(run_id: str, rel: str, *, max_px: int = 960) -> dict:
    state = _state_by_id(run_id)
    if state is None:
        return {"ok": False, "error": "No part run with that id."}
    project = Path(state["project"])
    path = safe_image(project, rel)
    if path is None:
        return {"ok": False, "error": "That image is outside this part run."}
    url = data_url(path, max_px=max_px)
    if not url:
        return {"ok": False, "error": "That image could not be read."}
    return {"ok": True, "mime": "image/jpeg", "data_url": url, "path": str(path.relative_to(project)).replace("\\", "/")}


def view_state(state: dict) -> dict:
    """Pane model for one saved run. Images are data URLs or empty strings."""
    project = Path(state["project"])
    metrics = state.get("metrics") if isinstance(state.get("metrics"), dict) else {}
    images = state.get("images") if isinstance(state.get("images"), dict) else {}
    approval = state.get("approval") if isinstance(state.get("approval"), dict) else {}
    iterations = []
    latest_n = 0
    for item in state.get("iterations") or []:
        if not isinstance(item, dict):
            continue
        try:
            number = int(item.get("n") or 0)
        except (TypeError, ValueError):
            number = 0
        latest_n = max(latest_n, number)
        thumb_path = _existing(project, item.get("render") or item.get("overlay") or item.get("photo"))
        iterations.append(
            {
                "n": number,
                "label": item.get("label") or f"v{number}",
                "ok": bool(item.get("ok")),
                "iou": item.get("iou"),
                "trust": item.get("trust") or "",
                "mesh": item.get("mesh") or "",
                "thumb": data_url(thumb_path, max_px=160) if thumb_path else "",
                "photo_path": _relative(project, item.get("photo")),
                "overlay_path": _relative(project, item.get("overlay")),
                "render_path": _relative(project, item.get("render")),
                "compare_path": _relative(project, item.get("compare")),
                "active": False,
            }
        )
    active_n = _active_iteration(state, iterations, latest_n)
    for item in iterations:
        item["active"] = item["n"] == active_n and active_n > 0
    stage = str(state.get("stage") or "ingest")
    status = str(state.get("status") or "idle")
    images_out = {
        "photo": _url(project, images.get("photo")),
        "overlay": _url(project, images.get("overlay")),
        "render": _url(project, images.get("render")),
        "compare": _url(project, images.get("compare")),
    }
    if not images_out["render"] and not images_out["compare"]:
        chosen = next((item for item in iterations if item.get("active")), None)
        if chosen:
            images_out["render"] = _url(project, chosen.get("render") or chosen.get("compare"))
            if not images_out["overlay"]:
                images_out["overlay"] = _url(project, chosen.get("overlay"))
    return {
        "id": state.get("id"),
        "title": state.get("title") or project.name,
        "stage": stage,
        "stage_label": _STAGE_LABELS.get(stage, stage),
        "status": status,
        "message": state.get("message") or "",
        "tool": state.get("tool") or "",
        "updated": state.get("updated") or "",
        "iteration": int(active_n or state.get("iteration") or latest_n or 0),
        "stages": _stage_rows(state),
        "metrics": {
            "iou": metrics.get("iou"),
            "iou_label": metrics.get("iou_label") or "",
            "iou_trusted": metrics.get("iou_trusted"),
            "scale_source": metrics.get("scale_source") or "",
            "scale_confidence": metrics.get("scale_confidence") or "",
            "scale_note": metrics.get("scale_note") or "",
            "trust": metrics.get("trust") or "pending",
            "dimensions": metrics.get("dimensions") or "",
            "px_per_mm": metrics.get("px_per_mm"),
        },
        "approval": {
            "status": approval.get("status") or "idle",
            "message": approval.get("message") or "",
            "rule_key": approval.get("rule_key") or "photo_part_build",
        },
        "warnings": _pane_warnings(state),
        "errors": [item for item in state.get("errors") or [] if isinstance(item, str)][:6],
        "images": images_out,
        "iterations": iterations,
        "outputs": [
            {"kind": item.get("kind") or "FILE", "path": _display_path(project, item.get("path") or "")}
            for item in state.get("outputs") or []
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        ],
    }


def safe_image(project: Path, rel: str) -> Path | None:
    """Resolve one image inside ``project``. Reject absolute paths, ``..``, and escapes."""
    if not isinstance(rel, str) or not rel.strip():
        return None
    text = rel.strip().replace("\\", "/")
    if text.startswith("/") or text.startswith("~") or ".." in Path(text).parts:
        return None
    try:
        project = project.resolve()
        path = (project / text).resolve()
    except OSError:
        return None
    if path.suffix.lower() not in _IMAGE_SUFFIXES or not path.is_file():
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
    return path


def data_url(path: Path | None, *, max_px: int) -> str:
    if path is None:
        return ""
    try:
        from PIL import Image

        with Image.open(path) as image:
            frame = image.convert("RGB")
            frame.thumbnail((max_px, max_px))
            buffer = BytesIO()
            frame.save(buffer, format="JPEG", quality=82)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    except (OSError, ValueError):
        return ""
    return "data:image/jpeg;base64," + encoded


def _stage_rows(state: dict) -> list[dict]:
    done = {item for item in state.get("done_stages") or [] if isinstance(item, str)}
    active = str(state.get("stage") or "")
    status = str(state.get("status") or "")
    refining = bool(state.get("refining")) or (int(state.get("iteration") or 0) >= 2 and "refine" not in done and status == "running")
    rows = []
    for key, label in _STAGES:
        if key == active and status == "error":
            flag = "error"
        elif key == active and status in {"running", "waiting", "stale"}:
            flag = "active"
        elif key == "refine" and refining and status in {"running", "stale"}:
            flag = "active"
        elif key in done or status in {"ready", "measured", "done"} and key == active:
            flag = "done"
        else:
            flag = "pending"
        rows.append({"id": key, "label": label, "state": flag})
    return rows


def _summary(state: dict) -> dict:
    return {
        "id": state.get("id"),
        "title": state.get("title") or "",
        "stage": state.get("stage") or "",
        "status": state.get("status") or "",
        "message": state.get("message") or "",
        "updated": state.get("updated") or "",
        "project": state.get("project") or "",
    }


def _index_entries() -> list[dict]:
    path = index_path()
    if path is None or not path.is_file():
        return []
    data = _read_json(path)
    runs = data.get("runs")
    if not isinstance(runs, list):
        return []
    return [row for row in runs if isinstance(row, dict)]


def _load_entry(entry: dict) -> dict | None:
    project = entry.get("project")
    if not isinstance(project, str) or not project.strip():
        return None
    return _load_project(Path(project))


def _state_by_id(run_id: str) -> dict | None:
    if not isinstance(run_id, str) or not run_id.strip():
        return None
    wanted = run_id.strip()
    for entry in _index_entries():
        if entry.get("id") != wanted:
            continue
        state = _load_entry(entry)
        if state is not None and state.get("id") == wanted:
            return state
    return None


def _load_project(project: Path) -> dict | None:
    try:
        resolved = project.expanduser().resolve()
    except OSError:
        return None
    if _blocked(resolved) or not resolved.is_dir():
        return None
    path = resolved / ".photopart" / "pane.json"
    state = _read_json(path)
    if not state or state.get("project") != str(resolved):
        return None
    if state.get("id") != run_id(resolved):
        return None
    try:
        from photopart.progress import settle_project

        settled = settle_project(resolved)
        if isinstance(settled, dict) and settled.get("id") == state.get("id"):
            state = settled
    except Exception:
        pass
    return state


def _existing(project: Path, raw) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        path = Path(raw).expanduser().resolve()
        path.relative_to(project.resolve())
    except (OSError, ValueError):
        return None
    if not path.is_file() or path.suffix.lower() not in _IMAGE_SUFFIXES:
        return None
    if _blocked(path) or _canary(path):
        return None
    return path


def _url(project: Path, raw) -> str:
    return data_url(_existing(project, raw), max_px=720)


def _display_path(project: Path, raw: str) -> str:
    """Show a project-relative path when the file lives in the run directory."""
    if not isinstance(raw, str) or not raw.strip():
        return ""
    try:
        path = Path(raw).expanduser().resolve()
        return str(path.relative_to(project.resolve())).replace("\\", "/")
    except (OSError, ValueError):
        return raw


def _relative(project: Path, raw) -> str:
    path = _existing(project, raw)
    if path is None:
        return ""
    try:
        return str(path.relative_to(project.resolve())).replace("\\", "/")
    except ValueError:
        return ""


def _active_iteration(state: dict, iterations: list[dict], latest_n: int) -> int:
    """Highlight the version that matches the headline, not a later failed build."""
    if not iterations:
        return 0
    metrics = state.get("metrics") if isinstance(state.get("metrics"), dict) else {}
    headline = metrics.get("iou")
    stored = 0
    try:
        stored = int(state.get("iteration") or 0)
    except (TypeError, ValueError):
        stored = 0
    ok_items = [item for item in iterations if item.get("ok")]

    def _iou_close(item) -> bool:
        if headline is None or item.get("iou") is None:
            return False
        try:
            return abs(float(item["iou"]) - float(headline)) < 1e-4
        except (TypeError, ValueError):
            return False

    if headline is not None and ok_items:
        matches = [item for item in ok_items if _iou_close(item)]
        if matches:
            for item in matches:
                if item["n"] == stored:
                    return stored
            return matches[-1]["n"]
    if stored and any(item["n"] == stored for item in iterations):
        current = next(item for item in iterations if item["n"] == stored)
        if current.get("ok") or not ok_items:
            return stored
        return max(ok_items, key=lambda item: ((item.get("iou") is not None), item.get("iou") or 0, item["n"]))["n"]
    if ok_items:
        return ok_items[-1]["n"]
    return stored or latest_n


def _pane_warnings(state: dict) -> list[str]:
    """Drop noisy hole and knuckle probe notes from the pane; keep them in tool JSON."""
    quiet_needles = (
        "per-hole probe disagrees",
        "knuckle probe is unreliable",
        "knuckle ring count",
        "the check is reported as a warning",
        "does not fail validation and does not block delivery",
        "by rings, 0 cylinders",
    )
    visible: list[str] = []
    quiet = 0
    for item in state.get("warnings") or []:
        if not isinstance(item, str):
            continue
        lower = item.lower()
        if any(needle in lower for needle in quiet_needles):
            quiet += 1
            continue
        visible.append(item)
    if quiet:
        noun = "note" if quiet == 1 else "notes"
        visible.append(f"{quiet} hole or knuckle probe {noun} hidden. They do not block delivery.")
    return visible[:6]
