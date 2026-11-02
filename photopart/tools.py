"""In-process tools. Hermes runs these inside the plugin environment.

Handlers return one JSON document and do not write status to stdout.
Importing this module does not import trimesh; the handlers do, on first use.
"""

from __future__ import annotations

import json
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
    return json.dumps(payload, indent=2, sort_keys=True)


def _lead(text: str) -> str:
    """Tool text Hermes shows. The exact skill id stays in front if it is cut."""
    return f"{SKILL_ID}. {text}"


def _emit(payload: dict, fallback: str, *, plain_error: bool = False) -> str:
    if payload.get("error") and not plain_error and SKILL_ID not in str(payload["error"]):
        payload["error"] = f"{payload['error']} Skill id: {SKILL_ID}."
    if not payload.get("next_step"):
        attach_flow(payload, fallback)
    elif "skill_id" not in payload:
        payload["skill_id"] = SKILL_ID
    return _dump(payload)


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
    try:
        args = _params(params)
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
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return _emit({"ok": False, "error": str(exc)}, "Fix the arguments, then photo_part_validate the mesh.")
    return _emit(report, "Next: photo_part_render the same file, then deliver it.")


def render_tool(params, **_kwargs) -> str:
    """Render fitted views and, with photo_scale, an outline overlay on the photo."""
    try:
        args = _params(params)
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
        elif isinstance(measure_json, dict):
            from photopart.measure import load_measure_hints

            rects, flagged = load_measure_hints(measure_json)
            for rect in rects:
                argv.extend(["--exclude-roi", _csv_rect(rect)])
            if flagged:
                argv.append("--angled")
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

        _code, report = run_render(argv)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return _emit({"ok": False, "error": str(exc)}, "Fix the render arguments, then photo_part_render the validated file.")
    return _emit(report, "Read stale_validation. Deliver the file only when it is false and validation_ok is true.")


def heal_tool(params, **_kwargs) -> str:
    """Heal a scan into a new STL. Report fan fallback and shell counts separately."""
    try:
        args = _params(params)
        argv = [str(args["mesh"]), "--out", str(args["out"])]
        if _flag(args, "fan"):
            argv.append("--fan")
        if _flag(args, "keep_all"):
            argv.append("--keep-all")
        if _flag(args, "union"):
            argv.append("--union")
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
        return _emit({"ok": False, "error": str(exc)}, "Fix the heal arguments. Write a new name_vN.stl. Do not overwrite a validated mesh.")
    return _emit(report, "Next: photo_part_validate the healed STL, then render it.")


