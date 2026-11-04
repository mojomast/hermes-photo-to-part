"""In-process tools. Hermes runs these inside the plugin environment.

Handlers return one JSON document and do not write status to stdout.
Importing this module does not import trimesh; the handlers do, on first use.
"""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

from photopart.flow import SKILL_ID, attach_flow

TOOL_NAMES = (
    "photo_part_validate",
    "photo_part_render",
    "photo_part_heal",
    "photo_part_template",
    "photo_part_measure",
    "photo_part_build",
)

_UNIT_HELP = "File units: mm, cm, m, or in. Converted to millimetres. Omit to treat numbers as millimetres."


def _params(params) -> dict:
    if params is None:
        return {}
    if isinstance(params, str):
        loaded = json.loads(params)
        if not isinstance(loaded, dict):
            raise ValueError("tool arguments must be an object")
        return loaded
    if not isinstance(params, dict):
        raise ValueError("tool arguments must be an object")
    return params


def _dump(payload: dict) -> str:
    """``skill_id`` and ``skill_view`` stay on the first lines. The rest is sorted."""
    ordered = {}
    for key in ("skill_id", "skill_view"):
        if key in payload:
            ordered[key] = payload[key]
    for key in sorted(payload):
        if key not in ordered:
            ordered[key] = payload[key]
    return json.dumps(ordered, indent=2)


def _lead(text: str) -> str:
    """Tool text Hermes shows. The exact skill id stays in front if it is cut."""
    return (
        f"{SKILL_ID}. "
        f'skill_view("{SKILL_ID}") is the only skill id. '
        "Copy that id exactly. It has no plugin: prefix and no slash. "
        "Do not pass it to skills_list. "
        f"{text}"
    )


_CONCISE_DROP = {"history", "overlay_poses", "stdout", "stderr", "versions"}

# PluginContext.register_tool on Hermes v0.21.7 (NousResearch/hermes-agent
# hermes_cli/plugins.py, tag v0.21.7, commit 71d34bad). output_schema is not
# one of these. Later builds may add keywords; those stay optional.
_HERMES_V0217_REGISTER_PARAMS = frozenset({
    "name",
    "toolset",
    "schema",
    "handler",
    "check_fn",
    "requires_env",
    "is_async",
    "description",
    "emoji",
    "override",
})
_UNEXPECTED_KEYWORD = re.compile(r"unexpected keyword argument '([^']+)'")


def _output_schema(name: str) -> dict:
    """Declared result. Hermes uses it when register_tool accepts output_schema."""
    return {
        "type": "object",
        "properties": {
            "ok": {"type": "boolean"},
            "error": {"type": "string"},
            "cause": {"type": "string"},
            "fix": {"type": "string"},
            "next_step": {"type": "string"},
            "skill_id": {"type": "string"},
            "response_format": {"type": "string"},
        },
        "required": ["ok", "next_step", "skill_id"],
        "description": name,
    }


def _emit(
    payload: dict,
    fallback: str,
    *,
    plain_error: bool = False,
    response_format: str = "concise",
    tool_name: str = "photo_part",
    calls_used=None,
) -> str:
    if payload.get("error") and not plain_error and SKILL_ID not in str(payload["error"]):
        payload["error"] = f"{payload['error']} Skill id: {SKILL_ID}."
    if payload.get("error"):
        text = str(payload["error"]).strip()
        payload.setdefault("cause", text.split("\n", 1)[0])
        payload.setdefault("fix", "Change that one input and run the same tool again.")
    if not payload.get("next_step"):
        attach_flow(payload, fallback)
    elif "skill_id" not in payload:
        payload["skill_id"] = SKILL_ID
    mode = response_format if response_format in {"concise", "detailed"} else "concise"
    payload["response_format"] = mode
    if mode == "detailed":
        payload["output_schema"] = _output_schema(tool_name)
    if mode == "concise":
        for key in _CONCISE_DROP:
            payload.pop(key, None)
        if isinstance(payload.get("failures"), list) and len(payload["failures"]) > 8:
            payload["failures"] = payload["failures"][:8]
    from photopart.budget import attach_budget

    payload["skill_view"] = f'skill_view("{SKILL_ID}")'
    attach_budget(payload, tool_name, calls_used=calls_used)
    return _dump(payload)


def _calls_used(args: dict):
    if not isinstance(args, dict) or "calls_used" not in args:
        return None
    value = args.get("calls_used")
    if value is None or value == "":
        return None
    return value


def _bind_session(kwargs) -> None:
    """Keep the session id Hermes v0.21.7 passes into the handler."""
    import os

    from photopart.budget import session_id_var

    found = None
    if isinstance(kwargs, dict):
        raw = kwargs.get("session_id")
        if isinstance(raw, str) and raw.strip():
            found = raw.strip()
    if not found:
        found = os.environ.get("HERMES_SESSION_ID", "").strip() or None
    session_id_var.set(found)


def _over_budget(args: dict, *, kind: str, mesh, final: bool = False):
    """Refuse a non-final render or a repeat validate once 80% of the cap is used.

    The final validate (no fresh passing sidecar yet, or a checklist answer)
    and a render with ``final`` true still run.
    """
    if final or not isinstance(mesh, str) or not mesh.strip():
        return None
    if kind == "validate" and not _repeat_validate(mesh, args):
        return None
    from photopart.budget import consumption, past_soft_wall

    info = consumption({"file": mesh}, _calls_used(args))
    if not past_soft_wall(info):
        return None
    name = _best_name(mesh)
    phrase = "repeat validate refused" if kind == "validate" else "render refused"
    text = f"Budget: deliver {name} now; {phrase}."
    return {
        "ok": False,
        "refused": True,
        "budget_refused": kind,
        "file": mesh,
        "error": text,
        "next_step": text,
        "skill_id": SKILL_ID,
    }


def _repeat_validate(mesh: str, args: dict) -> bool:
    """True when this file already has a fresh passing sidecar and no new answer."""
    if _answers_present(args):
        return False
    path = Path(mesh).expanduser()
    if not path.is_file():
        return False
    from photopart.stamp import mesh_hash, read_sidecar

    side = read_sidecar(path)
    if not isinstance(side, dict) or side.get("ok") is not True:
        return False
    try:
        return side.get("sha256") == mesh_hash(path)
    except OSError:
        return False


def _answers_present(args: dict) -> bool:
    raw = args.get("answer")
    if raw is None or raw == "":
        raw = args.get("answers")
    return raw not in (None, "", [])


