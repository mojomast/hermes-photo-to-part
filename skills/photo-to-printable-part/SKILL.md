---
name: photo-to-printable-part
description: >-
  Rebuild a physical part as a printable STL or 3MF, or an editable STEP solid,
  from photos and a few measurements, or turn a messy 3D scan into a clean solid.
  Use when the user wants a replacement part, a fit-test print, a resin or FDM
  model, an STL, STEP, or 3MF, caliper dimensions, a 2 mm grid-paper photo, a
  marked-up photo, or a scan cleaned up into CAD.
version: "0.1.1"
author: mojomast
license: MIT
compatibility: >-
  Python 3.11+. Mesh checks run as the photo_part_* tools inside the plugin
  environment. A STEP solid needs CadQuery or build123d in the project
  environment; that install downloads packages and can take several minutes.
metadata:
  hermes:
    tags: [cad, 3d-printing, stl, scan, fabrication]
    category: fabrication
    related_skills: []
---

# Photo or scan to printable part

Rebuild a part in code, then check it against the real object. Write every
version into the user's project. Do not edit the installed plugin.

The workflow is inspired by Michael Lydick's video
[I'm an Engineer. This ChatGPT Test Scared Me.](https://www.youtube.com/watch?v=TUqScwjnO_k)
It is a generic method, not a model of the object in that video.

The skill id is `photo-to-part:photo-to-printable-part`. Load that exact id.
`plugin:photo-to-part:photo-to-printable-part` is not a skill name. A `plugin:`
prefix in Hermes docs is a placeholder, not part of this id.

## Budget

Use one photo_part_validate and one photo_part_render per version.
Do not create a virtualenv, do not pip install trimesh, and do not write a
checker. Do not write an overlay script. The bundled tools are the tooling.
A turn spent rebuilding them is a turn that did not check the part.

Call the tools. They already run where trimesh is installed:

| Tool | Job |
| --- | --- |
| `photo_part_template` | Sample plate (STL, OpenSCAD, parameters). |
| `photo_part_validate` | Watertight, one shell, bounding box. |
| `photo_part_render` | Fitted views, side-by-side, outline overlay. |
| `photo_part_heal` | Weld and fill a scan. Caps are flat. |

If a shell is easier, `<SKILL_DIR>` is the directory of this `SKILL.md`:

```bash
python <SKILL_DIR>/scripts/make_template.py --out-dir ./part-v1
python <SKILL_DIR>/scripts/export_validate.py model.stl --size 60.6 51 6
python <SKILL_DIR>/scripts/render_views.py model.stl --out-dir ./renders --photo original.jpg --photo-scale 12.5 --grid-mm 2
python <SKILL_DIR>/scripts/heal_scan.py scan.stl --out healed.stl --units m
```

Those scripts re-exec into the plugin environment when system Python cannot
import trimesh. If that fails, call the tool. Do not pip install into the
system Python.

Stdout of each script is one JSON object. The words `ok` and `FAILED` go to
stderr, not stdout. Exit `0` passes, `2` means the mesh loaded but a check
failed, `1` means the command could not run.

`--size` is millimetres after `--units` or `--scale`. The default treats file
numbers as millimetres and does not guess. Pass `--units m`, `cm`, or `in`
when the file is not millimetres. A `unit_warning` is set when the longest
side is under 1 mm or over 2 m.

`--photo-scale` is pixels per millimetre. It writes `overlay.png` (the front
outline on the photo) and still writes the side-by-side. On 2 mm grid paper,
measure one square in pixels and divide by 2. Do not write an overlay script.

The front view uses the longest axis as up and looks along the shortest other
axis. Pass `up` (`x`, `y`, or `z`) when that guess is wrong. An upright peg
is tall on Z, so the front view is not always X–Y.

## 1. Gather inputs

Ask before building, and wait if a needed fact is missing.

- **Mode.** Replace: rebuild a broken part from photos. Scan cleanup: turn a mesh into a solid.
- **Output.** STL or 3MF for a slicer (say resin or FDM), and/or STEP when they will edit it in Fusion 360 or another CAD tool.
- **References.** Photos from several angles. Overall height, width, and thickness, plus mating features, from a caliper or micrometer. One straight-on photo of the part on **printed 2 mm grid paper** when they can take it.
- **Defects.** Cracks, glue, and wear are damage. The model copies them unless told they are not part of the design.

Load a reference only when that step needs it:

- `references/cad-backends.md` before choosing CadQuery, build123d, or OpenSCAD, and when a boolean fails.
- `references/print-tolerances.md` when they name resin, FDM, or a mating fit.
- `references/feedback-and-scale.md` when reading grid paper or a marked-up photo.
- `references/scan-cleanup.md` in scan mode.

## 2. Build version 1

Model the intended part, not the damage. Every measurement they gave becomes a named parameter in millimetres. Take remaining proportions from the photos and the grid. Smooth over cracks and glue.

`photo_part_template` writes a watertight sample plate with a hook and a slot (`plate_clip`). Use it only as a starting style for a flat clip-like part, then replace the profile with the real one. It is not the part from the video.

Prefer CadQuery or build123d when they want STEP or fillets. Use OpenSCAD for a prismatic STL or 3MF. Pin the tool version in a comment. Overlap boolean pieces by about 0.1 mm instead of letting faces lie exactly on top of each other. The pinned install lines are in `references/cad-backends.md`. That install downloads packages and can take several minutes. Do not describe it as offline, and do not install CadQuery or build123d into the Hermes environment.

Before you hand a file over, run `photo_part_validate` with `size` set to the stated overall dimensions (X Y Z millimetres). It must be watertight, one shell, positive volume, and inside the tolerance (default 0.3 mm). Loading an STL welds coincident vertices, because STL repeats them on every triangle. It does not fill holes. A kernel that says the solid is valid is not enough: check the exported mesh too.

In scan mode, run `photo_part_heal` first, then rebuild planes, cylinders, fillets, and recesses. Read `fan_requested`, `fan_used`, and `fan_fallback` before saying a fan was used. `fan_fallback` means `--fan` was not set and a second pass filled the holes that were still open. `shells_dropped` counts input shells only. If the input was one shell, `shells_dropped` is 0. Extra pieces created by the repair are `repair_fragments_removed`. Report CAD face count against the original triangle count. A healed mesh is not the finished solid. Details are in `references/scan-cleanup.md`.

## 3. Fit test

Run `photo_part_render`. Pass `photo` and `photo_scale` when you have a scale. Send front, side, top, iso, `overlay.png` when you drew one, and `compare_front.png` when a photo was passed. Ask them to print this version and compare it with the original **side by side and stacked**. Ask what is off.

Do not claim the part passed a fit test unless the user said the stacked print matches. A render is not acceptance.

## 4. Take feedback in the form that works

Ask in this order. Batch missed features into one rebuild.

1. **Marked-up photos.** Circles and labels such as "this should be a radius", "these are flat faces", "remove this".
2. **Hard dimensions.** For example, "the original is 60.6 mm tall by 51 mm wide; yours is bigger."
3. **Grid photo.** Original and print on 2 mm squares, straight on. Count squares. Estimate curves from the grid. One caliper size outranks the grid when they disagree.
4. **Missed features.** Ask whether anything else is missing before regenerating.

Change the named parameters, regenerate, run `photo_part_validate` again, and send new renders. Say what changed in this version, in a few lines.

If the user says to skip a file, leave it on disk. Do not delete a file the user told you to skip.

## 5. Repeat until it matches

Expect about 3 to 5 versions. Stop when they say the stacked print matches on the dimensions that matter. Do not claim the part passed a fit test on their behalf. Support marks from resin printing can be sanded off or avoided by moving supports. Those marks are not a reason to change the solid.

Model the measured nominal size. Add clearance only on mating faces, and say which faces changed. Do not scale the whole part for shrinkage unless they measured a systematic error. See `references/print-tolerances.md`.

## Deliverables

- The STL and/or 3MF, and a STEP file when they asked for an editable solid.
- The parametric source.
- A parameter table: name, millimetres, and where the number came from (caliper, grid count, or estimate).
- A version log of what changed in each round.
- The latest `photo_part_validate` JSON report.

## Pitfalls

- STL has no units. Tell the slicer the file is millimetres. Prefer 3MF when the slicer should read the unit itself (`lxml` is optional; STL does not need it).
- A pretty render can still be the wrong size. Trust `size` and the print, not the picture.
- Do not write an overlay script. Pass `photo_scale` to `photo_part_render`.
- Do not delete a file the user told you to skip.
- Do not claim the part passed a fit test unless the user said the stacked print matches.
- Fan-filled scan holes are flat caps. Rebuild curves in CAD.
- Do not invent a dimension. Mark it as an estimate and ask.
