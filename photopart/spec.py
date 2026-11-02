"""Compare a mesh to the dimensions the user asked for.

``spec.json`` holds bbox sizes, shell count, knuckle count, and hole count.
``--dim name=value±tol`` is the same check on one line. Lengths default to
the validate tolerance (0.3 mm). Counts default to an exact match.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

_DIM = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([+-]?\d+(?:\.\d+)?)"
    r"(?:\s*(?:±|\+/-|\+-)\s*(\d+(?:\.\d+)?))?\s*$"
)
_AXES = {"x": 0, "y": 1, "z": 2}
_COUNTS = {"shells", "knuckles", "hole_count"}
_NAMES = set(_AXES) | _COUNTS


def parse_dim(text: str) -> tuple[str, float, float | None]:
    """``x=100±0.5``, ``y=50+/-0.4``, or ``shells=2``."""
    match = _DIM.match(str(text))
    if not match:
        raise ValueError(f"dim must look like x=100±0.5 or shells=2, got {text!r}")
    name = match.group(1).lower()
    if name not in _NAMES:
        known = ", ".join(sorted(_NAMES))
        raise ValueError(f"unknown dim {name!r}. Use one of: {known}")
    tol = None if match.group(3) is None else float(match.group(3))
    return name, float(match.group(2)), tol


def load_spec(source) -> dict:
    """A path, a JSON string, or a dict. Returns the object."""
    if source is None or source == "":
        return {}
    if isinstance(source, dict):
        return source
    text = str(source).strip()
    path = Path(text).expanduser()
    if path.is_file():
        text = path.read_text(encoding="utf-8")
    loaded = json.loads(text)
    if not isinstance(loaded, dict):
        raise ValueError("spec must be a JSON object")
    return loaded


def apply_spec(mesh, *, spec=None, dims=None, tolerance: float = 0.3) -> tuple[list[str], list[dict]]:
    """Return failure strings and one row per check. Rows go in the report as ``spec``."""
    checks = _collect(spec, dims, tolerance)
    if not checks and not _holes_of(spec):
        return [], []
    failures: list[str] = []
    rows: list[dict] = []
    extents = np.asarray(mesh.extents, dtype=float)
    for name, value, tol in checks:
        if name in _AXES:
            actual = float(extents[_AXES[name]])
        elif name == "shells":
            actual = float(len(mesh.split(only_watertight=False)))
        elif name == "knuckles":
            actual = float(count_knuckles(mesh, axis=str(checks.axis or "x")))
        elif name == "hole_count":
            actual = float(count_holes(mesh))
        else:
            raise ValueError(f"unknown spec field {name}")
        ok = abs(actual - value) <= tol + 1e-9
        rows.append(
            {
                "name": name,
                "value": value,
                "tol": tol,
                "actual": actual,
                "ok": ok,
            }
        )
        if not ok:
            shown = int(actual) if name in _COUNTS else round(actual, 3)
            failures.append(f"spec {name}: actual {shown} is outside {value:g}±{tol:g}")
    hole_specs = _holes_of(spec)
    if hole_specs:
        from photopart.holes import check_holes

        hole_failures, hole_rows = check_holes(mesh, hole_specs, tolerance=tolerance)
        for failure in hole_failures:
            failures.append(f"spec {failure}")
        for row in hole_rows:
            rows.append({"name": "hole", "ok": row["ok"], "actual": row})
    return failures, rows


def count_knuckles(mesh, axis: str = "x") -> int:
    """Count pin knuckles along ``axis`` by sampling a ring of points.

    Cylinder meshes only have vertices on the end caps, so a vertex gap is
    not a knuckle. A run of stations where the ring is inside the solid is
    one knuckle. Call this only when the spec asks for knuckles.
    """
    from photopart.holes import _inside

    name = (axis or "x").lower()
    if name not in _AXES:
        raise ValueError("knuckle_axis must be x, y, or z")
    along = _AXES[name]
    bounds = np.asarray(mesh.bounds, dtype=float)
    span = float(bounds[1, along] - bounds[0, along])
    if span <= 0:
        return 0
    others = [slot for slot in range(3) if slot != along]
    cross = min(float(bounds[1, slot] - bounds[0, slot]) for slot in others)
    radius = max(0.4, 0.15 * cross)
    center = bounds.mean(axis=0)
    stations = 100
    angles = 8
    coords = np.linspace(bounds[0, along] + 0.02 * span, bounds[1, along] - 0.02 * span, stations)
    points = np.zeros((stations * angles, 3), dtype=float)
    for index, position in enumerate(coords):
        for turn in range(angles):
            angle = turn * 2.0 * np.pi / angles
            point = center.copy()
            point[along] = position
            point[others[0]] = center[others[0]] + radius * np.cos(angle)
            point[others[1]] = center[others[1]] + radius * np.sin(angle)
            points[index * angles + turn] = point
    inside = _inside(mesh, points).reshape(stations, angles).any(axis=1)
    runs = 0
    current = 0
    for flag in inside:
        if flag:
            current += 1
            continue
        if current >= 3:
            runs += 1
        current = 0
    if current >= 3:
        runs += 1
    return runs


def count_holes(mesh) -> int:
    """Through-hole count from the genus of each watertight shell.

    A solid shell is 0. One hole is 1. This is not a knuckle count: a hinge
    pin is material, and a bored knuckle is a hole.
    """
    total = 0
    for shell in mesh.split(only_watertight=False):
        if not shell.is_watertight:
            continue
        genus = (2 - int(shell.euler_number)) / 2
        if genus > 0:
            total += int(round(genus))
    return total


class _Checks(list):
    axis: str | None = None


def _collect(spec, dims, tolerance: float) -> _Checks:
    raw = load_spec(spec) if spec else {}
    axis = raw.get("knuckle_axis") or raw.get("axis") or "x"
    default_tol = float(raw.get("tolerance", tolerance))
    if default_tol < 0:
        raise ValueError("spec tolerance must be >= 0")
    found: dict[str, tuple[float, float]] = {}
    nested = raw.get("dims") if isinstance(raw.get("dims"), dict) else {}
    for name in _NAMES:
        item = raw.get(name, nested.get(name) if isinstance(nested, dict) else None)
        if item is None:
            continue
        value, tol = _value_tol(name, item, default_tol)
        found[name] = (value, tol)
    if isinstance(dims, str):
        dims = [dims]
    for item in dims or []:
        name, value, tol = parse_dim(item)
        if tol is None:
            tol = 0.0 if name in _COUNTS else default_tol
        found[name] = (value, tol)
    checks = _Checks((name, found[name][0], found[name][1]) for name in sorted(found))
    checks.axis = str(axis)
    return checks


def _value_tol(name: str, item, default_tol: float) -> tuple[float, float]:
    if isinstance(item, dict):
        if "value" not in item:
            raise ValueError(f"spec {name} needs value")
        value = float(item["value"])
        tol = float(item.get("tol", 0.0 if name in _COUNTS else default_tol))
    else:
        value = float(item)
        tol = 0.0 if name in _COUNTS else default_tol
    if tol < 0:
        raise ValueError(f"spec {name} tolerance must be >= 0")
    return value, tol


def _holes_of(spec) -> list | None:
    if not spec:
        return None
    raw = load_spec(spec)
    holes = raw.get("holes")
    if not holes:
        return None
    if not isinstance(holes, list):
        raise ValueError("spec holes must be a list of {x, y, diameter}")
    return holes
