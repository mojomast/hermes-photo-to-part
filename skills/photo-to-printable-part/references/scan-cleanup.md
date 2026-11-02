# Scan cleanup

Load this in scan mode, before rebuilding the solid.

## What the helper does

```bash
python <SKILL_DIR>/scripts/heal_scan.py scan.stl --out healed.stl
```

The script copies the mesh, welds vertices, drops degenerate and duplicate faces, fixes normals, and fills boundary holes. The default second pass uses a triangle fan if the first pass left the mesh open. It then keeps the shell with the most triangles.

The JSON report has `before` and `after` triangle counts, `fan_used`, and `shells_dropped`. Exit `0` means the result is watertight. Exit `2` means it is still open.

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
