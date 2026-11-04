# photo-to-part: best-practice research for v0.1.11 (2026-11-03)
Input: r9 REPORT (v0.1.10, e64fbc6), plus RESEARCH.md and RESEARCH_v018.md (not repeated here: SDF-lite cone, thin-area fraction, Quaoar exclusion, budget soft wall, overlay chamfer search).
Hermes source: /home/box/.hermes/hermes-agent (v0.21.7). Nothing in the repo was changed.

## Key finding: Hermes v0.21.7 plugins CAN hook every tool call
`hermes_cli/plugins.py:109 VALID_HOOKS` includes `pre_tool_call`, `post_tool_call`, `transform_tool_result`, `transform_terminal_output`, `on_session_start/end`. A plugin registers them with `ctx.register_hook(name, cb)` (`plugins.py:933`), and they fire for **all** tools, not only plugin tools:
- `pre_tool_call(tool_name, args, task_id, session_id, tool_call_id, turn_id, ...)` may return `{"action":"modify","args":{...}}` (shallow-merged into args, `plugins.py:1998-2005`), `{"action":"block","message":...}` (message becomes the tool result), or `{"action":"approve"}`.
- `post_tool_call(...)` is an observer (`model_tools.py:680-697`).
- `transform_tool_result(tool_name, args, result, session_id, ...)` returns a replacement string; first string wins (`model_tools.py:849-866`). It runs after post_tool_call and before the result enters context.
- Manifest field `provides_hooks: []` in plugin.yaml must list them.
This matches Claude Code's PreToolUse/PostToolUse design (`updatedInput`, `additionalContext`, `updatedToolOutput`): https://code.claude.com/docs/en/hooks · https://code.claude.com/docs/en/agent-sdk/hooks
It fixes issues 1 (budget), 6 (skill id), and part of 3. **Scope every hook**: act only in sessions where the plugin is in use (a photo_part_* call or skill_view of our skill seen for that `session_id`). Otherwise return None. Fail open, no I/O beyond the project's `.photopart/` budget file.

---
## 1. Agents bypass measure and probe pixels by hand (T8)

**Best practice**
- Enforcement belongs in the harness (hooks), not the prompt: PreToolUse is "your enforcement primitive"; PostToolUse `additionalContext` is the way to inject state next to a tool result. https://code.claude.com/docs/en/hooks-guide · https://code.claude.com/docs/en/hooks
- Write injected text as facts ("12 of 40 calls used"), not as system commands, or the model may treat it as injection (Claude Code hooks reference, same page).
- API `tool_choice` forcing (OpenAI `tool_choice: {"type":"function",...}`, Gemini `functionCallingConfig`) exists, but Hermes only exposes it per-adapter (`agent/gemini_native_adapter.py:460`); plugins cannot set it, so use hooks. https://platform.openai.com/docs/guides/function-calling
- Coin scale: detect the coin (HoughCircles or contour + circularity), px_per_mm = coin_px / coin_mm, then measure the part's min-area rect in the same plane; ~1-3% on flat objects, worse with standoff height and oblique views. https://pyimagesearch.com/2016/03/28/measuring-size-of-objects-in-an-image-with-opencv/ · https://github.com/kirankotari/visioncore · HoughCircles jitter of 2-6 px: https://answers.opencv.org/question/95015/hought-circle-coin-detection-variation/ · https://docs.opencv.org/4.x/da/d53/tutorial_py_houghcircles.html

**Fix**
1. Budget counts all calls (`photopart/budget.py`):
   - New `photopart/hooks.py` with `on_post_tool_call(**kw)`: per `session_id`, increment a counter in `.photopart/budget.json` (reuse `_bump`, add `tool_name` bucket `"other"`). Replace `_resolve_used` input: take `max(agent calls_used, hook count, sessions.session_call_count)`.
   - `on_transform_tool_result(tool_name, result, session_id, **kw)`: for non-plugin tools in an active session, when crossing 60/80/95% of `max_calls()`, append one line: `"[photo-to-part] 24 of 40 tool calls used; next: photo_part_measure / photo_part_build."` Only at thresholds (one append each), so context stays small.
   - `__init__.register`: `ctx.register_hook("post_tool_call", ...)`, `("transform_tool_result", ...)`, guarded by `hasattr(ctx, "register_hook")`; list them in `plugin.yaml provides_hooks`.
