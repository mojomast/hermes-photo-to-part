# Scan cleanup

Load this in scan mode, before rebuilding the solid.

## What the helper does

Prefer the `photo_part_heal` tool. The script form is:

```bash
python <SKILL_DIR>/scripts/heal_scan.py scan.stl --out healed.stl --units m
```

The healer copies the mesh, welds vertices, drops degenerate and duplicate faces, fixes normals, and fills boundary holes. If the first pass leaves the mesh open and `--fan` was not set, a second pass fan-fills the remaining holes and sets `fan_fallback` (and `fan_used`) to true. `fan_requested` is true only when `--fan` was passed. It then keeps the shell with the most triangles.

`shells_before` is the input shell count. `shells_dropped` counts input shells that were discarded. A one-shell input reports `shells_dropped: 0`. Pieces created by the repair and then discarded are `repair_fragments_removed`, not dropped input shells.

`--units` is `mm`, `cm`, `m`, or `in`. `--scale` is an extra multiplier. The output STL is millimetres after that conversion. With neither flag, file numbers are treated as millimetres and nothing is guessed. `unit_warning` is set when the longest side is under 1 mm or over 2 m. That warning fails the command (`ok: false`, exit 2) unless `--allow-size` is set. If `--units` was already applied and the part is still implausible, the warning says to drop that flag. `input_extents_file` is the size before conversion.

`--union` boolean-unions shells with manifold3d. Overlapping shells become one. Disjoint shells stay separate. `union_applied` says whether that union ran.

A validator line that names non-manifold edges or degenerate faces, including a mesh with zero boundary edges, is that cause. Run heal. Do not read "0 boundary edges" as the reason the solid failed to close.

Exit `0` means watertight and a plausible size. Exit `2` means still open, or an implausible size without `--allow-size`. Stdout is one JSON object. `ok` and `FAILED` go to stderr.

Limits, so you do not over-claim:

- Fan caps are **flat**. They are the wrong surface for a curved scan. `trimesh.repair.fill_holes` builds those caps from the boundary loop.
- This does not reconstruct a CAD solid and it does not report a face count in the CAD sense.
- Very large holes, self-intersections, and noise will survive. Say so in the report you give the user.

PyMeshLab is optional and not installed with the plugin. If they already have it, `meshing_close_holes`, `meshing_repair_non_manifold_edges`, and `meshing_remove_duplicate_vertices` are the usual filters. Screened Poisson (`generate_surface_reconstruction_screened_poisson`) rebuilds a surface from points and can invent thickness. Use it only when the user wants a new watertight shell, and still remodel the part afterwards. https://pymeshlab.readthedocs.io/

## Rebuild

After the heal, write a CadQuery or build123d solid of planes, cylinders, fillets, and recesses that match the healed mesh and the measurements. Do not deliver the triangle mesh as the editable model.

Report both numbers: triangles in the scan they handed you, and faces on the new solid (`len(solid.Faces())` in CadQuery, or the build123d equivalent for the pinned version). The video's example of this comparison was a flashlight scan of roughly 234,000 triangles rebuilt as a solid of 119 faces. That ratio is an illustration, not a target.

Then export STL or STEP and run `export_validate.py --size` against the overall measurements.

## 3MF manifold rule

If you write 3MF, the mesh should already pass the validator. The 3MF Core Specification 1.3 requires every edge to be shared by exactly two triangles, with consistent outward winding. https://3mf.io/specification/
