---
name: photo-to-printable-part
description: >-
  photo-to-part:photo-to-printable-part. Do not prefix it with plugin:.
  Rebuild a physical part as a printable STL or 3MF from photos and a few
  measurements, or turn a messy scan into a clean solid. Use for a replacement
  part, a fit-test print, an STL, a 2 mm grid-paper photo, or a scan cleaned
  into CAD. Call the photo_part_* tools. Read next_step. Stay under 25 calls.
version: "0.1.4"
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

The skill id is `photo-to-part:photo-to-printable-part`. Load that exact id
with `skill_view("photo-to-part:photo-to-printable-part")`.
`plugin:photo-to-part:photo-to-printable-part` is not a skill name. A `plugin:`
prefix in Hermes docs is a placeholder, not part of this id. Hermes has no
alias that registers that string: a skill name cannot contain a colon. Never
pass a `plugin:` id to `skill_view`.

trimesh and manifold3d are already installed. Do not search for them, do not
pip install them, and do not run sudo apt. Do not search for OpenSCAD or
CadQuery unless the user asked for a STEP file. That install is in
`references/cad-backends.md`. It downloads packages and can take several minutes.

Always call the photo_part_* tools. Do not call the scripts under `scripts/`
from Hermes. Those scripts are for a person at a shell. Do not write a
photo-measurement, perspective, overlay, or checker script. Try
`photo_part_template` shapes before any custom code: plate_clip, plate,
countersink, revolve, ribs, l_bracket, hinge, thread, knurl, sweep, hex_screw,
hex_standoff, bottle_cap. A custom solid is a `.py` file run only by
`photo_part_build`. That tool uses the plugin interpreter. The path is the
`interpreter` field. It is the unresolved Hermes venv `bin/python` when one
matches this process, otherwise the Python running the tool. The script can
import the same solids the template uses:

```python
from photopart.features import external_thread, internal_thread, knurl, revolve_profile, sweep_path, hex_screw, hex_standoff
```

Each call returns one watertight trimesh, in millimetres. `photo_part_build`
unions overlapping shells and reports `shells_before` and `shells_after`.
On failure the `error` field is the exception, not a status sentence.