2. Detect hand probing: in `on_pre_tool_call`, if tool is the terminal/execute_code tool and args match `cv2|PIL|Image.open|imread` on a file previously passed to `photo_part_measure`, count it; after 3 such calls, return `{"action":"block","message":"photo_part_measure already measures this photo: pass seed=[x,y] or roi=[x0,y0,x1,y1] to get the part size in mm."}`. Make blocking configurable (`PHOTOPART_BLOCK_PROBES=0` turns it into an appended note only). Start in note mode; block only if an eval shows notes are ignored.
3. `photopart/measure.py measure()`: add `part_seed` / `part_roi` / `auto: true`:
   - If `coin` given and no `diameter_px`/`points`: auto-detect the coin with `cv2.HoughCircles` on a blurred gray image, restricted to circles whose diameter fits the plausible px range; refine with contour `minEnclosingCircle` + circularity (4πA/P² > 0.85). Report `coin_px`, `coin_detect: hough|contour`, and a ±px uncertainty → `scale_uncertainty_pct`.
   - Part: reuse `overlay.grabcut_mask(image, roi, seed)` / `_component_at`, then `cv2.minAreaRect` on the mask and exclude the coin's circle. Return `part_bbox_mm: [L, W]`, `part_px`, `angle_deg`, `mask_png` path, and `same_plane_warning` (part height unknown → note standoff error ≈ h/camera distance).
   - Write the result to `last_measure.json` (`_write_last_measure`) so `photo_part_build`/spec can read `part_bbox_mm`.
4. SKILL.md: "Get every size from photo_part_measure (seed or roi). Do not open the photo with cv2/PIL." Keep it one line; enforcement is the hook.

**Coin-scale eval** (`evals/photos.json` + `tasks.json`, sealed): 3 photos, a small part (peg ~10-25 mm) next to a known coin (US quarter 24.26 mm, CAD loonie 26.5 mm, €1 23.25 mm), top-down, one at ~20° tilt. Ground truth from calipers. Task: deliver an STL. Pass = bbox within ±5% (±8% tilted), ≤ budget, `photo_part_measure` called with seed/roi, ≤2 terminal image-probe calls. Plus a unit test for `measure(auto)` on synthetic images (rendered disk + rectangle with noise): coin px within ±1.5%, part mm within ±3%.

**Acceptance**: T8 re-run delivers; first budget note appears at ≤60% of calls even with zero plugin calls (unit test: feed 25 fake `post_tool_call` events for `terminal`, then assert the transform appends a note); hook is a no-op in a session that never touched the plugin.

## 2. Thread/knurl tags lost in agent build scripts

**Cause in code**: `features.tag_faces/_store_tags` store **face indices** in `mesh.metadata`. Any boolean (`manifold_util` union with a head/cap body), `concatenate`, or `process()` renumbers or drops faces, so `printability._excluded_sources` sees nothing (cap 0.26, M3 0.076).

**Best practice**
- Exclude feature faces as ray sources, keep them as targets (Quaoar; already cited in v018).
- Make tags survive topology changes by storing **geometric descriptors**, not indices — the same way CAD kernels attach attributes to features and re-resolve them (topological naming problem): https://wiki.freecad.org/Topological_naming_problem
- Detect helices geometrically: a thread is a surface whose radius r(θ, z) is periodic in z with pitch p and shifts phase with θ (r(θ,z) ≈ f(z − pθ/2π)); a knurl is periodic in θ. Detect via FFT/autocorrelation of radius samples along z per θ bin. ISO coarse pitches (M3 0.5, M4 0.7, M5 0.8, M6 1.0) from ISO 261/262 give priors. https://en.wikipedia.org/wiki/ISO_metric_screw_thread
- Slicers already absorb sub-nozzle crests (Arachne min feature size): https://help.prusa3d.com/article/arachne-perimeter-generator_352769

