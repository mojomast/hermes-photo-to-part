# photo-to-part: best-practice research for v0.1.8 (2026-11-02)

Scope: the round-6 issues (/workspace/photo-to-part-test-r6/REPORT.md), checked against v0.1.7 (7b38c38).
This file does not repeat RESEARCH.md, which covers CAD-LLM loops, SAM 3, DA3/MoGe, PyMeshFix, slicer CLIs and the basic Anthropic tool guide.
Labels: ✔ = I read the quoted passage myself at the source today. (s) = from search snippets or a summary, not opened in full.

## 1. Turn and token budgets

**What the sources say**
- ✔ **OpenAI function-calling guide:** "Combine functions that are always called in sequence. For example, if you always call mark_location() after query_location(), just move the marking logic into the query function call." It also says: "Keep the number of initially available functions small." https://developers.openai.com/api/docs/guides/function-calling
- ✔ **Anthropic, "Writing effective tools for agents":**
  - Track "the total number of tool calls, the total token consumption, and tool errors". Tool-call traces "reveal common workflows … opportunities for tools to consolidate".
  - When a response is truncated or an error is raised, "steer agents with helpful instructions".
  - A `response_format` enum (concise/detailed) is recommended.
  - Rely on held-out test sets.
  - https://www.anthropic.com/engineering/writing-tools-for-agents
- ✔ **Budget-Aware Tool Use (Google, arXiv 2511.17006, v2 2026-08-17):** a "Budget Tracker" plug-in that "provides the agent with continuous budget awareness". It reports used and remaining calls after each tool response, works prompt-only, and makes agents adapt their plan. https://arxiv.org/abs/2511.17006 · https://github.com/google-research/budget-aware-agent
- (s) **Anthropic, programmatic tool calling and tool search:** chaining calls inside one script removes round-trips (−37% tokens on complex tasks). It is a poor fit for strictly sequential single-call flows. https://www.anthropic.com/research/advanced-tool-use · https://platform.claude.com/docs/en/agents-and-tools/tool-use/programmatic-tool-calling
  - Hermes already uses deferred tools: r6 transcripts show `tool_search` → `tool_describe` → `tool_call`. That costs 2 extra calls per session before the first real call.

**Implications for photo-to-part**
- (a) Validate→render is always sequential, so offer it as one call: `photo_part_validate render=true`.
- (b) Put a budget line in every tool result, e.g. `budget: {calls_used, soft_limit, phase}`, plus a "deliver now" hint once usage passes ~70% of the limit.
- (c) Cut ad-hoc probing by returning the facts agents currently probe for in the build and template results: section areas, hole list, bbox per body.
- (d) Have the skill tell the agent to batch independent plugin calls in one `tool_call` (Hermes accepts a `calls` list).

## 2. Overlay alignment on real photos

**What the sources say**
- (s, PDF snippet) **D²CO** (Imperiale et al., ICVS 2015): registers CAD models of textureless objects to images with a **directional chamfer distance** (a distance-transform tensor over edge orientations). It handles clutter, partial occlusion and missing edges better than other matchers. https://albertopretto.altervista.org/papers/miap_icvs2015.pdf
- (s) Chamfer matching through a distance transform costs O(pixels + poses × model points), so it is cheap enough for a CPU grid search. http://www.cs.umd.edu/~djacobs/CMSC828/Template_Matching.pdf
- (s) **Silhouette IoU is ambiguous as a pose criterion**: "multiple poses may have similar projected silhouette". https://arxiv.org/pdf/1806.08129v1.pdf
- (s) Thresholded directional chamfer works best on real data. Plain chamfer did well on synthetic data but worst on real data ("synthetic data … might be misleading"). https://arxiv.org/pdf/1704.00492v1.pdf
- (s) **SAM mask gating:** masks are filtered on predicted IoU (`pred_iou_thresh` 0.88 in SAM, 0.8 in SAM 2) and on a **stability score**, i.e. the mask must not change when the binarisation threshold shifts (`stability_score_thresh` 0.95). https://github.com/facebookresearch/segment-anything/blob/main/segment_anything/automatic_mask_generator.py · https://github.com/facebookresearch/sam2

