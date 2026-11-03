# Changelog

## 0.1.11 — 2026-11-03

- `post_tool_call` counts every tool call in a session that has already used this plugin, and `transform_tool_result` adds one budget line at 60%, 80%, and 95% of the cap. The budget uses the larger of that hook count, the Hermes session record, `calls_used`, and this plugin's own counter. A session that has not used the plugin is unchanged. A hook error does not block the other tool.
- Opening a photo already passed to `photo_part_measure` with cv2 or PIL adds a note that names `part_seed` or `part_roi`. `PHOTOPART_BLOCK_PROBES=1` blocks that probe after three tries. The default is the note only.
- `pre_tool_call` rewrites this skill's own misspellings (`plugin:`, `plugins:`, a slash, or the bare name) to `photo-to-part:photo-to-printable-part`. Other skills are not rewritten. The original id is logged under `.photopart/calls.jsonl`.
- `photo_part_measure` can detect a coin (Hough circle refined by a round contour) and return `part_bbox_mm` from `auto`, `part_seed`, or `part_roi`, with `scale_uncertainty_pct`. `cad_loonie` is 26.5 mm. The sealed coin check is a synthetic stand-in: caliper photos are not in this repo.
- Thread, knurl, and tooth regions are stored as a cylinder (axis, radius, height, pitch) and re-resolved after a boolean. If a script exports none, a periodic crest is detected and written to `<stl>.faces.json`. A 0.3 mm flange beside a thread still warns.
- `python -m evals.runner --hermes-session` reads a Hermes `tool_call` wrapper (`calls: [...]`), minutes from `state.db` timestamps, and leak paths inside tool arguments, including the eval canary.
- Overlay JSON names `segmentation_confidence`. Fit adds IoU, boundary IoU, chamfer, and HD95. `overall_confidence` is the lower of segmentation and fit. `confidence` is still the segmentation value.
- `photopart/standards.py` warns when a named fastener or a 608 bearing disagrees with a cited size (ISO 261/262, ISO 4017, ISO 4762, ISO 4032, ISO 4162 M5–M8 flange diameter, ASME B1.1 UNC, ISO 15 / SKF 608). It never edits the spec. ISO 273 clearance holes and catalogue M3 flange diameters are omitted.
- Evals stay in this repository rather than a `plugin/` subdirectory, because that move would break `hermes plugins install mojomast/hermes-photo-to-part`. Eval text files carry a canary string so a session that reads them is scored as a leak.

## 0.1.10 — 2026-11-03

- A per-hole probe that disagrees with the bore detector, or whose votes are split, is a warning. The row keeps both the probe and the bore. The warning does not fail validation and does not block delivery.
- The call budget reads Hermes v0.21.7 session records. `PluginContext` has no counter. The dispatcher passes `session_id`, and the count comes from `$HERMES_HOME/state.db` (`messages.tool_calls`) and from JSON/JSONL files under `$HERMES_HOME/sessions`. `calls_used` is the fallback the agent passes. The larger of the session count and `calls_used` wins, and a session count is not capped. Past 80% of the cap, a non-final `photo_part_render` and a repeat validate of a file that already passed are refused with `Budget: deliver <file> now`. The first validate of a file, a checklist answer, and a render with `final` still run.
- A build script that imports build123d, cadquery, or OCP when it is not installed names the libraries that are available, points at the matching template (for example `strap_hinge`), and says to use the trimesh/manifold path. The skill says to check the templates first and not to install or patch around the missing library.
- Wall thickness corrects the cone-ray path by the cosine of the angle off the inward normal, so a 0.70 mm plate warns and an 0.80 mm plate does not. `tag_faces` and an export hook write `<stl>.faces.json` so thread, knurl, and tooth faces are left out of that check.
- `python -m evals.runner --hermes-session` reads a session id or a JSON/JSONL/text export and counts the tool calls in it, including `<timestamp> TOOLCALL name` lines. The `bores_not_genus` prompt is a task that asks the agent to build and validate, not a statement to answer from the prompt.
- Tool descriptions and the first lines of help output lead with `photo-to-part:photo-to-printable-part` and `skill_view("photo-to-part:photo-to-printable-part")`. The text says that id has no `plugin:` prefix.

## 0.1.9 — 2026-11-03