**Fix**
1. `features.external_thread/internal_thread/knurl`: also store `mesh.metadata["feature_regions"] = [{"kind":"thread","axis":[0,0,1],"origin":[...],"r_min":..,"r_max":..,"z0":..,"z1":..,"pitch":..}]`. Write them in `<stl>.faces.json` as `regions` (`write_face_tags`).
2. `printability._excluded_sources(mesh, face_tags)`: if `regions` present, re-resolve on the final mesh: exclude faces whose centroid lies within the region's cylinder shell `[r_min−ε, r_max+ε] × [z0,z1]` and whose normal has a radial component > 0.3. Indices remain a fallback.
3. Auto-detect when no tags (`printability.detect_periodic_regions(mesh)`): fit the dominant axis (PCA of the thin-spot faces, or cylinder fit), sample radius on a θ×z grid via rays from the axis, FFT along z; a peak with amplitude > 0.2 mm at a period in 0.35-3 mm and phase drift consistent with one helix → thread; peak along θ with ≥12 periods → knurl. Report `auto_feature: thread pitch=0.5`, exclude those faces, and print the warning as `info` with `min_wall_raw_mm`.
4. Merge-safe tags: `features.tag_faces` docstring + `photo_part_build` example script: "tag after the final boolean"; `photo_part_build` (`build_run.py`) re-runs `detect_periodic_regions` and writes the sidecar if the script did not.
5. Only suppress a thin spot when the thin region is inside a detected/tagged region; a thin flange next to a thread must still warn.

**Acceptance**: new eval `thread_from_script_no_thin_wall`: script builds an M3×0.5 thread with `external_thread`, unions a hex head, exports → no thin-wall warning, `min_wall_raw_mm` < 0.3 reported. Same with an untagged helix built from raw numpy (auto-detect path). Negative: a 0.3 mm flange next to the thread still warns. Cap and M3 r9 meshes re-validated: no warn.

## 3. Scorer gaps in `--hermes-session` mode (`evals/runner.py`, `photopart/sessions.py`)
- **plugin_calls = 0**: `sessions._call_name` returns the wrapper name `tool_call`. Recurse: if name is `tool_call` (or args contain `calls: [...]`), yield each inner `name`. Implement in `sessions._parse_calls`/`names_from_messages`, so `_PLUGIN_CALL.fullmatch` sees `photo_part_*`. Test: a fixture message `{"name":"tool_call","arguments":"{\"calls\":[{\"name\":\"photo_part_validate\"}]}"}` → plugin_calls 1.
- **minutes null**: compute `(max(ts) − min(ts))/60` from the messages table timestamps in `_names_from_db` (state.db), fallback to session file mtimes. Test with two messages 90 s apart → 1.5.
- **leaks in arguments**: `score_hermes_session` applies `_text_leaks` only to text. Also scan every tool call's arguments (`path`, `command`, `file_path`, `pattern`) with the same regex (`evals/`, `runner.py`, `tasks.json`, `tests/`). Test: `read_file {"path":".../evals/runner.py"}` → leak true.
- Better: with the new `post_tool_call` hook writing a per-session JSONL (`.photopart/calls.jsonl`: tool name, ts, arg paths, no contents), the scorer can use it as ground truth and cross-check state.db.
- **Acceptance**: rescore r9 sessions: plugin_calls matches "mine" column (3,4,4,0,5,...), minutes non-null, best_version_filled leak = true.