def _best_name(mesh: str) -> str:
    path = Path(mesh).expanduser()
    try:
        from photopart.score import best_validated

        info = best_validated(path)
    except OSError:
        info = None
    if isinstance(info, dict) and info.get("name"):
        return str(info["name"])
    return "the best validated file"


def _wants_help(args: dict) -> bool:
    if not isinstance(args, dict):
        return False
    if args.get("help") or args.get("describe"):
        return True
    return str(args.get("mode") or "").strip().lower() in {"help", "describe"}


def _format(args: dict) -> str:
    value = str(args.get("response_format") or "concise")
    if value not in {"concise", "detailed"}:
        raise ValueError("response_format must be concise or detailed")
    return value


def _abs(path) -> str | None:
    if path is None:
        return None
    return str(Path(path).expanduser().resolve())


def _csv_rect(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return f"{float(value['x'])},{float(value['y'])},{float(value['w'])},{float(value['h'])}"
    return ",".join(str(float(item)) for item in value)


def _extend_rects(argv: list[str], value) -> None:
    if value is None or value == "":
        return
    if isinstance(value, str):
        argv.extend(["--exclude-roi", value.strip()])
        return
    if isinstance(value, dict):
        argv.extend(["--exclude-roi", _csv_rect(value)])
        return
    if isinstance(value, (list, tuple)):
        if len(value) == 4 and all(isinstance(item, (int, float)) for item in value):
            argv.extend(["--exclude-roi", _csv_rect(value)])
            return
        for item in value:
            _extend_rects(argv, item)


def _optional_int(params: dict, key: str) -> int | None:
    if key not in params or params[key] is None or params[key] == "":
        return None
    return int(params[key])


def _optional_float(params: dict, key: str) -> float | None:
    if key not in params or params[key] is None or params[key] == "":
        return None
    return float(params[key])


def _optional_str(params: dict, key: str) -> str | None:
    value = params.get(key)
    if value is None or value == "":
        return None
    return str(value)


def _flag(params: dict, key: str) -> bool:
    return bool(params.get(key, False))


def _size(params: dict) -> tuple[float, float, float] | None:
    raw = params.get("size")
    if raw is None or raw == "":
        return None
    if isinstance(raw, str):
        pieces = raw.replace(",", " ").split()
    else:
        pieces = list(raw)
    if len(pieces) != 3:
        raise ValueError("size must be three millimetre lengths, X Y Z")
    return tuple(float(piece) for piece in pieces)  # type: ignore[return-value]


def validate_tool(params, **_kwargs) -> str:
    """Check watertightness and the bounding box. Size targets are millimetres."""
    _bind_session(_kwargs)
    mode = "concise"
    args: dict = {}
    try:
        args = _params(params)
        mode = _format(args)
        blocked = _over_budget(args, kind="validate", mesh=args.get("mesh"))
        if blocked:
            return _emit(
                blocked,
                blocked["next_step"],
                plain_error=True,
                response_format=mode,
                tool_name="photo_part_validate",
                calls_used=_calls_used(args),
            )
        from photopart.validate import run_validate

        _code, report = run_validate(
            str(args["mesh"]),
            size=_size(args),
            tolerance=float(args.get("tolerance", 0.3)),
            allow_axis_swap=_flag(args, "allow_axis_swap"),
            allow_open=_flag(args, "allow_open"),
            allow_multi_shell=_flag(args, "allow_multi_shell"),
            expected_shells=_optional_int(args, "expected_shells"),
            allow_size=_flag(args, "allow_size"),
            holes=args.get("holes"),
            units=_optional_str(args, "units"),
            scale=_optional_float(args, "scale"),
            json_out=_optional_str(args, "json_out"),
            spec=args.get("spec"),
            dims=args.get("dims") or args.get("dim"),
            max_bytes=int(args.get("max_bytes", 256 * 1024 * 1024)),
            spec_reason=_optional_str(args, "reason"),
            min_wall_mm=float(args.get("min_wall_mm", 0.8)),
            overhang_deg=float(args.get("overhang_deg", 45)),
            max_overhang_fraction=float(args.get("max_overhang_fraction", 0.35)),
            min_bed_mm2=float(args.get("min_bed_mm2", 1)),
            min_gap_mm=float(args.get("min_gap_mm", 0.3)),
            print_strict=_flag(args, "print_strict"),
            answers=_answers(args),
        )
        _maybe_render(args, report)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return _emit(
            {"ok": False, "error": str(exc), "mesh": args.get("mesh") if isinstance(args.get("mesh"), str) else None},
            "Fix the arguments, then photo_part_validate the mesh.",
            response_format=mode,
            tool_name="photo_part_validate",
            calls_used=_calls_used(args),
        )
    return _emit(
        report,
        "Next: photo_part_render the same file, then deliver it.",
        response_format=mode,
        tool_name="photo_part_validate",
            calls_used=_calls_used(args),
    )


def _answers(args: dict) -> list | None:
    raw = args.get("answer")
    if raw is None or raw == "":
        raw = args.get("answers")
    if raw is None or raw == "":
        return None
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, (list, tuple)):
        return list(raw)
    raise ValueError("answer must be item=yes or a list of those")


def _num(value) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return str(number)


def _roi_arg(roi) -> str | None:
    if isinstance(roi, str) and roi.strip():
        return roi.strip()
    if isinstance(roi, dict) and {"x", "y", "w", "h"} <= set(roi):
        return ",".join(_num(roi[key]) for key in ("x", "y", "w", "h"))
    if isinstance(roi, (list, tuple)) and len(roi) == 4:
        return ",".join(_num(item) for item in roi)
    return None


def _seed_arg(seed) -> str | None:
    if isinstance(seed, str) and seed.strip():
        return seed.strip()
    if isinstance(seed, dict) and "x" in seed and "y" in seed:
        return f"{_num(seed['x'])},{_num(seed['y'])}"
    if isinstance(seed, (list, tuple)) and len(seed) == 2:
        return f"{_num(seed[0])},{_num(seed[1])}"
    return None


