# Changelog

## 0.1.3 — 2026-11-02

- `--roi`, `--seed`, and `--exclude-roi` choose the part for `--overlay-fit auto`. A `photo_part_measure` JSON supplies the coin or ruler box. The JSON names the blob that was used and warns when IoU is below 0.5 or the photo is angled.
- `photo_part_validate` writes `<file>.validate.json` with the mesh hash. Render and validate set `stale_validation` when the file no longer matches that sidecar. Template and heal refuse to replace an existing output unless `--overwrite` (`--force` still works).
- `photo_part_build` runs one local `.py` file with the plugin interpreter, a working directory, a timeout, and captured output. It does not start a shell. The interpreter path is in the JSON from template and build.
- Template and measure default to the working directory, refuse `$HERMES_HOME/cache`, and return absolute paths.
- Every tool description starts with `photo-to-part:photo-to-printable-part`, and every JSON result has `next_step` for measure, template or build, validate, render, deliver. The skill tells the agent to stay under 25 calls, to write `name_vN.stl` and not overwrite it, and to mark thickness or depth from a single flat photo as unobserved.
- Hermes still cannot register a skill name that contains a colon, so the mistaken `plugin:` id is not an alias. The description is what `skills_list` shows.

## 0.1.2 — 2026-11-02

- Helper scripts exec the venv `bin/python` symlink instead of the base interpreter it points at, so `python3 scripts/*.py` keeps the plugin's site-packages.
- The overlay is the silhouette contour of the z-buffer mask. `--overlay-fit auto` aligns it to the part in a straight-on photo and reports `overlay_iou` plus `overlay_diff.png`.
- A mesh that is open because of non-manifold edges or degenerate faces says so, with counts, and points at `photo_part_heal`. An implausible size (under 1 mm or over 2 m) fails validation and heal unless `--allow-size`. A warning names units that were already applied.
- `--expected-shells N` accepts a print-in-place part. `--holes` checks hole position and diameter.
- `photo_part_template` builds a plate with holes, a countersink, a revolved profile, radial ribs, an L-bracket, and a print-in-place hinge, on trimesh and manifold3d.
- `photo_part_measure` returns pixels per millimetre from a coin or a ruler, and can rectify a four-point quad. `photo_part_heal --union` merges overlapping shells.
- The skill id `photo-to-part:photo-to-printable-part` is the first line of the description `skills_list` shows. A colon alias is not registered, because Hermes skill names cannot contain a colon. The instructions say to call the tools, not the scripts, and to stop well within 40 turns.

## 0.1.1 — 2026-11-02

- Register `photo_part_validate`, `photo_part_render`, `photo_part_heal`, and `photo_part_template`. Hermes runs them inside the plugin environment, so a check no longer depends on system Python.
- Helper scripts re-exec into that environment when the current Python cannot import trimesh. They do not ask you to pip install into an externally managed interpreter.
- Document the skill id as `photo-to-part:photo-to-printable-part`. `plugin:photo-to-part:photo-to-printable-part` is not a skill name.
- Checker stdout is one JSON object. `ok` and `FAILED` go to stderr.
- `--units` and `--scale` convert a mesh to millimetres. Sizes under 1 mm or over 2 m warn, and nothing is rescaled automatically. Renders fit the frame to the part.
- Previews quadric-decimate above 8,000 faces and rasterize with a z-buffer, so a scan is not a sprinkle of dropped faces and a flat face does not streak.
- The front view uses the longest axis as up. `--up` and `--front-axis` override it.
- `--photo-scale` (pixels per millimetre) draws an outline overlay on the reference photo. The skill tells the agent to use it instead of writing a script.
- Heal reports `fan_requested`, `fan_used`, and `fan_fallback` separately. `shells_dropped` counts input shells only. Pieces created by the repair are `repair_fragments_removed`.
- The skill states a per-version tool budget, says not to delete a file the user skipped, and says not to claim a fit test the user did not accept.
- A STEP solid still needs CadQuery or build123d in the project environment. The install is pinned, it downloads packages, and it can take several minutes.

## 0.1.0 — 2026-11-02

- First public release of the photo-to-part Hermes plugin.
- Skill `photo-to-printable-part`: rebuild a part from photos and measurements, or clean up a scan, and iterate with fit tests.
- Helper scripts for a parametric sample plate, watertightness and bounding-box checks, orthographic previews, and scan healing.
- Local only. No network calls, credentials, telemetry, or printer connection.
