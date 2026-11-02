"""Close small holes and drop loose shells in a scan mesh.

This is a mesh prep step. A fan-filled hole is a flat cap, which is the wrong
shape for a curved scan. Rebuild the part as a CAD solid after this, and
report the scan's triangle count against the solid's face count.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import trimesh
from trimesh import repair

from photopart.geometry import export_stl
from photopart.io import DEFAULT_MAX_BYTES, load_mesh
from photopart.report import measure
from photopart.status import status
from photopart.units import add_unit_arguments, attach_units, prepare_mesh


def account_shells(shells_before: int | None, part_count: int) -> tuple[int, int]:
    """Split removed bodies into input shells and pieces the repair created.

    ``shells_dropped`` never counts a fragment that was not in the input.
    A one-shell input therefore reports ``shells_dropped`` 0 even if repair
    left an extra piece behind.
    """
    extra = max(0, int(part_count) - 1)
    if extra == 0:
        return 0, 0
    if shells_before is None:
        return 0, extra
    dropped = min(extra, max(0, int(shells_before) - 1))
    return dropped, extra - dropped


def heal_mesh(
    mesh: trimesh.Trimesh,
    *,
    use_fan: bool = False,
    keep_largest: bool = True,
) -> tuple[trimesh.Trimesh, dict]:
    """Return a repaired copy and a before/after report. The input is unchanged."""
    before = measure(mesh)
    shells_before = before["components"]
    repaired = mesh.copy()
    repaired.merge_vertices()
    keep = repaired.unique_faces() & repaired.nondegenerate_faces()
    repaired.update_faces(keep)
    repaired.remove_unreferenced_vertices()
    repair.fix_normals(repaired, multibody=True)
    fan_requested = bool(use_fan)
    fan_used = False
    fan_fallback = False
    if not repaired.is_watertight:
        repair.fill_holes(repaired, use_fan=use_fan)
        if use_fan:
            fan_used = True
    if not repaired.is_watertight and not use_fan:
        # The first pass skips holes larger than a quad unless a fan was requested.
        repair.fill_holes(repaired, use_fan=True)
        fan_used = True
        fan_fallback = True
    shells_dropped = 0
    repair_fragments_removed = 0
    if keep_largest:
        parts = repaired.split(only_watertight=False)
        shells_dropped, repair_fragments_removed = account_shells(shells_before, len(parts))
        if len(parts) > 1:
            repaired = max(parts, key=lambda item: len(item.faces)).copy()
    after = measure(repaired)
    note = (
        "Hole caps are flat fans. Rebuild curved regions as a CAD solid; "
        "do not treat a healed scan as the finished part."
    )
    if fan_fallback:
        note += (
            " fan_fallback is true because --fan was not set and the first fill left "
            "the mesh open, so a second pass fan-filled the remaining holes."
        )
    elif fan_requested:
        note += " fan_requested is true because --fan was set. Caps from that pass are flat."
    if repair_fragments_removed:
        note += (
            f" repair_fragments_removed is {repair_fragments_removed}: those pieces "
            "appeared during repair and are not counted in shells_dropped."
        )
    report = {
        "before": before,
        "after": after,
        "fan_requested": fan_requested,
        "fan_used": fan_used,
        "fan_fallback": fan_fallback,
        "shells_before": shells_before,
        "shells_dropped": shells_dropped,
        "repair_fragments_removed": repair_fragments_removed,
        "keep_largest": keep_largest,
        "note": note,
    }
    return repaired, report


def run_heal(argv: list[str] | None = None) -> tuple[int, dict]:
    parser = argparse.ArgumentParser(description="Heal a scan mesh and write a new STL.")
    parser.add_argument("mesh")
    parser.add_argument("--out", required=True, help="Output STL. Will not replace the input.")
    parser.add_argument("--force", action="store_true", help="Overwrite --out if it exists.")
    parser.add_argument("--ascii", action="store_true")
    parser.add_argument(
        "--fan",
        action="store_true",
        help="Fan-fill holes on the first pass. Caps are flat.",
    )
    parser.add_argument(
        "--keep-all",
        action="store_true",
        help="Keep every shell. The default keeps the shell with the most triangles.",
    )
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    add_unit_arguments(parser)
    args = parser.parse_args(argv)
    out_path = Path(args.out).expanduser().resolve()
    in_path = Path(args.mesh).expanduser().resolve()
    if out_path == in_path:
        return 1, {"ok": False, "error": "--out must be a different file from the input"}
    if out_path.exists() and not args.force:
        return 1, {"ok": False, "error": f"{out_path} exists. Pass --force to overwrite."}
    try:
        loaded = load_mesh(in_path, max_bytes=args.max_bytes)
        mesh, meta = prepare_mesh(loaded, args.units, args.scale)
        repaired, report = heal_mesh(
            mesh, use_fan=args.fan, keep_largest=not args.keep_all
        )
        export_stl(repaired, out_path, ascii_stl=args.ascii)
    except (OSError, ValueError) as exc:
        return 1, {"ok": False, "error": str(exc)}
    report["input"] = str(in_path)
    report["output"] = str(out_path)
    report["ok"] = bool(report["after"]["watertight"])
    attach_units(report, meta)
    if report["ok"]:
        return 0, report
    return 2, report


def main(argv: list[str] | None = None) -> int:
    code, report = run_heal(argv)
    print(json.dumps(report, indent=2, sort_keys=True))
    if code == 0:
        status("ok")
    elif report.get("error"):
        status(f"error: {report['error']}")
    else:
        status(
            "healed mesh is still open. Rebuild the part as a solid, "
            "or try --fan knowing the caps will be flat."
        )
    return code