def _maybe_render(args: dict, report: dict) -> None:
    """Render in-process after a passing validate that was given a spec.

    ``render`` defaults to that case. A failing validate does not render.
    The sheet includes the photo overlay from the last measure step (photo,
    pixels per millimetre, and region) so a later render is not required.
    ``photo_part_render`` stays available for an extra sheet.
    """
    if not isinstance(report, dict) or report.get("error"):
        return
    flag = args.get("render", None)
    if flag is None:
        wanted = bool(report.get("ok") and args.get("spec"))
    else:
        wanted = bool(flag) and bool(report.get("ok"))
    if not wanted:
        return
    mesh = report.get("file") or args.get("mesh")
    if not mesh:
        return
    project = Path(str(mesh)).expanduser().resolve().parent
    out = project / "renders"
    argv = [str(mesh), "--out-dir", str(out), "--overwrite"]
    from photopart.measure import load_last_measure
    from photopart.paths import not_a_project

    dirs = [project]
    cwd = Path.cwd().resolve()
    if not not_a_project(cwd):
        dirs.append(cwd)
    photo = _optional_str(args, "photo")
    hint = load_last_measure(*dirs, image=photo) or {}
    if not photo and isinstance(hint.get("image"), str):
        candidate = Path(hint["image"])
        if candidate.is_file():
            photo = str(candidate)
    if photo:
        argv.extend(["--photo", photo])
    scale = _optional_float(args, "photo_scale")
    if scale is None and hint.get("px_per_mm") not in {None, ""}:
        try:
            scale = float(hint["px_per_mm"])
        except (TypeError, ValueError):
            scale = None
    if scale is not None:
        argv.extend(["--photo-scale", str(scale)])
    fit = _optional_str(args, "overlay_fit") or _optional_str(args, "views")
    overlay = args.get("overlay")
    if fit in {"auto", "center"}:
        argv.extend(["--overlay-fit", fit])
    elif photo and scale is not None:
        argv.extend(["--overlay-fit", "auto"])
    elif overlay in {True, "auto"}:
        argv.extend(["--overlay-fit", "auto"])
    roi = args.get("roi")
    if roi is None or roi == "":
        roi = hint.get("roi")
    roi_text = _roi_arg(roi)
    if roi_text:
        argv.extend(["--roi", roi_text])
    seed = args.get("seed")
    if seed is None or seed == "":
        seed = hint.get("seed")
    seed_text = _seed_arg(seed)
    if seed_text:
        argv.extend(["--seed", seed_text])
    from photopart.render import run_render

    _code, manifest = run_render(argv)
    alignment = manifest.get("alignment") if isinstance(manifest, dict) else None
    report["render"] = {
        "sheet": None if not isinstance(manifest, dict) else manifest.get("sheet"),
        "overlay": None if not isinstance(manifest, dict) else manifest.get("overlay"),
        "overlay_status": None if not isinstance(manifest, dict) else manifest.get("overlay_status"),
        "next_step": None if not isinstance(manifest, dict) else manifest.get("next_step"),
        "alignment": alignment,
        "photo": photo,
        "photo_scale": scale,
        "roi": roi_text,
        "ok": bool(isinstance(manifest, dict) and manifest.get("ok")),
        "error": None if not isinstance(manifest, dict) else manifest.get("error"),
    }
    if report["render"].get("overlay_status") == "missing_scale":
        report["next_step"] = report["render"]["next_step"]


def render_tool(params, **_kwargs) -> str:
    """Render fitted views and, with photo_scale, an outline overlay on the photo."""
    _bind_session(_kwargs)
    mode = "concise"
    args: dict = {}
    try:
        args = _params(params)
        mode = _format(args)
        blocked = _over_budget(args, kind="render", mesh=args.get("mesh"), final=_flag(args, "final"))
        if blocked:
            return _emit(
                blocked,
                blocked["next_step"],
                plain_error=True,
                response_format=mode,
                tool_name="photo_part_render",
                calls_used=_calls_used(args),
            )
        argv = [str(args["mesh"]), "--out-dir", str(args["out_dir"])]
        photo = _optional_str(args, "photo")
        if photo:
            argv.extend(["--photo", photo])
        photo_scale = _optional_float(args, "photo_scale")
        if photo_scale is not None:
            argv.extend(["--photo-scale", str(photo_scale)])
        origin = args.get("overlay_origin")
        if isinstance(origin, (list, tuple)) and len(origin) == 2:
            argv.extend(["--overlay-origin", f"{float(origin[0])},{float(origin[1])}"])
        elif isinstance(origin, str) and origin.strip():
            argv.extend(["--overlay-origin", origin.strip()])
        fit = _optional_str(args, "overlay_fit")
        if fit:
            argv.extend(["--overlay-fit", fit])
        roi = args.get("roi")
        if isinstance(roi, str) and roi.strip():
            argv.extend(["--roi", roi.strip()])
        elif isinstance(roi, (list, tuple)) and len(roi) == 4:
            argv.extend(["--roi", _csv_rect(roi)])
        seed = args.get("seed")
        if isinstance(seed, str) and seed.strip():
            argv.extend(["--seed", seed.strip()])
        elif isinstance(seed, (list, tuple)) and len(seed) == 2:
            argv.extend(["--seed", f"{float(seed[0])},{float(seed[1])}"])
        _extend_rects(argv, args.get("exclude_roi"))
        measure_json = args.get("measure_json")
        if isinstance(measure_json, str) and measure_json.strip():
            argv.extend(["--measure-json", measure_json.strip()])
        if _flag(args, "angled"):
            argv.append("--angled")
        grid = _optional_float(args, "grid_mm")
        if grid is not None:
            argv.extend(["--grid-mm", str(grid)])
        up = _optional_str(args, "up")
        if up:
            argv.extend(["--up", up])
        front_axis = _optional_str(args, "front_axis")
        if front_axis:
            argv.extend(["--front-axis", front_axis])
        units = _optional_str(args, "units")
        if units:
            argv.extend(["--units", units])
        scale = _optional_float(args, "scale")
        if scale is not None:
            argv.extend(["--scale", str(scale)])
        if _flag(args, "force") or _flag(args, "overwrite"):
            argv.append("--overwrite")
        if _flag(args, "final"):
            argv.append("--final")
        if "max_bytes" in args and args["max_bytes"] is not None:
            argv.extend(["--max-bytes", str(int(args["max_bytes"]))])
        from photopart.render import run_render

        _code, report = run_render(argv, measure_payload=measure_json if isinstance(measure_json, dict) else None)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return _emit(
            {"ok": False, "error": str(exc)},
            "Fix the render arguments, then photo_part_render the validated file.",
            response_format=mode,
            tool_name="photo_part_render",
            calls_used=_calls_used(args),
        )
    return _emit(
        report,
        "Read stale_validation. Deliver the file only when it is false and validation_ok is true.",
        response_format=mode,
        tool_name="photo_part_render",
            calls_used=_calls_used(args),
    )


