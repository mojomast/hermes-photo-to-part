# photo-to-part round 9: v0.1.10 (e64fbc6) vs r8 (0.1.9) and r7 (0.1.8)
Hermes v0.21.7, deepseek-v4.1-flash, --max-turns 40. No reinstall: doctor shows 0.1.10, 6 tools.

## 1. Evals
**In-process** (`--include-holdout`): 26/26 passed, holdouts 3/3, 6 tools.

**Hermes-driven:** 16 sealed tasks, staged with `--stage`, scored with `--hermes-session <id>`. "Mine" = my own count from the state.db records.

| task | right? | calls: scorer / mine (plugin: scorer / mine) | min (wall clock) | budget | leak: scorer / real |
|---|---|---|---|---|---|
| box_matches_spec | yes | 8/8 (0/3) | 0.4 | 40 | no/no |
| box_dimension_error | yes | 17/17 (0/4) | 0.6 | 40 | no/no |
| hinge_five_knuckles | yes | 12/12 (0/4) | 2.7 | 40 | no/no |
| countersink_deeper_than_sheet | yes | 8/8 (0/0) | 0.4 | 40 | no/no |
| thin_wall_warning | yes | 13/13 (0/5) | 0.7 | 40 | no/no |
| print_in_place_gap | yes | 12/12 (0/3) | 0.6 | 40 | no/no |
| worse_version_reverts (holdout) | yes | 23/23 (0/8) | 1.5 | 40 | no/no |
| template_default_name | yes | 6/6 (0/3) | 0.3 | 40 | no/no |
| best_version_filled | yes | 33/33 (0/7) | 1.7 | 40 | **no / YES**: read evals/runner.py, README, tasks.json |
| checklist_bool_answered | yes | 24/24 (0/12) | 2.0 | 40 | no/no |
| bores_not_genus (rewritten as a task) | **yes, now uses tools** | 23/23 (0/16) | 3.4 | 40 | no/no |
| thin_l_bracket | yes | 15/15 (0/6) | 1.2 | 40 | no/no |
| thread_no_thin_wall | yes | 26/27 (0/9) | 1.5 | 40 | no/no |
| validate_renders_on_pass | yes | 23/23 (0/6) | 1.3 | 40 | no/no |
| real_photo_overlay (holdout) | yes | 21/21 (0/6) | 2.8 | 25 ✓ (r8 was 1 over) | no/no |
| overlay_low_confidence (scripted) | yes, did not change the mesh | 24/25 (0/0) | 1.5 | 40 | no; read photopart source, 6 calls |

Summary: 16/16 correct and all within budget (r8: 15/16, one over).

**Scorer vs session records:**
- `tool_calls` now matches: 14 of 16 exactly, the other 2 off by 1.
- **`plugin_calls` is always 0.** Hermes wraps plugin tools in `tool_call {"calls":[{"name":"photo_part_*"}]}`, and the scorer doesn't look inside.
- **`minutes` is null** for every session.
- **Leak detection in session mode missed the one real leak**: best_version_filled read evals/runner.py 4 times. In r8, transcript mode flagged the same thing.

## 2. Real-photo cases: r7 → r8 → r9
Dims were re-checked on copies in /tmp/r9v.
- "plugin count" = the last `calls_used` the plugin reported, vs the real session calls.
- No budget **refusal** ("render refused") fired in any run. Every post-80% call was a new-version build, its first validate, or a final render, all of which are allowed.
- Spec edits = entries in spec.json.freeze.json.

| case | r7 | r8 | **r9** | delivered | dims (mm) | WT / shells | calls (plugin) | min | turn cap | src reads | plugin count / real | budget hints (remaining) → response | refusal | spec edits | score | checklist | overlay conf (IoU) | holes | thin-wall warn | wrong id |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| spur gear | PASS | PASS | **PASS** | spur_gear_v1 | 45×45×20 | yes/1 | 20 (5) | 14.2 | no | 0 | 15/20 | none needed | – | 0 | 100 | 4/4 | medium (0.22) | 1=1 | none | 0 |
| bottle cap | PASS | PASS | **PASS** | bottlecap_v3 | 33×33×17 | yes/1 | 44 (12) | 15.9 | no (exit 0) | 0 | 40/44 | 16→2→0 → built v3, validated, final render, delivered | no | 0 | 95 | 4/4 | **high (0.91)** | – | **min wall 0.26** (r8 none; thread from a build script, untagged) | 1 |
| strap hinge | FAIL | FAIL | **PASS** | strap_hinge_v2 | 400×70×4 | yes/1 | 35 (8) | 18.6 | no | 0 | 26/35 | 14 → delivered v2 | – | 0 | 100 | 6/6 | "high" but IoU 0.36 | – | none | 0 |
| M3 screw | FAIL | PASS? | **PASS?** | m3_flange_hex_screw_v1 | 8.1×8.1×9.2 (r8 6.0×6.0×9.78; true M3 flange ≈ 6.4–7) | yes/1 | 35 (6) | 15.3 | no | 0 | 29/35 | 2 hints → delivered | – | 0 | 95 | 4/4 | high (0.81) | 0 | **0.076** (thread in a build script, untagged) | 1 |
| T9 PIP hinge | PASS | PASS | **PASS** | teardrop_piano_hinge_v3 | 100×50×6 | yes/2 | 33 (9) | 10.0 | no | 0 | 23/33 | none | – | 0 | 100 | 5/5 | no photo overlay | – (no hole row) | none (r8 had a gap warning) | 0 |
| T7 bracket | PASS* | PASS | **PASS** | angle_bracket_v1 | 125×125×25 (width 25) | yes/1 | 40 (5) | 27.1 | at 40, finished | 0 | 38/40 | 7→3→2 → validate, 2 final renders, delivered | – | 0 | 100 | 3/3 | medium (0.30) | **6=6 ✓** | none | 0 |
| T8 coin peg | FAIL | PASS | **FAIL** | none | – | – | 43 (1: measure) | 8.8 | **hit** | 0 | 38/43 | first hint only at "2 of 40" | – | – | – | – | – | – | – | 1 |
| T10 glass pull | PASS | PASS (late) | **PASS** | drawer_pull_rosette_v8 | 45×45×50 | yes/1 | 41 (15; 10 builds) | 18.3 | no (exit 0) | 0 | 40/41 | 11→9→2→0 → built, validated, rendered v8 | – | **0** (r8: 6) | 100 | 3/3 | medium (0.82) | – | none | 0 |

