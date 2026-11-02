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


def heal_mesh(
    mesh: trimesh.Trimesh,
    *,
    use_fan: bool = False,
    keep_largest: bool = True,
) -> tuple[trimesh.Trimesh, dict]:
    """Return a repaired copy and a before/after report. The input is unchanged."""
    before = measure(mesh)
    repaired = mesh.copy()
    repaired.merge_vertices()
    keep = repaired.unique_faces() & repaired.nondegenerate_faces()
    repaired.update_faces(keep)
    repaired.remove_unreferenced_vertices()
    repair.fix_normals(repaired, multibody=True)
    fan_used = False
    if not repaired.is_watertight:
        repair.fill_holes(repaired, use_fan=use_fan)
        fan_used = use_fan
    if not repaired.is_watertight and not use_fan:
        repair.fill_holes(repaired, use_fan=True)
        fan_used = True
    dropped_shells = 0
    if keep_largest:
        parts = repaired.split(only_watertight=False)
        if len(parts) > 1:
            repaired = max(parts, key=lambda item: len(item.faces)).copy()
            dropped_shells = len(parts) - 1
    after = measure(repaired)
    report = {
        "before": before,
        "after": after,
        "fan_used": fan_used,
        "shells_dropped": dropped_shells,
        "note": (
            "Hole caps are flat fans. Rebuild curved regions as a CAD solid; "
            "do not treat a healed scan as the finished part."
        ),
    }
    return repaired, report


def main(argv: list[str] | None = None) -> int:
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
    args = parser.parse_args(argv)
    out_path = Path(args.out).expanduser().resolve()
    in_path = Path(args.mesh).expanduser().resolve()
    if out_path == in_path:
        print("error: --out must be a different file from the input", flush=True)
        return 1
    if out_path.exists() and not args.force:
        print(f"error: {out_path} exists. Pass --force to overwrite.", flush=True)
        return 1
    try:
        mesh = load_mesh(in_path, max_bytes=args.max_bytes)
        repaired, report = heal_mesh(
            mesh, use_fan=args.fan, keep_largest=not args.keep_all
        )
        export_stl(repaired, out_path, ascii_stl=args.ascii)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", flush=True)
        return 1
    report["input"] = str(in_path)
    report["output"] = str(out_path)
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["after"]["watertight"]:
        print("ok", flush=True)
        return 0
    print(
        "healed mesh is still open. Rebuild the part as a solid, "
        "or try --fan knowing the caps will be flat.",
        flush=True,
    )
    return 2
