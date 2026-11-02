"""Check a mesh for a printable solid and an expected overall size."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from photopart.io import DEFAULT_MAX_BYTES, load_mesh
from photopart.report import measure


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


def evaluate(
    mesh,
    *,
    target: tuple[float, float, float] | None = None,
    tolerance: float = 0.3,
    allow_axis_swap: bool = False,
    allow_open: bool = False,
    allow_multi_shell: bool = False,
) -> dict:
    """Return a JSON-ready report. `ok` is true only when every check passes."""
    measured = measure(mesh)
    failures: list[str] = []
    if not measured["watertight"] and not allow_open:
        failures.append(
            f"not watertight ({measured['boundary_edges']} boundary edges)"
        )
    if measured["watertight"] and not measured["winding_consistent"]:
        failures.append("winding is inconsistent")
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
    if components is not None and components != 1 and not allow_multi_shell:
        failures.append(f"{components} shells; a printable part should be one shell")

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
    parser.add_argument("--json-out", help="Also write the report to this path.")
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    args = parser.parse_args(argv)
    if args.tolerance < 0:
        print("error: --tolerance must be >= 0", flush=True)
        return 1
    try:
        mesh = load_mesh(args.mesh, max_bytes=args.max_bytes)
        report = evaluate(
            mesh,
            target=None if args.size is None else tuple(args.size),
            tolerance=args.tolerance,
            allow_axis_swap=args.allow_axis_swap,
            allow_open=args.allow_open,
            allow_multi_shell=args.allow_multi_shell,
        )
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", flush=True)
        return 1
    report["file"] = str(Path(args.mesh).expanduser().resolve())
    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)
    if args.json_out:
        destination = Path(args.json_out).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text + "\n", encoding="utf-8")
    if report["failures"]:
        print("FAILED: " + "; ".join(report["failures"]), flush=True)
        return 2
    print("ok", flush=True)
    return 0
