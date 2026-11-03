"""Run the scripted photo-to-part tasks and score an optional Hermes transcript.

Eval marker p2p-canary-7f3a9c2e-6b14-4d88-a1e0-9c5d2f8b4a17


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
import os
import re
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

from photopart.flow import OVERLAY_LOW_STEP, SKILL_ID
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
_PLUGIN_CALL = re.compile(r"^photo_part_(?:validate|render|heal|template|measure|build)$")
_STAMP_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d+)?(?:Z)?\s+(\S+)")
_TOOLCALL_LINE = re.compile(r"\bTOOLCALL\s+([A-Za-z][A-Za-z0-9_]*)\b")
_NAME_ARG = re.compile(r'"name"\s*:\s*"([^"]+)"')
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
        self.hooks: list[tuple] = []

    def register_hook(self, name, callback) -> None:
        self.hooks.append((str(name), callback))

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
    if not isinstance(rows, list) or len(rows) < 24:
        raise ValueError("evals/tasks.json needs at least 24 tasks")
    return rows


def run_suite(include_holdout: bool = False) -> dict:
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
    tasks = load_tasks()
    prompts = {row["id"]: row for row in tasks}
    started = time.perf_counter()
    results = []
    for task_id, func in _CHECKS:
        spec = prompts.get(task_id)
        if spec is None:
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
        outcome["holdout"] = bool(spec.get("holdout"))
        _apply_budget(outcome, spec)
        results.append(outcome)
    elapsed = (time.perf_counter() - started) / 60.0
    holdouts = [row for row in results if row.get("holdout")]
    visible = results if include_holdout else [row for row in results if not row.get("holdout")]
    passed = sum(1 for row in visible if row.get("passed"))
    everything_passed = all(row.get("passed") for row in results) and len(results) == len(_CHECKS)
    return {
        "ok": everything_passed,
        "passed": passed,
        "tasks": len(visible),
        "holdout_passed": sum(1 for row in holdouts if row.get("passed")),
        "holdout_tasks": len(holdouts),
        "holdouts": holdouts,
        "minutes": elapsed,
        "dim_error_mm": _max_dim(results),
        "tool_calls": sum(int(row.get("tool_calls") or 0) for row in results),
        "wrong_skill_ids": sum(int(row.get("wrong_skill_ids") or 0) for row in results),
        "deleted_files": [item for row in results for item in row.get("deleted_files") or []],
        "tools_registered": registration["count"],
        "registered_tools": registration["names"],
        "results": visible,
    }


def _apply_budget(outcome: dict, spec: dict) -> None:
    calls = spec.get("budget_calls")
    minutes = spec.get("budget_minutes")
    if isinstance(calls, (int, float)) and int(outcome.get("tool_calls") or 0) > int(calls):
        outcome["passed"] = False
        outcome["detail"] = f"tool_calls {outcome.get('tool_calls')} over budget_calls {calls}"
    if isinstance(minutes, (int, float)) and float(outcome.get("minutes") or 0) > float(minutes):
        outcome["passed"] = False
        outcome["detail"] = f"minutes {outcome.get('minutes')} over budget_minutes {minutes}"


_SKILL_VIEW = re.compile(r"skill_view\(\s*([\"'])(.*?)\1")
_REL_LEAK = re.compile(
    r"(?<![A-Za-z0-9_])evals/(?:runner\.py|tasks\.json|meshes\.py|photos\.json|fixtures(?:/|$)|__init__\.py|README\.md)"
)
_CALL_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_]*")


def _remember_call(names: list[str], raw) -> None:
    if not isinstance(raw, str):
        return
    token = raw.strip().split("(")[0].strip("`\"'")
    if _CALL_TOKEN.fullmatch(token) and "_" in token:
        names.append(token)


def _call_records(text: str) -> list[str]:
    """Session records only. A prose mention of a tool name is not a call.

    JSON and JSONL go through the session reader so an assistant ``tool_calls``
    entry and its ``role=tool`` result count once. ``TOOLCALL`` lines count
    every name, including ones with no underscore such as ``terminal``.
    """
    from photopart.sessions import names_from_text

    structured = names_from_text(text)
    names = list(structured)
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped[:1] in "{[" or _TOOLCALL_LINE.search(stripped):
            continue
        stamp = _STAMP_LINE.match(stripped)
        if stamp:
            _remember_call(names, stamp.group(2).split("(")[0])
    if structured:
        return names
    for line in text.splitlines():
        stripped = line.strip()
        if stripped[:1] in "{[" or "arguments" not in line or "name" not in line:
            continue
        for match in _NAME_ARG.finditer(line):
            _remember_call(names, match.group(1))
    return names


def _text_leaks(text: str) -> bool:
    """True when the transcript reads this plugin's eval tree, not a lookalike path."""
    from photopart.canary import EVAL_CANARY

    if EVAL_CANARY and EVAL_CANARY in text:
        return True
    if _REL_LEAK.search(text):
        return True
    folded = text.replace("\\", "/")
    anchors = (
        ROOT,
        ROOT / "runner.py",
        ROOT / "tasks.json",
        ROOT / "meshes.py",
        ROOT / "photos.json",
        ROOT / "fixtures",
        ROOT / "__init__.py",
        ROOT / "README.md",
    )
    for path in anchors:
        if str(path).replace("\\", "/") in folded:
            return True
    return False