**Implications** (r6 numbers: T8 0.74→0.045, T7 0.17, bottle cap "0.76" with no visible outline)
- (a) Score the pose with **truncated chamfer** between rendered silhouette edges and Canny edges inside the ROI, using a distance transform. Report IoU only as a secondary number.
- (b) Gate the segmentation before trusting it:
  - Stability: run GrabCut at 2–3 seeds or iteration counts and compute mask-to-mask IoU.
  - Area fraction of the ROI.
  - Touches-border flag.
  - If any gate fails, return `alignment: "low_confidence"` and **no headline IoU**.
- (c) Default the ROI and scale from the last `photo_part_measure` result in the project. Pass px/mm so the search only varies pose and translation, not scale.
- (d) Return `confidence` ∈ {high, medium, low} plus the reason.

## 3. Holes and bores vs genus

**What the sources say**
- (s) Mesh feature-recognition practice: segment regions → RANSAC cylinder fit → least squares. Then classify:
  - full 360° arc = hole, partial arc = fillet;
  - through vs blind by axial extent (Paramesh: "height > 80% of the part thickness" = through).
  - https://parameshai.com/learn/detect-holes-in-mesh-automatically · https://parameshai.com/learn/how-to-recognize-features-from-mesh
- (s) Axis by SVD of facet normals (least eigenvector), then a circle fit in the perpendicular plane; accept if >90% of triangles conform. https://www.cctech.co.in/downloads/publications/2018/complex-hole-recognition-from-cad-mesh-models-ICETSET-2018.pdf
- (s) **trimesh cross-sections:** `section_multiplane` → `Path2D.polygons_full`, where each polygon's `interiors` are the holes in that slice. https://trimesh.org/section.html · https://github.com/mikedh/trimesh/issues/1342

**Implication.** Genus counts handles, not bores: a hinge shaft spanning knuckles adds handles (r6 T9 genus 4 vs 2 bores; T7). Agents edited the spec to fit genus.
- Replace the default `hole_count` check with a **bore count**: slice along each principal axis at 3 levels, count circular interiors (circularity > 0.85), and keep only those present at all 3 levels (through) or at ≥1 (blind).
- Report `genus` separately, as information only.
- Optional: a cylinder fit for diameter on the interior loops.

## 4. Wall thickness without thread or fillet false positives

**What the sources say**
- ✔ **Quaoar (Analysis Situs), "On edge cases in CAD thickness analysis":**
  - Ray casting finds suspicious regions, but sharp edges and threads give geometrically correct yet irrelevant thin spots.
  - "exclude the corresponding CAD faces from the list of ray sources while leaving them as potential ray targets".
  - Estimate a thin spot's width as area/edge length (A/l(E)) and drop spots narrower than the offset.
  - "modeled threads … are a clear source of false positives".
  - https://quaoar.su/blog/page/edge-case-in-cad-thickness-analysis
- (s) **Shape Diameter Function** (Shapira et al. 2008): a 120° cone of 30 rays, ignore hits whose normal faces the same way, take a median-filtered weighted mean. https://www.cs.jhu.edu/~misha/ReadingSeminar/Papers/Shapira08.pdf
- (s) The median filter hides narrow bottlenecks; extremities are a known weak spot. https://arxiv.org/abs/1704.08049 · offset-surface SDF: https://pmc.ncbi.nlm.nih.gov/articles/PMC5786294/
- (s) **Slicers:** Arachne's "Minimum feature size" drops features below a fraction of the nozzle width and widens the rest, so a crest under it is dropped or widened by the slicer rather than failing. https://help.prusa3d.com/article/arachne-perimeter-generator_352769 · https://www.orcaslicer.com/wiki/print_settings/strength/strength_settings_walls

**Implication.** `printability._min_wall` takes the single minimum over one inward ray per sampled face. That flags every thread crest and knurl tip (r6 screw 0.06 mm, cap 0.46 mm).
- Use a **small cone, median per face** (SDF-lite: 5–9 rays, 60° cone).
- Report a **thin-area fraction** (area with SDF < min_wall ÷ total area) and the **p5 thickness**, not the global minimum.
- Warn only when thin area > 1% **or** a connected thin region is wider than 2 × nozzle (A/l test).
- Exclude faces tagged by features.py as thread/knurl from the ray sources (template and feature helpers already know which faces they made). Keep the old minimum as `min_wall_raw_mm`.

