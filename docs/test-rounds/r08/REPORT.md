# photo-to-part round 8: v0.1.9 (b31f963) vs r7 (0.1.8) and r6 (0.1.7)
Hermes v0.21.7, deepseek-v4.1-flash, --max-turns 40. No reinstall: doctor shows 0.1.9, 6 tools.

## 1. Evals
**In-process** (`--include-holdout`): **26/26** passed, holdouts 3/3, 6 tools registered.

**Hermes-driven:** 16 tasks, staged with `--stage` into r8/he/<id>.
- Staging is now sealed. Only `prompt.txt` was staged; for real_photo_overlay, `washer_photo.jpg` too. No fixture.json, no truth mask.
- The runner's `--transcript` reported 0 tool_calls for my export format (`<ts> TOOLCALL name {args}`), so it does not parse it. The calls below are counted from the Hermes session records in state.db.

| task | right? | calls (plugin) / budget | min / 5 | leak (runner / real) |
|---|---|---|---|---|
| box_matches_spec | yes | 8 (3) / 40 | 0.3 | no |
| box_dimension_error | yes | 13 (2) / 40 | 0.5 | no |
| hinge_five_knuckles | yes | 14 (5) / 40 | 0.7 | no |
| countersink_deeper_than_sheet | yes | 17 (1) / 40 | 0.8 | no |
| thin_wall_warning | yes | 18 (7) / 40 | 0.8 | no |
| print_in_place_gap | yes | 17 (3) / 40 | 0.6 | flagged; actually my harness: it read r8/evals_inprocess.json |
| worse_version_reverts (holdout) | yes | 27 (9) / 40 | 1.5 | no |
| template_default_name | yes | 8 (3) / 40 | 0.3 | no |
| best_version_filled | yes | 36 (5) / 40 | 2.0 | **yes**: read the plugin's evals/tasks.json and runner.py (git install still ships them) |
| checklist_bool_answered | yes | 21 (9) / 40 | 1.4 | no |
| bores_not_genus | still answered without tools (prompt is a statement, not a task) | 10 (0) / 40 | 0.5 | no |
| thin_l_bracket (new) | yes: 6 through bores, hole_count 6, score 100 | 19 (7) / 40 | 2.2 | no |
| thread_no_thin_wall | yes | 33 (14) / 40 | 2.5 | no |
| validate_renders_on_pass | yes | 25 (6) / 40 | 1.1 | no |
| real_photo_overlay (holdout) | **yes**: high confidence, IoU 0.77, chamfer 0.0066, pose error 1° | 26 (7) / 25, *1 over* | 4.1 | no |
| overlay_low_confidence | prompt-only and scripted; the agent correctly did nothing | 12 (0) / 40 | 0.5 | no |

Summary: 15/16 tasks done correctly. All but one are within budget (real_photo_overlay is 1 call over). One genuine leak (best_version_filled).

Bugs found by the eval agents:
- **Per-hole probe rows false-fail on fan-tessellated caps.** thin_l_bracket flagged 5 of 6 identical bores; washer v1 failed until the tessellation was rotated.
- **Thin-wall gate misses a 0.7 mm plate.** p5 reads 0.807 because the probe offset biases it up; 0.65 mm warns, 0.70 mm does not (reported by the thread_no_thin_wall agent).

## 2. Real-photo cases: r6 → r7 → r8
Dims were re-checked on copies in /tmp/r8v.
- "calls" = all tool calls from the session records.
- "hint" = the plugin's "Budget: deliver now" fired (✓) and whether the agent then stopped.
- "turn cap" = Hermes exited 1 at the 40-turn limit.