## 4. Overlay "confidence" measures segmentation, not fit
**Best practice**: report fit with region overlap (IoU/Dice) plus boundary metrics, since IoU is insensitive to boundary errors on large objects and harsh on thin ones; use Boundary IoU, symmetric chamfer (mean contour distance, in px and mm) and Hausdorff/95th-percentile Hausdorff (HD95) for worst-case misfit.
https://arxiv.org/abs/2103.16562 (Boundary IoU) · https://scikit-image.org/docs/stable/auto_examples/segmentation/plot_hausdorff_distance.html · https://docs.opencv.org/4.x/d1/d32/tutorial_py_contour_properties.html · Metrics Reloaded (choose metrics by structure type): https://arxiv.org/abs/2206.01653
**Fix** (`photopart/overlay.py`):
- Rename `_segmentation_gate`'s output to `segmentation_confidence`; keep `confidence` as a deprecated alias for one release.
- New `fit_metrics(placed, foreground, px_per_mm)` used in `_alignment`: `iou`, `boundary_iou` (band width d = 2% of mask diagonal), `chamfer_px/mm` (both directions via `cv2.distanceTransform` of each contour ring; reuse `contour_ring`, `_chamfer_of_placed`), `hd95_px/mm`.
- `fit_confidence`: high if IoU ≥ 0.75 and boundary IoU ≥ 0.5 and chamfer ≤ 1.5 mm; medium if IoU ≥ 0.5; else low; and `overall = min(segmentation, fit)`. Thin parts (`_elongated`) use boundary IoU + chamfer, not IoU.
- Headline in `_write_overlay`/`_overlay_warnings`: "fit low (IoU 0.36, chamfer 4.1 mm)".
**Acceptance**: strap hinge r9 overlay → fit not "high"; cap (IoU 0.91) stays high; unit test with a shifted rectangle: IoU drops, chamfer ≈ shift.

