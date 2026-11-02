"""Run the scripted photo-to-part tasks and score an optional Hermes transcript.

The default path calls the plugin tools in-process. It does not start Hermes,
open a socket, or read a credential. ``--transcript`` scores a saved session
for tool calls, minutes, a mistaken skill id, and deleted meshes.

Usage (from the repo root):

    python -m evals.runner
    python -m evals.runner --transcript session.txt
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

from photopart.flow import SKILL_ID
from photopart.tools import TOOL_NAMES
from photopart.heal import run_heal
from photopart.measure import measure
from photopart.overlay import _foreground_for_overlay, grabcut_mask
from photopart.parts import build_shape, write_shape
from photopart.printability import check_printability
from photopart.render import run_render
from photopart.sheet import SHEET_VIEWS, render_sheet
from photopart.validate import run_validate

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
TASKS_PATH = ROOT / "tasks.json"
_EXPECTED_TOOLS = 6
_WRONG_SKILL = "plugin:photo-to-part:photo-to-printable-part"
_TOOL_CALL = re.compile(r"photo_part_(?:validate|render|heal|template|measure|build)")
_DELETE = re.compile(
    r"(?:\brm\b|\bunlink\b|\bos\.remove\b|\bshutil\.rmtree\b).{0,120}?\.(?:stl|3mf)\b",
    re.IGNORECASE,
)
_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


class HermesV0217Context:
    """PluginContext stand-in for Hermes v0.21.7.

    ``register_tool`` matches NousResearch/hermes-agent ``hermes_cli/plugins.py``
    at tag v0.21.7 (commit 71d34bad): no ``output_schema`` parameter and no
    ``**kwargs``.
    """

    def __init__(self) -> None:
        self.tools: list[dict] = []
        self.skills: list[tuple] = []

    def register_skill(self, name, path) -> None:
        self.skills.append((name, path))

    def register_tool(
        self,
        name,
        toolset,
        schema,
        handler,
        check_fn=None,
        requires_env=None,
        is_async=False,
        description="",
        emoji="",
        override=False,
    ) -> None:
        self.tools.append(
            {
                "name": name,
                "toolset": toolset,
                "schema": schema,
                "handler": handler,
                "check_fn": check_fn,
                "requires_env": requires_env,
                "is_async": is_async,
                "description": description,
                "emoji": emoji,
                "override": override,
            }
        )


def load_plugin_register():
    """Load the plugin entrypoint (``__init__.py`` ``register``)."""
    spec = importlib.util.spec_from_file_location("photo_to_part_plugin", REPO / "__init__.py")
    if spec is None or spec.loader is None:
        raise ImportError("could not load the plugin register entrypoint")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    register = getattr(module, "register", None)
    if register is None:
        raise ImportError("plugin entrypoint has no register(ctx)")
    return register


def registration_report() -> dict:
    """Register through the plugin entrypoint. Fewer than six tools is a failure."""
    ctx = HermesV0217Context()
    error = None
    try:
        load_plugin_register()(ctx)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    names = [item["name"] for item in ctx.tools]
    missing = [name for name in TOOL_NAMES if name not in names]
    message = None
    if error is not None or len(names) < _EXPECTED_TOOLS or missing:
        registered = ", ".join(names) if names else "none"
        message = (
            f"plugin registration failed: register(ctx) yielded {len(names)} tools, "
            f"expected {_EXPECTED_TOOLS} ({', '.join(TOOL_NAMES)}). Registered: {registered}."
        )
        if error:
            message += f" {error}"
    return {
        "count": len(names),
        "names": names,
        "error": message,
        "tools": ctx.tools,
    }


def load_tasks() -> list[dict]:
    payload = json.loads(TASKS_PATH.read_text(encoding="utf-8"))
    rows = payload.get("tasks")
    if not isinstance(rows, list) or len(rows) < 15:
        raise ValueError("evals/tasks.json needs at least 15 tasks")
    return rows


def run_suite() -> dict:
    """Execute every task. ``passed`` is how many met their expectation.

    The suite first calls the plugin ``register(ctx)`` entrypoint. Fewer than
    six tools is a failed run; the task functions are not a substitute for that.
    """
    registration = registration_report()
    if registration["error"]:
        return {
            "ok": False,
            "passed": 0,
            "tasks": 0,
            "minutes": 0.0,
            "dim_error_mm": None,
            "tool_calls": 0,
            "wrong_skill_ids": 0,
            "deleted_files": [],
            "tools_registered": registration["count"],
            "registered_tools": registration["names"],
            "registration_error": registration["error"],
            "results": [],
        }
    prompts = {row["id"]: row.get("prompt") or "" for row in load_tasks()}
    started = time.perf_counter()
    results = []
    for task_id, func in _CHECKS:
        if task_id not in prompts:
            results.append(_row(task_id, False, detail="missing prompt in tasks.json"))
            continue
        one = time.perf_counter()
        try:
            outcome = func()
        except Exception as exc:
            outcome = {"passed": False, "detail": f"{type(exc).__name__}: {exc}"}
        outcome["id"] = task_id
        outcome["minutes"] = (time.perf_counter() - one) / 60.0
        outcome.setdefault("dim_error_mm", None)
        outcome.setdefault("tool_calls", 0)
        outcome.setdefault("wrong_skill_ids", 0)
        outcome.setdefault("deleted_files", [])
        results.append(outcome)
    elapsed = (time.perf_counter() - started) / 60.0
    passed = sum(1 for row in results if row.get("passed"))
    return {
        "ok": passed == len(results),
        "passed": passed,
        "tasks": len(results),
        "minutes": elapsed,
        "dim_error_mm": _max_dim(results),
        "tool_calls": sum(int(row.get("tool_calls") or 0) for row in results),
        "wrong_skill_ids": sum(int(row.get("wrong_skill_ids") or 0) for row in results),
        "deleted_files": [item for row in results for item in row.get("deleted_files") or []],
        "tools_registered": registration["count"],
        "registered_tools": registration["names"],
        "results": results,
    }


def score_transcript(text: str) -> dict:
    """Count tool calls, a mistaken plugin: skill id, deletions, and minutes."""
    wrong = 0
    for line in text.splitlines():
        if "is not a skill name" in line:
            continue
        wrong += line.count(_WRONG_SKILL)
    stamps = _STAMP.findall(text)
    minutes = None
    if len(stamps) >= 2:
        first = datetime.strptime(stamps[0], "%Y-%m-%dT%H:%M:%S")
        last = datetime.strptime(stamps[-1], "%Y-%m-%dT%H:%M:%S")
        minutes = max(0.0, (last - first).total_seconds() / 60.0)
    return {
        "tool_calls": len(_TOOL_CALL.findall(text)),
        "wrong_skill_ids": wrong,
        "deleted_files": _DELETE.findall(text),
        "minutes": minutes,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run photo-to-part evals.")
    parser.add_argument("--transcript", help="Score a saved Hermes transcript in addition to the suite.")
    parser.add_argument("--json-out", help="Write the suite report to this path.")
    args = parser.parse_args(argv)
    report = run_suite()
    if report.get("registration_error"):
        print(report["registration_error"], file=sys.stderr)
    if args.transcript:
        report["transcript"] = score_transcript(Path(args.transcript).read_text(encoding="utf-8"))
    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)
    if args.json_out:
        Path(args.json_out).write_text(text + "\n", encoding="utf-8")
    return 0 if report["ok"] else 1


def _checks() -> list[tuple[str, object]]:
    return [
        ("box_matches_spec", _box_matches),
        ("box_dimension_error", _box_drift),
        ("hinge_four_knuckles", lambda: _hinge(4)),
        ("hinge_five_knuckles", lambda: _hinge(5)),
        ("countersink_deeper_than_sheet", _countersink),
        ("dropped_template_knuckles", _dropped_knuckles),
        ("frozen_edit_needs_reason", _freeze),
        ("thin_wall_warning", _thin_wall),
        ("print_in_place_gap", _gap),
        ("eight_view_sheet", _sheet),
        ("out_of_plane_uncertainty", _plane),
        ("aruco_scale", _aruco),
        ("unvalidated_version_refused", _unvalidated),
        ("worse_version_reverts", _revert),
        ("meshfix_absent_degrades", _meshfix),
        ("grabcut_seed", _grabcut),
    ]


def _row(task_id: str, passed: bool, **extra) -> dict:
    extra["id"] = task_id
    extra["passed"] = passed
    return extra


def _max_dim(results: list[dict]):
    values = [float(row["dim_error_mm"]) for row in results if isinstance(row.get("dim_error_mm"), (int, float))]
    if not values:
        return None
    return max(values)


def _skill_misses(*reports) -> int:
    missed = 0
    for report in reports:
        if not isinstance(report, dict):
            continue
        if report.get("skill_id") not in {None, SKILL_ID}:
            missed += 1
        text = json.dumps(report)
        if _WRONG_SKILL in text and "is not a skill name" not in text:
            missed += 1
    return missed


def _dim_error(report: dict):
    worst = 0.0
    found = False
    for row in report.get("spec") or []:
        if not isinstance(row, dict) or row.get("actual") is None or row.get("value") is None:
            continue
        if row.get("name") not in {"x", "y", "z"}:
            continue
        found = True
        worst = max(worst, abs(float(row["actual"]) - float(row["value"])))
    return worst if found else None


def _snapshot(root: Path) -> set[str]:
    return {str(path) for path in root.rglob("*") if path.is_file()}


def _deleted(before: set[str], root: Path) -> list[str]:
    after = _snapshot(root)
    return sorted(before - after)


def _box(path: Path, extents) -> None:
    trimesh.creation.box(extents=extents).export(path)


def _box_matches() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        before = _snapshot(root)
        mesh = root / "part_v1.stl"
        _box(mesh, (10, 20, 30))
        spec = root / "spec.json"
        spec.write_text(json.dumps({"x": 10, "y": 20, "z": 30, "shells": 1}), encoding="utf-8")
        code, report = run_validate(str(mesh), spec=str(spec))
        return {
            "passed": code == 0 and report.get("ok") is True and "stop" in str(report.get("next_step")),
            "dim_error_mm": _dim_error(report),
            "tool_calls": 1,
            "wrong_skill_ids": _skill_misses(report),
            "deleted_files": _deleted(before, root),
            "detail": report.get("next_step"),
        }


def _box_drift() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        mesh = root / "part_v1.stl"
        _box(mesh, (10, 20, 30))
        code, report = run_validate(str(mesh), dims=["x=12±0.2"])
        error = _dim_error(report)
        return {
            "passed": code == 2 and report.get("ok") is False and error is not None and error > 1.5,
            "dim_error_mm": error,
            "tool_calls": 1,
            "wrong_skill_ids": _skill_misses(report),
            "deleted_files": [],
        }


def _hinge(count: int) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        before = _snapshot(root)
        written = write_shape(root, "hinge", {"knuckles": count}, write_3mf=False)
        spec = written["spec_checks"]
        code, report = run_validate(str(written["stl"]), spec=spec, expected_shells=2)
        knuckles = [row for row in report.get("spec") or [] if row.get("name") == "knuckles"]
        ok = code == 0 and knuckles and knuckles[0].get("actual") == count
        return {
            "passed": bool(ok),
            "dim_error_mm": _dim_error(report),
            "tool_calls": 2,
            "wrong_skill_ids": _skill_misses(report),
            "deleted_files": _deleted(before, root),
            "detail": None if ok else report.get("failures"),
        }


def _countersink() -> dict:
    try:
        build_shape("countersink", {"thickness_mm": 2, "countersink_depth_mm": 8.5, "hole_diameter_mm": 4.5})
    except ValueError as exc:
        return {
            "passed": "deeper than the sheet" in str(exc),
            "tool_calls": 1,
            "wrong_skill_ids": 0,
            "deleted_files": [],
        }
    return {"passed": False, "tool_calls": 1, "detail": "countersink was accepted"}


def _dropped_knuckles() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        written = write_shape(root, "hinge", {"knuckles": 4}, write_3mf=False)
        spec = dict(written["spec_checks"])
        spec.pop("knuckles", None)
        code, report = run_validate(str(written["stl"]), spec=spec, expected_shells=2)
        text = " ".join(report.get("failures") or [])
        return {
            "passed": code != 0 and "knuckles" in text,
            "tool_calls": 2,
            "wrong_skill_ids": _skill_misses(report),
            "deleted_files": [],
        }


def _freeze() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        mesh = root / "part_v1.stl"
        _box(mesh, (10, 20, 30))
        spec = root / "spec.json"
        body = {
            "x": 10,
            "y": 20,
            "z": 30,
            "features": ["5 knuckles", "teardrop", "scroll ends"],
        }
        spec.write_text(json.dumps(body), encoding="utf-8")
        code, first = run_validate(str(mesh), spec=str(spec))
        body["features"] = ["teardrop", "scroll ends"]
        spec.write_text(json.dumps(body), encoding="utf-8")
        _code, blocked = run_validate(str(mesh), spec=str(spec))
        _code, allowed = run_validate(str(mesh), spec=str(spec), spec_reason="user dropped a knuckle requirement")
        edits = allowed.get("spec_edits") or []
        items = [row.get("item") for row in first.get("checklist") or []]
        passed = (
            code == 0
            and blocked.get("ok") is False
            and any("reason" in item for item in blocked.get("failures") or [])
            and edits
            and edits[-1].get("reason") == "user dropped a knuckle requirement"
            and items == ["5 knuckles", "teardrop", "scroll ends"]
        )
        return {
            "passed": passed,
            "tool_calls": 3,
            "wrong_skill_ids": _skill_misses(first, blocked, allowed),
            "deleted_files": [],
            "detail": None if passed else blocked.get("failures"),
        }


def _thin_wall() -> dict:
    plate = trimesh.creation.box(extents=(20, 20, 0.4))
    report = check_printability(plate, min_wall_mm=0.8)
    wall = report.get("min_wall_mm")
    return {
        "passed": wall is not None and wall < 0.8 and any("wall" in item for item in report["warnings"]),
        "tool_calls": 1,
        "wrong_skill_ids": 0,
        "deleted_files": [],
        "detail": report,
    }


def _gap() -> dict:
    left = trimesh.creation.box(extents=(10, 10, 10))
    right = trimesh.creation.box(extents=(10, 10, 10))
    right.apply_translation((10.15, 0, 0))
    both = trimesh.util.concatenate([left, right])
    report = check_printability(both, min_gap_mm=0.3)
    gap = report.get("min_gap_mm")
    return {
        "passed": gap is not None and gap < 0.3 and any("gap" in item for item in report["warnings"]),
        "tool_calls": 1,
        "wrong_skill_ids": 0,
        "deleted_files": [],
        "detail": {"min_gap_mm": gap, "warnings": report["warnings"]},
    }


def _sheet() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        previous = trimesh.creation.box(extents=(10, 20, 30))
        current = trimesh.creation.box(extents=(10, 20, 32))
        sheet = render_sheet(
            current,
            root / "sheet.png",
            previous=previous,
            rows=[{"name": "z", "value": 30, "actual": 32, "ok": False}],
            pixels=48,
        )
        image = np.array(Image.open(sheet["sheet"]))
        has_green = bool(np.any((image[:, :, 1] > 120) & (image[:, :, 0] < 90)))
        has_red = bool(np.any((image[:, :, 0] > 150) & (image[:, :, 1] < 80)))
        error = sheet["dimension_errors"][0]["error_mm"]
        return {
            "passed": sheet["sheet_views"] == list(SHEET_VIEWS) and has_green and has_red and abs(error - 2) < 0.2,
            "dim_error_mm": abs(error),
            "tool_calls": 1,
            "wrong_skill_ids": 0,
            "deleted_files": [],
        }


def _plane() -> dict:
    report = measure(
        {
            "diameter_mm": 24.26,
            "diameter_px": 200,
            "measurements": [
                {"name": "width", "length_px": 100, "plane": "in_plane"},
                {"name": "thickness", "length_px": 40, "plane": "out_of_plane"},
            ],
        }
    )
    by_name = {item["name"]: item for item in report["measurements"]}
    passed = (
        by_name["width"]["plane"] == "in_plane"
        and by_name["thickness"]["plane"] == "out_of_plane"
        and by_name["thickness"]["uncertainty_mm"] > by_name["width"]["uncertainty_mm"]
        and "thickness" in str(report.get("out_of_plane_warning"))
    )
    return {
        "passed": passed,
        "tool_calls": 1,
        "wrong_skill_ids": _skill_misses(report),
        "deleted_files": [],
    }


def _aruco() -> dict:
    import cv2

    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    marker = cv2.aruco.generateImageMarker(dictionary, 0, 80)
    canvas = np.full((200, 200), 255, np.uint8)
    canvas[60:140, 60:140] = marker
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "marker.png"
        Image.fromarray(canvas).save(path)
        report = measure({"image": str(path), "marker_mm": 20})
    marker_info = report.get("marker") or {}
    return {
        "passed": report.get("ok") is True and marker_info.get("kind") == "aruco" and report["px_per_mm"] > 1,
        "tool_calls": 1,
        "wrong_skill_ids": _skill_misses(report),
        "deleted_files": [],
        "detail": marker_info,
    }


def _unvalidated() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        mesh = root / "part_v1.stl"
        _box(mesh, (10, 8, 4))
        code, report = run_render([str(mesh), "--out-dir", str(root / "views")])
        return {
            "passed": code == 2 and report.get("unvalidated") is True and not (root / "views" / "front.png").exists(),
            "tool_calls": 1,
            "wrong_skill_ids": _skill_misses(report),
            "deleted_files": [],
        }


def _revert() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        spec = {"x": 10, "y": 20, "z": 30, "tolerance": 0.4}
        good = root / "part_v1.stl"
        bad = root / "part_v2.stl"
        _box(good, (10, 20, 30))
        _box(bad, (10, 20, 40))
        _code, first = run_validate(str(good), spec=spec)
        code, second = run_validate(str(bad), spec=spec)
        step = str(second.get("next_step"))
        final_code, delivered = run_render(
            [str(bad), "--out-dir", str(root / "ship"), "--final"]
        )
        passed = (
            first.get("ok") is True
            and code == 2
            and "Revert to part_v1.stl" in step
            and final_code == 0
            and delivered.get("best_version") == "part_v1.stl"
        )
        return {
            "passed": passed,
            "dim_error_mm": _dim_error(second),
            "tool_calls": 3,
            "wrong_skill_ids": _skill_misses(first, second, delivered),
            "deleted_files": [],
            "detail": step,
        }


def _meshfix() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "scan.stl"
        _box(src, (8, 8, 8))
        code, report = run_heal([str(src), "--out", str(root / "healed.stl"), "--engine", "meshfix"])
        note = str(report.get("meshfix_note") or "")
        available = report.get("meshfix_available")
        if available:
            passed = code == 0 and report.get("meshfix_applied") is True
        else:
            passed = code == 0 and report.get("meshfix_applied") is False and "not installed" in note
        return {
            "passed": passed,
            "tool_calls": 1,
            "wrong_skill_ids": _skill_misses(report),
            "deleted_files": [],
            "detail": note,
        }


def _grabcut() -> dict:
    image = np.full((140, 180, 3), 255, np.uint8)
    image[40:100, 50:130] = (18, 18, 22)
    mask = grabcut_mask(image, seed=(90, 70))
    _cut, blob, _warnings, _expanded = _foreground_for_overlay(
        image, roi=None, seed=(90, 70), exclude=None, hints=True
    )
    covered = mask is not None and int(mask[70, 90]) == 1 and int(mask[5, 5]) == 0
    return {
        "passed": covered and isinstance(blob, dict) and blob.get("source") == "grabcut",
        "tool_calls": 1,
        "wrong_skill_ids": 0,
        "deleted_files": [],
    }


_CHECKS = _checks()


if __name__ == "__main__":
    raise SystemExit(main())