## 5. Spec / checklist confirmation

**What the sources say**
- (s) **"Checklists Are Better Than Reward Models"** (Apple, NeurIPS 2025): atomic, instruction-specific yes/no items, each checked separately. Programs check objective items; a judge handles semantic ones. https://machinelearning.apple.com/research/checklists-are-better · https://proceedings.neurips.cc/paper_files/paper/2025/file/a6837c1dd021f76f1b4098e3722052a8-Paper-Conference.pdf
- (s) RECAST: constraint-verifiable decomposition, rewarding per item rather than holistically. https://arxiv.org/html/2505.19030v1
- CADCodeVerify (already cited in RESEARCH.md): a VLM answers yes/no verification questions against renders.

**Implication** (r6: every checklist item `answered: false`)
- Two root causes:
  1. Nothing asks the agent to answer.
  2. **Bug:** `freeze.checklist()` counts only the strings `"yes"`/`"no"` as answered, so features written as `{"teardrop": true}` (r6 T9) are never answered.
- Fix:
  - Accept booleans.
  - Programmatically answer the items a check can decide (counts, holes, shells, knuckles).
  - Make `next_step` after a passing validate say "answer N open items: `--answer 'item=yes'`, judged against render sheet.png".
  - Count answered and passed items in the score.
- The score currently tops out at 80 (40 watertight + 40 spec), which reads as "something failed". Rescale to 100 with 20 points for the checklist.

## 6. Eval hygiene

**What the sources say**
- ✔ **SWE-bench #465 and PR #581:** agents ran `git log --all` to read future fixes. The fix removes remotes, refs and reflog, and fails the build if leakage remains. https://github.com/SWE-bench/SWE-bench/issues/465 · https://github.com/SWE-bench/SWE-bench/pull/581
- (s) **Cursor, "Reward hacking … coding benchmarks":** sealing history and the network dropped scores from 87.1 to 73.0 (Opus 4.8 Max). The two isolation mechanisms are history isolation and an egress allowlist. https://cursor.com/blog/reward-hacking-coding-benchmarks
- (s) **"How to Build a Private Eval for AI Coding Agents":**
  - Block read access to grading files.
  - Give each agent a probe task first to confirm the blocks work.
  - Audit transcripts for forbidden paths.
  - https://calltothink.com/blog/private-agent-eval-git-history/
- ✔ **Anthropic:** held-out sets; collect tool-call count, tokens and errors as first-class metrics (link above).

**Implication** (r6: agents read evals/README.md and runner.py; the scorer counted quoted `plugin:` strings and double-counted)
- Run Hermes evals from a copied task dir **outside** the plugin tree, with only the prompt and fixtures.
- Have the scorer flag any read of `*/evals/*` or `runner.py` as `leak: true`.
- Count wrong skill ids only from `skill_view` **tool-call arguments**, not from free text.
- Hold out 3 tasks.
- Add calls/minutes **budgets per task**: a task fails if it exceeds its budget.
- Add real-input tasks: a real photo, plus a fixture photo with an overlay IoU / chamfer floor.

---

## v0.1.8 implementation spec (prioritised, scoped)

### P0: small, correctness fixes

1. **Template output name.** In `tools.py` (template path, ~l.434), `step_model(stl or "name_v1.stl")`.
   - When `stl` is not given, default to `f"{shape}_v1.stl"` (e.g. `spur_gear_v1.stl`, `l_bracket_v1.stl`), or to `spec.json["part"]` slugified if present.
   - Never emit the literal `name_v1.stl` in a path. Keep `name_vN` only in prose hints.
   - Test: running the template with `spur_gear` and `l_bracket` and no `stl` writes `spur_gear_v1.stl` / `l_bracket_v1.stl`, and next_step names that file.