def score_hermes_session(source: str, *, home: Path | None = None) -> dict:
    """Score a Hermes v0.21.7 session id or a JSON/JSONL/text export.

    ``source`` may be a session id under ``HERMES_HOME`` (``state.db`` and
    ``sessions/*.json`` / ``*.jsonl``) or a path to an export. Tool calls are
    the records in that file, including ``<timestamp> TOOLCALL name {args}``.
    """
    from photopart.sessions import load_session_calls, session_span_minutes, session_text

    text = session_text(source, home=home)
    loaded = load_session_calls(source, home=home)
    if loaded is None and not text:
        return {
            "ok": False,
            "error": f"no Hermes session records for {source}",
            "tool_calls": 0,
            "plugin_calls": 0,
            "wrong_skill_ids": 0,
            "skill_id_rewritten": 0,
            "deleted_files": [],
            "minutes": None,
            "leak": False,
            "calls_source": None,
        }
    scored = score_transcript(text, _calls_log(source, home)) if text else {
        "tool_calls": 0,
        "plugin_calls": 0,
        "wrong_skill_ids": 0,
        "skill_id_rewritten": 0,
        "deleted_files": [],
        "minutes": None,
        "leak": False,
    }
    if loaded is not None:
        names, label = loaded
        scored["tool_calls"] = len(names)
        scored["plugin_calls"] = sum(1 for name in names if _PLUGIN_CALL.fullmatch(name))
        scored["calls_source"] = label
    else:
        scored["calls_source"] = "transcript"
    span = session_span_minutes(source, home=home)
    if span is not None:
        scored["minutes"] = span
    scored["ok"] = True
    return scored


def score_transcript(text: str, calls=None) -> dict:
    """Count tool-call records, mistaken skill_view ids, deletions, leaks, and minutes.

    ``tool_calls`` counts session records (JSON tool calls and timestamped
    calls), not mentions in prose. ``plugin_calls`` is the photo_part_* subset.
    ``wrong_skill_ids`` counts ``skill_view`` and ``skills_list`` arguments
    that were not rewritten, including ids inside a ``tool_call`` ``calls``
    list. A slash or ``plugin:`` form of this skill counts. ``calls`` is a
    ``calls.jsonl`` path or a list of rewrite rows. A ``rewrite_from`` row is
    ``skill_id_rewritten`` and is left out of ``wrong_skill_ids``. A sentence
    that mentions the plugin: form is not a call. ``leak`` is true when the
    transcript reads this repo's ``evals/`` files or their absolute paths.
    """
    from photopart.skillref import misspelled_skill_arguments

    views = misspelled_skill_arguments(text)
    rewrites = _rewrite_rows(calls)
    if views and rewrites:
        paired = min(len(views), len(rewrites))
        rewritten = paired
        wrong = len(views) - paired
    elif rewrites:
        rewritten = len(rewrites)
        wrong = 0
    else:
        rewritten = 0
        wrong = len(views)
    stamps = _STAMP.findall(text)
    minutes = None
    if len(stamps) >= 2:
        first = datetime.strptime(stamps[0], "%Y-%m-%dT%H:%M:%S")
        last = datetime.strptime(stamps[-1], "%Y-%m-%dT%H:%M:%S")
        minutes = max(0.0, (last - first).total_seconds() / 60.0)
    records = _call_records(text)
    plugin = [name for name in records if _PLUGIN_CALL.fullmatch(name)]
    return {
        "tool_calls": len(records),
        "plugin_calls": len(plugin),
        "wrong_skill_ids": wrong,
        "skill_id_rewritten": rewritten,
        "deleted_files": _DELETE.findall(text),
        "minutes": minutes,
        "leak": _text_leaks(text),
    }


def _rewrite_rows(calls) -> list[str]:
    """``rewrite_from`` values from a calls.jsonl path or an in-memory list."""
    if calls is None:
        return []
    if isinstance(calls, (str, Path)):
        from photopart.sessions import rewrite_ids

        return rewrite_ids(calls)
    found = []
    for item in calls:
        if isinstance(item, str) and item.strip():
            found.append(item.strip())
        elif isinstance(item, dict) and item.get("rewrite_from"):
            found.append(str(item["rewrite_from"]))
    return found


