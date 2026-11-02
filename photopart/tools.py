"""In-process tools. Hermes runs these inside the plugin environment.

Handlers return one JSON document and do not write status to stdout.
Importing this module does not import trimesh; the handlers do, on first use.
"""

from __future__ import annotations

import json
from pathlib import Path

TOOL_NAMES = (
    "photo_part_validate",
    "photo_part_render",
    "photo_part_heal",
    "photo_part_template",
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
            units=_optional_str(args, "units"),
            scale=_optional_float(args, "scale"),
            json_out=_optional_str(args, "json_out"),
            max_bytes=int(args.get("max_bytes", 256 * 1024 * 1024)),
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return _dump({"ok": False, "error": str(exc)})
    return _dump(report)


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
        if _flag(args, "force"):
            argv.append("--force")
        if "max_bytes" in args and args["max_bytes"] is not None:
            argv.extend(["--max-bytes", str(int(args["max_bytes"]))])
        from photopart.render import run_render

        _code, report = run_render(argv)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return _dump({"ok": False, "error": str(exc)})
    return _dump(report)


def heal_tool(params, **_kwargs) -> str:
    """Heal a scan into a new STL. Report fan fallback and shell counts separately."""
    try:
        args = _params(params)
        argv = [str(args["mesh"]), "--out", str(args["out"])]
        if _flag(args, "fan"):
            argv.append("--fan")
        if _flag(args, "keep_all"):
            argv.append("--keep-all")
        if _flag(args, "ascii"):
            argv.append("--ascii")
        if _flag(args, "force"):
            argv.append("--force")
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
        return _dump({"ok": False, "error": str(exc)})
    return _dump(report)


def template_tool(params, **_kwargs) -> str:
    """Write the sample plate into out_dir. It is a starting style, not a final part."""
    try:
        args = _params(params)
        from photopart.geometry import write_template

        overrides = args.get("params") or None
        if overrides is not None and not isinstance(overrides, dict):
            raise ValueError("params must be an object of millimetre values")
        out_dir = Path(str(args["out_dir"])).expanduser().resolve()
        if not _flag(args, "force"):
            names = ["plate_clip.stl", "plate_clip.scad", "params.json"]
            if not _flag(args, "no_3mf"):
                names.append("plate_clip.3mf")
            existing = [name for name in names if (out_dir / name).exists()]
            if existing:
                joined = ", ".join(existing)
                raise ValueError(f"refusing to overwrite {joined}. Pass force.")
        written = write_template(
            out_dir,
            overrides,
            ascii_stl=bool(args.get("ascii", False)),
            write_3mf=not bool(args.get("no_3mf", False)),
        )
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        return _dump({"ok": False, "error": str(exc)})
    summary = {
        "ok": bool(written["mesh"].is_watertight),
        "stl": str(written["stl"]),
        "scad": str(written["scad"]),
        "threemf": None if written["threemf"] is None else str(written["threemf"]),
        "threemf_error": written["threemf_error"],
        "expected_extents_mm": {
            "x": written["expected_extents_mm"][0],
            "y": written["expected_extents_mm"][1],
            "z": written["expected_extents_mm"][2],
        },
        "triangles": int(len(written["mesh"].faces)),
        "watertight": bool(written["mesh"].is_watertight),
    }
    return _dump(summary)


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
        "description": "Check a mesh for a watertight single shell and an expected size in millimetres.",
        "schema": _schema(
            "photo_part_validate",
            "Check watertightness, one shell, and the bounding box. "
            "size is X Y Z millimetres after units/scale. "
            "Does not upload the file. Returns JSON. Do not write a replacement checker.",
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
                "allow_multi_shell": {"type": "boolean"},
                "units": {"type": "string", "description": _UNIT_HELP},
                "scale": {"type": "number", "description": "Extra multiplier after units."},
                "json_out": {"type": "string", "description": "Also write the report to this path."},
                "max_bytes": {"type": "integer"},
            },
            ["mesh"],
        ),
        "handler": validate_tool,
    }
    render = {
        "name": "photo_part_render",
        "description": "Render fitted views and an optional outline overlay at a known pixels-per-millimetre scale.",
        "schema": _schema(
            "photo_part_render",
            "Write front, side, top, iso, and contact PNGs fitted to the part. "
            "up defaults to the longest axis. "
            "Pass photo and photo_scale (pixels per millimetre) to draw overlay.png on the photo. "
            "Also writes compare_front.png when photo is set. Do not write an overlay script.",
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
                    "description": "Optional image pixel [x, y] of the model minimum corner. Image y grows downward. Default centers the model.",
                },
                "grid_mm": {"type": "number", "description": "Square grid spacing in millimetres. Not drawn on the iso view."},
                "up": {"type": "string", "description": "x, y, or z. Default is the longest side."},
                "front_axis": {"type": "string", "description": "Axis the front camera looks along."},
                "units": {"type": "string", "description": _UNIT_HELP},
                "scale": {"type": "number"},
                "force": {"type": "boolean"},
                "max_bytes": {"type": "integer"},
            },
            ["mesh", "out_dir"],
        ),
        "handler": render_tool,
    }
    heal = {
        "name": "photo_part_heal",
        "description": "Weld a scan, fill holes, and write a new STL. Fan caps are flat.",
        "schema": _schema(
            "photo_part_heal",
            "Copy a scan to out. Welds vertices, drops degenerate faces, fills holes. "
            "fan_fallback means a second pass used flat fans because fan was not set. "
            "shells_dropped counts input shells only; repair_fragments_removed is separate. "
            "Pass units when the file is not millimetres. Does not guess a scale.",
            {
                "mesh": {"type": "string", "description": "Input scan. Not overwritten."},
                "out": {"type": "string", "description": "Output STL path, different from mesh."},
                "fan": {"type": "boolean", "description": "Fan-fill on the first pass. Caps are flat."},
                "keep_all": {"type": "boolean", "description": "Keep every shell. Default keeps the largest."},
                "units": {"type": "string", "description": _UNIT_HELP},
                "scale": {"type": "number"},
                "ascii": {"type": "boolean"},
                "force": {"type": "boolean"},
                "max_bytes": {"type": "integer"},
            },
            ["mesh", "out"],
        ),
        "handler": heal_tool,
    }
    template = {
        "name": "photo_part_template",
        "description": "Write the generic sample plate as STL, OpenSCAD, and parameters.",
        "schema": _schema(
            "photo_part_template",
            "Write a watertight sample plate with a hook and a slot. "
            "A starting style for a flat clip, not a copy of any commercial part. "
            "Replace the profile with the user's part.",
            {
                "out_dir": {"type": "string", "description": "Directory to create or reuse."},
                "params": {"type": "object", "description": "Millimetre overrides such as width_mm."},
                "ascii": {"type": "boolean", "description": "Write an ASCII STL."},
                "no_3mf": {"type": "boolean", "description": "Skip 3MF. 3MF needs lxml."},
                "force": {"type": "boolean", "description": "Overwrite files already in out_dir."},
            },
            ["out_dir"],
        ),
        "handler": template_tool,
    }
    return [validate, render, heal, template]


def register_tools(ctx) -> None:
    """Register the four checkers. Names match plugin.yaml provides_tools."""
    for spec in tool_specs():
        ctx.register_tool(
            name=spec["name"],
            toolset="photo-to-part",
            schema=spec["schema"],
            handler=spec["handler"],
            description=spec["description"],
        )