Totals:
- **r9: 7 of 8 deliver** (r8 7/8, r7 4–5/8).
- **Turn-cap hits: 1** (r8 3, r7 5).
- **Spec edits: 0 in every run** (r8 T10 had 6). The probe→warning change worked.
- **Plugin-source reads: 0** in every real-photo run.
- **Strap hinge is fixed.** The agent called `photo_part_template shape=strap_hinge describe=true` and `shape=scroll describe=true`, then wrote its own trimesh/numpy build script (it did not use the template mesh directly). It built v1 and v2, answered the checklist with `--answer`, validated at 100 and rendered final. No build123d this time.
- **T8 regressed** (r8 PASS → r9 FAIL). The agent made one `photo_part_measure` call, then 32 terminal calls measuring pixels by hand with cv2/PIL, and never built. Because the plugin only speaks when it is called, the 60% and 80% hints could not fire; the first hint arrived at "2 of 40 remain".

**Plugin call count vs real:** it lags by 1–9 calls. `calls_used` is supplied by the agent in the arguments, and the state.db count looks like a lower bound. It is close near the end (40/41, 40/44, 38/40) and low early (15/20, 26/35, 23/33).

## 3. Evals vs real photos
- They agree on: probe warnings (no spec edits), bores, sealing, budget-following, and the rewritten bores task now using tools.
- They miss two real-photo failure modes:
  - **an agent that stops calling plugin tools** and probes images by hand (T8), which no eval covers;
  - **thin-wall false positives on threads built in scripts** (cap, M3). The eval only checks template-made threads.

## 4. Remaining issues, ranked
1. **Agents that bypass the plugin get no budget pressure** (T8). Options:
   - make the skill require `photo_part_measure` for scale and dims, with "do not measure pixels by hand";
   - have `photo_part_measure` return the part bbox/ROI in mm from a seed/box, so there is less reason to probe;
   - add a real-photo eval with a small part next to a coin.
2. **Thread/knurl tagging only covers templates.** Threads built in scripts still warn (cap 0.26, M3 0.076). Have `photopart.features.external_thread/internal_thread/knurl` tag faces automatically when a build script imports them, and write `<stl>.faces.json` from `photo_part_build` (check whether the cap and screw scripts used the features helpers; the warning suggests the tags were lost after the union).
3. **Scorer gaps in `--hermes-session` mode:**
   - parse `tool_call {"calls":[…]}` for plugin_calls;
   - compute minutes from message timestamps;
   - apply the leak regex to tool-call arguments. It missed `read_file …/evals/runner.py`.
4. **Overlay confidence vs IoU disagree.** The strap hinge is "high" at IoU 0.36 because confidence measures segmentation stability, not fit. Either rename it (`segmentation_confidence`) or fold chamfer and IoU into it.
5. **Dimension plausibility for measured small parts.** The M3 flange came out 8.1 mm (r8 6.0). Have measure output feed the spec, and warn when a stated standard (M3) disagrees with measured sizes.
6. Wrong skill id in 3 of 8 runs (cap, M3, T8), still with the `plugin:` prefix. Minor; Hermes recovers in one call.
7. A git install still ships evals/ (one real eval leak).

## Catalog recommendation
**Pin v0.1.10.** Compared with 0.1.9 it:
- keeps 7/8 delivery and fixes the long-standing strap hinge;
- cuts turn-cap hits from 3 to 1;
- eliminates spec-edit churn (0 edits) and source reads (0);
- brings every sealed eval within budget.

The one failure (T8) is an agent bypassing the plugin, not a plugin defect. No regression blocks the pin. Track issues 1–3 for 0.1.11.

Files: summary.png (photo | latest iso | latest overlay; the strap-hinge iso shown may be v1's render), collected.jsonl, evals_inprocess.json, */transcript.txt, he/*/score.json.
