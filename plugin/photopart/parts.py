"""Parametric building blocks.

plate_clip stays the Shapely sample. The other shapes are manifold3d solids:
a plate with holes, a countersink, a revolved profile, radial ribs, an
L-bracket, a print-in-place hinge (two shells that do not touch), and the
feature helpers (thread, knurl, sweep, hex screw, hex standoff, bottle cap,
spur gear, spiral scroll, strap hinge). Those helpers each return one
watertight body. The strap hinge is one shell; the print-in-place hinge
is still two.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import trimesh

SHAPES = (
    "plate_clip",
    "plate",
    "countersink",
    "revolve",
    "ribs",
    "l_bracket",
    "hinge",
    "thread",
    "knurl",
    "sweep",
    "hex_screw",
    "hex_standoff",
    "bottle_cap",
    "spur_gear",
    "scroll",
    "strap_hinge",
)


def build_shape(shape: str, params: dict | None = None) -> tuple[trimesh.Trimesh, dict]:
    """Return a mesh in millimetres and a parameter document."""
    name = (shape or "plate_clip").strip()
    if name not in SHAPES:
        known = ", ".join(SHAPES)
        raise ValueError(f"unknown shape {shape!r}. Known shapes: {known}")
    raw = dict(params or {})
    if name == "plate_clip":
        from photopart.geometry import build_mesh, expected_extents, parse_params

        resolved = parse_params(raw)
        mesh = build_mesh(resolved)
        extents = expected_extents(resolved)
        return mesh, {
            "shape": name,
            "units": "millimeters",
            "parameters": resolved,
            "expected_extents_mm": {"x": extents[0], "y": extents[1], "z": extents[2]},
            "shells": 1,
        }
    builders = {
        "plate": _plate,
        "countersink": _countersink,
        "revolve": _revolve,
        "ribs": _ribs,
        "l_bracket": _l_bracket,
        "hinge": _hinge,
        "thread": _thread,
        "knurl": _knurl,
        "sweep": _sweep,
        "hex_screw": _hex_screw,
        "hex_standoff": _hex_standoff,
        "bottle_cap": _bottle_cap,
        "spur_gear": _spur_gear,
        "scroll": _scroll,
        "strap_hinge": _strap_hinge,
    }
    mesh, resolved, shells = builders[name](raw)
    mesh.metadata["units"] = "millimeters"
    mesh.metadata["photo_to_part_shape"] = name
    extents = [float(v) for v in np.asarray(mesh.extents, dtype=float)]
    return mesh, {
        "shape": name,
        "units": "millimeters",
        "parameters": resolved,
        "expected_extents_mm": {"x": extents[0], "y": extents[1], "z": extents[2]},
        "shells": shells,
    }


def write_shape(
    out_dir: Path,
    shape: str = "plate_clip",
    params: dict | None = None,
    *,
    ascii_stl: bool = False,
    write_3mf: bool = True,
    stl_name: str | None = None,
) -> dict:
    """Write one building block. plate_clip keeps its existing filenames."""
    name = (shape or "plate_clip").strip()
    if name == "plate_clip" and not stl_name:
        from photopart.geometry import write_template

        written = write_template(out_dir, params, ascii_stl=ascii_stl, write_3mf=write_3mf)
        written["shape"] = "plate_clip"
        written["shells"] = 1
        if written.get("stl"):
            from photopart.freeze import snap_path_to_spec

            snap_path_to_spec(written["stl"], Path(out_dir) / "spec.json")
        _record_template_spec(written)
        return written
    mesh, doc = build_shape(name, params)
    mesh, snapped = _snap_to_spec(mesh, out_dir)
    if snapped:
        doc = dict(doc)
        extents = [float(v) for v in mesh.extents[:3]]
        doc["expected_extents_mm"] = {"x": extents[0], "y": extents[1], "z": extents[2]}
    out_dir.mkdir(parents=True, exist_ok=True)
    from photopart.geometry import export_3mf, export_stl

    stem = Path(stl_name).stem if stl_name else f"{name}_v1"
    stl_path = out_dir / f"{stem}.stl"
    export_stl(mesh, stl_path, ascii_stl=ascii_stl)
    (out_dir / "params.json").write_text(
        json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    threemf = out_dir / f"{stem}.3mf"
    threemf_error = None
    if write_3mf:
        try:
            export_3mf(mesh, threemf)
        except RuntimeError as exc:
            threemf_error = str(exc)
            if threemf.exists():
                threemf.unlink()
    result = {
        "mesh": mesh,
        "shape": name,
        "shells": doc["shells"],
        "params": doc["parameters"],
        "stl": stl_path,
        "scad": None,
        "threemf": None if threemf_error or not write_3mf else threemf,
        "threemf_error": threemf_error,
        "expected_extents_mm": (
            doc["expected_extents_mm"]["x"],
            doc["expected_extents_mm"]["y"],
            doc["expected_extents_mm"]["z"],
        ),
    }
    _record_template_spec(result)
    return result


def _snap_to_spec(mesh, out_dir: Path):
    """Keep frozen user axes exact before the template is written."""
    spec_path = Path(out_dir) / "spec.json"
    if not spec_path.is_file():
        return mesh, False
    try:
        import json

        raw = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return mesh, False
    if not isinstance(raw, dict):
        return mesh, False
    from photopart.freeze import locked_axes_from_spec, snap_mesh_to_locked_axes

    locked = locked_axes_from_spec(spec_path, raw)
    return snap_mesh_to_locked_axes(mesh, locked)


def default_stl_name(shape: str, out_dir: Path, requested: str | None = None) -> str | None:
    """Filename for a template. plate_clip stays put. Never the placeholder name_v1.stl."""
    if requested:
        name = Path(str(requested)).name
        if not name.lower().endswith(".stl"):
            name = name + ".stl"
        if name == "name_v1.stl":
            raise ValueError("refusing the placeholder name_v1.stl. Name the file after the part, such as spur_gear_v1.stl.")
        return name
    if (shape or "plate_clip") == "plate_clip":
        return None
    slug = _spec_part_slug(out_dir)
    base = slug or (shape or "part")
    return f"{base}_v1.stl"


def _spec_part_slug(out_dir: Path) -> str | None:
    import re

    for directory in (Path(out_dir), Path.cwd()):
        spec_path = directory / "spec.json"
        if not spec_path.is_file():
            continue
        try:
            loaded = json.loads(spec_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            continue
        if not isinstance(loaded, dict) or not loaded.get("part"):
            continue
        slug = re.sub(r"[^a-z0-9]+", "_", str(loaded["part"]).strip().lower()).strip("_")
        if slug and slug != "name":
            return slug
    return None


def output_names(shape: str, *, write_3mf: bool, stl_name: str | None = None) -> list[str]:
    name = shape or "plate_clip"
    if name == "plate_clip" and not stl_name:
        names = ["plate_clip.stl", "plate_clip.scad", "params.json"]
        if write_3mf:
            names.append("plate_clip.3mf")
        return names
    stem = Path(stl_name).stem if stl_name else f"{name}_v1"
    names = [f"{stem}.stl", "params.json"]
    if write_3mf:
        names.append(f"{stem}.3mf")
    return names


def _number(params: dict, key: str, default: float) -> float:
    if key not in params or params[key] is None or params[key] == "":
        return float(default)
    try:
        value = float(params[key])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a number") from exc
    if not np.isfinite(value):
        raise ValueError(f"{key} must be finite")
    return value


def _require_positive(name: str, value: float) -> float:
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value}")
    return value


def _plate(params: dict):
    width = _require_positive("width_mm", _number(params, "width_mm", 40.0))
    height = _require_positive("height_mm", _number(params, "height_mm", 30.0))
    thickness = _require_positive("thickness_mm", _number(params, "thickness_mm", 4.0))
    holes = _hole_list(params.get("holes"), width, height, width / 2.0, height / 2.0, 6.0)
    _holes_fit(holes, width, height, "plate")
    plate = _cube(width, height, thickness)
    cutters = [_cylinder_z(hole["diameter"] / 2.0, thickness + 0.4, hole["x"], hole["y"], -0.2) for hole in holes]
    mesh = _as_mesh(_difference(plate, cutters))
    resolved = {"width_mm": width, "height_mm": height, "thickness_mm": thickness, "holes": holes}
    return mesh, resolved, 1


def _countersink(params: dict):
    width = _require_positive("width_mm", _number(params, "width_mm", 40.0))
    height = _require_positive("height_mm", _number(params, "height_mm", 30.0))
    thickness = _require_positive("thickness_mm", _number(params, "thickness_mm", 4.0))
    hole_d = _require_positive("hole_diameter_mm", _number(params, "hole_diameter_mm", 4.0))
    cs_d = _require_positive("countersink_diameter_mm", _number(params, "countersink_diameter_mm", 8.0))
    cs_depth = _require_positive("countersink_depth_mm", _number(params, "countersink_depth_mm", 1.5))
    cx = _number(params, "hole_x_mm", width / 2.0)
    cy = _number(params, "hole_y_mm", height / 2.0)
    if cs_depth >= thickness:
        raise ValueError(
            f"countersink_depth_mm {cs_depth:g} is not less than thickness_mm {thickness:g}. "
            "A countersink deeper than the sheet is impossible."
        )
    if cs_d <= hole_d:
        raise ValueError("countersink_diameter_mm must be larger than hole_diameter_mm")
    if hole_d >= min(width, height) or cs_d >= min(width, height):
        raise ValueError("the countersink does not fit inside the plate")
    margin = cs_d / 2.0 + 1.0
    if not (margin <= cx <= width - margin and margin <= cy <= height - margin):
        raise ValueError("the countersink is not inside the plate")
    plate = _cube(width, height, thickness)
    hole = _cylinder_z(hole_d / 2.0, thickness + 0.4, cx, cy, -0.2)
    cone = _cylinder_z(hole_d / 2.0, cs_depth + 0.2, cx, cy, thickness - cs_depth, radius_high=cs_d / 2.0)
    mesh = _as_mesh(_difference(plate, [hole, cone]))
    resolved = {
        "width_mm": width,
        "height_mm": height,
        "thickness_mm": thickness,
        "hole_diameter_mm": hole_d,
        "countersink_diameter_mm": cs_d,
        "countersink_depth_mm": cs_depth,
        "hole_x_mm": cx,
        "hole_y_mm": cy,
    }
    return mesh, resolved, 1


def _revolve(params: dict):
    height = _require_positive("height_mm", _number(params, "height_mm", 18.0))
    radius = _require_positive("radius_mm", _number(params, "radius_mm", 12.0))
    # Closed profile in the +X half-plane. X is the radius, Y is the height.
    profile = [
        [radius * 0.22, 0.0],
        [radius * 0.84, 0.0],
        [radius, height * 0.16],
        [radius * 0.70, height * 0.62],
        [radius * 0.42, height * 0.78],
        [radius * 0.42, height],
        [radius * 0.22, height],
    ]
    mesh = _as_mesh(_revolve_profile(profile, segments=64))
    return mesh, {"height_mm": height, "radius_mm": radius}, 1


def _ribs(params: dict):
    radius = _require_positive("radius_mm", _number(params, "radius_mm", 8.0))
    height = _require_positive("height_mm", _number(params, "height_mm", 12.0))
    count = int(_number(params, "rib_count", 6))
    if count < 3 or count > 24:
        raise ValueError("rib_count must be from 3 to 24")
    thickness = _require_positive("rib_thickness_mm", _number(params, "rib_thickness_mm", 1.6))
    length = _require_positive("rib_length_mm", _number(params, "rib_length_mm", radius * 1.6))
    if thickness >= radius:
        raise ValueError("rib_thickness_mm must be narrower than the hub radius")
    hub = _cylinder_z(radius, height, 0.0, 0.0, 0.0, segments=64)
    ribs = []
    for index in range(count):
        angle = 360.0 * index / count
        rib = _cube(length, thickness, height * 0.72).translate([radius * 0.55, -thickness / 2.0, height * 0.14])
        ribs.append(rib.rotate([0.0, 0.0, angle]))
    mesh = _as_mesh(_union_many([hub, *ribs]))
    resolved = {
        "radius_mm": radius,
        "height_mm": height,
        "rib_count": count,
        "rib_thickness_mm": thickness,
        "rib_length_mm": length,
    }
    return mesh, resolved, 1


def _l_bracket(params: dict):
    length = _require_positive("length_mm", _number(params, "length_mm", 50.0))
    width = _require_positive("width_mm", _number(params, "width_mm", 24.0))
    height = _require_positive("height_mm", _number(params, "height_mm", 40.0))
    thickness = _require_positive("thickness_mm", _number(params, "thickness_mm", 3.0))
    hole_d = _require_positive("hole_diameter_mm", _number(params, "hole_diameter_mm", 5.0))
    if thickness >= height - 2 or thickness >= length - 2:
        raise ValueError("thickness_mm leaves no flange")
    if hole_d >= width - 2:
        raise ValueError("hole_diameter_mm is wider than the bracket")
    horiz = _cube(length, width, thickness)
    vert = _cube(thickness, width, height)
    hole_h = _cylinder_z(hole_d / 2.0, thickness + 0.4, length * 0.62, width / 2.0, -0.2)
    hole_v = _cylinder_x(hole_d / 2.0, thickness + 0.4, -0.2, width / 2.0, height * 0.62)
    mesh = _as_mesh(_difference(_union_many([horiz, vert]), [hole_h, hole_v]))
    resolved = {
        "length_mm": length,
        "width_mm": width,
        "height_mm": height,
        "thickness_mm": thickness,
        "hole_diameter_mm": hole_d,
    }
    return mesh, resolved, 1


def _hinge(params: dict):
    """Two watertight leaves. The pin sits inside the other leaf's bore with clearance."""
    length = _require_positive("length_mm", _number(params, "length_mm", 34.0))
    leaf = _require_positive("leaf_mm", _number(params, "leaf_mm", 14.0))
    pin_r = _require_positive("pin_radius_mm", _number(params, "pin_radius_mm", 2.0))
    clearance = _require_positive("clearance_mm", _number(params, "clearance_mm", 0.45))
    if clearance >= pin_r:
        raise ValueError("clearance_mm must be smaller than pin_radius_mm")
    raw_count = _number(params, "knuckles", 4)
    count = int(round(raw_count))
    if abs(raw_count - count) > 1e-6 or count < 2 or count > 11:
        raise ValueError("knuckles must be an integer from 2 to 11")
    tube_in = pin_r + clearance
    tube_out = tube_in + 1.15
    gap = max(0.4, clearance)
    # Alternating knuckles along X, with an axial gap so the leaves never touch.
    # Even indexes are solid pins on leaf A. Odd indexes are bored tubes on leaf B.
    span = length
    seg = (span - (count - 1) * gap) / float(count)
    if seg <= 2:
        raise ValueError(f"length_mm is too short for {count} hinge knuckles")
    starts = [0.0]
    for _ in range(count - 1):
        starts.append(starts[-1] + seg + gap)
    a_segs = []
    b_segs = []
    for index, start in enumerate(starts):
        pair = (start, start + seg)
        if index % 2 == 0:
            a_segs.append(pair)
        else:
            b_segs.append(pair)
    plate_gap = 0.35
    parts_a = [_cube(span, leaf, 3.0).translate([0.0, -(leaf + tube_out + plate_gap), -1.5])]
    parts_b = [_cube(span, leaf, 3.0).translate([0.0, tube_out + plate_gap, -1.5])]
    bridge_z = pin_r * 1.2
    for start, end in a_segs:
        parts_a.append(_cylinder_x(pin_r, end - start, start, 0.0, 0.0))
        # From inside the plate (negative Y) into the pin. Stays on this knuckle's X span.
        y0 = -(tube_out + plate_gap + 0.6)
        y1 = -0.15
        parts_a.append(_cube(end - start, y1 - y0, bridge_z).translate([start, y0, -bridge_z / 2.0]))
    for start, end in b_segs:
        parts_b.append(_tube_x(tube_out, tube_in, end - start, start, 0.0, 0.0))
        y0 = 0.15
        y1 = tube_out + plate_gap + 0.6
        parts_b.append(_cube(end - start, y1 - y0, bridge_z).translate([start, y0, -bridge_z / 2.0]))
    leaf_a = _union_many(parts_a)
    leaf_b = _union_many(parts_b)
    # batch Add of bodies that do not touch keeps two shells. A fuse would be a single solid.
    import manifold3d

    combined = manifold3d.Manifold.batch_boolean([leaf_a, leaf_b], manifold3d.OpType.Add)
    mesh = _as_mesh(combined)
    shells = int(len(mesh.split(only_watertight=False)))
    if shells != 2:
        raise ValueError(f"print-in-place hinge produced {shells} shells, expected 2")
    resolved = {
        "length_mm": length,
        "leaf_mm": leaf,
        "pin_radius_mm": pin_r,
        "clearance_mm": clearance,
        "knuckles": count,
    }
    return mesh, resolved, 2