The method is inspired by Michael Lydick's video
[I'm an Engineer. This ChatGPT Test Scared Me.](https://www.youtube.com/watch?v=TUqScwjnO_k)
The sample is a generic plate. Write files into the user's project. Paths
must be absolute. Do not write under `$HERMES_HOME/cache`. Do not edit the
installed plugin.

## Order

Stay under 25 tool calls. The whole job is one measure only if the photo has a coin or ruler, one template or one build, one validate, one render, then stop. A failed build may be fixed once. Read each JSON `next_step` and do that. Do not spend the whole 40 turns. Do not explore, install, or re-render.

1. Write `spec.json` from the user's numbers before any modelling or measuring: bbox (`x`, `y`, `z`) and the key features (shells, hole count, knuckle count, diameters). Check dimensions. Reject impossible geometry, such as a countersink deeper than the sheet. A single flat photo cannot show thickness or depth. Say which of those are unobserved. Ask the user or mark them assumed. Do not copy an in-plane width into thickness.
2. `photo_part_measure` only when the photo has a coin or ruler. Keep its JSON. Pass it to render so the coin is excluded. Skip this call when there is no reference.
3. `photo_part_template` first. If you must script, one `photo_part_build` with an absolute project `cwd`. Write `name_v1.stl`. If the script fails, fix it once and build again, then stop editing.
4. One `photo_part_validate` of that file, passing `spec.json`. Keep every check the template emitted. Use one photo_part_validate and one photo_part_render per version.
5. One `photo_part_render` of that same file, and only after that validate. A render of `name_vN` with no fresh sidecar is refused (`unvalidated: true`). Look at `contact.png` once. The deliver render sets `final` true.
6. Deliver that file only when validate `ok` is true and `stale_validation` is not true. Stop.

Write `name_vN.stl`. Never overwrite a file. Never `rm`, unlink, or otherwise delete an STL or 3MF, including one you just wrote. The next edit is a new version. Template and heal refuse to replace an existing file unless `--overwrite`. When a tool does replace a file, it keeps the previous bytes in `.p2p_history/` next to it. If `name_vN` is written and `name_v(N-1)` is missing, the JSON lists it under `missing_earlier`. Do not delete that older file to hide the gap.

## Tools

| Tool | Job |
| --- | --- |
| `photo_part_template` | Shapes above, including thread, knurl, sweep, hex_screw, hex_standoff, and bottle_cap. Absolute `out_dir`. Returns `interpreter`. |
| `photo_part_build` | One local `.py` with the plugin interpreter. Unions overlapping shells. Timeout, no shell. |
| `photo_part_validate` | Watertight, shells, box, holes, and `spec.json` or `--dim`. The only sidecar is `<file>.validate.json`. A new run appends the previous record to `history`. |
| `photo_part_render` | Fitted views and silhouette overlay. `overlay_fit auto` reports rotation, mirror, and view. A render of `name_vN` with no fresh sidecar is refused (`unvalidated: true`), including when `final` is set. `stale_validation` when the hash differs. |
| `photo_part_heal` | Weld and fill. `--union` merges overlapping shells. |
| `photo_part_measure` | px/mm, `reference_bbox` for the coin or ruler, absolute paths. |

`--size` is millimetres after `--units` or `--scale`. The default treats file numbers as millimetres and does not guess. A longest side under 1 mm or over 2 m fails (`ok: false`) unless `allow_size` is set. If you already passed `--units m` and the part is still implausible, drop `--units`. Do not pass it again.

A print-in-place part (the hinge template has 2 shells) needs `expected_shells`. `allow_multi_shell` accepts any count. `expected_shells` wins and checks the exact count.

`holes` is a list of `{x, y, diameter}` in millimetres, `axis` optional (default `z`).

`--photo-scale` is pixels per millimetre. It writes `overlay.png` (the silhouette contour, not facet edges), `overlay_diff.png`, and `overlay_iou`. `overlay_fit: auto` searches rotation and a mirror, then chooses front, side, or top. The JSON reports `overlay_rotation_deg`, `overlay_mirror`, and `overlay_view`. It can still lock onto the largest object, such as a coin. Pass `--roi x,y,w,h` or `--seed x,y`, and the measure JSON or `--exclude-roi`. The JSON names that blob. If `overlay_iou` is below 0.5, or the photo is angled, the JSON warns. Do not write an overlay script. Skip the overlay on an angled photo unless `photo_part_measure` rectified it, and say why: perspective puts the outline off the part.

`photo_part_validate --spec spec.json` fails when the mesh drifts from that file, and fails when a check the template wrote is missing from the spec. `--dim name=value±tol` is the same check for `x`, `y`, `z`, `shells`, `knuckles`, or `hole_count`. Knuckles use `knuckle_axis` (default `x`). The probe samples between the pin and the knuckle wall, so do not delete a knuckle check. Hole count is the genus, not the knuckle count. The only validation file is `<file>.validate.json`. Each run keeps the previous record in `history`. Do not pass a second path such as `model.validate.json`.

`photo_part_heal` reports `fan_requested`, `fan_used`, and `fan_fallback`. `shells_dropped` counts input shells only. `union_applied` is true when `--union` merged shells. Caps are flat. Read `references/scan-cleanup.md` in scan mode.

Load a reference only when that step needs it: `references/cad-backends.md`, `references/print-tolerances.md`, `references/feedback-and-scale.md`, `references/scan-cleanup.md`.

## Fit

Send `contact.png`. Ask them to print and compare side by side and stacked. Do not claim the part passed a fit test unless the user said the stacked print matches. A render is not acceptance.

Change named parameters, then one validate and one render of the new `name_vN.stl`. Say what changed. If the user says to skip a file, leave it on disk. Do not delete a file the user told you to skip.

Model the measured nominal size. Add clearance only on mating faces. See `references/print-tolerances.md`. Thickness and depth that a flat photo cannot show stay marked assumed.

## Deliver

The last two calls are `photo_part_validate` of the exact file you will deliver (with `spec.json`), then one `photo_part_render` of that file with `final` true. Any render of a `name_vN` with no fresh `<file>.validate.json` is refused (`unvalidated: true`). If `stale_validation` is true, or validate `ok` is false, do not deliver. List spec deviations in the final answer: every validate failure, including a template check removed from `spec.json`. Do not ship a file that failed the spec.

STL or 3MF, STEP only if they asked, the parametric source, a parameter table (name, millimetres, source, and which values were assumed), the version log, `spec.json`, and `<file>.validate.json`. STL has no units. Tell the slicer the file is millimetres.
