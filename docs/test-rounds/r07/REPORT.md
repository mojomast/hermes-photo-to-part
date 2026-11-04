# photo-to-part round 7: v0.1.8 (436cf87) vs round 6 (v0.1.7), Hermes v0.21.7, deepseek-v4.1-flash, --max-turns 40

## Install
- Already in place, no reinstall. Doctor: manifest 0.1.8, 6 tools, registration OK.
- Hermes tools run in env `8902151c…`, which has the 0.1.8 code. The older env `74aa…` (my r6 /tmp/vp6) still holds 0.1.7 `photopart`. That stale env is what likely confused the earlier /tmp-clone doctor result. Re-checks below use the 0.1.8 env.

## 1. Evals
**In-process** (`python -m evals.runner --include-holdout`): 25/25 passed, 3/3 holdouts passed, 6 tools registered, 62 calls (evals_inprocess.json).

**Hermes-driven:** 15 tasks were staged with `--stage DIR --task ID` into r7/hevals/<id>, outside the plugin, and scored with `--transcript`.
- I recomputed "calls" myself as all tool calls (the runner counts every *mention* of `photo_part_*`, including in tool output).
- Budgets come from tasks.json (calls / minutes).

| task | done right? | calls (plugin) / budget | min / budget | leak (real) |
|---|---|---|---|---|
| box_matches_spec | yes | 10 (2) / 40 | 0.5 / 5 | no |
| box_dimension_error | yes | 26 (2) / 40 | 2.1 / 5 | yes, read evals/ |
| hinge_five_knuckles | yes | 21 (3) / 40 | 0.8 / 5 | yes: tasks.json, runner.py |
| countersink_deeper_than_sheet | yes | 21 (1) / 40 | 1.2 / 5 | yes |
| thin_wall_warning | yes | 19 (7) / 40 | 1.0 / 5 | no |
| print_in_place_gap | yes | 21 (4) / 40 | 1.0 / 5 | yes |
| worse_version_reverts (holdout) | yes | 25 (5) / 40 | 1.6 / 5 | yes: grep "worse_version" in runner.py |
| template_default_name | yes | 3 (2) / 40 | 0.1 / 5 | no |
| best_version_filled | yes | 29 (8) / 40 | 1.2 / 5 | yes |
| checklist_bool_answered | yes | 34 (4) / 40 | 1.7 / 5 | yes |
| bores_not_genus | **no tool use**: answered from reading runner.py and spec.py | 9 (0) / 40 | 0.3 / 5 | yes |
| thread_no_thin_wall | yes | 58 (11) / **40, over** | 3.3 / 5 | yes |
| validate_renders_on_pass | yes | 44 (5) / **40, over** | **5.3 / 5, over** | yes |
| real_photo_overlay (holdout) | yes: confidence high, IoU 0.80, chamfer_norm 0.003 | 29 (5) / **25, over** | 3.7 / 5 | yes: read runner.py, meshes.py **and fixture.json** (holds the true pose) |
| overlay_low_confidence | **no**: the agent "corrected the premise" and rendered with a good roi, so confidence came out high | 37 (5) / 40 | 3.5 / 5 | no |

**Leak flag:** it works, but staging does not seal anything.
- 11 of 15 sessions read the installed plugin's `evals/runner.py` / `tasks.json`, because the plugin dir is readable.
- The staged dir also contains the answer files (`fixture.json` with pose and coin points, `washer_mask.png`).
- The `evals/` regex also fires on any path containing `evals/` (my `hevals/` dir). I renamed it before scoring.

## 2. Real-photo cases, r6 → r7
Re-checked on copies in /tmp/r7v. "Score" is the agent's sidecar score (/100 in 0.1.8; r6's /80).