## 5. Sanity check against standard sizes
**Sources**
- ISO 4162 flange bolts cover M5-M16 only (dc max M5 11.4, M6 13.6, M8 17.0; s M5 7/8 mm per edition): https://cdn.standards.iteh.ai/samples/56451/10d71b8d8c634e9790d4ddcf4c296cc2/ISO-4162-2012.pdf · https://www.nufast.co.uk/uploads/ISO4162.pdf · https://www.globalfastener.com/standards/detail_151.html
- M3 has **no ISO flange-bolt row**; catalogue M3 flange screws are ~6-7 mm flange, so 8.1 mm should warn, not snap. Use ISO 4017 hex (M3 s 5.5, k 2), ISO 4762 socket head (M3 dk 5.5, k 3), ISO 4032 nut (M3 s 5.5, m 2.4), ISO 261 coarse pitch: https://www.fasteners.eu/standards/ISO/4017/ · https://www.fasteners.eu/standards/ISO/4762/ · https://en.wikipedia.org/wiki/ISO_metric_screw_thread
- Clearance holes ISO 273 (M3 fine 3.2 / medium 3.4 / coarse 3.6; values from memory, verify before shipping the table)
- Inch: ASME B18.2.1 / UNC pitches: https://en.wikipedia.org/wiki/Unified_Thread_Standard
**Fix**: new `photopart/standards.py` with a small table (M2-M12: major d, coarse pitch, hex s/k, socket dk/k, nut s/m, ISO 273 holes; ISO 4162 dc for M5+; #4-1/2" UNC; 608 bearing 8×22×7; common magnets). `check_standard(spec, report)`: parse `M\d+(\.\d+)?`, `#\d+-\d+`, `608` from spec name/notes; compare measured bbox/features; warn when off > max(0.3 mm, 8%), with the standard value and source, and `suggest` (never auto-edit; consistent with v0.1.10's no spec edits). Call from `validate.py` → report `standards` row, and from `measure` when the spec names a standard but `part_bbox_mm` disagrees (photo is then the suspect: report both).
**Acceptance**: M3 r9 mesh (8.1 flange, 9.2 length) → warning "M3: flange 8.1 mm above typical 6-7 mm; hex s 5.5"; M5 flange 11.4 → no warning; thread pitch 0.5 detected for M3 matches table.

## 6. Wrong skill id (`plugin:photo-to-part:photo-to-printable-part`, 3/8 runs)
Cause (Hermes `tools/skills_tool.py _resolve_plugin_skill`): namespace parsed as `plugin`, no such plugin, falls to local scan, fails; the agent recovers next call. `register_skill` cannot alias a colon name (`__init__.py` docstring).
**Best practice**: tolerate common misspellings at the dispatcher (Claude Code `updatedInput`; Hermes `modify`) and give one canonical id everywhere. https://code.claude.com/docs/en/hooks
**Fix**: `hooks.on_pre_tool_call`: if `tool_name == "skill_view"` and `args["name"]` matches `^(plugin:|plugins:)?photo-to-part[:/](photo-to-printable-part)$` or bare `photo-to-printable-part`, return `{"action":"modify","args":{"name":"photo-to-part:photo-to-printable-part"}}`. Only exact patterns for our own id; never touch other skills. Also log the rewrite so the scorer still counts "mistaken id" (count from the hook log, not failures).
**Acceptance**: unit test via a fake ctx: hook rewrites the three variants, leaves `superpowers:x` untouched; live run: skill_view with the `plugin:` prefix returns the skill on the first call.

## 7. Git install still ships evals/
Hermes facts: no exclude in plugin.yaml; install = shallow clone; **a subdir install** (`owner/repo/sub/dir`, `hermes_cli/plugins_cmd.py:300-326`) does a blobless clone + sparse checkout of only that subdir (`plugins_cmd_git.py _restrict_checkout_to_subdir`, `_clone_plugin_repo`).
Options (best first):
1. **Repo layout split (recommended)**: move the plugin to `plugin/` (or keep `plugins/photo-to-part/`) and move `evals/` and `tests/` to repo-root siblings. Catalog install string becomes `mojomast/hermes-photo-to-part/plugin`; sparse checkout then never downloads evals blobs (blobless clone). Sources: git sparse-checkout and partial clone docs https://git-scm.com/docs/git-sparse-checkout · https://git-scm.com/docs/partial-clone
2. **Sealed tasks**: keep public evals but move holdout/sealed task answers to a private repo or an encrypted archive (`age`/`gpg`) decrypted by the runner with a key outside the repo; public tasks.json holds only prompts. Benchmarks do this to prevent contamination (canary strings + hidden test sets): https://github.com/google/BIG-bench/blob/main/bigbench/benchmark_tasks/README.md (canary) · SWE-bench hidden tests pattern https://www.swebench.com/
3. Release branch: a `release` branch without evals/tests, built by CI (`git subtree split` or a workflow), with the catalog pinned to it. Works but double maintenance.
4. Add a canary GUID to every eval file and have the scorer + `post_tool_call` hook flag any read of a file containing it (covers leaks even if files are on disk).
**Acceptance**: `hermes plugins install mojomast/hermes-photo-to-part/plugin` → installed tree has no `evals/` or `tests/`; `hermes plugins doctor` still shows 6 tools; `python -m evals.runner` works from the repo root; a git-install session cannot `read_file` any eval path (path does not exist).

## Suggested v0.1.11 order
P0: hooks.py (budget counting all calls + skill-id rewrite) · scorer fixes (3) · region tags + re-resolve (2.1-2.2).
P1: measure auto coin + part bbox + coin eval (1.3) · fit metrics (4) · standards warnings (5).
P2: periodic auto-detect (2.3) · repo split for evals (7) · probe blocking (1.2) only if notes fail in eval.
Re-run r9's 8 real-photo cases + 16 sealed tasks; targets: 8/8 deliver, first budget note ≤ 60% calls in every run, 0 thin-wall warns on cap/M3, wrong-id 0, scorer plugin_calls/minutes/leak match manual counts.