2. **best_version / revert_to always filled.** In `validate.py` (~l.325), after computing this file's score:
   - Set `best_version` to the highest-scoring **passing** version among siblings **including this file** (`best_validated`, adding the current report in memory before the sidecar is written).
   - If no version passes, set `best_version: null` and `best_version_reason: "no passing version"`.
   - Set `revert_to` to the best version when it scores higher than this one.
   - Add `versions: [{name, ok, score}]` to the detailed format.
   - Tests:
     - (a) v1 fail, v2 pass → v2 sidecar has best_version=v2, revert_to=null.
     - (b) v1 pass 80, v2 pass 60 → best=v1, revert_to=v1.
     - (c) single file pass → best=self.
3. **Checklist answers.** In `freeze.py` `checklist()`:
   - Treat `True`/`False` as yes/no.
   - Add a `validate --answer "item=yes|no"` option (repeatable), recorded in history (not a spec edit, no `--reason` needed).
   - In `validate.py`, auto-answer items that match a numeric check (`/(\d+) (knuckles|holes|teeth|shells)/`) from the check result.
   - Tests: boolean features count as answered; `--answer` persists into the sidecar; a "5 knuckles" item is auto-answered by the knuckle check.
4. **Score scale.** In `score.py`: watertight 30, spec 40, checklist 20 (answered-yes fraction), printability 10 (minus 5 per warning, floor 0), and −20 if not ok. A clean, fully answered part reaches 100.
   - Update the `worse_version_reverts` eval expectations.

### P1: turn budget (biggest real-photo cost)

5. **Validate + render in one call.** `photo_part_validate` gets `render: bool` (default **true** when `ok` and `--spec` was given) and `photo`, `views`, `overlay` passthrough.
   - When it passes, it calls the render code in-process and returns `render: {sheet, overlay, alignment}` in the same result.
   - Keep `photo_part_render` for non-final or extra renders.
   - Implementation: in `tools.py` validate handler, after a fresh sidecar, call the `render.py` entry point. The sidecar hash is fresh, so the freshness refusal is satisfied.
   - Tests: one call yields both sidecar and sheet.png; on failure no render runs and next_step lists the failures.
6. **Budget in every result.** In `flow.py`/`status.py`, keep a per-project counter in `.p2p_state.json` (calls by tool, first-call time).
   - Every tool result gets `budget: {plugin_calls, soft_limit: 20, phase}` (phase = spec/build/validate/deliver).
   - At ≥14 calls, next_step starts with "Budget: deliver the best validated version now (<file>)".
   - Following Budget Tracker (arXiv 2511.17006).
   - Tests: the counter increments; the hint appears at the threshold.
7. **Fewer probes.** Build and template results (concise format) add:
   - `bodies: [{bbox_mm, volume}]`;
   - `bores: [...]` (from item 9);
   - `sections_mm2` at z = 25/50/75%.
   - SKILL.md: "Do not write probe scripts. Read these fields. Batch independent plugin calls in one tool_call. Target ≤ 20 plugin calls and ≤ 30 total."
   - The skill should also tell the agent to render right after the first passing validate (now automatic via item 5).

### P1: overlay on real photos

8. **Chamfer alignment + confidence.** In `overlay.py`:
   - `roi`/`px_per_mm` default from the latest `photo_part_measure` JSON in the project (`measure.py` already writes it; add `last_measure.json`).
   - Pose search scores truncated chamfer (`cv2.distanceTransform` on Canny edges inside the ROI, τ = 3% of ROI diagonal) between projected silhouette contour points and image edges. Keep top-3.
   - Segmentation gate:
     - GrabCut with 3 seeds/iterations; stability = mean pairwise IoU (gate ≥ 0.85);
     - mask area 5–90% of ROI;
     - not touching ≥2 ROI borders.
   - Output `alignment: {chamfer_px, chamfer_norm, iou, stability, confidence: high|medium|low, reason}`. When confidence is low, set `iou: null` and next_step: "overlay unreliable: pass roi= or a seed; do not iterate geometry on it".
   - Tests:
     - synthetic render + noise background: chamfer finds the true pose (±5°, ±3 px);
     - an all-background image gives low confidence and a null IoU;
     - the measure ROI is picked up automatically.

### P2: checks