def heal_tool(params, **_kwargs) -> str:
    """Heal a scan into a new STL. Report fan fallback and shell counts separately."""
    _bind_session(_kwargs)
    mode = "concise"
    args: dict = {}
    try:
        args = _params(params)
        mode = _format(args)
        argv = [str(args["mesh"]), "--out", str(args["out"])]
        if _flag(args, "fan"):
            argv.append("--fan")
        if _flag(args, "keep_all"):
            argv.append("--keep-all")
        if _flag(args, "union"):
            argv.append("--union")
        engine = _optional_str(args, "engine")
        if engine:
            argv.extend(["--engine", engine])
        if _flag(args, "allow_size"):
            argv.append("--allow-size")
        if _flag(args, "ascii"):
            argv.append("--ascii")
        if _flag(args, "force") or _flag(args, "overwrite"):
            argv.append("--overwrite")
        units = _optional_str(args, "units")
        if units:
            argv.extend(["--units", units])
        scale = _optional_float(args, "scale")
        if scale is not None:
            argv.extend(["--scale", str(scale)])
        if "max_bytes" in args and args["max_bytes"] is not None:
            argv.extend(["--max-bytes", str(int(args["max_bytes"]))])
        from photopart.heal import run_heal

        _code, report = run_heal(argv)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return _emit(
            {"ok": False, "error": str(exc)},
            "Fix the heal arguments. Write a new name_vN.stl. Do not overwrite a validated mesh.",
            response_format=mode,
            tool_name="photo_part_heal",
            calls_used=_calls_used(args),
        )
    return _emit(
        report,
        "Next: photo_part_validate the healed STL, then render it.",
        response_format=mode,
        tool_name="photo_part_heal",
            calls_used=_calls_used(args),
    )


def template_tool(params, **_kwargs) -> str:
    """Write a building block. The default shape is still the sample plate."""
    _bind_session(_kwargs)
    mode = "concise"
    args: dict = {}
    try:
        args = _params(params)
        mode = _format(args)
        if _wants_help(args):
            from photopart.catalog import describe_shapes
            from photopart.flow import step_model

            described = describe_shapes(_optional_str(args, "shape"))
            attach_flow(described, step_model("the STL from this template"))
            return _emit(
                described,
                step_model("the STL from this template"),
                response_format=mode,
                tool_name="photo_part_template",
                calls_used=_calls_used(args),
            )
        from photopart.parts import default_stl_name, output_names, write_shape

        shape = str(args.get("shape") or "plate_clip")
        overrides = _template_params(args, shape)
        from photopart.paths import absolute_path

        raw_out = args.get("out_dir")
        out_dir = absolute_path(raw_out if raw_out else ".")
        stl_name = default_stl_name(shape, out_dir, _optional_str(args, "stl"))
        write_3mf = not bool(args.get("no_3mf", False))
        if not (_flag(args, "force") or _flag(args, "overwrite")):
            existing = [
                name
                for name in output_names(shape, write_3mf=write_3mf, stl_name=stl_name)
                if (out_dir / name).exists()
            ]
            if existing:
                joined = ", ".join(existing)
                raise ValueError(f"refusing to overwrite {joined}. Pass --overwrite.")
        written = write_shape(
            out_dir,
            shape,
            overrides,
            ascii_stl=bool(args.get("ascii", False)),
            write_3mf=write_3mf,
            stl_name=stl_name,
        )
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        return _emit(
            {"ok": False, "error": str(exc)},
            "Try a photo_part_template shape before a custom script. Pass an absolute project out_dir.",
            response_format=mode,
            tool_name="photo_part_template",
            calls_used=_calls_used(args),
        )
    from photopart.flow import step_model
    from photopart.history import missing_versions
    from photopart.launcher import plugin_python

    stl = _abs(written["stl"])
    missing = missing_versions(written["stl"]) if written.get("stl") else []
    summary = {
        "ok": bool(written["mesh"].is_watertight),
        "shape": written.get("shape", "plate_clip"),
        "shells": written.get("shells", 1),
        "stl": stl,
        "scad": _abs(written["scad"]),
        "threemf": _abs(written["threemf"]),
        "threemf_error": written["threemf_error"],
        "interpreter": plugin_python(),
        "missing_earlier": missing,
        "expected_extents_mm": {
            "x": written["expected_extents_mm"][0],
            "y": written["expected_extents_mm"][1],
            "z": written["expected_extents_mm"][2],
        },
        "triangles": int(len(written["mesh"].faces)),
        "watertight": bool(written["mesh"].is_watertight),
        "spec_checks": written.get("spec_checks"),
    }
    from photopart.facts import mesh_facts
    from photopart.spec import note_missing_spec

    summary.update(mesh_facts(written["mesh"]))
    named = stl or str((out_dir / (stl_name or f"{shape}_v1.stl")).resolve())
    attach_flow(summary, step_model(named))
    note_missing_spec(summary, Path.cwd(), out_dir)
    return _emit(
        summary,
        step_model(named),
        response_format=mode,
        tool_name="photo_part_template",
            calls_used=_calls_used(args),
    )


def measure_tool(params, **_kwargs) -> str:
    """Pixel scale from a coin or a ruler, plus an optional rectified image."""
    _bind_session(_kwargs)
    mode = "concise"
    args: dict = {}
    try:
        args = _params(params)
        mode = _format(args)
        from photopart.measure import measure

        report = measure(args)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return _emit(
            {"ok": False, "error": str(exc)},
            "Fix the measure arguments. Pass an absolute project path for out.",
            response_format=mode,
            tool_name="photo_part_measure",
            calls_used=_calls_used(args),
        )
    return _emit(
        report,
        "Next: photo_part_template or photo_part_build, then photo_part_validate the new STL.",
        response_format=mode,
        tool_name="photo_part_measure",
            calls_used=_calls_used(args),
    )


