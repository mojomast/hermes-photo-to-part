# photo-to-part round 10: v0.1.11 (6ab3e1d) vs r9 (v0.1.10)
Hermes home /workspace/hermes-p2p, deepseek-v4.1-flash via opencode-go, --max-turns 40. Doctor: 0.1.11, 6 tools, 3 hooks. Repo unchanged.

## 0. Why attempts 1 and 2 failed: harness and box, not v0.1.11
Raw logs are kept in attempt1_stalled/ and attempt2_killed/.

**Attempt 1** (started 09:31, every run ended 10:05:38–39 with exit 130 = SIGINT).
- All 8 runs made their last tool calls between 09:32 and 09:34, then went silent for about 31 min.
  - T9: last tool result 09:33:16, then "Operation interrupted: waiting for model response (1942.0s elapsed)".
  - Gear: `vision_analyze` started 09:34:00 and returned "timed out after 420.0s" only at 10:05:39.
- **The hooks were not the cause.** `.photopart/calls.jsonl` shows the pre/post hooks logging each call within the same second as the tool (e.g. T9: 14:31:47Z, 14:31:48Z, 14:31:51Z…). `budget.json` was written at the same timestamp as the last tool result, and no tool result was ever held up waiting on a hook.
- The 16 sealed evals running alongside all finished normally (exit 0, 0.4–2.7 min).
- **What happened instead:**
  - Box load average was about 95–98 on 8 cores at 10:05, from other agents' jobs (colab-mcp, desktop sessions, fetch_day.py…).
  - The model provider and Hermes vision calls stalled.
  - My blocking Shell wait then hit the 840 s tool limit; the tool killed the shell and SIGINT reached the child `hermes chat` processes. That is why everything stopped at the same second.
- The 34-min / 16-call gear run is that stall: 2 min of work, about 31 min frozen, then killed.

**Attempt 2** (10:06–10:18): all 8 exited 130 at the same moment after about 700 s, when the box connection dropped. They were launched as children of that shell.

**Attempt 3:** launched with `setsid nohup`. All 8 completed normally (exit 0).

Two sealed evals had timed out under the same load (real_photo_overlay, coin_scale_sealed; exit 124, kept as `*_attempt1_timeout`). Both were re-run and passed.

**Conclusion:** no v0.1.11 defect. The causes were provider/vision slowness under box overload plus my harness's process-group handling. Future rounds should launch detached.

## 1. Sealed evals
**In-process** (`--include-holdout`): **28/28** passed, holdouts 4/4, 6 tools.

**Hermes:** 18 sealed tasks, all done correctly.
- Scorer counts now match the session records: tool_calls equal to my count in every task, and **plugin_calls is now non-zero and matches** (r9 was always 0). Minutes are reported.
- Leaks: 0 by the scorer; 0 reads of `plugins/photo-to-part/{evals,photopart}` in the records. Wrong skill ids: 0.

| task | calls (plugin) | min | right? |
|---|---|---|---|
| box_matches_spec | 7 (3) | 0.4 | yes |
| box_dimension_error | 19 (3) | 0.7 | yes |
| hinge_five_knuckles | 11 (4) | 0.7 | yes |
| countersink_deeper_than_sheet | 22 (1) | 2.1 | yes |
| thin_wall_warning | 15 (5) | 0.8 | yes |
| print_in_place_gap | 16 (5) | 0.8 | yes |
| worse_version_reverts (holdout) | 33 (5) | 1.8 | yes |
| template_default_name | 4 (3) | 0.2 | yes |
| best_version_filled | 20 (8) | 1.7 | yes; **no leak** (r9 read runner.py) |
| checklist_bool_answered | 20 (6) | 1.3 | yes |
| bores_not_genus | 24 (16) | 2.7 | yes |
| thin_l_bracket | 14 (5) | 1.4 | yes |
| thread_no_thin_wall | 25 (10) | 1.6 | yes |
| thread_from_script_no_thin_wall (new) | 18 (9) | 2.1 | yes |
| validate_renders_on_pass | 12 (2) | 0.9 | yes |
| real_photo_overlay (holdout, rerun) | 25 (6) / 25 | 5.0 | yes |
| overlay_low_confidence (scripted) | 12 (0) | 0.8 | yes (no mesh change) |
| coin_scale_sealed (new, rerun) | 15 (2) | 1.4 | yes: "both runs inside the 5% band", measured via photo_part_measure |