| case | r6 | **r7** | delivered | dims re-checked (mm) | WT / shells | calls (plugin) | min | turn cap | best ver. filled | checklist answered | score | spec edits | auto-render on validate | overlay confidence (IoU) | budget hint | bores / genus | thread thin-wall warn | wrong id | deleted |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| spur gear | PASS | **PASS** | gear_v2 | 45×45×20 | yes/1 | 39 (12) | 31.3 | no (39) | yes (self) | 5/5 | 96 | 0 | yes (renders/, no photo) | low on all 6 tries (mask touches ROI border, stability 0.48) | not reached | 1 / 1 | none | 0 | none |
| bottle cap | PASS | **PASS** | cap_v1 | 33×33×17 | yes/1 | 42 (4) | 9.0 | no | yes | 4/4 | 100 | 0 | yes | medium (0.81) | not reached | 1 / 1 | **none** (r6 0.46 warn); p5 0.95, raw 0.63 | 0 | none |
| strap hinge | PASS | **FAIL**: turn cap, never validated | none (v3 400×70×4 on disk) | 399.99×70×4 | yes/1 | 43 (3) | 5.8 | **hit** | – | – | – | – | – | – | not reached | – | – | **1** | none |
| M3 screw | PARTIAL | **FAIL**: turn cap; v1 is 3 loose bodies, unvalidated | none | 7.3×7.3×8.05 | yes/**3** | 43 (2) | 15.2 | **hit** | – | – | – | – | – | – | not reached | – | broken mesh warns 0.077 | 0 | none |
| T9 PIP hinge | PASS | **PASS** | teardrop_hinge_v1 | 100×50×6 | yes/2 | 40 (5) | 14.6 | at the limit (40), finished | yes | 6/6 | 100 | **0** (r6 1 hole edit) | yes | none (no photo overlay) | not reached | **2 / 2** | none | 0 | none |
| T7 bracket | PASS | **PASS with a caveat** | bracket_v1 | 125×**30**×125 (r6 16), 6 Ø5 holes | yes/1 | 44 (2) | 18.7 | **hit** after delivering | yes | 5/5 | 92 | **1, with reason: removed hole checks** because the bore counter found 0 of 6 holes in 1.5 mm sheet | yes | none | not reached | **0 / 6** (Euler −10); `count_holes` also returns 0 | none | 1 | none |
| T8 coin peg | weak PASS | **FAIL**: turn cap, validate failed `hole_count 0 vs 2` | none passing | 7.6×25.6×5.5 | yes/1 | 48 (5) | 10.1 | **hit** | null (no pass) | 6/6 | 72 | 0 | no (failed) | – | not reached | 0 / 0 | none | 0 | none |
| T10 glass pull | PARTIAL | **PASS** | glass_pull_v2 | 45×45×50, M5 4.2 blind | yes/1 | 34 (4) | 9.8 | no | yes | 7/7 | 100 | 0 | yes | medium (0.77) | not reached | 1 blind / 1 | none | 0 | none |

Overall: 4 PASS (gear, cap, T9, T10), 1 PASS with caveat (T7), 3 FAIL (strap hinge, screw, T8).
- **Turn-cap hits: r6 4/8 → r7 5/8.** This got worse.
- Plugin calls per run *fell* (2–12, about 4 on average). Total calls stayed at 34–48.
- The extra calls are reads of the plugin's own source:
  - strap hinge 15, T9 14, screw 9 (sed/grep of photopart/*.py, launcher.py, evals/);
  - plus terminal and vision probes.

**What improved:**
- No `name_v1.stl`.
- best_version filled on every passing sidecar.
- Every checklist answered.
- Score is out of 100.
- Validate auto-renders on pass.
- Thread crests no longer warn.
- T9 bores = 2 with no spec edit.
- Overlay now reports `confidence` and withholds IoU when it is low (gear). The washer fixture scores high.

**Did evals agree with the real-photo runs?** They agree on the mechanics, not on cost or holes:
- Evals have no thin-sheet or L-bracket bore case, so they missed the T7/T8 bore failures.
- `budget_hint` passes in-process, but in real runs the hint never fired: it counts plugin calls (max 12) while Hermes's cap counts all calls.
- `overlay_low_confidence` fails through Hermes because the agent "fixes" the roi.

## 3. Remaining issues, ranked
1. **Budget counts the wrong thing.** The hint triggers at 14 *plugin* calls, but agents hit Hermes's 40-call cap with 2–12 plugin calls. Fixes:
   - count the session's turns (or let the agent pass `turn` and `max_turns`), or trigger on wall-clock or on calls since the last validate;
   - add the cap to SKILL.md ("you have 40 tool calls in total; read no plugin source").
2. **Agents read plugin source** (up to 15 calls per run): features.py, parts.py, launcher.py, evals/. Signatures should come back from `photo_part_template`/`build` (e.g. `shape=strap_hinge, help=true` returns params plus an example script). Also move evals/ out of the installed plugin, or exclude it from the install.
3. **Bore counter misses holes in thin or L-shaped parts.** T7 found 0 of 6 Ø5 holes in 1.5 mm sheet; T8 got 0 vs 2. Slicing at 25/50/75% of the *whole-part* extent misses each leg's holes. `count_holes` (genus) also returned 0 on T7 although Euler is −10 (genus 6), which suggests `split` loses watertightness per shell. Fixes:
   - slice per planar region / per leg at mid-thickness, or ray-probe along face normals of large planar faces;
   - when bores=0 but genus>0, report "bores undetected" instead of failing hole_count;
   - add an eval with an L-bracket in 1.5 mm sheet with 6 holes.
4. **Eval sealing.**
   - Stage only the prompt and input files. Keep `fixture.json` / truth masks for the scorer.
   - Ship evals outside the installed plugin.
   - Anchor the leak regex to the plugin path.
   - Count calls from tool-call records, not from mentions.
   - Make `overlay_low_confidence` a scripted render with a fixed roi, so it doesn't depend on the agent's choice.
5. **The auto-render on validate does not use the photo.** No photo overlay is attached, so agents call render again (gear: 7 renders). Pass `photo`/`roi` from `last_measure.json` into the auto-render.
6. **`last_measure.json` lands in the plugin install dir** when `measure` gets no image. It falls back to the cwd, which is the plugin dir, and that file can feed the wrong px/mm to another project's overlay. Write it to the project dir instead (`out_dir`/`cwd` argument) and never to the plugin root.
7. **Real-photo overlay is still low on the gear** (partial gear held in a caliper). The confidence gate correctly says low; the next_step should suggest a seed or roi automatically.
8. Wrong skill id twice (`plugin:` first): strap hinge and T7.

Files: summary.png (photo | iso | overlay), collected.jsonl, */transcript.txt, hevals/*/{prompt.txt,transcript.txt,score.json}, evals_inprocess.json.
