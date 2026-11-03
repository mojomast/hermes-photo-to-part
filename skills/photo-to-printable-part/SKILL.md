---
name: photo-to-printable-part
description: >-
  skill_view("photo-to-part:photo-to-printable-part"). That string is the
  whole skill id. Do not add a plugin: prefix.
  photo-to-part:photo-to-printable-part. Rebuild a physical part as a
  printable STL or 3MF from photos and a few measurements, or turn a messy
  scan into a clean solid. Use for a replacement part, a fit-test print, an
  STL, a 2 mm grid-paper photo, or a scan cleaned into CAD. Call the
  photo_part_* tools. Read next_step. About 40 tool calls in total. Deliver
  as soon as validate passes.
version: "0.1.10"
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

skill_view("photo-to-part:photo-to-printable-part")

The skill id is exactly `photo-to-part:photo-to-printable-part`. Load that
exact id with `skill_view("photo-to-part:photo-to-printable-part")`. Copy it
exactly. It has no plugin: prefix.
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
photo-measurement, perspective, overlay, or checker script. Check
`photo_part_template` shapes before any custom code, and before importing a
CAD library: plate_clip, plate,
countersink, revolve, ribs, l_bracket, hinge, thread, knurl, sweep, hex_screw,
hex_standoff, bottle_cap, spur_gear, scroll, strap_hinge. Do not import
build123d or cadquery. If a build fails because one of those is missing, do
not install it and do not patch the environment. Use the template the error
names (for example strap_hinge) and the trimesh/manifold path below. A custom solid is a `.py` file run only by
`photo_part_build`. That tool uses the plugin interpreter. The path is the
`interpreter` field. It is the unresolved Hermes venv `bin/python` when one
matches this process, otherwise the Python running the tool. The script can
import the same solids the template uses:

```python
from photopart.features import external_thread, internal_thread, knurl, revolve_profile, sweep_path, hex_screw, hex_standoff, spur_gear, spiral_scroll, strap_hinge, tag_faces
```

`tag_faces(mesh, thread=indices, knurl=indices, path=stl)` writes
`<stl>.faces.json` so the wall check skips those faces. `external_thread`,
`knurl`, and the other helpers tag their own faces, and exporting the mesh
to a path writes that sidecar. Do not leave a script-built thread untagged.

Each call returns one watertight trimesh, in millimetres. `spur_gear(module, teeth, pressure_angle=20, face_width, bore=None)` is an involute gear: tip diameter `module * (teeth + 2)`, root diameter `module * (teeth - 2.5)`, optional keyway or D-flat, optional hub. `spiral_scroll(width, thickness, turns, end_radius, kind="archimedean")` is a spiral strip (`kind` `log` is the other). `strap_hinge` attaches one or two of those scrolls to a strap. `photo_part_build`
unions overlapping shells and reports `shells_before` and `shells_after`.
On failure the `error` field is the exception, not a status sentence.