def build_tool(params, **_kwargs) -> str:
    """Run a local Python build script with the plugin interpreter."""
    _bind_session(_kwargs)
    mode = "concise"
    args: dict = {}
    try:
        args = _params(params)
        mode = _format(args)
        if _wants_help(args):
            from photopart.catalog import describe_features
            from photopart.flow import step_build

            described = describe_features()
            attach_flow(described, step_build([], ok=True))
            return _emit(
                described,
                step_build([], ok=True),
                response_format=mode,
                tool_name="photo_part_build",
                calls_used=_calls_used(args),
            )
        if not args.get("script"):
            raise ValueError("script is required unless help or describe is true")
        from photopart.build_run import run_build

        extra = args.get("args") or []
        if extra is None:
            extra = []
        if isinstance(extra, str):
            raise ValueError("args must be a list of strings")
        report = run_build(
            str(args["script"]),
            cwd=args.get("cwd"),
            timeout=float(args.get("timeout", 60) if args.get("timeout") is not None else 60),
            args=list(extra),
        )
        from photopart.facts import facts_for_stl

        for output in report.get("outputs") or []:
            if str(output).lower().endswith(".stl"):
                facts = facts_for_stl(output)
                if facts:
                    report.update(facts)
                break
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return _emit(
            {"ok": False, "error": str(exc)},
            "Try photo_part_template shapes such as l_bracket before a custom script.",
            response_format=mode,
            tool_name="photo_part_build",
            calls_used=_calls_used(args),
        )
    return _emit(
        report,
        "Next: photo_part_validate the STL the script wrote, with spec.json. Do not overwrite it.",
        plain_error=bool(report.get("error")),
        response_format=mode,
        tool_name="photo_part_build",
            calls_used=_calls_used(args),
    )


def _schema(name: str, description: str, properties: dict, required: list[str]) -> dict:
    fields = dict(properties)
    fields["response_format"] = {
        "type": "string",
        "enum": ["concise", "detailed"],
        "description": "concise drops history, full pose lists, and build logs. Default concise.",
    }
    fields["calls_used"] = {
        "type": "integer",
        "description": (
            "Tool calls already used in this Hermes session, including skill_view and other tools. "
            "Pass it on every call. Hermes v0.21.7 also supplies session_id; when that session "
            "is on disk the count comes from state.db or HERMES_HOME/sessions. The larger number wins. "
            "The cap is about 40 (PHOTO_PART_MAX_CALLS). Omit both and remaining is estimated high."
        ),
    }
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": fields,
            "required": required,
        },
    }