def _record_template_spec(written: dict) -> None:
    """Write the checks this template expects validate to keep."""
    mesh = written["mesh"]
    extents = np.asarray(mesh.extents, dtype=float)
    checks = {
        "x": round(float(extents[0]), 3),
        "y": round(float(extents[1]), 3),
        "z": round(float(extents[2]), 3),
        "shells": int(written.get("shells") or 1),
        "tolerance": 0.5,
    }
    if written.get("shape") == "hinge":
        params = written.get("params") or {}
        checks["knuckles"] = int(params.get("knuckles", 4))
        checks["knuckle_axis"] = "x"
    written["spec_checks"] = checks
    stl = written.get("stl")
    if not stl:
        return
    stl_path = Path(stl)
    sidecar = Path(str(stl_path) + ".template.json")
    payload = {
        "file": str(stl_path.resolve()),
        "shape": written.get("shape"),
        "spec_checks": checks,
    }
    if written.get("shape") == "spur_gear":
        params = written.get("params") or {}
        outer = params.get("outer_diameter_mm")
        if not isinstance(outer, (int, float)) or float(outer) <= 0:
            module = params.get("module")
            teeth = params.get("teeth")
            if isinstance(module, (int, float)) and isinstance(teeth, (int, float)):
                outer = float(module) * (int(teeth) + 2)
        if isinstance(outer, (int, float)) and float(outer) > 0:
            payload["outer_diameter_mm"] = float(outer)
    sidecar.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    params_path = stl_path.parent / "params.json"
    if not params_path.is_file():
        return
    try:
        doc = json.loads(params_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    if isinstance(doc, dict):
        doc["spec_checks"] = checks
        params_path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _thread(params: dict):
    from photopart.features import external_thread, internal_thread

    length = _require_positive("length_mm", _number(params, "length_mm", 6.0))
    designation = str(params.get("designation") or "M3")
    diameter = params.get("diameter_mm")
    pitch = params.get("pitch_mm")
    kwargs = {
        "designation": designation,
        "diameter": None if diameter in (None, "") else _number(params, "diameter_mm", 3.0),
        "pitch": None if pitch in (None, "") else _number(params, "pitch_mm", 0.5),
        "length": length,
    }
    internal = bool(params.get("internal"))
    if internal:
        wall = _require_positive("wall_mm", _number(params, "wall_mm", 2.0))
        mesh = internal_thread(**kwargs, wall=wall)
    else:
        wall = None
        mesh = external_thread(**kwargs)
    resolved = {"designation": designation, "length_mm": length, "internal": internal}
    if wall is not None:
        resolved["wall_mm"] = wall
    return mesh, resolved, 1


def _knurl(params: dict):
    from photopart.features import knurl

    style = str(params.get("style") or "straight")
    diameter = _require_positive("diameter_mm", _number(params, "diameter_mm", 8.0))
    length = _require_positive("length_mm", _number(params, "length_mm", 6.0))
    count = int(_number(params, "count", 12))
    mesh = knurl(style, diameter=diameter, length=length, count=count)
    return mesh, {"style": style, "diameter_mm": diameter, "length_mm": length, "count": count}, 1


def _sweep(params: dict):
    from photopart.features import hook_path, sweep_path

    radius = _require_positive("radius_mm", _number(params, "radius_mm", 1.0))
    segments = int(_number(params, "segments", 8))
    path = params.get("path") or hook_path()
    mesh = sweep_path(path, radius=radius, segments=segments)
    return mesh, {"radius_mm": radius, "segments": segments}, 1


def _hex_screw(params: dict):
    from photopart.features import hex_screw

    designation = str(params.get("designation") or "M3")
    length = _require_positive("length_mm", _number(params, "length_mm", 8.0))
    mesh = hex_screw(designation=designation, length=length)
    return mesh, {"designation": designation, "length_mm": length}, 1


def _hex_standoff(params: dict):
    from photopart.features import hex_standoff

    designation = str(params.get("designation") or "M3")
    body = _require_positive("body_length_mm", _number(params, "body_length_mm", 6.0))
    thread = _require_positive("thread_length_mm", _number(params, "thread_length_mm", 3.0))
    mesh = hex_standoff(designation=designation, body_length=body, thread_length=thread)
    return mesh, {"designation": designation, "body_length_mm": body, "thread_length_mm": thread}, 1


def _bottle_cap(params: dict):
    from photopart.features import bottle_cap

    diameter = _require_positive("diameter_mm", _number(params, "diameter_mm", 20.0))
    pitch = _require_positive("pitch_mm", _number(params, "pitch_mm", 3.0))
    length = _require_positive("length_mm", _number(params, "length_mm", 8.0))
    outer = _require_positive("outer_diameter_mm", _number(params, "outer_diameter_mm", 26.0))
    count = int(_number(params, "knurl_count", 16))
    top = _require_positive("top_thickness_mm", _number(params, "top_thickness_mm", 1.2))
    mesh = bottle_cap(diameter=diameter, pitch=pitch, length=length, outer_diameter=outer, knurl_count=count,
                     top_thickness=top)
    resolved = {
        "diameter_mm": diameter,
        "pitch_mm": pitch,
        "length_mm": length,
        "outer_diameter_mm": outer,
        "knurl_count": count,
        "top_thickness_mm": top,
    }
    return mesh, resolved, 1


def _spur_gear(params: dict):
    from photopart.features import spur_gear

    module = _require_positive("module_mm", _number(params, "module_mm", 1.0))
    teeth = int(_number(params, "teeth", 20))
    pressure = _number(params, "pressure_angle_deg", 20.0)
    face = _require_positive("face_width_mm", _number(params, "face_width_mm", 6.0))
    bore = _optional_number(params, "bore_diameter_mm")
    key_w = _optional_number(params, "keyway_width_mm")
    key_d = _optional_number(params, "keyway_depth_mm")
    flat = _optional_number(params, "d_flat_mm")
    hub_d = _optional_number(params, "hub_diameter_mm")
    hub_l = _optional_number(params, "hub_length_mm")
    mesh = spur_gear(
        module=module,
        teeth=teeth,
        pressure_angle=pressure,
        face_width=face,
        bore=bore,
        keyway_width=key_w,
        keyway_depth=key_d,
        d_flat=flat,
        hub_diameter=hub_d,
        hub_length=hub_l,
    )
    resolved = {
        "module_mm": module,
        "teeth": teeth,
        "pressure_angle_deg": pressure,
        "face_width_mm": face,
        "outer_diameter_mm": module * (teeth + 2),
        "root_diameter_mm": module * (teeth - 2.5),
        "pitch_diameter_mm": module * teeth,
    }
    if bore is not None:
        resolved["bore_diameter_mm"] = bore
    if key_w is not None:
        resolved["keyway_width_mm"] = key_w
    if key_d is not None:
        resolved["keyway_depth_mm"] = key_d
    if flat is not None:
        resolved["d_flat_mm"] = flat
    if hub_d is not None:
        resolved["hub_diameter_mm"] = hub_d
    if hub_l is not None:
        resolved["hub_length_mm"] = hub_l
    return mesh, resolved, 1


def _scroll(params: dict):
    from photopart.features import spiral_scroll

    width = _require_positive("width_mm", _number(params, "width_mm", 6.0))
    thickness = _require_positive("thickness_mm", _number(params, "thickness_mm", 3.0))
    turns = _number(params, "turns", 1.25)
    end_radius = _require_positive("end_radius_mm", _number(params, "end_radius_mm", 18.0))
    kind = str(params.get("spiral") or params.get("kind") or "archimedean")
    tongue = _optional_number(params, "tongue_mm") or 0.0
    strap = _optional_number(params, "strap_length_mm") or 0.0
    mesh = spiral_scroll(
        width=width,
        thickness=thickness,
        turns=turns,
        end_radius=end_radius,
        kind=kind,
        tongue=tongue,
        strap_length=strap,
    )
    resolved = {
        "width_mm": width,
        "thickness_mm": thickness,
        "turns": turns,
        "end_radius_mm": end_radius,
        "spiral": kind,
    }
    if tongue:
        resolved["tongue_mm"] = tongue
    if strap:
        resolved["strap_length_mm"] = strap
    return mesh, resolved, 1


def _strap_hinge(params: dict):
    from photopart.features import strap_hinge

    length = _require_positive("length_mm", _number(params, "length_mm", 80.0))
    width = _require_positive("width_mm", _number(params, "width_mm", 8.0))
    thickness = _require_positive("thickness_mm", _number(params, "thickness_mm", 3.0))
    turns = _number(params, "turns", 1.25)
    end_radius = _require_positive("end_radius_mm", _number(params, "end_radius_mm", 16.0))
    kind = str(params.get("spiral") or params.get("kind") or "archimedean")
    ends = int(_number(params, "ends", 2))
    pivot = bool(params.get("pivot"))
    mesh = strap_hinge(
        length=length,
        width=width,
        thickness=thickness,
        turns=turns,
        end_radius=end_radius,
        kind=kind,
        ends=ends,
    )
    resolved = {
        "length_mm": length,
        "width_mm": width,
        "thickness_mm": thickness,
        "turns": turns,
        "end_radius_mm": end_radius,
        "spiral": kind,
        "ends": ends,
        "pivot": pivot,
    }
    if pivot and params.get("knuckles") not in (None, ""):
        resolved["knuckles"] = int(_number(params, "knuckles", 0))
    return mesh, resolved, 1


def _optional_number(params: dict, key: str) -> float | None:
    if key not in params or params[key] is None or params[key] == "":
        return None
    return _number(params, key, 0.0)


def _hole_list(raw, width, height, dx, dy, diameter) -> list[dict]:
    if raw is None:
        return [{"x": float(dx), "y": float(dy), "diameter": float(diameter)}]
    if not isinstance(raw, list):
        raise ValueError("holes must be a list of {x, y, diameter}")
    holes = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"hole {index} must be an object")
        holes.append(
            {
                "x": float(item["x"]),
                "y": float(item["y"]),
                "diameter": _require_positive("diameter", float(item["diameter"])),
            }
        )
    return holes