- The tool budget is the whole Hermes session, default 40 calls (`PHOTO_PART_MAX_CALLS`). Pass `calls_used`. When it is omitted, `remaining` is estimated high. `next_step` starts with `Budget: deliver now.` at about 60% and again at about 80%, and adds `Stop exploring.` at 80%.
- `photo_part_template` and `photo_part_build` take `help` or `describe` and return shape parameters and a minimal example script. Do not open `features.py`, `parts.py`, or `launcher.py`.
- `evals/` and `tests/` are excluded from the Python package. A Hermes git install still copies them onto disk; the skill says not to read them.
- Bore counting slices every planar leg on all three axes and ray-casts through-holes. A 1.5 mm six-hole L-bracket counts as six through holes. When no circular bore is found but genus is positive or unreliable, `hole_count` is `undetected` and does not fail the check.
- Eval staging copies the prompt and inputs only. `fixture.json` and truth masks stay with the scorer. Leak detection is anchored to this repo's `evals/` paths. Transcript tool counts come from session records. The low-confidence overlay task is a scripted render.
- A passing validate that was given a spec draws the photo overlay from the last measure step (photo, scale, and region) in the same call.
- `last_measure.json` is written in the project or output directory, scoped by project, and is not written into the plugin install directory.
- A low-confidence overlay tells the agent to pass a seed point or a region box.
- Tool descriptions lead with the skill id `photo-to-part:photo-to-printable-part`. `plugin:photo-to-part:photo-to-printable-part` is not a skill name.

## 0.1.8 — 2026-11-02

- Template output defaults to `<shape>_v1.stl`, or the `part` slug from spec.json. `plate_clip.stl` is unchanged. The placeholder `name_v1.stl` is not written.
- `best_version` is the highest-scoring passing sibling, including the file just checked. `revert_to` is set only when that sibling scores higher. A run with no passing file sets `best_version_reason` to `no passing version`. Detailed results include `versions`.
- Checklist booleans count as yes/no. `photo_part_validate --answer item=yes` is repeatable, stored on the sidecar, and is not a spec edit. Count items such as `5 knuckles` are filled from the matching check.
- The score is out of 100: watertight 30, spec 40, checklist 20, printability 10 minus 5 per warning. A mesh that is not ok loses 20.
- A passing validate that was given a spec also renders `sheet.png`. `photo_part_render` remains for an extra or final render.
- Every tool result includes `budget` (`plugin_calls`, `soft_limit` 20, `phase`). At 14 calls, `next_step` leads with a deliver hint. Template and build results include `bodies`, `bores`, and `sections_mm2`.
- Overlay pose search uses a truncated chamfer on Canny edges and keeps a fixed pixels-per-millimetre scale. `roi` and `px_per_mm` default from `last_measure.json`. Segmentation stability gates the IoU: low confidence reports a null IoU.
- `hole_count` is the circular bore count. Genus is reported separately. Wall thickness uses a 7-ray median, ignores thread, knurl, and tooth faces as ray sources, and warns on the area-weighted 5th percentile or a thin-area fraction over 1%.
- Evals stage one task outside the plugin tree, count wrong skill ids only from `skill_view` arguments, flag a transcript that reads `evals/` or `runner.py`, and hold out three tasks unless `--include-holdout`.

## 0.1.7 — 2026-11-02

- `ctx.register_tool` receives `output_schema` only when that Hermes build accepts it. Hermes v0.21.7 (`PluginContext.register_tool` has no `output_schema` parameter and no `**kwargs`) no longer fails `hermes plugins doctor` with `unexpected keyword argument 'output_schema'`, so all six tools register. Any other keyword the live signature does not accept is skipped the same way. A `TypeError` that names an unexpected keyword retries without it. A schema that cannot be passed is appended to the tool description and included on `response_format=detailed` results.
- `python -m evals.runner` loads the plugin `register(ctx)` entrypoint against a Hermes v0.21.7-shaped context and exits non-zero, with a clear message, when fewer than six tools register.
- CI checks `hermes plugins validate` and `hermes plugins doctor` against Hermes v0.21.7. PyPI has no 0.21.7 release and that tag refuses a wheel build, so the job editable-installs the git tag on Python 3.14 (its dependencies are marked for 3.14 only) with a temporary `HERMES_HOME`. The 3.11 and 3.12 jobs skip that CLI and cover both `register_tool` signatures in unit tests.

## 0.1.6 — 2026-11-02

