"""Shape parameters and example scripts returned by the tools.

Agents should use this instead of opening features.py, parts.py, or launcher.py.
"""

from __future__ import annotations

from photopart.flow import SKILL_ID

_NOTE = (
    f'skill_view("{SKILL_ID}"). That is the only skill id. It has no plugin: prefix.\n'
    "Do not open features.py, parts.py, launcher.py, evals/, or tests/. "
    "Check photo_part_template before a custom script. "
    "Do not import build123d or cadquery, and do not install or patch around a missing CAD library. "
    "These parameters and the example script are enough."
)

SHAPES: dict[str, dict] = {
    "plate_clip": {
        "summary": "Sample plate with a hook and one slot. Filename stays plate_clip.stl.",
        "params": {
            "width_mm": 51.0,
            "height_mm": 60.6,
            "thickness_mm": 6.0,
            "lower_taper_mm": 4.0,
            "hook_width_mm": 16.0,
            "hook_rise_mm": 12.0,
            "hook_lip_mm": 5.0,
            "hook_overlap_mm": 2.0,
            "slot_width_mm": 22.0,
            "slot_height_mm": 14.0,
            "slot_center_x_mm": 32.0,
            "slot_center_y_mm": 28.0,
        },
    },
    "plate": {
        "summary": "Rectangular plate. holes is a list of {x, y, diameter}.",
        "params": {"width_mm": 40.0, "height_mm": 30.0, "thickness_mm": 4.0, "holes": [{"x": 20.0, "y": 15.0, "diameter": 6.0}]},
    },
    "countersink": {
        "summary": "Plate with one countersunk hole. countersink_depth_mm must be less than thickness_mm.",
        "params": {
            "width_mm": 40.0,
            "height_mm": 30.0,
            "thickness_mm": 4.0,
            "hole_diameter_mm": 4.0,
            "countersink_diameter_mm": 8.0,
            "countersink_depth_mm": 1.5,
            "hole_x_mm": 20.0,
            "hole_y_mm": 15.0,
        },
    },
    "revolve": {
        "summary": "Revolved profile. height_mm and radius_mm only.",
        "params": {"height_mm": 18.0, "radius_mm": 12.0},
    },
    "ribs": {
        "summary": "Hub with radial ribs.",
        "params": {"radius_mm": 8.0, "height_mm": 12.0, "rib_count": 6, "rib_thickness_mm": 1.6, "rib_length_mm": 12.8},
    },
    "l_bracket": {
        "summary": "One L bracket. Holes go through the horizontal leg (Z) and the vertical leg (X).",
        "params": {"length_mm": 50.0, "width_mm": 24.0, "height_mm": 40.0, "thickness_mm": 3.0, "hole_diameter_mm": 5.0},
    },
    "hinge": {
        "summary": "Print-in-place hinge. Two shells. knuckles default 4, along X.",
        "params": {"length_mm": 34.0, "leaf_mm": 14.0, "pin_radius_mm": 2.0, "clearance_mm": 0.45, "knuckles": 4},
    },
    "thread": {
        "summary": "External ISO thread, or internal when internal is true.",
        "params": {"designation": "M3", "length_mm": 6.0, "internal": False, "wall_mm": 2.0},
    },
    "knurl": {
        "summary": "Straight or diamond knurl on a cylinder.",
        "params": {"style": "straight", "diameter_mm": 8.0, "length_mm": 6.0, "count": 12},
    },
    "sweep": {
        "summary": "Tube swept along path, or the built-in hook when path is omitted.",
        "params": {"radius_mm": 1.0, "segments": 8},
    },
    "hex_screw": {
        "summary": "Hex-head screw. length_mm is the thread under the head.",
        "params": {"designation": "M3", "length_mm": 8.0},
    },
    "hex_standoff": {
        "summary": "Hex standoff with a blind bore and a male thread.",
        "params": {"designation": "M3", "body_length_mm": 6.0, "thread_length_mm": 3.0},
    },
    "bottle_cap": {
        "summary": "Cap with an internal thread and straight knurl.",
        "params": {"diameter_mm": 20.0, "pitch_mm": 3.0, "length_mm": 8.0, "outer_diameter_mm": 26.0, "knurl_count": 16},
    },
    "spur_gear": {
        "summary": "Involute gear. Tip diameter is module_mm * (teeth + 2). Root diameter is module_mm * (teeth - 2.5).",
        "params": {
            "module_mm": 1.0,
            "teeth": 20,
            "pressure_angle_deg": 20.0,
            "face_width_mm": 6.0,
            "bore_diameter_mm": None,
            "keyway_width_mm": None,
            "keyway_depth_mm": None,
            "d_flat_mm": None,
            "hub_diameter_mm": None,
            "hub_length_mm": None,
        },
    },
    "scroll": {
        "summary": "Archimedean or log spiral strip. spiral is archimedean or log.",
        "params": {"width_mm": 6.0, "thickness_mm": 3.0, "turns": 1.25, "end_radius_mm": 18.0, "spiral": "archimedean"},
    },
    "strap_hinge": {
        "summary": "Straight strap with a spiral scroll on one or both ends. One shell. No knuckle check unless pivot is true.",
        "params": {
            "length_mm": 80.0,
            "width_mm": 8.0,
            "thickness_mm": 3.0,
            "turns": 1.25,
            "end_radius_mm": 16.0,
            "spiral": "archimedean",
            "ends": 2,
            "pivot": False,
            "knuckles": None,
        },
    },
}

