# CAD backends

Load this when choosing a kernel or when a boolean or export fails.

All parameters stay in millimetres. Pin the version in a comment at the top of the script. Write the script into the user's project.

## Which one

| Need | Use |
| --- | --- |
| STEP for Fusion 360 or another CAD tool, fillets, a real solid | CadQuery or build123d (Open CASCADE) |
| A prism, a plate, or holes, and STL or 3MF is enough | OpenSCAD, or the plugin's Shapely/trimesh template |
| The checked sample plate | `scripts/make_template.py` |

OpenSCAD exports STL, OFF, AMF, and 3MF. It does not export STEP and it has no fillet operator. CadQuery and build123d both export STEP and STL from one script. CadQuery's API has been stable longer. build123d's API has moved between releases, so a pin matters more there. The Druckworks comparison (accessed 2026-11-02) is a clear current write-up of that split: https://druckworks.eu/guides/openscad-or-build123d-with-ai

Do not add CadQuery, build123d, or OpenSCAD to the Hermes environment just to preview. Install one of them in the working environment when the user actually wants that solid.

## Sketch

CadQuery:

```python
import cadquery as cq
height_mm = 60.6
part = cq.Workplane("XY").box(51, height_mm, 6)
cq.exporters.export(part, "part.step")
cq.exporters.export(part, "part.stl")
```

build123d:

```python
from build123d import Box, export_step, export_stl
part = Box(51, 60.6, 6)
export_step(part, "part.step")
export_stl(part, "part.stl")
```

OpenSCAD:

```bash
openscad -o part.stl part.scad
```

Confirm the real calls against the pinned version. Selectors and export names drift.

## Booleans and manifold meshes

Exact coplanar faces make a boolean look successful in the kernel and then tessellate into non-manifold edges. Overlap joining pieces by about 0.1 mm so the intersection is real. The plugin template overlaps its hook into the plate by `hook_overlap_mm` (default 2) for the same reason.

A solid that the kernel calls valid can still export an STL that `trimesh` says is open. Always run:

```bash
python <SKILL_DIR>/scripts/export_validate.py part.stl --size <X> <Y> <Z>
```

## File formats

- **STL** is the slicer default. It stores triangles and no units. Say "millimetres" when you hand it over.
- **3MF** stores the unit. The 3MF Core Specification 1.3 requires a model mesh to have manifold edges, consistent orientation, and outward normals. The plugin writes `unit="millimeter"` when `lxml` is installed. https://3mf.io/specification/
- **STEP** keeps exact faces. That is the file to open in Fusion 360 when they want an editable solid. STL will come in as a mesh.

## The sample plate

`plate_clip` is a tapered plate, a top hook, and one slot. Change its JSON parameters, or throw the profile away and keep only the pattern: named millimetre parameters, an exported mesh, and `export_validate.py`. Do not present it as a replica of a commercial clip.
