---
name: photo-to-printable-part
description: >-
  Skill id: photo-to-part:photo-to-printable-part. Do not prefix it with plugin:.
  Rebuild a physical part as a printable STL or 3MF, or an editable STEP solid,
  from photos and a few measurements, or turn a messy 3D scan into a clean solid.
  Use when the user wants a replacement part, a fit-test print, an STL, a 2 mm
  grid-paper photo, or a scan cleaned into CAD. Call the photo_part_* tools.
version: "0.1.2"
author: mojomast
license: MIT
compatibility: >-
  Python 3.11+. trimesh and manifold3d are already installed in the plugin
  environment. A STEP solid needs CadQuery or build123d in the project
  environment; that install downloads packages and can take several minutes.
metadata:
  hermes:
    tags: [cad, 3d-printing, stl, scan, fabrication]
    category: fabrication
    related_skills: []
---

# Photo or scan to printable part

The skill id is `photo-to-part:photo-to-printable-part`. Load that exact id.
`plugin:photo-to-part:photo-to-printable-part` is not a skill name. A `plugin:`
prefix in Hermes docs is a placeholder, not part of this id.

trimesh and manifold3d are already installed. Do not search for them, do not
pip install them, and do not run sudo apt. Do not search for OpenSCAD or
CadQuery unless the user asked for a STEP file. That install is in
`references/cad-backends.md`. It downloads packages and can take several minutes.

Always call the photo_part_* tools. Do not call the scripts under `scripts/`
from Hermes. Those scripts are for a person at a shell. Do not write a
photo-measurement, perspective, overlay, or checker script.

The method is inspired by Michael Lydick's video
[I'm an Engineer. This ChatGPT Test Scared Me.](https://www.youtube.com/watch?v=TUqScwjnO_k)
The sample is a generic plate, not the object in that video. Write files into
the user's project. Do not edit the installed plugin.

## Order

Finish well within 40 turns.

1. Check the user's dimensions before modelling. Reject impossible geometry, such as a countersink deeper than the sheet or a hole wider than the part. Ask instead of building it.
2. Build once, with `photo_part_template` or a short solid. A handful of edits, then stop editing.
3. One `photo_part_validate`. Use one photo_part_validate and one photo_part_render per version.
4. One `photo_part_render`. Look at `contact.png` with one image-analysis call, not one call per view.
5. Report the JSON and stop.

Scale comes from `photo_part_measure` (a coin or a ruler). Coin diameters, and when to skip an angled overlay, are in `references/feedback-and-scale.md`.

## Tools

| Tool | Job |
| --- | --- |
| `photo_part_template` | `shape`: plate_clip (default), plate, countersink, revolve, ribs, l_bracket, hinge. |
| `photo_part_validate` | Watertight, shell count, bounding box, optional holes. |
| `photo_part_render` | Fitted views, side-by-side, silhouette overlay. |
| `photo_part_heal` | Weld and fill a scan. `--union` merges overlapping shells. |
| `photo_part_measure` | px/mm from a coin or ruler. Optional 4-point rectified image. |

`--size` is millimetres after `--units` or `--scale`. The default treats file numbers as millimetres and does not guess. A longest side under 1 mm or over 2 m fails (`ok: false`) unless `allow_size` is set. If you already passed `--units m` and the part is still implausible, drop `--units`. Do not pass it again.

A print-in-place part (the hinge template has 2 shells) needs `expected_shells`. `allow_multi_shell` accepts any count. `expected_shells` wins and checks the exact count.

`holes` is a list of `{x, y, diameter}` in millimetres, `axis` optional (default `z`).

`--photo-scale` is pixels per millimetre. It writes `overlay.png` (the silhouette contour, not facet edges), `overlay_diff.png`, and `overlay_iou`. `overlay_fit: auto` aligns that contour to a straight-on photo. Do not write an overlay script. Skip the overlay on an angled photo unless `photo_part_measure` rectified it, and say why: perspective puts the outline off the part.

`photo_part_heal` reports `fan_requested`, `fan_used`, and `fan_fallback`. `shells_dropped` counts input shells only. `union_applied` is true when `--union` merged shells. Caps are flat. Read `references/scan-cleanup.md` in scan mode.

Load a reference only when that step needs it: `references/cad-backends.md`, `references/print-tolerances.md`, `references/feedback-and-scale.md`, `references/scan-cleanup.md`.

## Fit

Send `contact.png`. Ask them to print and compare side by side and stacked. Do not claim the part passed a fit test unless the user said the stacked print matches. A render is not acceptance.

Change named parameters, then one validate and one render. Say what changed. If the user says to skip a file, leave it on disk. Do not delete a file the user told you to skip.

Model the measured nominal size. Add clearance only on mating faces. See `references/print-tolerances.md`.

## Deliver

STL or 3MF, STEP only if they asked, the parametric source, a parameter table (name, millimetres, source), the version log, and the latest validate JSON. STL has no units. Tell the slicer the file is millimetres.