def _holes_fit(holes: list[dict], width: float, height: float, label: str) -> None:
    for index, hole in enumerate(holes):
        radius = hole["diameter"] / 2.0
        if hole["diameter"] >= min(width, height):
            raise ValueError(f"{label} hole {index} is wider than the part")
        if not (radius + 0.8 <= hole["x"] <= width - radius - 0.8 and radius + 0.8 <= hole["y"] <= height - radius - 0.8):
            raise ValueError(f"{label} hole {index} is not inside the plate")


def _cube(x: float, y: float, z: float):
    import manifold3d

    return manifold3d.Manifold.cube((float(x), float(y), float(z)), center=False)


def _cylinder_z(radius, height, x, y, z, radius_high=None, segments=40):
    import manifold3d

    high = radius if radius_high is None else radius_high
    return manifold3d.Manifold.cylinder(float(height), float(radius), float(high), int(segments), False).translate(
        (float(x), float(y), float(z))
    )


def _cylinder_x(radius, length, x, y, z, segments=40):
    import manifold3d

    return (
        manifold3d.Manifold.cylinder(float(length), float(radius), float(radius), int(segments), False)
        .rotate((0.0, 90.0, 0.0))
        .translate((float(x), float(y), float(z)))
    )


def _tube_x(r_out, r_in, length, x, y, z, segments=40):
    import manifold3d

    outer = manifold3d.Manifold.cylinder(float(length), float(r_out), float(r_out), int(segments), False)
    inner = manifold3d.Manifold.cylinder(float(length) + 0.8, float(r_in), float(r_in), int(segments), False).translate(
        (0.0, 0.0, -0.4)
    )
    body = manifold3d.Manifold.batch_boolean([outer, inner], manifold3d.OpType.Subtract)
    return body.rotate((0.0, 90.0, 0.0)).translate((float(x), float(y), float(z)))


def _as_mesh(body):
    from photopart.manifold_util import as_mesh

    return as_mesh(body)


def _revolve_profile(profile: list[list[float]], segments: int):
    import manifold3d

    section = manifold3d.CrossSection([profile])
    return manifold3d.Manifold.revolve(section, circular_segments=segments)


def _union_many(bodies):
    import manifold3d

    bodies = list(bodies)
    if len(bodies) == 1:
        return bodies[0]
    return manifold3d.Manifold.batch_boolean(bodies, manifold3d.OpType.Add)


def _difference(base, cutters):
    import manifold3d

    if not cutters:
        return base
    return manifold3d.Manifold.batch_boolean([base, *cutters], manifold3d.OpType.Subtract)