| case | r6 | r7 | **r8** | delivered | dims (mm) | WT / shells | calls (plugin) | min | turn cap | src reads r7→r8 | hint fired / followed | best ver | checklist | score /100 | spec edits | auto-render | overlay conf (IoU) | bores (spec hole_count) | thread thin-wall | wrong id | deleted |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| spur gear | PASS | PASS | **PASS** | gear_v1 | 45×45×20 | yes/1 | 46 (13) | 26.8 | **hit** after delivering | 1→0 | ✓ at 25 and 27 calls / **no**, 9 renders in total | self | 3/3 | 100 | 0 | yes, with the photo | medium (0.55); r7 low | 1=1 | none | 1 | none |
| bottle cap | PASS | PASS | **PASS** | cap_v2 (v1 was 41.2 OD, fixed) | 33×33×17 | yes/1 | 26 (6) | 11.8 | no | 1→1 | not reached | self | 4/4 | 100 | 0 | yes | medium (0.90) | 1=1 | none | 1 | none |
| strap hinge | PASS | FAIL | **FAIL** | none | – | – | 47 (3) | 10.7 | **hit** | 15→2 | not reached by the plugin counter (calls_used 16) | – | – | – | – | – | – | – | – | 0 | none |
| M3 screw | PARTIAL | FAIL | **PASS** (dims questionable) | m3_flange_hex_v2 | 6.0×6.0×9.78 (4.8 A/F, 6.0 flange measured) | yes/1 | 44 (12) | 22.0 | no (exit 0) | 9→0 | ✓ / yes, delivered | self | 4/4 | 95 | 1, with reason | yes | medium (0.16), then low | 0=0 | **warns 0.088** (thread built in a script, faces untagged) | 0 | none |
| T9 PIP hinge | PASS | PASS | **PASS** | hinge_v1 | 100×50×6 | yes/2 | 28 (9) | 9.8 | no | 14→0 | not reached | self | 0/0 (no features) | 95 | 1 (shells 2, with reason) | yes | medium (0.59) | 2=2 | gap 0.20 warn (0.4 diametral, correct per 0.3/side rule) | 0 | none |
| T7 bracket | PASS | PASS* | **PASS** | angle_bracket_v1 | 125×**40**×125 (r7 30, r6 16), 6 holes | yes/1 | 28 (7) | 18.5 | no | 3→0 | not reached | self | 4/4 | 100 | **0** (r7 removed the hole check) | yes | medium (0.30) | **6 = 6 ✓** (r7 0 of 6) | none | 0 | none |
| T8 coin peg | weak PASS | FAIL | **PASS** | minipeg_leg_v1 | 7.86×3.0×26.15 | yes/1 | 35 (7) | 13.6 | no | 1→0 | not reached | self | 0/0 | 95 | 0 | yes | low → medium (0.87) after seed/box | **1 = 1 ✓** (r7 0 vs 2) | thin area 1.2% warn (jaw tip) | 0 | none |
| T10 glass pull | PASS | PASS | **PASS (late)** | glass_pull_v5 (byte-identical to v1) | 45×45×50 | yes/1 | 42 (21) | 15.3 | **hit** after delivering | 0→0 | ✓ at 29 and 33 / **no**, kept fighting the hole probe | self | 5/7 | 94.3 | **6 edits**, all moving hole probe planes | yes | none recorded | blind M5 via probe | none | 0 | none |

Totals:
- **r8: 7 of 8 PASS** (r7: 4 PASS + 1 caveat; r6: 5 PASS).
- **Turn-cap hits: 3 of 8** (r7 5, r6 4), and 2 of those 3 had already delivered.
- **Plugin-source reads: 0–2 per run** (r7 up to 15). help/describe modes were used in 7 of 8 runs.

**What still fails:**
- **Strap hinge:** the agent wrote a build123d script; build123d is not installed, so it hit `ModuleNotFoundError`, then spent 26 terminal and 11 patch calls. It never used the strap_hinge template's mesh.
- **calls_used undercounts:** it counts plugin calls plus some others, not Hermes turns. Strap hinge showed 16 at 47 real calls, so the hint never fired there.

## 3. Evals vs real photos
- They agree on bores (thin_l_bracket ↔ T7/T8), sealing, checklist, best version and auto-render.
- They disagree on:
  - **budget-following:** agents ignore the hint when the overlay or hole probe keeps failing;
  - **per-hole probe friction** (T10 made 6 spec edits);
  - **build-script failure modes** (missing build123d).

## 4. Remaining issues, ranked
1. **Per-hole probe rows are fragile.** T10 made 6 spec edits and an identical re-upload; thin_l_bracket and the washer false-failed. When a probe disagrees with the bore list, trust the bore detector (diameter and through/blind already exist) and drop the probe failure to a warning, or derive probes from detected bores.
2. **Budget is undercounted and hints are not binding.**
   - `calls_used` misses non-plugin calls.
   - After the 80% hint, agents kept rendering and validating.
   - Fix: let the agent pass the turn count, or refuse non-deliver renders after the 80% mark (return "budget: deliver <best> now; render refused").
3. **build123d (or cadquery) imports in build scripts fail without guidance.** The error should say "build123d is not available; use photopart.features / trimesh / manifold3d", and the skill should name the allowed libraries.
4. **Thin-wall gate edge case.** A 0.70 mm plate passes because of probe-offset bias in p5. Untagged threads from build scripts still warn (M3). Export a `tag_faces()` helper, or auto-tag helical features from features.thread.
5. **Eval scorer cannot parse a Hermes state.db export.** Add a `--hermes-session ID` or state.db reader so scores don't depend on the transcript format. Also, a git install still ships evals/ (one leak).
6. **Overlay still medium or low on hard photos** (M3 0.16, T7 0.30). The confidence gate is honest about it. This is low priority.
7. Wrong skill id in 2 of 8 runs (gear, cap) despite the more prominent id.

## Catalog recommendation
**Pin v0.1.9.** Reasons:
- It is the first round where 7 of 8 real-photo cases deliver a validated, watertight part with correct key dims and an honest overlay confidence.
- It fixes the r7 regressions (bores, source reading, turn-cap rate).
- The in-process suite and all sealed tasks pass.

Before or with the pin:
- Note the known limits: per-hole probe friction, build123d not bundled, best-effort budget hints.
- Track issues 1–3 for 0.1.10.
- The strap-hinge failure is an agent and library-choice problem, not a plugin defect, so it should not block the pin.

Files: summary.png (photo | iso | overlay; the M3 row shows an agent crop as the "photo"), collected.jsonl, */transcript.txt, he/*.