- Validate writes a `score` from spec checks, watertightness, and printability. `next_step` says stop when every check passes, or revert to the better `name_vK` when a version regresses. A final render delivers the best validated version.
- `spec.json` features are a frozen checklist. Changing the frozen requirement requires `--reason`, which is copied into the report.
- Render writes an eight-view `sheet.png` (six orthographic views and two isometric views). The previous version is red and the new one is green, with a dimension-error table.
- Printability checks report minimum wall thickness, overhang area past 45°, bed contact, and the gap between bodies. The gap warns under 0.3 mm per side. Thresholds are arguments. Ray queries use `rtree`.
- Overlay segmentation tries OpenCV GrabCut from `--roi` or `--seed` and reports the top 3 poses.
- `photo_part_measure` tags each value `in_plane` or `out_of_plane` with `uncertainty_mm`, warns on out-of-plane use, and can scale from an ArUco or AprilTag marker.
- Every tool takes `response_format` `concise` or `detailed` (default concise). Errors include `cause` and `fix`. Each tool declares an output schema.
- `evals/` runs about 15 scripted tasks and records pass, dimension error, tool calls, minutes, wrong skill ids, and deleted files. Photos are not committed; the manifest names openly licensed URLs.
- `photo_part_heal --engine meshfix` and a non-manifold build union try PyMeshFix when that optional package is installed, and leave the mesh unchanged when it is not.

## 0.1.5 — 2026-11-02

- Knuckle checks sample between the pin radius and the knuckle wall, so a solid pin is not reported as zero knuckles. The hinge template takes `knuckles` (default 4).
- Templates write `<file>.template.json` with the spec checks they emitted. Validate fails when the user spec drops one of those checks.
- A render of `name_vN` without a fresh sidecar is refused and marked `unvalidated`. Build `next_step` always names `photo_part_validate`, including a failed script.
- The skill writes `spec.json` first. Template and build warn when that file is missing. The deliver step lists every spec deviation, including a removed template check.
- Each validate appends the previous record to `history` in `<file>.validate.json` instead of dropping it.
- `spur_gear` in `photopart.features`, and the `spur_gear` template shape. Involute teeth from module, tooth count, and pressure angle (default 20°), plus face width. Optional bore with a keyway or a D-flat, and an optional hub. Tip diameter is module × (teeth + 2). Root diameter is module × (teeth − 2.5). One watertight body.
- `spiral_scroll` and the `scroll` template shape: an Archimedean or log spiral strip with width, thickness, turns, and end radius. `strap_hinge` attaches one or two of those scrolls to a straight strap. Each is one watertight body. A build script imports `spur_gear`, `spiral_scroll`, and `strap_hinge`.
- `--overlay-fit auto` tries front, side, and top. Rotation is a 15° search followed by 1°, and a mirror is included. `overlay_poses` lists each view's best pose. A photo flagged angled is still scored, and `overlay_iou_label` is `guide_only`. An `--roi` that meets the silhouette edge is expanded, with a warning and `overlay_roi_expanded`.

## 0.1.4 — 2026-11-02

- Feature helpers in `photopart.features` always return one watertight body: external and internal ISO metric thread, straight or diamond knurl, revolve, sweep, hex-head screw, and hex standoff. `photo_part_template` adds `thread`, `knurl`, `sweep`, `hex_screw`, `hex_standoff`, and `bottle_cap`. A build script imports the same functions. `photo_part_build` unions overlapping shells and reports `shells_before` and `shells_after`.
- `--overlay-fit auto` searches rotation (coarse, then fine) and a mirror, then chooses front, side, or top. The JSON reports `overlay_rotation_deg`, `overlay_mirror`, and `overlay_view`.
- The skill forbids deleting or overwriting an STL or 3MF. A tool that replaces one keeps the previous bytes in `.p2p_history/`, and a missing `name_v(N-1)` is reported as `missing_earlier`.
- `photo_part_validate --spec spec.json` and `--dim name=value±tol` fail when the bbox, shell count, knuckle count, or hole count drifts. The skill writes `spec.json` first and lists deviations in the final answer.
- The deliver step validates the file it ships, then renders with `final`. A final render is refused when the latest `name_vN` has no fresh sidecar. Other renders set `needs_validation`.
- The only validation sidecar is `<file>.validate.json`. A build failure's `error` field is the exception, not a skill-id sentence. The skill id stays the first line of every description. A colon still cannot be a skill name, so the `plugin:` form is not registered.

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