The method is inspired by Michael Lydick's video
[I'm an Engineer. This ChatGPT Test Scared Me.](https://www.youtube.com/watch?v=TUqScwjnO_k)
The sample is a generic plate. Write files into the user's project. Paths
must be absolute. Do not write under `$HERMES_HOME/cache`. Do not edit the
installed plugin.

## Order

About 40 tool calls in total. Don't read the plugin's source or evals. Use the tools' help/params outputs. Batch independent calls. Deliver as soon as validate passes. Pass `calls_used` (tool calls already used in the session, including `skill_view`) on every photo_part_* call. Hermes v0.21.7 does not put a call counter on the plugin context. It does pass `session_id`. When that session is on disk, the count is read from `$HERMES_HOME/state.db` and from JSON/JSONL files under `$HERMES_HOME/sessions`. The larger of the session count and `calls_used` wins. `PHOTO_PART_MAX_CALLS` overrides the default cap of 40. When both are omitted, `budget.remaining` is estimated high. At about 60% and about 80% of the cap, `next_step` starts with `Budget: deliver now.` Past 80%, a `photo_part_render` without `final` is refused, and a repeat `photo_part_validate` of a file that already passed is refused. The message is `Budget: deliver <file> now; render refused.` The validate of a file that does not yet have a fresh passing sidecar, a checklist `--answer`, and a render with `final` true still run.

The whole job is one measure only if the photo has a coin or ruler, one template or one build, one validate, then stop. A failed build may be fixed once. Read each JSON `next_step` and do that. Do not spend the whole 40 turns. Do not explore, install, or re-render. Do not open `features.py`, `parts.py`, `launcher.py`, `evals/`, or `tests/`. `photo_part_template` and `photo_part_build` with `help` or `describe` true return the shape parameters and a minimal example script.

Do not write probe scripts. Read `bodies`, `bores`, and `sections_mm2` on the template or build result. A passing `photo_part_validate` that was given a spec writes the sheet and, when the last measure step recorded a photo, the overlay, in that same call. Do not re-render just to draw the overlay. `photo_part_render` is for an extra or final render. Every result includes `budget`.

1. Write `spec.json` from the user's numbers before any modelling or measuring: bbox (`x`, `y`, `z`) and the key features (shells, hole count, knuckle count, diameters). Check dimensions. Reject impossible geometry, such as a countersink deeper than the sheet. A single flat photo cannot show thickness or depth. Say which of those are unobserved. Ask the user or mark them assumed. Do not copy an in-plane width into thickness.
2. `photo_part_measure` only when the photo has a coin or ruler. Keep its JSON. Pass it to render so the coin is excluded. Skip this call when there is no reference.
3. `photo_part_template` first. If you must script, one `photo_part_build` with an absolute project `cwd`. The template names the file `<shape>_v1.stl` (or the `part` slug from spec.json). plate_clip stays `plate_clip.stl`. If the script fails, fix it once and build again, then stop editing.
4. One `photo_part_validate` of that file, passing `spec.json`. Keep every check the template emitted. Use one photo_part_validate and one photo_part_render per version.
5. One `photo_part_render` of that same file, and only after that validate. A render of `name_vN` with no fresh sidecar is refused (`unvalidated: true`). Look at `contact.png` once. The deliver render sets `final` true.
6. Deliver the best validated `name_vN` only when validate `ok` is true and `stale_validation` is not true. `next_step` says stop when every check passed. If a later version scores worse, it says revert to the better `name_vK`. Stop.

Write `name_vN.stl`. Never overwrite a file. Never `rm`, unlink, or otherwise delete an STL or 3MF, including one you just wrote. The next edit is a new version. Template and heal refuse to replace an existing file unless `--overwrite`. When a tool does replace a file, it keeps the previous bytes in `.p2p_history/` next to it. If `name_vN` is written and `name_v(N-1)` is missing, the JSON lists it under `missing_earlier`. Do not delete that older file to hide the gap.

## Tools

| Tool | Job |
| --- | --- |
| `photo_part_template` | Shapes above, including thread, knurl, sweep, hex_screw, hex_standoff, bottle_cap, spur_gear, scroll, and strap_hinge. Absolute `out_dir`. Returns `interpreter`. |
| `photo_part_build` | One local `.py` with the plugin interpreter. Unions overlapping shells. Timeout, no shell. |
| `photo_part_validate` | Watertight, shells, box, holes, printability, and `spec.json` or `--dim`. Writes a `score`. The only sidecar is `<file>.validate.json`. A new run appends the previous record to `history`. |
| `photo_part_render` | Fitted views, an eight-view `sheet.png` (previous in red, new in green), and a silhouette overlay. `overlay_fit auto` tries front, side, and top at 15° then 1°, plus a mirror, and reports rotation, mirror, view, `overlay_poses`, and the top 3 poses. GrabCut uses `--roi` or `--seed`. An angled photo is still scored with `overlay_iou_label` `guide_only`. A render of `name_vN` with no fresh sidecar is refused (`unvalidated: true`). `final` delivers the best validated version. `stale_validation` when the hash differs. |
| `photo_part_heal` | Weld and fill. `--union` merges overlapping shells. `--engine meshfix` tries PyMeshFix when it is installed. |
| `photo_part_measure` | px/mm, `reference_bbox` for the coin, ruler, or ArUco/AprilTag marker, `plane` and `uncertainty_mm`, absolute paths. |

`--size` is millimetres after `--units` or `--scale`. The default treats file numbers as millimetres and does not guess. A longest side under 1 mm or over 2 m fails (`ok: false`) unless `allow_size` is set. If you already passed `--units m` and the part is still implausible, drop `--units`. Do not pass it again.

A print-in-place part (the hinge template has 2 shells) needs `expected_shells`. `allow_multi_shell` accepts any count. `expected_shells` wins and checks the exact count.

`holes` is a list of `{x, y, diameter}` in millimetres, `axis` optional (default `z`).

`--photo-scale` is pixels per millimetre. It writes `overlay.png` (the silhouette contour, not facet edges), `overlay_diff.png`, and `overlay_iou`. `overlay_fit: auto` tries front, side, and top. Rotation is searched at 15°, then at 1°, and a mirror is tried too. The JSON reports `overlay_rotation_deg`, `overlay_mirror`, `overlay_view`, and `overlay_poses` (each view's best pose, winner first). It can still lock onto the largest object, such as a coin. Pass `--roi x,y,w,h` or `--seed x,y`, and the measure JSON or `--exclude-roi`. The JSON names that blob. If the ROI meets the silhouette edge, it is expanded and the JSON warns. If `overlay_iou` is below 0.5, the JSON warns. An angled photo is not skipped: the fit still runs and `overlay_iou_label` is `guide_only`, because perspective can move the outline. Say that the number is a guide, not a measurement, unless `photo_part_measure` rectified the photo. Do not write an overlay script.

`response_format` is `concise` or `detailed` on every tool. The default is concise. Errors lead with `cause` and one `fix`.

`spec.json` can list yes/no `features` such as `5 knuckles`, `teardrop`, and `scroll ends`. The first validate freezes that checklist. A later edit needs `--reason`, and the reason is in the report. Do not drop a feature to make the mesh pass.

`photo_part_validate --spec spec.json` fails when the mesh drifts from that file, and fails when a check the template wrote is missing from the spec. It also reports min wall, overhang past 45 degrees, bed contact, and the gap between bodies (warn under 0.3 mm per side). `--dim name=value±tol` is the same check for `x`, `y`, `z`, `shells`, `knuckles`, or `hole_count`. Knuckles use `knuckle_axis` (default `x`). The probe samples between the pin and the knuckle wall, so do not delete a knuckle check. Hole count is the circular bore count, not the genus and not the knuckle count. Genus counts handles and is reported beside the bore count. The only validation file is `<file>.validate.json`. Each run keeps the previous record in `history`. Do not pass a second path such as `model.validate.json`.

`photo_part_heal` reports `fan_requested`, `fan_used`, and `fan_fallback`. `shells_dropped` counts input shells only. `union_applied` is true when `--union` merged shells. Caps are flat. Read `references/scan-cleanup.md` in scan mode.

Load a reference only when that step needs it: `references/cad-backends.md`, `references/print-tolerances.md`, `references/feedback-and-scale.md`, `references/scan-cleanup.md`.

## Fit

Send `contact.png`. Ask them to print and compare side by side and stacked. Do not claim the part passed a fit test unless the user said the stacked print matches. A render is not acceptance.

Change named parameters, then one validate and one render of the new `name_vN.stl`. Say what changed. If the user says to skip a file, leave it on disk. Do not delete a file the user told you to skip.

Model the measured nominal size. Add clearance only on mating faces. See `references/print-tolerances.md`. Thickness and depth that a flat photo cannot show stay marked assumed.

## Deliver

The last two calls are `photo_part_validate` of the exact file you will deliver (with `spec.json`), then one `photo_part_render` of that file with `final` true. Any render of a `name_vN` with no fresh `<file>.validate.json` is refused (`unvalidated: true`). If `stale_validation` is true, or validate `ok` is false, do not deliver. List spec deviations in the final answer: every validate failure, including a template check removed from `spec.json`. Do not ship a file that failed the spec.

STL or 3MF, STEP only if they asked, the parametric source, a parameter table (name, millimetres, source, and which values were assumed), the version log, `spec.json`, and `<file>.validate.json`. STL has no units. Tell the slicer the file is millimetres.