## 2. Real-photo cases, r9 → r10 (attempt 3)
- Dims were re-checked on copies in /tmp/r10v.
- "hook count" = calls in `.photopart/budget.json` vs the real session records.
- Notes = the 60/80/95% notes the hook added to tool results.

| case | r9 | **r10** | delivered | dims (mm) | WT / shells | calls (plugin) | min | turn cap | hook count / real | notes fired → response | src reads | pixel probes (cv2/PIL) | spec edits | score | checklist | overall / segm. conf (IoU) | holes | thin-wall warn | standards | wrong id |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| spur gear | PASS | **PASS** (one concern) | spur_gear_v2 | 45×45×**23** (adds an assumed 3 mm hub boss over the stated 20 face width; documented in the spec) | yes/1 | 27 (8) | 21.2 | no | 27/27 | 60% → delivered | 0 | 0 | 0 | 100 | 3/3 | low/low (null) | 1=1 | none | – | 0 |
| bottle cap | PASS (0.26 thin-wall FP) | **PASS** | bottle_cap_v4 | 33×33×17 | yes/1 | 26 (8) | 17.2 | no | 26/26 | 60% | 0 | 0 | 0 | 100 | 6/6 | medium/medium (0.90) | 1=1 | **none** ✓ (also none on my untagged copy) | – | 1 |
| strap hinge | PASS | **PASS** | strap_hinge_v2 | 400×69.3×4 | yes/1 | 43 (10) | 18.2 | no (exit 0) | 42/43 | 60→80→95%, plus "13 / 3 / 0 remain" → validated and delivered | 1 | 1 | 1 (removed the knuckle check, with reason: "knuckle probe reports 7 rounded-link features on a plate that has none") | 100 | 5/5 | **medium** / high (0.38); r9 said "high" at 0.36 ✓ | 4=4 | none | – | 1 |
| M3 screw | PASS? (8.1 flange, 0.076 FP) | **PASS** | m3_flange_hex_screw_v3 | 7.0×7.0×9.15 (flange 7.0, close to ISO M3 flange ≈ 6.4–7.0) | yes/1 | 35 (12) | 22.1 | no | 34/35 | 60→80% → delivered v3 | 0 | 0 | 0 | 92 | 5/5 | medium/medium (0.60; v1 low at 0.07) | 0 | **none in the agent sidecar** ✓; my copy without faces.json warns 0.70 mm, so tags are sidecar-based | no M3 warning (flange 7.0 is within range) | 0 |
| T9 PIP hinge | PASS | **PASS** | teardrop_hinge_v3 | 100×50×6 | yes/2 | 32 (7) | 15.6 | no | 30/32 | 60% | 0 | 0 | 0 | 100 | 5/5 | no overlay | **0 of 2 "undetected"** (warning; r8 found 2) | none | – | 0 |
| T7 bracket | PASS | **PASS** | angle_bracket_v3 | 125×25×125, 6 holes | yes/1 | 28 (8) | 19.5 | no (r9: at 40) | 28/28 | 60% | 0 | 0 | 0 | 100 | 5/5 | low/low (null) | 6=6 | none | – | 0 |
| T8 coin peg | **FAIL** (32 hand pixel probes) | **PASS** ✓ | jaw_half_v1 | 3.2×26.1×3.0 (one leg; r8 7.86×3×26.15) | yes/1 | 30 (11) | 15.0 | no | 30/30 | 60% | 0 | **0** (3× `photo_part_measure coin=euro_1 auto=true part_seed=…`) | 0 | 100 | 4/4 | low/low | – | none | – | 0 |
| T10 glass pull | PASS (10 builds) | **PASS** | glass_pull_v2 | 45×45×50 | yes/1 | 28 (7) | 13.7 | no | 28/28 | 60% | 0 | 1 | 0 | 100 | 7/7 | **low** / medium (0.44) | 1=1 | none | **false positive**: "M5: measured 45.0 mm is 33.6 mm from flange diameter 11.4 mm (ISO 4162)" (compares the 45 mm rosette to an M5 screw flange) | 0 |