FEATURES: dict[str, dict] = {
    "external_thread": {
        "signature": "external_thread(designation='M3', diameter=None, pitch=None, length=8, segments_per_turn=12)",
        "summary": "One external ISO metric thread along Z.",
    },
    "internal_thread": {
        "signature": "internal_thread(designation='M3', diameter=None, pitch=None, length=8, outer_diameter=None, wall=2, segments_per_turn=12)",
        "summary": "Cylinder with an internal thread. The hole breaks both ends.",
    },
    "knurl": {
        "signature": "knurl(style='straight', diameter=10, length=8, count=20)",
        "summary": "style is straight or diamond.",
    },
    "revolve_profile": {
        "signature": "revolve_profile(points, segments=48)",
        "summary": "points is [[radius, height], ...]. Radius (X) stays >= 0. Revolves around Y.",
    },
    "sweep_path": {
        "signature": "sweep_path(path, radius=1.5, segments=12)",
        "summary": "path is [[x, y, z], ...]. radius is the tube radius.",
    },
    "hex_screw": {
        "signature": "hex_screw(designation='M3', length=12, head_height=None, across_flats=None, diameter=None, pitch=None)",
        "summary": "length is the thread under the head.",
    },
    "hex_standoff": {
        "signature": "hex_standoff(designation='M3', body_length=10, thread_length=6, across_flats=None, diameter=None, pitch=None)",
        "summary": "Hex body, blind bore, male thread on +Z.",
    },
    "bottle_cap": {
        "signature": "bottle_cap(diameter=20, pitch=3, length=8, outer_diameter=26, knurl_count=16)",
        "summary": "Internal thread plus straight knurl.",
    },
    "spur_gear": {
        "signature": "spur_gear(module, teeth, pressure_angle=20, face_width, bore=None, keyway_width=None, keyway_depth=None, d_flat=None, hub_diameter=None, hub_length=None)",
        "summary": "Tip diameter module*(teeth+2). Root diameter module*(teeth-2.5). Keyway or D-flat, not both.",
    },
    "spiral_scroll": {
        "signature": "spiral_scroll(width, thickness, turns, end_radius, kind='archimedean', inner_radius=None, tongue=0, strap_length=0)",
        "summary": "kind is archimedean or log.",
    },
    "strap_hinge": {
        "signature": "strap_hinge(length, width, thickness, turns=1.25, end_radius=16, kind='archimedean', ends=2)",
        "summary": "ends is 1 or 2. One watertight body.",
    },
}

_FEATURE_EXAMPLE = f"""# skill_view("{SKILL_ID}")
from photopart.features import strap_hinge, spur_gear, tag_faces

mesh = strap_hinge(length=80, width=8, thickness=3, turns=1.25, end_radius=16, ends=2)
mesh.export("/absolute/project/strap_hinge_v1.stl")

gear = spur_gear(module=1.0, teeth=20, face_width=6, bore=5)
gear.export("/absolute/project/spur_gear_v1.stl")

# Tag after the final boolean. Indices do not survive a union.
# tag_faces(mesh, thread=[0, 1], path="/absolute/project/part_v1.stl")
"""


def _example_for(shape: str, params: dict) -> str:
    shown = {key: value for key, value in params.items() if value is not None}
    return (
        f'# skill_view("{SKILL_ID}")\n'
        f"# photo_part_template. Do not open parts.py.\n"
        f"# shape={shape}\n"
        f"# params={shown}\n"
    )


def describe_shapes(shape: str | None = None) -> dict:
    """Parameters for one template shape, or every shape when ``shape`` is omitted."""
    if shape:
        name = str(shape).strip()
        spec = SHAPES.get(name)
        if spec is None:
            known = ", ".join(SHAPES)
            raise ValueError(f"unknown shape {shape!r}. Known shapes: {known}")
        return {
            "ok": True,
            "help": True,
            "shape": name,
            "summary": spec["summary"],
            "params": spec["params"],
            "example_script": _example_for(name, spec["params"]),
            "feature_example_script": _FEATURE_EXAMPLE if name in {"spur_gear", "scroll", "strap_hinge", "thread", "knurl", "sweep", "hex_screw", "hex_standoff", "bottle_cap"} else None,
            "note": _NOTE,
        }
    return {
        "ok": True,
        "help": True,
        "shapes": {name: {"summary": spec["summary"], "params": spec["params"]} for name, spec in SHAPES.items()},
        "example_script": _example_for("l_bracket", SHAPES["l_bracket"]["params"]),
        "feature_example_script": _FEATURE_EXAMPLE,
        "note": _NOTE,
    }


def describe_features() -> dict:
    """Signatures for photopart.features and one script that exports an STL."""
    return {
        "ok": True,
        "help": True,
        "features": FEATURES,
        "example_script": _FEATURE_EXAMPLE,
        "import": "from photopart.features import external_thread, internal_thread, knurl, revolve_profile, sweep_path, hex_screw, hex_standoff, bottle_cap, spur_gear, spiral_scroll, strap_hinge, tag_faces",
        "note": _NOTE,
    }
