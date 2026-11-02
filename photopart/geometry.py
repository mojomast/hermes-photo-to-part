"""Parametric plate-with-hook solid, used as a stand-in sample.

The shape is a generic tapered plate, a top hook, and one slot. It is not a
model of any commercial part. Profiles are built with Shapely and extruded
with trimesh, so the sample runs without a CAD kernel. Use CadQuery or
build123d when the real part needs fillets or a STEP file.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Mapping

import numpy as np
import trimesh
from shapely.geometry import Polygon, box

# name, default millimetres, minimum, what it controls
FIELDS: tuple[tuple[str, float, float, str], ...] = (
    ("width_mm", 51.0, 5.0, "Overall width across the top of the plate."),
    ("height_mm", 60.6, 10.0, "Plate height, not counting the hook."),
    ("thickness_mm", 6.0, 0.4, "Extrusion thickness."),
    ("lower_taper_mm", 4.0, 0.0, "Inset of each bottom corner. Zero is a straight plate."),
    ("hook_width_mm", 16.0, 2.0, "How far the hook extends in from the left edge."),
    ("hook_rise_mm", 12.0, 2.0, "How far the hook rises above the plate."),
    ("hook_lip_mm", 5.0, 0.8, "Thickness of the hook's left bar and top lip."),
    ("hook_overlap_mm", 2.0, 0.2, "How far the hook digs into the plate so the union is not a kiss."),
    ("slot_width_mm", 22.0, 1.0, "Slot width."),
    ("slot_height_mm", 14.0, 1.0, "Slot height."),
    ("slot_center_x_mm", 32.0, 0.0, "Slot center, from the left edge."),
    ("slot_center_y_mm", 28.0, 0.0, "Slot center, from the bottom edge."),
)
DEFAULTS: dict[str, float] = {name: value for name, value, _min, _help in FIELDS}
_MINIMUM: dict[str, float] = {name: minimum for name, _value, minimum, _help in FIELDS}


def parse_params(raw: Mapping[str, object] | None = None) -> dict[str, float]:
    """Merge overrides onto the defaults and reject unknown or non-finite values."""
    params = dict(DEFAULTS)
    for key, value in (raw or {}).items():
        if key not in params:
            known = ", ".join(sorted(params))
            raise ValueError(f"unknown parameter {key!r}. Known parameters: {known}")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} must be a number, got {value!r}") from exc
        if not np.isfinite(number):
            raise ValueError(f"{key} must be finite")
        if number < _MINIMUM[key]:
            raise ValueError(f"{key} must be >= {_MINIMUM[key]}, got {number}")
        params[key] = number
    _check_relationships(params)
    return params


def _check_relationships(params: Mapping[str, float]) -> None:
    width = params["width_mm"]
    height = params["height_mm"]
    taper = params["lower_taper_mm"]
    if taper * 2 >= width - 1:
        raise ValueError("lower_taper_mm leaves less than 1 mm of bottom edge")
    if params["hook_width_mm"] >= width - 1:
        raise ValueError("hook_width_mm must stay inside the plate width")
    if params["hook_lip_mm"] >= params["hook_width_mm"] - 0.4:
        raise ValueError("hook_lip_mm must be narrower than hook_width_mm")
    if params["hook_lip_mm"] >= params["hook_rise_mm"] - 0.4:
        raise ValueError("hook_lip_mm must be shorter than hook_rise_mm")
    if params["hook_overlap_mm"] >= height / 3:
        raise ValueError("hook_overlap_mm is too deep for this plate height")


def expected_extents(params: Mapping[str, float]) -> tuple[float, float, float]:
    """Axis-aligned design size: X width, Y height plus hook, Z thickness."""
    return (
        float(params["width_mm"]),
        float(params["height_mm"] + params["hook_rise_mm"]),
        float(params["thickness_mm"]),
    )


def build_profile(params: Mapping[str, float]) -> Polygon:
    """Build the 2D silhouette, in millimetres, with the slot as a hole."""
    width = params["width_mm"]
    height = params["height_mm"]
    taper = params["lower_taper_mm"]
    hook_width = params["hook_width_mm"]
    rise = params["hook_rise_mm"]
    lip = params["hook_lip_mm"]
    overlap = params["hook_overlap_mm"]

    body = Polygon(
        [(taper, 0.0), (width - taper, 0.0), (width, height), (0.0, height)]
    )
    hook_rect = box(0.0, height - overlap, hook_width, height + rise)
    # The notch runs past the hook's right edge so it opens to the outside.
    notch = box(lip, height, hook_width + 1.0, height + rise - lip)
    solid = body.union(hook_rect.difference(notch))

    slot = box(
        params["slot_center_x_mm"] - params["slot_width_mm"] / 2,
        params["slot_center_y_mm"] - params["slot_height_mm"] / 2,
        params["slot_center_x_mm"] + params["slot_width_mm"] / 2,
        params["slot_center_y_mm"] + params["slot_height_mm"] / 2,
    )
    if not body.contains(slot):
        raise ValueError(
            "slot is not strictly inside the plate. Move slot_center or shrink the slot."
        )
    solid = solid.difference(slot)
    if solid.geom_type != "Polygon" or not solid.is_valid or solid.is_empty:
        raise ValueError(
            f"profile is {solid.geom_type}, not a single polygon. Adjust the parameters."
        )
    return solid


def build_mesh(params: Mapping[str, float] | None = None) -> trimesh.Trimesh:
    """Extrude the profile into a watertight solid of the requested thickness."""
    resolved = parse_params(params)
    profile = build_profile(resolved)
    mesh = trimesh.creation.extrude_polygon(profile, height=resolved["thickness_mm"])
    mesh.merge_vertices()
    mesh.metadata["units"] = "millimeters"
    mesh.metadata["photo_to_part_params"] = resolved
    return mesh


def scad_source(params: Mapping[str, float] | None = None) -> str:
    """OpenSCAD of the same silhouette. It previews the profile; it is not STEP."""
    resolved = parse_params(params)
    profile = build_profile(resolved)

    def points(ring) -> str:
        coords = list(ring.coords)[:-1]
        return ", ".join(f"[{x:.4f}, {y:.4f}]" for x, y in coords)

    holes = "\n".join(
        f"    polygon(points=[{points(ring)}]);" for ring in profile.interiors
    )
    return (
        "// Generated plate-clip profile. Units are millimetres.\n"
        "// This is a mesh preview. A STEP solid needs CadQuery or build123d.\n"
        f"linear_extrude(height={resolved['thickness_mm']:.4f}, convexity=4)\n"
        "  difference() {\n"
        f"    polygon(points=[{points(profile.exterior)}]);\n"
        f"{holes}\n"
        "  }\n"
    )


def export_stl(mesh: trimesh.Trimesh, path: Path, *, ascii_stl: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if ascii_stl:
        from trimesh.exchange.stl import export_stl_ascii

        path.write_text(export_stl_ascii(mesh), encoding="utf-8")
        return
    path.write_bytes(mesh.export(file_type="stl"))


def export_3mf(mesh: trimesh.Trimesh, path: Path) -> None:
    """Write a 3MF in millimetres. Requires lxml, which is not a plugin dependency."""
    try:
        import lxml  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "3MF export needs the optional lxml package. "
            "Install it with: python -m pip install 'lxml>=5,<6.2'"
        ) from exc
    payload = mesh.export(file_type="3mf")
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def params_document(params: Mapping[str, float]) -> dict:
    extents = expected_extents(params)
    return {
        "units": "millimeters",
        "description": (
            "Generic tapered plate with a top hook and one slot. "
            "A sample for the photo-to-part workflow, not a commercial part."
        ),
        "parameters": {key: params[key] for key in DEFAULTS},
        "parameter_help": {name: text for name, _v, _m, text in FIELDS},
        "expected_extents_mm": {"x": extents[0], "y": extents[1], "z": extents[2]},
    }


def write_template(
    out_dir: Path,
    params: Mapping[str, float] | None = None,
    *,
    ascii_stl: bool = False,
    write_3mf: bool = True,
) -> dict:
    """Write the STL, optional 3MF, OpenSCAD, and parameter JSON."""
    resolved = parse_params(params)
    mesh = build_mesh(resolved)
    out_dir.mkdir(parents=True, exist_ok=True)
    stl_path = out_dir / "plate_clip.stl"
    export_stl(mesh, stl_path, ascii_stl=ascii_stl)
    scad_path = out_dir / "plate_clip.scad"
    scad_path.write_text(scad_source(resolved), encoding="utf-8")
    doc = params_document(resolved)
    (out_dir / "params.json").write_text(
        json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    threemf = out_dir / "plate_clip.3mf"
    threemf_error = None
    if write_3mf:
        try:
            export_3mf(mesh, threemf)
        except RuntimeError as exc:
            threemf_error = str(exc)
            if threemf.exists():
                threemf.unlink()
    return {
        "mesh": mesh,
        "params": resolved,
        "stl": stl_path,
        "scad": scad_path,
        "threemf": None if threemf_error or not write_3mf else threemf,
        "threemf_error": threemf_error,
        "expected_extents_mm": expected_extents(resolved),
    }


def _load_overrides(path: str | None, sets: list[str] | None) -> dict[str, float]:
    raw: dict[str, object] = {}
    if path:
        loaded = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
        if isinstance(loaded, dict) and isinstance(loaded.get("parameters"), dict):
            loaded = loaded["parameters"]
        if not isinstance(loaded, dict):
            raise ValueError("--params must be a JSON object or a document with parameters")
        raw.update(loaded)
    for item in sets or []:
        if "=" not in item:
            raise ValueError(f"--set expects key=value, got {item!r}")
        key, value = item.split("=", 1)
        raw[key.strip()] = value.strip()
    return parse_params(raw)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write the sample plate-clip STL, OpenSCAD, and parameter file."
    )
    parser.add_argument("--out-dir", required=True, help="Directory to create or reuse.")
    parser.add_argument("--params", help="JSON object of parameter overrides.")
    parser.add_argument("--set", action="append", default=[], help="Override one key=value.")
    parser.add_argument("--ascii", action="store_true", help="Write an ASCII STL.")
    parser.add_argument("--no-3mf", action="store_true", help="Skip the 3MF file.")
    parser.add_argument("--force", action="store_true", help="Overwrite files in --out-dir.")
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    args = parser.parse_args(argv)
    out_dir = Path(args.out_dir).expanduser().resolve()
    targets = [out_dir / "plate_clip.stl", out_dir / "plate_clip.scad", out_dir / "params.json"]
    if not args.no_3mf:
        targets.append(out_dir / "plate_clip.3mf")
    existing = [path for path in targets if path.exists()]
    if existing and not args.force:
        names = ", ".join(path.name for path in existing)
        print(f"refusing to overwrite {names}. Pass --force.", flush=True)
        return 1
    try:
        params = _load_overrides(args.params, args.set)
        written = write_template(
            out_dir, params, ascii_stl=args.ascii, write_3mf=not args.no_3mf
        )
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", flush=True)
        return 1
    summary = {
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
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["watertight"] else 2