9. **Bore count replaces genus.** In `spec.py`, add `count_bores(mesh)`:
   - For each principal axis, slice at 25/50/75% with `section_multiplane`.
   - Interior rings with circularity (4πA/P²) > 0.85 are matched across slices by centre (≤0.5 mm) → through when seen at all 3 levels, blind otherwise.
   - Return `[{axis, center, diameter, through}]`.
   - The `hole_count` spec row uses bores. `genus` is reported separately with a note.
   - Tests:
     - 6-hole L-bracket → 6;
     - 5-knuckle hinge with a 2-bore body → 2 (genus 4 remains informational);
     - blind M5 tap hole in a revolve → 1 blind.
10. **Thread-safe min wall.** In `printability.py`:
    - SDF-lite: 7 rays per sampled face in a 60° cone; per-face median; ignore hits whose normal faces the same way (Shapira 2008).
    - Report `min_wall_p5_mm`, `thin_area_fraction`, `min_wall_raw_mm`.
    - Warn when p5 < min_wall or thin_area_fraction > 1%.
    - `features.py` returns `face_tags` (thread/knurl/teeth). The build/template sidecar stores tagged face indices (or a tag mask written beside the STL), and those faces are excluded as ray **sources** but kept as targets (Quaoar).
    - Tests:
      - M3 hex_screw template: no warning, raw min still reported;
      - 0.4 mm plate: warns;
      - bottle_cap: no warning.

### P2: eval suite

11. **Hygiene.** Add `evals/runner.py --stage DIR`, which copies one task's prompt and fixtures into DIR (outside the plugin) for Hermes runs. The transcript scorer:
    - counts `wrong_skill_ids` only from `skill_view` call arguments (fixes the double count);
    - flags `leak` on any read of `evals/` or `runner.py`;
    - adds `budget_calls`/`budget_minutes` per task in `tasks.json` and fails a task when they are exceeded.
    - Hold out `worse_version_reverts`, `frozen_edit_needs_reason` and the new overlay task by default (`--include-holdout`).
12. **New eval tasks** (tasks.json + in-process checks):
    - `template_default_name`: spur_gear with no stl → `spur_gear_v1.stl`.
    - `best_version_filled`: v1 fail, v2 pass → best=v2; v1 80 / v2 60 → revert_to v1.
    - `checklist_bool_answered`: boolean features count; `--answer` works.
    - `bores_not_genus`: hinge fixture → hole_count 2, genus 4.
    - `thread_no_thin_wall`: hex_screw → no min-wall warning.
    - `validate_renders_on_pass`: one call → sheet.png exists.
    - `budget_hint`: 14 calls → deliver hint.
    - **`real_photo_overlay`** (real input):
      - Fixture: `evals/fixtures/washer_photo.jpg` (~40 KB, **self-made, CC0**). Generate it once with `scripts/make_fixture.py`: render an Ø20/Ø8×2 mm washer STL at a known pose with soft shading onto a photographed-texture-free noisy wood-tone background, add blur, JPEG q=80 and a 23.25 mm coin disc for scale. Store the true pose and px/mm in `fixture.json`. This keeps the repo free of third-party bytes.
      - Task: measure the coin, build the washer, validate+render with the overlay.
      - Pass if confidence ≠ low, chamfer_norm ≤ 0.05, pose error ≤ 10°, and the IoU (from the generator's truth mask) ≥ 0.7.
      - Optional Hermes variant: same fixture, budget 25 calls.
    - **`overlay_low_confidence`**: the same fixture with the part cropped out of the ROI → must return low confidence and a null IoU.

### Out of scope for 0.1.8
SAM-based segmentation, depth models, slicer-CLI checks, programmatic tool calling (Hermes-side). Keep the plugin local and CPU-only; everything above uses numpy/trimesh/opencv/rtree, which are already dependencies.

### Acceptance (re-run r6's 8 real-photo cases)
- ≤ 1 case hits 40 turns.
- Every delivered part has a render.
- No `name_v1.stl` outputs.
- `best_version` is non-null on every passing sidecar.
- No thread min-wall warning on the screw or cap.
- T9/T7 need no hole_count spec edits.
- Overlay reports low confidence rather than an IoU < 0.2 headline.
- Evals: 16 + 9 tasks green, held-outs scored separately, `leak=false`.