def tool_specs() -> list[dict]:
    validate = {
        "name": "photo_part_validate",
        "description": _lead(
            "Check a mesh for a watertight single shell and an expected size in millimetres. "
            "Writes <file>.validate.json with the mesh hash. Do not overwrite name_vN.stl."
        ),
        "schema": _schema(
            "photo_part_validate",
            _lead(
                "Check watertightness, one shell, and the bounding box. "
                "size is X Y Z millimetres after units/scale. "
                "Does not upload the file. Returns JSON. Do not write a replacement checker. "
                "Writes <file>.validate.json with the mesh hash. That is the only sidecar name. "
                "Pass spec or dims (name=value±tol) for bbox, shells, knuckles, and hole_count. "
                "A deviation fails the check. The report includes a score, printability, and the frozen checklist. "
                "Pass reason when a frozen spec.json changed."
            ),
            {
                "mesh": {"type": "string", "description": "Path to an STL, 3MF, OBJ, or PLY file."},
                "size": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Target extents in millimetres: X, Y, Z.",
                },
                "tolerance": {"type": "number", "description": "Allowed error in millimetres. Default 0.3."},
                "allow_axis_swap": {"type": "boolean", "description": "Compare sorted extents."},
                "allow_open": {"type": "boolean"},
                "allow_multi_shell": {
                    "type": "boolean",
                    "description": "Accept any shell count. A print-in-place part should prefer expected_shells.",
                },
                "expected_shells": {
                    "type": "integer",
                    "description": "Exact shell count. Use 2 for a print-in-place hinge. Wins over the one-shell rule.",
                },
                "allow_size": {
                    "type": "boolean",
                    "description": "Accept a longest side under 1 mm or over 2 m. Without this, that size fails.",
                },
                "holes": {
                    "type": "array",
                    "description": "Holes to check: {x, y, diameter, optional z, optional axis}. Millimetres.",
                    "items": {"type": "object"},
                },
                "units": {"type": "string", "description": _UNIT_HELP},
                "scale": {"type": "number", "description": "Extra multiplier after units."},
                "json_out": {
                    "type": "string",
                    "description": "Not a second sidecar. The only validation file is <file>.validate.json.",
                },
                "spec": {
                    "type": "string",
                    "description": "Path to spec.json, or a JSON object of x, y, z, shells, knuckles, hole_count, holes.",
                },
                "dims": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Checks such as x=100±0.5 or knuckles=5. Counts are exact unless a tolerance is given.",
                },
                "reason": {
                    "type": "string",
                    "description": "Why a frozen spec.json checklist or number changed. Required after the first validate of that file.",
                },
                "answer": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Checklist answers item=yes or item=no. Repeatable. Not a spec edit and does not need reason.",
                },
                "render": {
                    "type": "boolean",
                    "description": (
                        "Render sheet.png in this call. Default true when the check passes and spec was given. "
                        "A failure does not render. The photo overlay uses the region and scale from the last measure step."
                    ),
                },
                "photo": {"type": "string", "description": "Photo passed through to the automatic render."},
                "photo_scale": {"type": "number", "description": "Pixels per millimetre for the automatic overlay."},
                "views": {"type": "string", "description": "Overlay fit passed through: auto or center."},
                "overlay": {"type": "boolean", "description": "When true, the automatic render uses overlay_fit auto."},
                "roi": {"type": "array", "items": {"type": "number"}, "description": "Part region passed through to the overlay."},
                "min_wall_mm": {"type": "number", "description": "Warn when the thinnest inward ray is under this. Default 0.8."},
                "overhang_deg": {"type": "number", "description": "Overhang starts past this angle from vertical. Default 45."},
                "max_overhang_fraction": {"type": "number", "description": "Warn when overhang area exceeds this fraction. Default 0.35."},
                "min_bed_mm2": {"type": "number", "description": "Warn when bed contact is under this area. Default 1."},
                "min_gap_mm": {"type": "number", "description": "Warn when bodies are closer than this. Default 0.3 mm per side."},
                "print_strict": {"type": "boolean", "description": "Turn printability warnings into failures."},
                "max_bytes": {"type": "integer"},
            },
            ["mesh"],
        ),
        "handler": validate_tool,
    }
    render = {
        "name": "photo_part_render",
        "description": _lead(
            "Render fitted views and an optional outline overlay at a known pixels-per-millimetre scale. "
            "Reports stale_validation when the mesh hash differs from <file>.validate.json."
        ),
        "schema": _schema(
            "photo_part_render",
            _lead(
                "Write front, side, top, iso, and contact PNGs fitted to the part. "
                "up defaults to the longest axis. "
                "Pass photo and photo_scale (pixels per millimetre) to draw overlay.png, the silhouette contour, on the photo. "
                "overlay_fit auto tries front, side, and top, rotation at 15 degrees then 1 degree, and a mirror. "
                "Pass roi or seed, and measure_json, so a coin is not the blob. "
                "An roi that crops the silhouette is expanded. "
                "Writes overlay_iou, overlay_iou_label, and overlay_poses. "
                "An angled photo is still scored and the label is guide_only. "
                "Also writes compare_front.png when photo is set. Do not write an overlay script. "
                "Reports stale_validation against <file>.validate.json."
            ),
            {
                "mesh": {"type": "string", "description": "Path to the mesh."},
                "out_dir": {"type": "string", "description": "Directory for the PNGs. Must be empty unless force is true."},
                "photo": {"type": "string", "description": "Reference image."},
                "photo_scale": {
                    "type": "number",
                    "description": "Pixels per millimetre for the outline overlay. For a 2 mm grid, measure one square in pixels and divide by 2.",
                },
                "overlay_origin": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Optional image pixel [x, y] of the model minimum corner. Image y grows downward. Overrides overlay_fit.",
                },
                "overlay_fit": {
                    "type": "string",
                    "description": "center (default) or auto. auto tries front, side, and top at 15° then 1°, plus a mirror. Returns overlay_rotation_deg, overlay_mirror, overlay_view, overlay_iou, overlay_iou_label, and overlay_poses.",
                },
                "final": {
                    "type": "boolean",
                    "description": "Deliver render. Refuses when the latest name_vN has no fresh <file>.validate.json. Otherwise sets needs_validation.",
                },
                "roi": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Part region [x, y, w, h] in image pixels.",
                },
                "seed": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "One image pixel [x, y] on the part. auto uses that object.",
                },
                "exclude_roi": {
                    "type": "array",
                    "description": "Rectangles to ignore, [x, y, w, h] or a list of them. A coin from photo_part_measure.",
                },
                "measure_json": {
                    "description": "photo_part_measure JSON object or a path to it. Reuses rectification and its scale when present, and reference exclusions and angled hints in the matching photo frame.",
                },
                "angled": {
                    "type": "boolean",
                    "description": "The photo is not straight-on. IoU is still computed and overlay_iou_label is guide_only.",
                },
                "grid_mm": {"type": "number", "description": "Square grid spacing in millimetres. Not drawn on the iso view."},
                "up": {"type": "string", "description": "x, y, or z. Default is the longest side."},
                "front_axis": {"type": "string", "description": "Axis the front camera looks along."},
                "units": {"type": "string", "description": _UNIT_HELP},
                "scale": {"type": "number"},
                "force": {"type": "boolean", "description": "Alias of overwrite."},
                "overwrite": {"type": "boolean", "description": "Write into a directory that is not empty."},
                "max_bytes": {"type": "integer"},
            },
            ["mesh", "out_dir"],
        ),
        "handler": render_tool,
    }
    heal = {
        "name": "photo_part_heal",
        "description": _lead(
            "Weld a scan, fill holes, and write a new STL. Refuses to overwrite unless overwrite is set. Fan caps are flat."
        ),
        "schema": _schema(
            "photo_part_heal",
            _lead(
                "Copy a scan to out. Welds vertices, drops degenerate faces, fills holes. "
                "fan_fallback means a second pass used flat fans because fan was not set. "
                "shells_dropped counts input shells only; repair_fragments_removed is separate. "
                "Pass units when the file is not millimetres. Does not guess a scale. "
                "Refuses to overwrite out unless overwrite is set."
            ),
            {
                "mesh": {"type": "string", "description": "Input scan. Not overwritten."},
                "out": {"type": "string", "description": "Output STL path, different from mesh."},
                "fan": {"type": "boolean", "description": "Fan-fill on the first pass. Caps are flat."},
                "keep_all": {"type": "boolean", "description": "Keep every shell. Default keeps the largest."},
                "union": {
                    "type": "boolean",
                    "description": "Boolean-union shells. Overlapping shells merge. Disjoint shells stay separate.",
                },
                "engine": {
                    "type": "string",
                    "enum": ["default", "meshfix"],
                    "description": "meshfix runs PyMeshFix when it is installed. If it is absent the manifold result is kept.",
                },
                "allow_size": {
                    "type": "boolean",
                    "description": "Accept a longest side under 1 mm or over 2 m. Without this, that size fails.",
                },
                "units": {"type": "string", "description": _UNIT_HELP},
                "scale": {"type": "number"},
                "ascii": {"type": "boolean"},
                "force": {"type": "boolean", "description": "Alias of overwrite."},
                "overwrite": {"type": "boolean", "description": "Replace an existing out file. Default is to refuse."},
                "max_bytes": {"type": "integer"},
            },
            ["mesh", "out"],
        ),
        "handler": heal_tool,
    }
    template = {
        "name": "photo_part_template",
        "description": _lead(
            "Write a building block such as l_bracket before any custom script. "
            "Pass help or describe true for shape parameters and a minimal example script. "
            "Do not open parts.py, features.py, or launcher.py. "
            "About 40 tool calls in total. "
            "out_dir defaults to the working directory and must not be HERMES_HOME/cache. "
            "Returns the absolute STL path and the plugin interpreter."
        ),
        "schema": _schema(
            "photo_part_template",
            _lead(
                "Write a watertight building block. shape defaults to plate_clip, the sample plate. "
                "Other shapes: plate, countersink, revolve, ribs, l_bracket, hinge, "
                "thread, knurl, sweep, hex_screw, hex_standoff, bottle_cap, "
                "spur_gear, scroll, strap_hinge. "
                "Pass help or describe true (or mode help) for every parameter and an example script. "
                "Do not open parts.py. "
                "Try these before photo_part_build. "
                "hinge is a print-in-place part with two shells. "
                "Reject a countersink deeper than the sheet before calling this. "
                "out_dir is an absolute project path. Refuses HERMES_HOME/cache and refuses to overwrite unless overwrite is set."
            ),
            {
                "out_dir": {
                    "type": "string",
                    "description": "Absolute project directory. Default: the working directory. Refuses HERMES_HOME/cache.",
                },
                "shape": {
                    "type": "string",
                    "description": "plate_clip, plate, countersink, revolve, ribs, l_bracket, hinge, thread, knurl, sweep, hex_screw, hex_standoff, bottle_cap, spur_gear, scroll, or strap_hinge.",
                },
                "params": {
                    "type": "object",
                    "description": (
                        "Shape values, in millimetres. Put knuckles and the other overrides here, "
                        "for example params={knuckles: 5}. A known shape value passed next to shape "
                        "is moved into params. An unknown name is an error that names params. "
                        "plate holes is a list of {x, y, diameter}."
                    ),
                },
                "ascii": {"type": "boolean", "description": "Write an ASCII STL."},
                "no_3mf": {"type": "boolean", "description": "Skip 3MF. 3MF needs lxml."},
                "force": {"type": "boolean", "description": "Alias of overwrite."},
                "stl": {
                    "type": "string",
                    "description": "STL filename. Default is <shape>_v1.stl, or the spec.json part slug. plate_clip stays plate_clip.stl.",
                },
                "overwrite": {"type": "boolean", "description": "Replace files already in out_dir. Default is to refuse."},
                "help": {
                    "type": "boolean",
                    "description": "Return shape parameters and a minimal example script. Does not write an STL.",
                },
                "describe": {"type": "boolean", "description": "Same as help."},
                "mode": {
                    "type": "string",
                    "enum": ["help", "describe"],
                    "description": "help or describe returns parameters and an example script instead of writing files.",
                },
            },
            [],
        ),
        "handler": template_tool,
    }
    measure = {
        "name": "photo_part_measure",
        "description": _lead(
            "Pixel-to-millimetre scale from a coin, ruler, or a user-given part dimension. Returns reference_bbox so render can exclude a separate reference, and absolute paths. "
            "Pass auto, part_seed, or part_roi to size the part. Do not open the photo with cv2 or PIL."
        ),
        "schema": _schema(
            "photo_part_measure",
            _lead(
                "Measure px_per_mm from a coin (coin id or diameter_mm, plus diameter_px or two points, "
                "or image alone to detect the circle) "
                "or a ruler (ruler_mm plus two points). "
                "auto, part_seed [x, y], or part_roi [x0, y0, x1, y1] also returns part_bbox_mm. "
                "Optional quad of four pixels TL, TR, BR, BL plus width_mm, height_mm, and image "
                "writes a rectified PNG in the working directory, never HERMES_HOME/cache. "
                "With a quad, input hints and measurement points are source-image pixels; returned px_per_mm is for the rectified frame. "
                "Returns reference_bbox and absolute paths. Same-plane, straight-on, unless a quad was given. "
                "Do not open the photo with cv2 or PIL. Do not write a perspective script. Returns JSON."
            ),
            {
                "coin": {"type": "string", "description": "euro_1, euro_2, euro_50c, us_quarter, us_penny, us_nickel, us_dime, us_half, gbp_1, cad_quarter, cad_loonie."},
                "diameter_mm": {"type": "number", "description": "Reference diameter when it is not a known coin."},
                "diameter_px": {"type": "number", "description": "That diameter in source-image pixels."},
                "reference_is_part": {"type": "boolean", "description": "True when points span a user-given part dimension rather than a separate coin or ruler. Keeps the part in the overlay mask. This scale is not independent dimensional verification."},
                "out_dir": {"type": "string", "description": "Absolute project directory for last_measure.json so validate/render can reuse this photo and scale."},
                "roi": {"type": "array", "description": "Part overlay region [x, y, width, height] in pixels."},
                "seed": {"type": "array", "description": "One [x, y] pixel on the part for the overlay."},
                "points": {
                    "type": "array",
                    "description": "Two [x, y] pixels spanning the coin diameter or the ruler length.",
                },
                "ruler_mm": {"type": "number", "description": "Real millimetres between points."},
                "measurements": {
                    "type": "array",
                    "description": "Spans to convert: {name, points or length_px, optional plane in_plane or out_of_plane}. With quad, give two source-image points per span; length_px alone cannot be perspective-corrected.",
                    "items": {"type": "object"},
                },
                "image": {"type": "string", "description": "Photo to rectify when quad is set, or the image that contains an ArUco or AprilTag."},
                "marker_mm": {"type": "number", "description": "Side length in millimetres of an ArUco or AprilTag in image."},
                "quad": {
                    "type": "array",
                    "description": "Four [x, y] pixels: top-left, top-right, bottom-right, bottom-left of a known rectangle.",
                },
                "width_mm": {"type": "number"},
                "height_mm": {"type": "number"},
                "out": {
                    "type": "string",
                    "description": "Absolute rectified .png path. Default: the working directory, never HERMES_HOME/cache. Refuses an existing file unless overwrite is set.",
                },
                "force": {"type": "boolean", "description": "Alias of overwrite."},
                "overwrite": {"type": "boolean", "description": "Replace an existing out file. Default is to refuse."},
                "angled": {"type": "boolean", "description": "True when the photo is not straight-on."},
                "auto": {"type": "boolean", "description": "Detect the coin and the part in image. Do not open the photo with cv2 or PIL."},
                "part_seed": {"type": "array", "description": "One [x, y] pixel on the part, not on the coin."},
                "part_roi": {"type": "array", "description": "Part box [x0, y0, x1, y1]. {x, y, w, h} is also accepted."},
            },
            [],
        ),
        "handler": measure_tool,
    }
    build = {
        "name": "photo_part_build",
        "description": _lead(
            "Run one local .py build script with the plugin interpreter. "
            "Pass help or describe true for feature signatures and a minimal example script. "
            "Do not run python build.py, cadquery, or photopart.build_run from the terminal. Use this tool. "
            "Do not open features.py or launcher.py. "
            "About 40 tool calls in total. "
            "Import photopart.features for a thread, knurl, revolve, sweep, hex screw, standoff, spur gear, or spiral scroll. "
            "Check photo_part_template first, including strap_hinge. "
            "Do not import build123d or cadquery, and do not install or patch around a missing CAD library. "
            "Overlapping shells are unioned. The error field is the exception, not a status line. "
            "No shell. Try photo_part_template first."
        ),
        "schema": _schema(
            "photo_part_build",
            _lead(
                "Run a Python file with the plugin environment interpreter and return the new files. "
                "Do not run that file from the terminal. Use photo_part_build. "
                "from photopart.features import external_thread, internal_thread, knurl, revolve_profile, sweep_path, hex_screw, hex_standoff, spur_gear, spiral_scroll, strap_hinge, tag_faces. "
                "Check photo_part_template first. Do not import build123d or cadquery. "
                "Each returns one watertight trimesh in millimetres. Overlapping shells are unioned; shells_before and shells_after are in the JSON. "
                "tag_faces(mesh, thread=indices, path=stl) excludes those faces from the wall check. "
                "On failure the error field starts with the exception. "
                "Pass cwd as an absolute project path. Do not write into HERMES_HOME/cache. "
                "Do not delete an STL or 3MF. The interpreter path is in the JSON."
            ),
            {
                "script": {
                    "type": "string",
                    "description": "Path to a .py file in the project. Omit when help or describe is true.",
                },
                "help": {
                    "type": "boolean",
                    "description": "Return feature signatures and a minimal example script. Does not run a script.",
                },
                "describe": {"type": "boolean", "description": "Same as help."},
                "mode": {
                    "type": "string",
                    "enum": ["help", "describe"],
                    "description": "help or describe returns signatures and an example script. script is not required.",
                },
                "cwd": {
                    "type": "string",
                    "description": "Absolute project directory. Default: the working directory, refused when that is HERMES_HOME/cache.",
                },
                "timeout": {"type": "number", "description": "Seconds. Default 60. Maximum 300."},
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Extra arguments after the script path. Not a shell string.",
                },
            },
            [],
        ),
        "handler": build_tool,
    }
    return [validate, render, heal, template, measure, build]