**Totals:**
- **8 of 8 PASS** (r9: 7/8).
- **0 turn-cap hits** (r9: 1 hit, plus T7 at exactly 40).
- Calls 26–43, versus 20–44 in r9.
- Hook budget count matches the real calls within 0–2 (r9's plugin count lagged by 1–9).
- Source reads: 0 except 1 (strap hinge).
- Spec edits: 1 (strap hinge, with a reason).
- Wrong skill id: 2 (r9: 3).

## 3. Checks requested vs r9
- **T8:** the agent used `photo_part_measure` (coin auto-detect plus part_seed) three times and made 0 cv2/PIL probes (r9: 32). Only the 60% note fired (at 24 calls), and the run delivered at 30 calls. Fixed.
- **Thin-wall false positives:** gone on the cap and the screw. Note: the tags live in the build sidecar; a copy of the STL without `.faces.json` warns again (screw 0.70 mm), so the tags are not purely geometric at validate time.
- **M3 flange warning:** none, because the flange came out 7.0 mm (plausible). The standards check did misfire on T10 (rosette OD vs M5 flange).
- **Skill-id errors:** 2 of 8 (cap, strap hinge), versus 3 in r9. I did not check whether the hook rewrites the wrong id.
- **Turn-limit hits:** 0 (r9: 1).
- **Source reads / spec edits:** 1 / 1. The strap-hinge edit removed the knuckle check because the probe found 7 "knuckles" on a flat scroll plate. That is a knuckle-probe false positive on scroll links.
- **overall_confidence vs fit:** now tracks IoU. Strap hinge: seg high / overall medium at 0.38. Glass pull: overall low at 0.44. Screw: low at 0.07, medium at 0.60. Gear, T7 and T8 are low with IoU null. The overall label is honest; IoU on hard photos is still low.

## 4. Remaining issues, ranked
1. **Standards false positive:** the standards check applies an "M5" mention to the part's overall diameter (T10). Match designations only to thread or flange features, or to dims named in the spec.
2. **Knuckle probe false positive on scroll/link plates** (strap hinge), which led to a spec edit. Skip the knuckle check unless the spec declares knuckles or a hinge template was used.
3. **Bores undetected on the T9 print-in-place hinge** (0 of 2, warning only). r8 found 2.
4. **Thread tags depend on the `.faces.json` sidecar.** A copied STL loses them. Detecting helical or periodic regions from the mesh would make validation portable.
5. Overlay fit is still low on the gear, T7 and T8 (IoU null). Honest, but weak.
6. Wrong skill id in 2 of 8 runs.
7. Gear z = 23 (assumed hub) vs the user's 20 mm face width. The agent added an assumed feature that changes a user-given dim. The spec could flag a user-stated dim being exceeded.

**Harness lesson (mine):** launch Hermes runs with setsid/nohup and poll in the background. Blocking waits on an overloaded box killed two attempts.

## Recommendation
**v0.1.11 is at least as good as v0.1.10 and better on every tracked metric:**
- 8/8 vs 7/8;
- 0 turn-cap hits vs 1;
- T8 fixed without pixel probing;
- thin-wall false positives gone;
- budget count accurate;
- scorer counts correct, and 18/18 sealed evals pass.

The stalls were box/provider load, not the hooks. **Pin v0.1.11.** Issues 1–3 are worth a 0.1.12.

Files: summary.png (photo | iso | overlay), collected.jsonl, evals_inprocess.json, he_scores_part1.txt, he/*/score.json, attempt1_stalled/, attempt2_killed/.
