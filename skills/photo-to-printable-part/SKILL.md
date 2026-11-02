---
name: photo-to-printable-part
description: >-
  photo-to-part:photo-to-printable-part. Do not prefix it with plugin:.
  Rebuild a physical part as a printable STL or 3MF from photos and a few
  measurements, or turn a messy scan into a clean solid. Use for a replacement
  part, a fit-test print, an STL, a 2 mm grid-paper photo, or a scan cleaned
  into CAD. Call the photo_part_* tools. Read next_step. Stay under 25 calls.
version: "0.1.3"
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
prefix in Hermes docs is a placeholder, not part of this id. Hermes has no
alias that registers that string: a skill name cannot contain a colon.

trimesh and manifold3d are already installed. Do not search for them, do not
pip install them, and do not run sudo apt. Do not search for OpenSCAD or
CadQuery unless the user asked for a STEP file. That install is in
`references/cad-backends.md`. It downloads packages and can take several minutes.

Always call the photo_part_* tools. Do not call the scripts under `scripts/`
from Hermes. Those scripts are for a person at a shell. Do not write a
photo-measurement, perspective, overlay, or checker script. Try
`photo_part_template` shapes before any custom code: plate_clip, plate,
countersink, revolve, ribs, l_bracket, hinge. A custom solid is a `.py` file
run only by `photo_part_build`. That tool uses the plugin interpreter. The
path is the `interpreter` field. It is the unresolved Hermes venv `bin/python`
when one matches this process, otherwise the Python running the tool.

The method is inspired by Michael Lydick's video
[I'm an Engineer. This ChatGPT Test Scared Me.](https://www.youtube.com/watch?v=TUqScwjnO_k)
The sample is a generic plate. Write files into the user's project. Paths
must be absolute. Do not write under `$HERMES_HOME/cache`. Do not edit the
installed plugin.

## Order

Stay under 25 tool calls. Read each JSON `next_step` and do that. Do not spend the whole 40 turns.

1. `photo_part_measure` when the photo has a coin or ruler. Keep its JSON. Pass it to render so the coin is excluded.
2. Check dimensions before modelling. Reject impossible geometry, such as a countersink deeper than the sheet. A single flat photo cannot show thickness or depth. Say which of those are unobserved. Ask the user or mark them assumed. Do not copy an in-plane width into thickness.
3. `photo_part_template` first. If you must script, `photo_part_build` with an absolute project `cwd`. Write `name_v1.stl`.
4. One `photo_part_validate` of that file. Use one photo_part_validate and one photo_part_render per version.
5. One `photo_part_render` of that same file. Look at `contact.png` once.
6. Deliver that file only when `stale_validation` is not true. Stop.

Write `name_vN.stl`. Never overwrite a file. The next edit is a new version. Template and heal refuse to replace an existing file unless `--overwrite`.

## Tools

| Tool | Job |
| --- | --- |
| `photo_part_template` | Shapes above. Absolute `out_dir`. Returns `interpreter`. |
| `photo_part_build` | One local `.py` with the plugin interpreter. Timeout, no shell. |
| `photo_part_validate` | Watertight, shells, box, holes. Writes `<file>.validate.json` with the mesh hash. |
| `photo_part_render` | Fitted views and silhouette overlay. `stale_validation` when the hash differs. |
| `photo_part_heal` | Weld and fill. `--union` merges overlapping shells. |
| `photo_part_measure` | px/mm, `reference_bbox` for the coin or ruler, absolute paths. |

`--size` is millimetres after `--units` or `--scale`. The default treats file numbers as millimetres and does not guess. A longest side under 1 mm or over 2 m fails (`ok: false`) unless `allow_size` is set. If you already passed `--units m` and the part is still implausible, drop `--units`. Do not pass it again.

A print-in-place part (the hinge template has 2 shells) needs `expected_shells`. `allow_multi_shell` accepts any count. `expected_shells` wins and checks the exact count.

`holes` is a list of `{x, y, diameter}` in millimetres, `axis` optional (default `z`).

`--photo-scale` is pixels per millimetre. It writes `overlay.png` (the silhouette contour, not facet edges), `overlay_diff.png`, and `overlay_iou`. `overlay_fit: auto` can lock onto the largest object, such as a coin. Pass `--roi x,y,w,h` or `--seed x,y`, and the measure JSON or `--exclude-roi`. The JSON names that blob. If `overlay_iou` is below 0.5, or the photo is angled, the JSON warns. Do not write an overlay script. Skip the overlay on an angled photo unless `photo_part_measure` rectified it, and say why: perspective puts the outline off the part.

`photo_part_heal` reports `fan_requested`, `fan_used`, and `fan_fallback`. `shells_dropped` counts input shells only. `union_applied` is true when `--union` merged shells. Caps are flat. Read `references/scan-cleanup.md` in scan mode.

Load a reference only when that step needs it: `references/cad-backends.md`, `references/print-tolerances.md`, `references/feedback-and-scale.md`, `references/scan-cleanup.md`.

## Fit

Send `contact.png`. Ask them to print and compare side by side and stacked. Do not claim the part passed a fit test unless the user said the stacked print matches. A render is not acceptance.

Change named parameters, then one validate and one render of the new `name_vN.stl`. Say what changed. If the user says to skip a file, leave it on disk. Do not delete a file the user told you to skip.

Model the measured nominal size. Add clearance only on mating faces. See `references/print-tolerances.md`. Thickness and depth that a flat photo cannot show stay marked assumed.

## Deliver

The delivered file is the one you just validated and rendered. If `stale_validation` is true, do not deliver; validate that same file again. STL or 3MF, STEP only if they asked, the parametric source, a parameter table (name, millimetres, source, and which values were assumed), the version log, and `<file>.validate.json`. STL has no units. Tell the slicer the file is millimetres.