_TEMPLATE_KEYS = frozenset(
    {
        "out_dir",
        "shape",
        "params",
        "ascii",
        "no_3mf",
        "force",
        "stl",
        "overwrite",
        "help",
        "describe",
        "mode",
        "response_format",
        "calls_used",
    }
)


def _template_params(args: dict, shape: str) -> dict | None:
    """Shape values live in ``params``. Known top-level ones are moved there.

    An unknown name is an error. A value that disagrees with the same key
    inside ``params`` is an error. Nothing is dropped silently.
    """
    from photopart.catalog import SHAPES

    known = set()
    spec = SHAPES.get(shape)
    if spec is not None:
        known = set(spec["params"])
    overrides = args.get("params")
    if isinstance(overrides, str) and overrides.strip():
        loaded = json.loads(overrides)
        if not isinstance(loaded, dict):
            raise ValueError("params must be an object of millimetre values")
        overrides = loaded
    if overrides is None:
        overrides = {}
    elif not isinstance(overrides, dict):
        raise ValueError("params must be an object of millimetre values")
    else:
        overrides = dict(overrides)
    unknown = []
    for key, value in args.items():
        if key in _TEMPLATE_KEYS:
            continue
        if key in known:
            if key in overrides and overrides[key] != value:
                raise ValueError(
                    f"{key} was passed both at the top level ({value!r}) and inside params "
                    f"({overrides[key]!r}). Put shape values only in params."
                )
            overrides.setdefault(key, value)
            continue
        unknown.append(str(key))
    if unknown:
        listed = ", ".join(sorted(unknown))
        if known:
            names = ", ".join(sorted(known))
            raise ValueError(
                f"unknown argument {listed} for shape {shape!r}. "
                f"Shape values belong in params, not next to shape. "
                f"Known params for {shape}: {names}."
            )
        raise ValueError(
            f"unknown argument {listed}. Shape values belong in params, not next to shape."
        )
    return overrides or None


