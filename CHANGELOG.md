# Changelog

## 0.1.19 — 2026-11-09

- Overlay refinement no longer treats truncated chamfer (capped near 0.03 of the diagonal) as a finished fit. A silhouette refines only when the untruncated symmetric contour distance is above 2 px. The warp is Euclidean (rotation and translation). A result that changes mask area, or that does not improve that distance, is discarded. Nonconvergence keeps the prior pose. Pose choice uses overlap and edge distance. A saturated chamfer score cannot replace a better-overlap pose. A fully observed photo keeps border edges. Padding seams are still dropped. Half-pixel nearest-pixel rounding stays.
- A frozen user x, y, or z that is rewritten to a nearby photo measurement fails validation. The message names both numbers. The mesh is scored against the user's number, and the freeze hash is not advanced. A checklist edit, or a number that does not track a measurement, still updates when `--reason` is set.
- The stability reason and the 0.85 comparison use the same two-decimal value, so a score that prints as 0.85 is not reported as under 0.85.
- Stability GrabCut samples stop once the first two agree. The primary part mask stays full resolution. A measurement `next_step` reports `part_bbox_mm` and says to stop when the request was only a measurement. Template and build text point at `bottle_cap`, `strap_hinge`, and `spur_gear` instead of reading plugin source.
- A `pre_tool_call` error still blocks a read of eval scoring files and `tests/regression`. An ordinary read still proceeds. `pytest` and `unittest` stay allowed.
- Docs state that Hermes `--yolo` auto-approves the build prompt. The plugin still returns the approve action and does not block that flag. `PHOTOPART_BUILD_APPROVAL=allow` remains the test and sealed-eval skip.
- Optional Part studio pane for Hermes Desktop 0.23 or newer (`plugin/desktop/plugin.js`). While a run is in progress it shows the stage, the photo and overlay, each render beside the photo, iteration history, overlay IoU, scale source and confidence, trust, dimensions, the approval gate, warnings and errors, and the STL and CAD paths.
- Tools write `<project>/.photopart/pane.json` and, when `HERMES_HOME` is set, `$HERMES_HOME/.photopart/pane-index.json`. The pane polls `GET /api/plugins/photo-to-part/` and also listens for `plugin.photo-to-part.run.updated` when the gateway can broadcast it. No tool schema changed.
- The pane is not required. Hermes versions without it, including the 0.21.7 doctor check, still install the same six tools and the same hooks. The build approval decision and the eval read block are unchanged. Progress writes are skipped for the plugin directory, the source checkout, `evals/`, and `tests/regression`.

## 0.1.18 — 2026-11-04

- Calibrated photo overlays preserve pixels-per-millimetre scale in the IoU fallback, including coarse/fine pose search and mirror comparisons. A wrong-size model can no longer be resized to match the foreground by this fallback when image edges are weak.
- Consistent nearest-pixel rounding preserves solid silhouettes at half-pixel translations, and chamfer sampling uses that same rule so a half-pixel tie is not scored on a collapsed contour. Pose tie-breaking prefers upright orientation only when overlap also ties, preserving evidence from asymmetric features such as notches.
- Quad rectification now saves one metric transform, full-photo canvas, isotropic output scale, and image identities. The PNG, overlay, measurement endpoints, and part-mask dimensions share that transform. Canvas downsampling updates the same scale; reference landmarks no longer inherit pixel-bounding-box aspect ratios or an off-by-one scale error.
- Overlay regions, seeds, origins, and reference exclusions follow rectification. Padding is the area outside the source photo's pixel coverage: observed border pixels stay in the image, and fits that touch unobserved padding are untrusted. Rendering the saved rectified image reuses its calibration without warping twice. Changed photos, incompatible explicit scales, and legacy matrix-only perspective contexts require remeasurement.
- A foreshortened coin ellipse leaves the image in its source frame and produces a guide-only overlay instead of an uncalibrated stretch. A nearly circular coin is not treated as tilt. Quad calibration still assumes the measured feature and reference share a plane.
- The ECC skip threshold is unchanged. Normalized chamfer is still capped near 0.03, so refinement that could rescale a calibrated silhouette stays deferred.
- Research notes record the calibration defects and fixes, that deferred refinement, and an evidence-based improvement plan in `docs/research/pipeline-best-practices-v0118.md`.

## 0.1.17 — 2026-11-04

