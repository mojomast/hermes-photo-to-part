"""Check a mesh for a printable solid and an expected overall size."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from photopart.flow import attach_flow, failed, step_validate
from photopart.io import DEFAULT_MAX_BYTES, load_mesh
from photopart.paths import absolute_path
from photopart.report import measure
from photopart.stamp import sidecar_path, stamp_status, write_sidecar
from photopart.status import status
from photopart.units import add_unit_arguments, attach_units, prepare_mesh


def compare_extents(
    actual: dict[str, float],
    target: tuple[float, float, float],
    *,
    tolerance: float,
    allow_axis_swap: bool,
) -> tuple[bool, dict[str, float]]:
    """Compare X, Y, Z extents. Optional swap matches sorted sizes only."""
    got = np.array([actual["x"], actual["y"], actual["z"]], dtype=float)
    want = np.array(target, dtype=float)
    if allow_axis_swap:
        got = np.sort(got)
        want = np.sort(want)
        labels = ("sorted_a", "sorted_b", "sorted_c")
    else:
        labels = ("x", "y", "z")
    delta = {label: float(abs(got[i] - want[i])) for i, label in enumerate(labels)}
    return bool(np.all(np.abs(got - want) <= tolerance)), delta


def _closure_failure(measured: dict) -> str:
    """Say why a mesh is open. A count of zero boundary edges is not a cause."""
    parts: list[str] = []
    if measured["nonmanifold_edges"]:
        parts.append(f"{measured['nonmanifold_edges']} non-manifold edges")
    if measured["degenerate_faces"]:
        parts.append(f"{measured['degenerate_faces']} degenerate faces")
    if measured["boundary_edges"]:
        parts.append(f"{measured['boundary_edges']} boundary edges")
    if not parts:
        parts.append("the surface does not close")
    detail = ", ".join(parts)
    return (
        f"not watertight: {detail}. "
        "Run photo_part_heal to weld vertices, drop degenerate faces, and round-trip through manifold3d."
    )


def evaluate(
    mesh,
    *,
    target: tuple[float, float, float] | None = None,
    tolerance: float = 0.3,
    allow_axis_swap: bool = False,
    allow_open: bool = False,
    allow_multi_shell: bool = False,
    expected_shells: int | None = None,
    holes: list | None = None,
) -> dict:
    """Return a JSON-ready report. `ok` is true only when every check passes."""
    measured = measure(mesh)
    failures: list[str] = []
    if not measured["watertight"] and not allow_open:
        failures.append(_closure_failure(measured))
    elif measured["watertight"] and not measured["winding_consistent"]:
        failures.append("winding is inconsistent")
    if measured["watertight"] or allow_open:
        if measured["nonmanifold_edges"]:
            failures.append(f"{measured['nonmanifold_edges']} non-manifold edges")
        if measured["degenerate_faces"]:
            failures.append(f"{measured['degenerate_faces']} degenerate faces")
    volume = measured["volume_mm3"]
    if measured["watertight"] and measured["winding_consistent"] and (
        volume is None or volume <= 0
    ):
        failures.append("volume is not positive")
    components = measured["components"]
    if expected_shells is not None:
        if components != int(expected_shells):
            failures.append(f"{components} shells; expected {int(expected_shells)}")
    elif components is not None and components != 1 and not allow_multi_shell:
        failures.append(
            f"{components} shells; a printable part should be one shell. "
            "For a print-in-place part, pass --expected-shells N or --allow-multi-shell."
        )
    hole_report = None
    if holes:
        from photopart.holes import check_holes

        hole_failures, hole_report = check_holes(mesh, holes, tolerance=tolerance)
        failures.extend(hole_failures)

    delta = None
    if target is not None:
        passed, delta = compare_extents(
            measured["extents_mm"],
            target,
            tolerance=tolerance,
            allow_axis_swap=allow_axis_swap,
        )
        if not passed:
            pieces = ", ".join(f"{name} off by {value:.3f} mm" for name, value in delta.items())
            failures.append(
                f"bounding box outside ±{tolerance:.3f} mm ({pieces})"
            )
    report = {
        "ok": not failures,
        "failures": failures,
        "tolerance_mm": tolerance,
        "axis_swap": allow_axis_swap,
        "target_mm": None
        if target is None
        else {"x": target[0], "y": target[1], "z": target[2]},
        "extent_delta_mm": delta,
        "expected_shells": None if expected_shells is None else int(expected_shells),
        "holes": hole_report,
        **measured,
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check watertightness and bounding box of an STL, 3MF, OBJ, or PLY."
    )
    parser.add_argument("mesh", help="Mesh to check.")
    parser.add_argument(
        "--size",
        nargs=3,
        type=float,
        metavar=("X", "Y", "Z"),
        help="Target extents in millimetres, X Y Z.",
    )
    parser.add_argument("--tolerance", type=float, default=0.3, help="Millimetres. Default 0.3.")
    parser.add_argument(
        "--allow-axis-swap",
        action="store_true",
        help="Compare sorted extents when the mesh axes may be permuted.",
    )
    parser.add_argument("--allow-open", action="store_true")
    parser.add_argument("--allow-multi-shell", action="store_true")
    parser.add_argument(
        "--expected-shells",
        type=int,
        help="Exact shell count. Use 2 for a print-in-place hinge. Overrides the one-shell rule.",
    )
    parser.add_argument(
        "--allow-size",
        action="store_true",
        help="Accept a longest side under 1 mm or over 2 m. Without this, that size fails.",
    )
    parser.add_argument(
        "--holes",
        help="JSON list of {x, y, diameter, axis?} holes to check, in millimetres.",
    )
    parser.add_argument(
        "--spec",
        help="JSON file of x,y,z, shells, knuckles, hole_count, and holes. Fails when the mesh drifts.",
    )
    parser.add_argument(
        "--dim",
        action="append",
        default=[],
        help="One check, name=value±tol. Repeatable. x, y, z, shells, knuckles, hole_count.",
    )
    parser.add_argument(
        "--json-out",
        help="Ignored unless it is the canonical <file>.validate.json. That sidecar is the only validation file.",
    )
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    add_unit_arguments(parser)
    args = parser.parse_args(argv)
    code, report = run_validate(
        args.mesh,
        size=None if args.size is None else tuple(args.size),
        tolerance=args.tolerance,
        allow_axis_swap=args.allow_axis_swap,
        allow_open=args.allow_open,
        allow_multi_shell=args.allow_multi_shell,
        expected_shells=args.expected_shells,
        allow_size=args.allow_size,
        holes=args.holes,
        units=args.units,
        scale=args.scale,
        json_out=args.json_out,
        spec=args.spec,
        dims=args.dim,
        max_bytes=args.max_bytes,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    if report.get("unit_warning"):
        status(report["unit_warning"])
    if code == 0:
        status("ok")
    elif report.get("failures"):
        status("FAILED: " + "; ".join(report["failures"]))
    elif report.get("error"):
        status(f"error: {report['error']}")
    return code


def run_validate(
    mesh_path: str,
    *,
    size: tuple[float, float, float] | None = None,
    tolerance: float = 0.3,
    allow_axis_swap: bool = False,
    allow_open: bool = False,
    allow_multi_shell: bool = False,
    expected_shells: int | None = None,
    allow_size: bool = False,
    holes: list | str | None = None,
    units: str | None = None,
    scale: float | None = None,
    json_out: str | None = None,
    spec=None,
    dims=None,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> tuple[int, dict]:
    """Load, scale, and check a mesh. The report is the stdout document."""
    if tolerance < 0:
        return 1, failed("--tolerance must be >= 0")
    if expected_shells is not None and int(expected_shells) < 1:
        return 1, failed("--expected-shells must be >= 1")
    try:
        hole_specs = _load_holes(holes)
        loaded = load_mesh(mesh_path, max_bytes=max_bytes)
        mesh, meta = prepare_mesh(loaded, units, scale)
        report = evaluate(
            mesh,
            target=size,
            tolerance=tolerance,
            allow_axis_swap=allow_axis_swap,
            allow_open=allow_open,
            allow_multi_shell=allow_multi_shell,
            expected_shells=expected_shells,
            holes=hole_specs,
        )
        if spec or dims:
            from photopart.spec import apply_spec

            spec_failures, spec_rows = apply_spec(mesh, spec=spec, dims=dims, tolerance=tolerance)
            report["spec"] = spec_rows
            report["failures"].extend(spec_failures)
            report["ok"] = not report["failures"]
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return 1, failed(str(exc))
    resolved = Path(mesh_path).expanduser().resolve()
    report["file"] = str(resolved)
    attach_units(report, meta)
    if meta["unit_warning"] and not allow_size:
        report["failures"].append(meta["unit_warning"])
        report["ok"] = False
    report["allow_size"] = bool(allow_size)
    try:
        prior = stamp_status(resolved)
        attach_flow(
            report,
            step_validate(str(resolved), ok=bool(report["ok"]), was_stale=prior["stale_validation"]),
        )
        stamp = write_sidecar(resolved, report)
    except OSError as exc:
        return 1, failed(str(exc))
    report["sha256"] = stamp["sha256"]
    report["stale_validation"] = stamp["stale_validation"]
    report["validation_sidecar"] = stamp["validation_sidecar"]
    canonical = sidecar_path(resolved)
    report["sidecar_note"] = f"The only validation file is {canonical.name}."
    if json_out:
        try:
            destination = absolute_path(json_out)
        except ValueError as exc:
            return 1, failed(str(exc))
        if destination.resolve() != canonical.resolve():
            report["sidecar_note"] = (
                f"The only validation file is {canonical.name}. "
                "--json-out was not written."
            )
    return (0 if report["ok"] else 2), report


def _load_holes(holes: list | str | None) -> list | None:
    if holes is None or holes == "":
        return None
    if isinstance(holes, str):
        text = Path(holes).expanduser().read_text(encoding="utf-8")
        holes = json.loads(text)
        if isinstance(holes, dict) and "holes" in holes:
            holes = holes["holes"]
    if not isinstance(holes, list):
        raise ValueError("holes must be a JSON list of {x, y, diameter}")
    return holes