def _signature_parameters(func):
    try:
        return inspect.signature(func).parameters
    except (TypeError, ValueError):
        return None


def _register_tool_accepts(func, name: str, parameters) -> bool:
    """True when func lists `name` or accepts **kwargs."""
    if parameters is None:
        return name in _HERMES_V0217_REGISTER_PARAMS
    if name in parameters:
        kind = parameters[name].kind
        return kind in {
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        }
    return any(param.kind is inspect.Parameter.VAR_KEYWORD for param in parameters.values())


def _dropped_note(description: str, dropped: dict) -> str:
    """Keep a schema Hermes could not take as a register_tool keyword."""
    if not dropped:
        return description
    notes = []
    schema = dropped.get("output_schema")
    if isinstance(schema, dict):
        notes.append("output_schema=" + json.dumps(schema, sort_keys=True, separators=(",", ":")))
    others = {key: value for key, value in dropped.items() if key != "output_schema"}
    if others:
        notes.append("unsupported_register_kwargs=" + json.dumps(others, sort_keys=True, default=str))
    suffix = " ".join(notes)
    if not suffix or suffix in description:
        return description
    return f"{description} {suffix}"


def _payload_without(kwargs: dict, dropped_keys: set[str]) -> dict:
    """Copy the call, folding dropped keywords into the descriptions."""
    dropped = {key: kwargs[key] for key in dropped_keys if key in kwargs and key != "description"}
    payload = {key: value for key, value in kwargs.items() if key not in dropped_keys}
    if not dropped:
        return payload
    base = str(kwargs.get("description") or "")
    if "description" in payload:
        payload["description"] = _dropped_note(str(payload.get("description") or ""), dropped)
    schema = payload.get("schema")
    if isinstance(schema, dict):
        schema = dict(schema)
        schema["description"] = _dropped_note(str(schema.get("description") or base), dropped)
        payload["schema"] = schema
    return payload


def _call_register_tool(register, **kwargs) -> None:
    """Call register_tool, omitting keywords this Hermes build does not accept.

    Hermes v0.21.7 raises TypeError on output_schema. The signature check skips
    unknown keywords, including any optional keyword besides output_schema.
    A TypeError that names an unexpected keyword retries without it. Dropped
    schemas stay on the tool description. Detailed results still include
    output_schema.
    """
    parameters = _signature_parameters(register)
    dropped = {key for key in kwargs if not _register_tool_accepts(register, key, parameters)}
    last_error: TypeError | None = None
    for _attempt in range(1 + len(kwargs)):
        payload = _payload_without(kwargs, dropped)
        try:
            register(**payload)
            return
        except TypeError as exc:
            last_error = exc
            match = _UNEXPECTED_KEYWORD.search(str(exc))
            if match is None:
                raise
            name = match.group(1)
            if name not in kwargs or name in dropped:
                raise
            dropped.add(name)
    if last_error is not None:
        raise last_error
    names = ", ".join(sorted(dropped))
    raise TypeError(f"register_tool rejected optional keywords: {names}")


def register_tools(ctx) -> None:
    """Register the mesh tools. Names match plugin.yaml provides_tools."""
    register = ctx.register_tool
    for spec in tool_specs():
        _call_register_tool(
            register,
            name=spec["name"],
            toolset="photo-to-part",
            schema=spec["schema"],
            handler=spec["handler"],
            description=spec["description"],
            output_schema=spec.get("output_schema") or _output_schema(spec["name"]),
        )