- An overlay is trusted only when both segmentation and fit are usable. Zero overlap is untrusted even with a stable foreground mask, with an explicit fit reason. The numeric IoU remains visible.
- The bottle-cap template now has a closed top (`top_thickness_mm`, default 1.2 mm). `length_mm` is total height and `outer_diameter_mm` includes the knurl crests. Straight ribs no longer extend beyond their intended radius or intrude into an internal thread. Invalid top thickness and insufficient thread wall are rejected.
- Broad, centred blind openings spanning at least 70% of both transverse body dimensions, with a thin closed end, are classified as `cavities`, outside `hole_count`. The closed end must be no thicker than max(1.5 mm, 15% of the opening diameter), allowing one 0.45 mm depth-probe station of uncertainty. This is a geometric cap-like-shell heuristic, not thread recognition. Through-holes, pin clearances, blind bores in thick stock, and shallow recesses retain their existing classifications. Archived specs that counted a cap cavity as a bore now correctly fail that count; their original specs are preserved.
- A known, visible user-given part dimension can calibrate a photo without a coin or ruler: pass `reference_is_part: true` to measure. The part is kept in the foreground, the scale provenance is reported, and the overlay is labelled as a guide rather than independent size verification. The skill uses this path for photo comparison.
- Render reuses photo context from the mesh's project directory, including reference exclusion and perspective flags, and refuses to borrow measurements for a different explicit photo. A missing scale is reported as `overlay_status: missing_scale` with a measurement next step instead of silently omitting the comparison.
- The Hermes integration test validates `plugin/`, not the repository-root refusal stub.

## 0.1.16 — 2026-11-04

- A terminal or code tool that runs a photo-to-part build asks for the same Hermes approval as `photo_part_build` (`rule_key` `photo_part_build`). That covers `python build.py`, `photo-part-build`, `python -m photopart.build_run` or `photopart.stamp`, a CadQuery or build123d export, and a Python file whose text imports those modules or writes an STL, STEP, STP, or 3MF. `ls`, `cat`, `echo`, `rg`, and `pytest` are not builds. `PHOTOPART_BUILD_APPROVAL=allow` (also `yes`, `true`, `1`, `off`, `skip`) skips the prompt. Anything else still asks, and Hermes blocks the command when nobody can approve.
- The skill, `photo_part_build`, and the template note say to use `photo_part_build` rather than the terminal.
- `evals/`, `tests/` (including `tests/regression`), and the runner stay at the repository root. The installable plugin is `plugin/`. `hermes plugins install mojomast/hermes-photo-to-part/plugin` sparse-checks out that directory only, so the scorer, fixtures, and regression meshes are not published. The `plugin.yaml` at the repository root refuses a root install on Hermes v0.21.7 (`requires_hermes >=999` and `manifest_version: 99`) before files are copied. A full checkout still has `evals/` on disk. `pre_tool_call` blocks a session read of `evals/` scoring files and `tests/regression`. `pytest` and `unittest` are not blocked. `python -m evals.runner` from the repository root still runs the suite.
- `last_measure.json` and `.p2p_state.json` are not written into the plugin directory or into the source checkout root. A Hermes install is unaffected. The test suite runs with that root as its working directory.

## 0.1.15 — 2026-11-03

- From @teknium1: `photo_part_build` asks for Hermes approval before it runs a script. The callback is a second `pre_tool_call` hook, so the skill-id rewrite, the session call budget, and the probe note stay. `help` and `describe` do not run a script and are not prompted. `PHOTOPART_BUILD_APPROVAL=allow` skips the prompt for a test or a sealed eval. The default is to ask.
- From @teknium1: output paths that Hermes's write denylist refuses are rejected, including `<file>.validate.json`. A rectified measure PNG must end in `.png` and is not replaced unless `overwrite` (or `force`) is set.

## 0.1.14 — 2026-11-03

- Knuckle count uses the individual rings along the axis when a pin or a fillet has merged neighbouring cylinders. The r12 teardrop hinge reports 5, and the r11 hinge stays 5. Zero cylinders is still not a knuckle, so a strap hinge and a bottle cap are unchanged.
- A copied thread is detected from the crest again. Run splits follow the neighbouring radius (1.5 mm) and a drift from the run's first sample, the crest may be up to 2.2 mm, and a bottle thread whose second harmonic hides the helix is accepted when the columns agree on pitch. The wall check then skips the collar around an external crest and the skirt around an internal one. The r12 cap and the r12 screw do not warn. A 0.3 mm flange of radius 6 mm beside an M3 thread still warns, and a 0.70 mm plate still warns.
- `score_hermes_session` reads the case directory's `.photopart/calls.jsonl`, filtered to that session. It does not read the shared `$HERMES_HOME/.photopart/calls.jsonl`. `box_matches_spec` no longer reports 9 rewrites from other sessions.
- `photo_part_measure` intersects the GrabCut mask with the border-color mask and snaps a nearby seed onto the part. The staged loonie photo with seed `[479, 252]` measures 22.30×12.16 mm, inside 5% of 22×12.
- The gear overlay drop (0.66 trusted in r11 to 0.13 untrusted in r12) was checked on the same photo and the same mesh. Unseeded fit is 0.43 on both v0.1.12 and v0.1.13. GrabCut downscale, the iteration cap, the ECC skip, and the elevation skip do not explain the live drop. Those speedups stay. A seeded fit on the current code is about 0.90 and trusted.
- `tests/regression/` holds the r10–r12 meshes and `tests/test_regression_rounds.py` checks knuckle count, bore count, the dish-versus-bore split, and thin-wall warnings with and without sidecars. `unittest discover` runs that module on every pull request.