def template_tool(params, **_kwargs) -> str:
    """Write a building block. The default shape is still the sample plate."""
    try:
        args = _params(params)
        from photopart.parts import output_names, write_shape

        overrides = args.get("params") or None
        if overrides is not None and not isinstance(overrides, dict):
            raise ValueError("params must be an object of millimetre values")
        shape = str(args.get("shape") or "plate_clip")
        from photopart.paths import absolute_path

        raw_out = args.get("out_dir")
        out_dir = absolute_path(raw_out if raw_out else ".")
        write_3mf = not bool(args.get("no_3mf", False))
        if not (_flag(args, "force") or _flag(args, "overwrite")):
            existing = [name for name in output_names(shape, write_3mf=write_3mf) if (out_dir / name).exists()]
            if existing:
                joined = ", ".join(existing)
                raise ValueError(f"refusing to overwrite {joined}. Pass --overwrite.")
        written = write_shape(
            out_dir,
            shape,
            overrides,
            ascii_stl=bool(args.get("ascii", False)),
            write_3mf=write_3mf,
        )
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        return _emit(
            {"ok": False, "error": str(exc)},
            "Try a photo_part_template shape before a custom script. Pass an absolute project out_dir.",
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
    from photopart.spec import note_missing_spec

    attach_flow(summary, step_model(stl or "name_v1.stl"))
    note_missing_spec(summary, Path.cwd(), out_dir)
    return _emit(summary, step_model(stl or "name_v1.stl"))


def measure_tool(params, **_kwargs) -> str:
    """Pixel scale from a coin or a ruler, plus an optional rectified image."""
    try:
        args = _params(params)
        from photopart.measure import measure

        report = measure(args)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return _emit({"ok": False, "error": str(exc)}, "Fix the measure arguments. Pass an absolute project path for out.")
    return _emit(report, "Next: photo_part_template or photo_part_build, then validate name_v1.stl.")


def build_tool(params, **_kwargs) -> str:
    """Run a local Python build script with the plugin interpreter."""
    try:
        args = _params(params)
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
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return _emit(
            {"ok": False, "error": str(exc)},
            "Try photo_part_template shapes such as l_bracket before a custom script.",
        )
    return _emit(
        report,
        "Next: photo_part_validate the STL the script wrote, with spec.json. Do not overwrite it.",
        plain_error=bool(report.get("error")),
    )


def _schema(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
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
                "A deviation fails the check."
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
                "overlay_fit auto aligns that contour. Pass roi or seed, and measure_json, so a coin is not the blob. "
                "Writes overlay_iou plus overlay_diff.png. Warns when IoU is below 0.5 or the photo is angled. "
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
                    "description": "center (default) or auto. auto searches rotation and mirror, then front, side, and top. Returns overlay_rotation_deg, overlay_mirror, overlay_view, and overlay_iou.",
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
                    "description": "photo_part_measure JSON object or a path to it. Uses reference_bbox and angled.",
                },
                "angled": {
                    "type": "boolean",
                    "description": "The photo is not straight-on. The JSON warns.",
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
            "out_dir defaults to the working directory and must not be HERMES_HOME/cache. "
            "Returns the absolute STL path and the plugin interpreter."
        ),
        "schema": _schema(
            "photo_part_template",
            _lead(
                "Write a watertight building block. shape defaults to plate_clip, the sample plate. "
                "Other shapes: plate, countersink, revolve, ribs, l_bracket, hinge, "
                "thread, knurl, sweep, hex_screw, hex_standoff, bottle_cap. "
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
                    "description": "plate_clip, plate, countersink, revolve, ribs, l_bracket, hinge, thread, knurl, sweep, hex_screw, hex_standoff, or bottle_cap.",
                },
                "params": {"type": "object", "description": "Millimetre overrides. plate holes is a list of {x, y, diameter}."},
                "ascii": {"type": "boolean", "description": "Write an ASCII STL."},
                "no_3mf": {"type": "boolean", "description": "Skip 3MF. 3MF needs lxml."},
                "force": {"type": "boolean", "description": "Alias of overwrite."},
                "overwrite": {"type": "boolean", "description": "Replace files already in out_dir. Default is to refuse."},
            },
            [],
        ),
        "handler": template_tool,
    }
    measure = {
        "name": "photo_part_measure",
        "description": _lead(
            "Pixel-to-millimetre scale from a coin or a ruler. Returns reference_bbox so render can exclude that object, and absolute paths."
        ),
        "schema": _schema(
            "photo_part_measure",
            _lead(
                "Measure px_per_mm from a coin (coin id or diameter_mm, plus diameter_px or two points) "
                "or a ruler (ruler_mm plus two points). "
                "Optional quad of four pixels TL, TR, BR, BL plus width_mm, height_mm, and image "
                "writes a rectified PNG in the working directory, never HERMES_HOME/cache. "
                "Returns reference_bbox and absolute paths. Same-plane, straight-on, unless a quad was given. "
                "Do not write a perspective script. Returns JSON."
            ),
            {
                "coin": {"type": "string", "description": "euro_1, euro_2, euro_50c, us_quarter, us_penny, us_nickel, us_dime, us_half, gbp_1, cad_quarter."},
                "diameter_mm": {"type": "number", "description": "Reference diameter when it is not a known coin."},
                "diameter_px": {"type": "number", "description": "That diameter in source-image pixels."},
                "points": {
                    "type": "array",
                    "description": "Two [x, y] pixels spanning the coin diameter or the ruler length.",
                },
                "ruler_mm": {"type": "number", "description": "Real millimetres between points."},
                "measurements": {
                    "type": "array",
                    "description": "Spans to convert: {name, points} or {name, length_px}.",
                    "items": {"type": "object"},
                },
                "image": {"type": "string", "description": "Photo to rectify when quad is set."},
                "quad": {
                    "type": "array",
                    "description": "Four [x, y] pixels: top-left, top-right, bottom-right, bottom-left of a known rectangle.",
                },
                "width_mm": {"type": "number"},
                "height_mm": {"type": "number"},
                "out": {
                    "type": "string",
                    "description": "Absolute rectified PNG path. Default: the working directory, never HERMES_HOME/cache.",
                },
                "angled": {"type": "boolean", "description": "True when the photo is not straight-on."},
            },
            [],
        ),
        "handler": measure_tool,
    }
    build = {
        "name": "photo_part_build",
        "description": _lead(
            "Run one local .py build script with the plugin interpreter. "
            "Import photopart.features for a thread, knurl, revolve, sweep, hex screw, or standoff. "
            "Overlapping shells are unioned. The error field is the exception, not a status line. "
            "No shell. Try photo_part_template first."
        ),
        "schema": _schema(
            "photo_part_build",
            _lead(
                "Run a Python file with the plugin environment interpreter and return the new files. "
                "from photopart.features import external_thread, internal_thread, knurl, revolve_profile, sweep_path, hex_screw, hex_standoff. "
                "Each returns one watertight trimesh in millimetres. Overlapping shells are unioned; shells_before and shells_after are in the JSON. "
                "On failure the error field starts with the exception. "
                "Pass cwd as an absolute project path. Do not write into HERMES_HOME/cache. "
                "Do not delete an STL or 3MF. The interpreter path is in the JSON."
            ),
            {
                "script": {"type": "string", "description": "Path to a .py file in the project."},
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
            ["script"],
        ),
        "handler": build_tool,
    }
    return [validate, render, heal, template, measure, build]


def register_tools(ctx) -> None:
    """Register the mesh tools. Names match plugin.yaml provides_tools."""
    for spec in tool_specs():
        ctx.register_tool(
            name=spec["name"],
            toolset="photo-to-part",
            schema=spec["schema"],
            handler=spec["handler"],
            description=spec["description"],
        )
