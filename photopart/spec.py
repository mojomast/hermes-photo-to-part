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
    """Count knuckles along ``axis`` between the pin and the knuckle wall.

    A ring at the bbox centre sits inside a continuous pin and reports one
    solid run. Several radii are sampled, from just off the axis out to just
    under half the short cross-section (inside the knuckle, short of the
    leaves). A radius that is solid for the whole span is the pin core and is
    skipped. The count is the largest remaining run. Call this only when the
    spec asks for knuckles.
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
    if cross <= 0:
        return 0
    outer = 0.48 * cross
    if outer <= 0.55:
        radii = np.array([max(0.2, outer * 0.6)], dtype=float)
    else:
        radii = np.linspace(0.5, outer, 6)
    center = bounds.mean(axis=0)
    stations = int(np.clip(round(span / 0.15), 80, 360))
    angles = 8
    pad = min(0.15, 0.005 * span)
    coords = np.linspace(bounds[0, along] + pad, bounds[1, along] - pad, stations)
    turns = np.arange(angles, dtype=float) * (2.0 * np.pi / angles)
    n_radii = len(radii)
    points = np.empty((n_radii, stations, angles, 3), dtype=float)
    points[...] = center
    points[..., along] = coords[None, :, None]
    points[..., others[0]] = center[others[0]] + radii[:, None, None] * np.cos(turns)[None, None, :]
    points[..., others[1]] = center[others[1]] + radii[:, None, None] * np.sin(turns)[None, None, :]
    inside = _inside(mesh, points.reshape(-1, 3)).reshape(n_radii, stations, angles)
    occupied = inside.any(axis=2)
    best = 0
    for row in occupied:
        runs, fraction = _occupied_runs(row)
        if runs == 1 and fraction >= 0.97:
            continue
        if runs == 0:
            continue
        if runs > best:
            best = runs
    return best


def _occupied_runs(flags) -> tuple[int, float]:
    """Runs of at least three inside samples, and the occupied fraction."""
    row = np.asarray(flags, dtype=bool)
    if len(row) == 0:
        return 0, 0.0
    padded = np.concatenate(([False], row, [False]))
    changes = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(changes == 1)
    ends = np.flatnonzero(changes == -1)
    runs = int(np.count_nonzero((ends - starts) >= 3))
    fraction = float(np.count_nonzero(row)) / float(len(row))
    return runs, fraction


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


_TEMPLATE_CHECKS = ("x", "y", "z", "shells", "knuckles", "hole_count")
_VERSION_STEM = re.compile(r"^(?P<prefix>.+)_v\d+$")
SPEC_NUDGE = (
    "No spec.json in the working directory. Write the user's bbox and key features "
    "to spec.json before photo_part_validate."
)


def find_template_spec(mesh_path) -> dict | None:
    """Spec checks a template wrote beside this mesh, or beside its unversioned name."""
    path = Path(mesh_path).expanduser()
    if path.exists():
        path = path.resolve()
    stems = [path.stem]
    match = _VERSION_STEM.match(path.stem)
    if match:
        stems.append(match.group("prefix"))
    seen: set[str] = set()
    for stem in stems:
        for candidate in (
            path.parent / f"{stem}.template.json",
            path.parent / f"{stem}.stl.template.json",
        ):
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            loaded = _read_object(candidate)
            if loaded is None:
                continue
            checks = loaded.get("spec_checks")
            if isinstance(checks, dict):
                return checks
    return None


def template_omissions(mesh_path, spec, dims) -> list[str]:
    """Failures for checks the template emitted that the user spec dropped."""
    checks = find_template_spec(mesh_path)
    if not checks:
        return []
    present = _present_names(spec, dims)
    missing = []
    for name in _TEMPLATE_CHECKS:
        if name not in checks or name in present:
            continue
        missing.append(
            f"spec dropped template check {name} (template expected {checks[name]}). "
            "Do not remove a check the template emitted."
        )
    return missing


def note_missing_spec(report: dict, *dirs) -> dict:
    """Warn when none of ``dirs`` contains ``spec.json``. Does not fail the tool."""
    for raw in dirs:
        if raw is None or raw == "":
            continue
        if (Path(raw).expanduser() / "spec.json").is_file():
            return report
    report["spec_warning"] = SPEC_NUDGE
    step = str(report.get("next_step") or "")
    if SPEC_NUDGE not in step:
        report["next_step"] = f"{SPEC_NUDGE} {step}".strip()
    return report


def _present_names(spec, dims) -> set[str]:
    names: set[str] = set()
    raw = load_spec(spec) if spec else {}
    nested = raw.get("dims") if isinstance(raw.get("dims"), dict) else {}
    for name in _NAMES:
        if raw.get(name) is not None or (isinstance(nested, dict) and nested.get(name) is not None):
            names.add(name)
    if isinstance(dims, str):
        dims = [dims]
    for item in dims or []:
        name, _value, _tol = parse_dim(item)
        names.add(name)
    return names


def _read_object(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    if not isinstance(loaded, dict):
        return None
    return loaded