def _calls_log(source: str, home: Path | None) -> Path | None:
    """Sidecar the hook writes. A missing file leaves the transcript count alone."""
    candidates = []
    raw = Path(str(source))
    if raw.is_file():
        candidates.append(raw.parent / ".photopart" / "calls.jsonl")
    if home is not None:
        candidates.append(Path(home) / ".photopart" / "calls.jsonl")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _answer_name(name: str) -> bool:
    """Answer files stay with the scorer. The staged directory never receives them."""
    base = Path(name).name.lower()
    return base == "fixture.json" or base.startswith("truth") or "mask" in base


def _stage_lists(spec: dict) -> tuple[list[str], list[str]]:
    inputs = [str(name) for name in (spec.get("inputs") or [])]
    answers = [str(name) for name in (spec.get("answers") or [])]
    if inputs or answers:
        return inputs, answers
    for name in spec.get("fixtures") or []:
        text = str(name)
        if _answer_name(text):
            answers.append(text)
        else:
            inputs.append(text)
    return inputs, answers


def stage_task(task_id: str, dest: Path) -> dict:
    """Copy one task prompt and its inputs. Answer files stay in the scorer."""
    destination = Path(dest).expanduser().resolve()
    repo = REPO.resolve()
    if destination == repo or repo in destination.parents:
        raise ValueError(f"stage directory must be outside the plugin tree, got {destination}")
    spec = next((row for row in load_tasks() if row["id"] == task_id), None)
    if spec is None:
        raise ValueError(f"unknown task {task_id}")
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "prompt.txt").write_text(str(spec.get("prompt") or "") + "\n", encoding="utf-8")
    inputs, answers = _stage_lists(spec)
    copied = []
    withheld = list(answers)
    if not spec.get("scripted"):
        for name in inputs:
            if _answer_name(name):
                withheld.append(name)
                continue
            source = ROOT / "fixtures" / name
            if not source.is_file():
                raise ValueError(f"fixture not found: {source}")
            target = destination / name
            target.write_bytes(source.read_bytes())
            copied.append(name)
    if task_id == "coin_scale_sealed":
        copied.extend(_stage_coin_photos(destination))
    return {
        "ok": True,
        "task": task_id,
        "dir": str(destination),
        "fixtures": copied,
        "inputs": copied,
        "answers_withheld": withheld,
        "scripted": bool(spec.get("scripted")),
        "leak": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run photo-to-part evals.")
    parser.add_argument("--transcript", help="Score a saved Hermes transcript in addition to the suite.")
    parser.add_argument(
        "--hermes-session",
        help="Score a Hermes session id or a JSON/JSONL session file. Reads HERMES_HOME/state.db and sessions/.",
    )
    parser.add_argument("--hermes-home", help="HERMES_HOME for --hermes-session. Defaults to $HERMES_HOME.")
    parser.add_argument("--json-out", help="Write the suite report to this path.")
    parser.add_argument("--stage", help="Copy one task prompt and fixtures to this directory, outside the plugin.")
    parser.add_argument("--task", help="Task id for --stage.")
    parser.add_argument("--include-holdout", action="store_true", help="Include held-out tasks in results.")
    args = parser.parse_args(argv)
    if args.stage:
        if not args.task:
            parser.error("--stage needs --task")
        report = stage_task(args.task, Path(args.stage))
        text = json.dumps(report, indent=2, sort_keys=True)
        print(text)
        if args.json_out:
            Path(args.json_out).write_text(text + "\n", encoding="utf-8")
        return 0
    report = run_suite(include_holdout=args.include_holdout)
    if report.get("registration_error"):
        print(report["registration_error"], file=sys.stderr)
    if args.transcript:
        report["transcript"] = score_transcript(Path(args.transcript).read_text(encoding="utf-8"))
    if args.hermes_session:
        home = Path(args.hermes_home).expanduser() if args.hermes_home else None
        report["hermes_session"] = score_hermes_session(args.hermes_session, home=home)
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
        ("template_default_name", _template_default_name),
        ("best_version_filled", _best_version_filled),
        ("checklist_bool_answered", _checklist_bool),
        ("bores_not_genus", _bores_not_genus),
        ("thin_l_bracket", _thin_l_bracket),
        ("thread_no_thin_wall", _thread_wall),
        ("validate_renders_on_pass", _validate_renders),
        ("budget_hint", _budget_hint),
        ("real_photo_overlay", _real_photo),
        ("overlay_low_confidence", _overlay_low),
        ("thread_from_script_no_thin_wall", _thread_from_script),
        ("coin_scale_sealed", _coin_scale_sealed),
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


def _template_default_name() -> dict:
    from photopart.tools import template_tool

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        gear = json.loads(template_tool({"out_dir": str(root), "shape": "spur_gear", "no_3mf": True}))
        bracket = json.loads(
            template_tool({"out_dir": str(root / "bracket"), "shape": "l_bracket", "no_3mf": True})
        )
        gear_name = str(gear.get("stl") or "")
        bracket_name = str(bracket.get("stl") or "")
        passed = (
            gear.get("ok") is True
            and gear_name.endswith("spur_gear_v1.stl")
            and Path(gear_name).is_file()
            and "name_v1.stl" not in gear_name
            and bracket_name.endswith("l_bracket_v1.stl")
            and "name_v1.stl" not in str(bracket.get("next_step"))
            and isinstance(gear.get("bodies"), list)
            and gear["bodies"]
            and "bbox_mm" in gear["bodies"][0]
            and "bores" in gear
            and "sections_mm2" in gear
        )
        return {
            "passed": passed,
            "tool_calls": 2,
            "wrong_skill_ids": _skill_misses(gear, bracket),
            "deleted_files": [],
            "detail": None if passed else {"gear": gear_name, "bracket": bracket_name},
        }


def _best_version_filled() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        spec = {"x": 10, "y": 20, "z": 30, "tolerance": 0.4}
        failed_v1 = root / "part_v1.stl"
        passed_v2 = root / "part_v2.stl"
        _box(failed_v1, (10, 20, 40))
        _box(passed_v2, (10, 20, 30))
        run_validate(str(failed_v1), spec=spec)
        code, second = run_validate(str(passed_v2), spec=spec)
        pair = root / "scores"
        pair.mkdir()
        low = pair / "part_v1.stl"
        high = pair / "part_v2.stl"
        _box(low, (10, 20, 30))
        _box(high, (10, 20, 30))
        code_low, first = run_validate(str(low), spec=spec)
        code_high, later = run_validate(
            str(high),
            spec={**spec, "features": ["teardrop"]},
        )
        alone = root / "only.stl"
        _box(alone, (8, 8, 8))
        _code, single = run_validate(str(alone))
        passed = (
            code == 0
            and second.get("best_version") == "part_v2.stl"
            and second.get("revert_to") is None
            and code_low == 0
            and code_high == 0
            and float(first["score"]) > float(later["score"])
            and later.get("best_version") == "part_v1.stl"
            and later.get("revert_to") == "part_v1.stl"
            and single.get("best_version") == "only.stl"
            and single.get("revert_to") is None
            and isinstance(second.get("versions"), list)
        )
        return {
            "passed": passed,
            "tool_calls": 5,
            "wrong_skill_ids": _skill_misses(second, later, single),
            "deleted_files": [],
            "detail": None
            if passed
            else {
                "second": second.get("best_version"),
                "revert": later.get("revert_to"),
                "scores": [first.get("score"), later.get("score")],
            },
        }


def _checklist_bool() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        written = write_shape(root, "hinge", {"knuckles": 5}, write_3mf=False)
        spec = dict(written["spec_checks"])
        spec["features"] = ["5 knuckles", {"teardrop": True}, "scroll ends"]
        code, report = run_validate(str(written["stl"]), spec=spec, expected_shells=2)
        by_item = {row["item"]: row for row in report.get("checklist") or []}
        code2, answered = run_validate(
            str(written["stl"]),
            spec=spec,
            expected_shells=2,
            answers=["scroll ends=yes"],
        )
        stored = json.loads(Path(str(written["stl"]) + ".validate.json").read_text(encoding="utf-8"))
        code3, remembered = run_validate(str(written["stl"]), spec=spec, expected_shells=2)
        passed = (
            code == 0
            and by_item["5 knuckles"].get("answer") == "yes"
            and by_item["5 knuckles"].get("auto") is True
            and by_item["teardrop"].get("answer") == "yes"
            and code2 == 0
            and stored.get("answers", {}).get("scroll ends") == "yes"
            and remembered.get("answers", {}).get("scroll ends") == "yes"
        )
        return {
            "passed": passed,
            "tool_calls": 4,
            "wrong_skill_ids": _skill_misses(report, answered),
            "deleted_files": [],
            "detail": None if passed else report.get("checklist"),
        }


def _bores_not_genus() -> dict:
    from evals.meshes import bore_hinge, six_hole_bracket, blind_tap
    from photopart.spec import GENUS_NOTE

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        hinge = bore_hinge()
        hinge_path = root / "hinge_v1.stl"
        hinge.export(hinge_path)
        code, report = run_validate(str(hinge_path), spec={"hole_count": 2})
        row = next(item for item in report.get("spec") or [] if item.get("name") == "hole_count")
        bracket = six_hole_bracket()
        bracket_path = root / "bracket.stl"
        bracket.export(bracket_path)
        _code, six = run_validate(str(bracket_path), spec={"hole_count": 6})
        six_row = next(item for item in six.get("spec") or [] if item.get("name") == "hole_count")
        tap = blind_tap()
        tap_path = root / "tap.stl"
        tap.export(tap_path)
        _code, blind = run_validate(str(tap_path), spec={"hole_count": 1})
        blind_row = next(item for item in blind.get("spec") or [] if item.get("name") == "hole_count")
        bores = blind_row.get("bores") or []
        passed = (
            code == 0
            and row.get("actual") == 2
            and row.get("genus") == 4
            and GENUS_NOTE in str(row.get("note"))
            and six.get("ok") is True
            and six_row.get("actual") == 6
            and blind.get("ok") is True
            and len(bores) == 1
            and bores[0].get("through") is False
        )
        return {
            "passed": passed,
            "tool_calls": 3,
            "wrong_skill_ids": _skill_misses(report),
            "deleted_files": [],
            "detail": None if passed else {"hinge": row, "six": six_row, "blind": bores},
        }


def _thin_l_bracket() -> dict:
    """1.5 mm L with three holes in each leg. Whole-part stations miss both legs."""
    from evals.meshes import thin_l_bracket

    mesh = thin_l_bracket()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "thin_l_v1.stl"
        mesh.export(path)
        code, report = run_validate(str(path), spec={"hole_count": 6, "shells": 1})
    row = next(item for item in report.get("spec") or [] if item.get("name") == "hole_count")
    bores = row.get("bores") or []
    axes: dict[str, int] = {}
    for bore in bores:
        axis = str(bore.get("axis"))
        axes[axis] = axes.get(axis, 0) + 1
    passed = (
        code == 0
        and report.get("ok") is True
        and row.get("actual") == 6
        and axes.get("x") == 3
        and axes.get("z") == 3
        and all(bore.get("through") is True for bore in bores)
    )
    return {
        "passed": passed,
        "tool_calls": 1,
        "wrong_skill_ids": _skill_misses(report),
        "deleted_files": [],
        "detail": None if passed else {"row": row, "axes": axes},
    }


def _thread_wall() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        screw = write_shape(root / "screw", "hex_screw", {"designation": "M3", "length_mm": 8}, write_3mf=False)
        cap = write_shape(root / "cap", "bottle_cap", write_3mf=False)
        plate = root / "thin.stl"
        trimesh.creation.box(extents=(20, 20, 0.4)).export(plate)
        _code, screw_report = run_validate(str(screw["stl"]))
        _code, cap_report = run_validate(str(cap["stl"]))
        _code, thin = run_validate(str(plate))
        screw_warn = screw_report["printability"]["warnings"]
        cap_warn = cap_report["printability"]["warnings"]
        passed = (
            not any("wall" in item for item in screw_warn)
            and screw_report["printability"].get("min_wall_raw_mm") is not None
            and not any("wall" in item for item in cap_warn)
            and thin["printability"].get("min_wall_mm") is not None
            and thin["printability"]["min_wall_mm"] < 0.8
            and any("wall" in item for item in thin["printability"]["warnings"])
        )
        return {
            "passed": passed,
            "tool_calls": 3,
            "wrong_skill_ids": 0,
            "deleted_files": [],
            "detail": None if passed else {"screw": screw_warn, "cap": cap_warn, "thin": thin["printability"]},
        }


def _validate_renders() -> dict:
    from photopart.tools import validate_tool

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        mesh = root / "part_v1.stl"
        _box(mesh, (10, 20, 30))
        spec = root / "spec.json"
        spec.write_text(json.dumps({"x": 10, "y": 20, "z": 30, "shells": 1}), encoding="utf-8")
        report = json.loads(validate_tool({"mesh": str(mesh), "spec": str(spec)}))
        bad = root / "bad" / "part_v1.stl"
        bad.parent.mkdir()
        _box(bad, (10, 20, 40))
        spec_bad = bad.parent / "spec.json"
        spec_bad.write_text(spec.read_text(encoding="utf-8"), encoding="utf-8")
        failed = json.loads(validate_tool({"mesh": str(bad), "spec": str(spec_bad)}))
        sheet = Path(str(report.get("render", {}).get("sheet") or ""))
        passed = (
            report.get("ok") is True
            and sheet.is_file()
            and sheet.name == "sheet.png"
            and failed.get("ok") is False
            and "Failed:" in str(failed.get("next_step"))
            and not failed.get("render")
        )
        return {
            "passed": passed,
            "tool_calls": 2,
            "wrong_skill_ids": _skill_misses(report, failed),
            "deleted_files": [],
            "detail": None if passed else {"ok": report.get("ok"), "sheet": str(sheet), "fail": failed.get("next_step")},
        }


def _budget_hint() -> dict:
    from photopart.tools import measure_tool

    saved = os.environ.pop("PHOTO_PART_MAX_CALLS", None)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "photo.png"
            Image.new("RGB", (32, 32), (255, 255, 255)).save(image)
            payload = {"image": str(image), "diameter_mm": 20, "diameter_px": 80}
            quiet = json.loads(measure_tool({**payload, "calls_used": 16}))
            mid = json.loads(measure_tool({**payload, "calls_used": 24}))
            late = json.loads(measure_tool({**payload, "calls_used": 32}))
            quiet_budget = quiet.get("budget") or {}
            mid_budget = mid.get("budget") or {}
            late_budget = late.get("budget") or {}
            passed = (
                int(quiet_budget.get("max_calls") or 0) == 40
                and int(quiet_budget.get("remaining") or 0) == 24
                and not str(quiet.get("next_step") or "").startswith("Budget:")
                and str(mid.get("next_step") or "").startswith("Budget: deliver now.")
                and int(mid_budget.get("remaining") or 0) == 16
                and str(late.get("next_step") or "").startswith("Budget: deliver now.")
                and "Stop exploring." in str(late.get("next_step") or "")
                and int(late_budget.get("remaining") or 0) <= 8
            )
            return {
                "passed": passed,
                "tool_calls": 3,
                "wrong_skill_ids": _skill_misses(quiet, mid, late),
                "deleted_files": [],
                "detail": None
                if passed
                else {
                    "quiet": quiet.get("next_step"),
                    "mid": mid.get("next_step"),
                    "late": late.get("next_step"),
                    "budgets": [quiet_budget, mid_budget, late_budget],
                },
            }
    finally:
        if saved is not None:
            os.environ["PHOTO_PART_MAX_CALLS"] = saved


def _angle_distance(found: float, target: float) -> float:
    return abs((float(found) - float(target) + 180.0) % 360.0 - 180.0)


def _real_photo() -> dict:
    from evals.meshes import washer_mesh
    from photopart.overlay import _iou, _place, raster_model
    from photopart.render import _project, choose_axes

    fixture = json.loads((ROOT / "fixtures" / "fixture.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        photo = root / "washer_photo.jpg"
        photo.write_bytes((ROOT / "fixtures" / "washer_photo.jpg").read_bytes())
        truth = np.asarray(Image.open(ROOT / "fixtures" / "washer_mask.png")) > 127
        measured = measure(
            {
                "image": str(photo),
                "diameter_mm": fixture["coin_mm"],
                "points": fixture["coin_points"],
                "roi": fixture["part_roi"],
            }
        )
        mesh = washer_mesh()
        stl = root / "washer_v1.stl"
        mesh.export(stl)
        extents = [float(value) for value in mesh.extents]
        spec = {
            "x": round(extents[0], 1),
            "y": round(extents[1], 1),
            "z": round(extents[2], 1),
            "tolerance": 0.5,
            "hole_count": 1,
            "shells": 1,
        }
        code, checked = run_validate(str(stl), spec=spec)
        cx, cy = fixture["coin_center_px"]
        diameter = float(fixture["coin_diameter_px"])
        exclude = f"{cx - diameter / 2 - 6},{cy - diameter / 2 - 6},{diameter + 12},{diameter + 12}"
        _render_code, manifest = run_render(
            [
                str(stl),
                "--out-dir",
                str(root / "renders"),
                "--photo",
                str(photo),
                "--overlay-fit",
                "auto",
                "--exclude-roi",
                exclude,
                "--overwrite",
            ]
        )
        alignment = manifest.get("alignment") or {}
        axes = choose_axes(mesh.extents)
        points, _depth = _project(np.asarray(mesh.vertices, dtype=float), "front", axes)
        model, _minimum, _maximum = raster_model(points, np.asarray(mesh.faces), float(fixture["px_per_mm"]))
        placed = _place(
            model,
            truth,
            float(manifest.get("overlay_rotation_deg") or 0),
            bool(manifest.get("overlay_mirror")),
            close=True,
            scale_mode="fixed",
        )
        overlap = float(_iou(placed, truth))
        rotation = float(manifest.get("overlay_rotation_deg") or 0)
        pose_error = min(
            _angle_distance(rotation, fixture["angle_deg"]),
            _angle_distance(rotation, -float(fixture["angle_deg"])),
        )
        passed = (
            code == 0
            and checked.get("ok") is True
            and alignment.get("confidence") not in {None, "low"}
            and alignment.get("chamfer_norm") is not None
            and float(alignment["chamfer_norm"]) <= 0.05
            and pose_error <= 10.0
            and overlap >= 0.7
            and abs(float(manifest.get("photo_scale_px_per_mm") or 0) - float(fixture["px_per_mm"])) < 0.05
        )
        return {
            "passed": passed,
            "tool_calls": 4,
            "wrong_skill_ids": _skill_misses(checked, manifest),
            "deleted_files": [],
            "detail": None
            if passed
            else {
                "confidence": alignment.get("confidence"),
                "chamfer_norm": alignment.get("chamfer_norm"),
                "pose_error": pose_error,
                "iou": overlap,
                "scale": manifest.get("photo_scale_px_per_mm"),
                "failures": checked.get("failures"),
            },
        }


def _pip_hinge_fine() -> dict:
    """160-segment barrels, Ø3.8 pin-clearance bores, five coaxial knuckles.

    Not registered in ``_checks``: ``tasks.json`` has no prompt for it.
    ``tests/test_v0112.py`` covers the same mesh.
    """
    from evals.meshes import pip_hinge_fine_tessellation

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        mesh = pip_hinge_fine_tessellation()
        path = root / "pip_hinge_v1.stl"
        mesh.export(path)
        code, report = run_validate(
            str(path),
            spec={"hole_count": 2, "knuckles": 5, "knuckle_axis": "x"},
        )
        rows = {item.get("name"): item for item in report.get("spec") or []}
        bores = (rows.get("hole_count") or {}).get("bores") or []
        diameters = [float(item.get("diameter") or 0) for item in bores if isinstance(item, dict)]
        clearances = [float(item.get("clearance_mm") or 0) for item in bores if isinstance(item, dict)]
        kinds = [item.get("kind") for item in bores if isinstance(item, dict)]
        knuckles = rows.get("knuckles") or {}
        passed = (
            code == 0
            and rows.get("hole_count", {}).get("actual") == 2
            and len(diameters) == 2
            and all(abs(item - 3.8) <= 0.08 for item in diameters)
            and all(item == "pin_clearance" for item in kinds)
            and all(abs(item - 0.4) <= 0.05 for item in clearances)
            and knuckles.get("actual") == 5
            and int(knuckles.get("cylinders") or 0) >= 2
        )
        return {
            "passed": passed,
            "tool_calls": 2,
            "wrong_skill_ids": 0,
            "deleted_files": [],
            "detail": None if passed else {"code": code, "spec": report.get("spec"), "failures": report.get("failures")},
        }


def _overlay_low() -> dict:
    from evals.meshes import washer_mesh

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        photo = root / "washer_photo.jpg"
        photo.write_bytes((ROOT / "fixtures" / "washer_photo.jpg").read_bytes())
        mesh = washer_mesh()
        stl = root / "washer_v1.stl"
        mesh.export(stl)
        run_validate(str(stl))
        _code, manifest = run_render(
            [
                str(stl),
                "--out-dir",
                str(root / "renders"),
                "--photo",
                str(photo),
                "--photo-scale",
                "4",
                "--overlay-fit",
                "auto",
                "--roi",
                "2,2,28,28",
                "--overwrite",
            ]
        )
        alignment = manifest.get("alignment") or {}
        passed = (
            alignment.get("confidence") == "low"
            and alignment.get("iou_trusted") is False
            and alignment.get("iou") is not None
            and manifest.get("overlay_iou") is not None
            and OVERLAY_LOW_STEP in str(manifest.get("next_step"))
        )
        return {
            "passed": passed,
            "tool_calls": 2,
            "wrong_skill_ids": _skill_misses(manifest),
            "deleted_files": [],
            "detail": None if passed else {"alignment": alignment, "next": manifest.get("next_step")},
        }


def _thread_from_script() -> dict:
    """An exported thread keeps its crest out of the wall check after the tags are gone."""
    import numpy as np
    import trimesh

    from photopart.features import external_thread
    from photopart.manifold_util import union_components
    from photopart.printability import check_printability

    def naked(mesh):
        return trimesh.Trimesh(
            vertices=np.asarray(mesh.vertices, dtype=float),
            faces=np.asarray(mesh.faces),
            process=True,
        )

    def wall_warning(report):
        return any("wall" in item or "thin area" in item for item in report.get("warnings") or [])

    thread = external_thread(designation="M3", length=8)
    head = trimesh.creation.cylinder(radius=2.8, height=3.0, sections=6)
    head.apply_translation((0.0, 0.0, 9.5))
    merged, _did = union_components(trimesh.util.concatenate([thread, head]))
    union_report = check_printability(naked(merged))
    raw_report = check_printability(naked(thread))
    flange = trimesh.creation.cylinder(radius=6.0, height=0.3, sections=48)
    flange.apply_translation((0.0, 0.0, 4.0))
    flanged, _did = union_components(trimesh.util.concatenate([external_thread(designation="M3", length=8), flange]))
    flange_report = check_printability(naked(flanged))
    passed = (
        not wall_warning(union_report)
        and isinstance(union_report.get("min_wall_raw_mm"), (int, float))
        and union_report["min_wall_raw_mm"] < 0.3
        and not wall_warning(raw_report)
        and bool(raw_report.get("auto_feature"))
        and wall_warning(flange_report)
    )
    return {
        "passed": passed,
        "tool_calls": 3,
        "wrong_skill_ids": 0,
        "deleted_files": [],
        "detail": None
        if passed
        else {"union": union_report, "raw": raw_report, "flange": flange_report},
    }


def _coin_scene(diameter_mm: float, length_mm: float, width_mm: float, tilt_deg: float = 0.0):
    """Synthetic coin and peg. Straight pegs are exact pixel rectangles."""
    import math

    import numpy as np

    scale = 4.0
    coin_px = float(diameter_mm) * scale
    height, width = 560, 720
    canvas = np.full((height, width, 3), 245, dtype=np.uint8)
    yy, xx = np.ogrid[:height, :width]
    cx, cy, radius = 200.0, 270.0, coin_px / 2.0
    canvas[((xx - cx) ** 2 + (yy - cy) ** 2) <= radius ** 2] = (70, 74, 78)
    length = length_mm * scale
    wide = width_mm * scale
    pcx, pcy = 480.0, 280.0
    if tilt_deg:
        angle = math.radians(tilt_deg)
        cos, sin = math.cos(angle), math.sin(angle)
        x0 = np.arange(width)[None, :] - pcx
        y0 = np.arange(height)[:, None] - pcy
        xr = cos * x0 + sin * y0
        yr = -sin * x0 + cos * y0
        canvas[(np.abs(xr) <= length / 2.0) & (np.abs(yr) <= wide / 2.0)] = (18, 18, 18)
    else:
        x0 = int(round(pcx - length / 2.0))
        y0 = int(round(pcy - wide / 2.0))
        canvas[y0 : y0 + int(round(wide)), x0 : x0 + int(round(length))] = (18, 18, 18)
    noise = np.random.default_rng(11).normal(0, 2.5, canvas.shape)
    canvas = np.clip(canvas.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    return canvas, (int(round(pcx)), int(round(pcy)))


def _stage_coin_photos(destination: Path) -> list[str]:
    """Write the three synthetic coin scenes the sealed task measures.

    Real caliper photos are not in this repo. Staging used to copy nothing,
    so a Hermes session drew its own fixture and never called measure on a
    known image. These are the same scenes the in-process check renders.
    """
    from PIL import Image

    names = []
    cases = (
        ("us_quarter", 24.26, 18.0, 10.0, 0.0),
        ("cad_loonie", 26.5, 22.0, 12.0, 0.0),
        ("euro_1", 23.25, 16.0, 8.0, 20.0),
    )
    for coin, diameter, length, width, tilt in cases:
        image, _seed = _coin_scene(diameter, length, width, tilt)
        name = f"{coin}.png"
        Image.fromarray(image, mode="RGB").save(destination / name)
        names.append(name)
    return names


def _coin_scale_sealed() -> dict:
    """Synthetic stand-in for the sealed coin task. Real caliper photos are not in the repo."""
    from PIL import Image

    from photopart.measure import measure

    cases = (
        ("us_quarter", 24.26, 18.0, 10.0, 0.0, 0.05),
        ("cad_loonie", 26.5, 22.0, 12.0, 0.0, 0.05),
        ("euro_1", 23.25, 16.0, 8.0, 20.0, 0.08),
    )
    details = []
    passed = True
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for coin, _diameter, length, width, tilt, tolerance in cases:
            image, seed = _coin_scene(_diameter, length, width, tilt)
            path = root / f"{coin}.png"
            Image.fromarray(image, mode="RGB").save(path)
            report = measure(
                {
                    "coin": coin,
                    "image": str(path),
                    "auto": True,
                    "part_seed": [seed[0], seed[1]],
                    "out_dir": str(root / coin),
                }
            )
            got = report.get("part_bbox_mm") or [0.0, 0.0]
            truth = sorted((length, width), reverse=True)
            errors = [abs(float(got[index]) - truth[index]) / truth[index] for index in range(2)]
            ok = max(errors) <= tolerance
            passed = passed and ok
            if not ok:
                details.append({"coin": coin, "got": got, "truth": truth, "errors": errors})
    return {
        "passed": passed,
        "tool_calls": 3,
        "wrong_skill_ids": 0,
        "deleted_files": [],
        "detail": None if passed else details,
    }


_CHECKS = _checks()


if __name__ == "__main__":
    raise SystemExit(main())