## 0.1.13 — 2026-11-03

- `photo_part_template` no longer drops a shape value that arrives next to `shape`. Known keys, for every template, are merged into `params`. `knuckles: 5` at the top level builds a 5-knuckle hinge. An unknown name, or the same key with two different values, is an error that says the value belongs in `params`.
- A blind opening shallower than max(1 mm, 0.35 × diameter) is a recess, not a bore. `hole_count` leaves it out and says so in `recess_note`. Through-holes stay bores. A pin-clearance bore and a blind tap of meaningful depth stay too. The decorative 23.5 mm rosette dish does not become a second hole.
- `pre_tool_call` rewrites this skill's id on `skill_view`, on `skills_list`, and inside a `tool_call` `{calls:[...]}` list, including a JSON-string `arguments` and slash or `plugin:` forms. The scorer reads those same forms. A `rewrite_from` row counts as `skill_id_rewritten`. A wrong id with no matching rewrite counts as `wrong_skill_ids`. A sentence that only mentions the `plugin:` form is not a call. The exact id is `photo-to-part:photo-to-printable-part`.
- Bore rays are vectorised, and a body that does not cross the slice is skipped. Overlay skips ECC when the chamfer is already within 2 px or 0.05 of the diagonal, estimates ECC on a mask no wider than 360 px, and skips 30°/60° views when an orthographic IoU is already at least 0.72. GrabCut downscales images longer than 960 px, caps iterations at 5, and uses a fixed OpenCV RNG seed so a mask does not depend on earlier cv2 calls.
- `coin_scale_sealed` staging writes `us_quarter.png`, `cad_loonie.png`, and `euro_1.png`, so `photo_part_measure` runs on a photo. Real caliper photos are still not in this repo.

## 0.1.12 — 2026-11-03

- Bores are accepted by a least-squares circle fit on a simplified outline, not by 4πA/P² on a snapped staircase. The snap grid is `min(0.05, 0.01 × the smallest extent)` and uses `shapely.set_precision`. Each shell is sliced on its own, so a pin inside a sleeve is a `pin_clearance` bore with `clearance_mm`. A 0.5 mm staircase square is still not a bore.
- `check_standard` runs only for a fastener role: a `fasteners` entry, a tagged thread, or a part name that is a screw, bolt, nut, washer, or standoff. "Mounts with an M5 screw" is compared with ISO 273 clearance holes (fine/medium/coarse for M2.5–M8, the rows read from the ISO 273:1979 preview), never with the bounding box. A size outside 0.5× nominal to 2× the largest cited dimension is skipped. A named flange is compared with the ISO 4162 dc max, not with the nearest hex. The spec is not edited.
- `detect_knuckles` counts coaxial cylinders (arc, radius, length, and a gap). `count_knuckles` stays a warning when it disagrees. Zero cylinders is a warning, not a failure, and the strap-hinge template does not add a knuckle check unless `pivot` is true.
- Thread and knurl detection from the mesh is the source of truth when no sidecar and no face tags are present. The crest gate stays 0.12 mm: an M3 thread unioned with a hex head measures under 0.15 mm. Tags already on the mesh still exclude those faces. The sidecar is a cache keyed by `mesh_sha256`. A copied screw without a sidecar is not a thin-wall warning. A thin flange beside a thread still warns. `tags_source` is `sidecar`, `3mf`, `detected`, or `none`.
- 3MF export can carry `photopart:regions` metadata and a `photopart-thread` triangle set. Those are read before the sidecar.
- Overlay fit IoU is always reported. `iou_trusted` is false, with the gate reason, when segmentation is low. GrabCut grows the ROI by ×1.5 up to twice when the mask touches the box. ECC may refine a coarse chamfer. Elevation views at 30° and 60° are searched after the orthographic views and listed only when one of them wins. `last_measure.json` stores a quad homography and a coin ellipse.
- A user dimension that an assumed feature pushes out of tolerance is a warning (`z 23.0 > user 20.0; assumed hub boss adds 3.0`) and does not fail when the addition explains the gap.
- Hook rewrites of a skill id (`rewrite_from` in `.photopart/calls.jsonl`) count as `skill_id_rewritten`, not `wrong_skill_ids`.
- Plugin tools are called through Hermes `tool_call` (`calls: [{name, arguments}]`). `photo_part_template` is not a bare tool name. Real-photo runs should be launched detached (`setsid nohup`) and polled.

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
