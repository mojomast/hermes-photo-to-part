# photo-to-part round 11: v0.1.12 (7f65735) vs r10 (v0.1.11)
- Setup: Hermes home /workspace/hermes-p2p, deepseek-v4.1-flash via opencode-go, --max-turns 40. Doctor: 0.1.12, 6 tools, 3 hooks. Repo and catalog PR unchanged.
- Smoke call at 12:12 EST answered "OK". All runs were launched detached (setsid nohup) at 12:12:54 EST; evals ran 6 at a time. Peak load was 7.2 on 8 cores, so nothing was throttled. Every run exited 0.
- attempt1_auth401/ and REPORT_attempt1_auth401.md hold the 11:48 attempt, which failed on the expired key (26 runs × HTTP 401, 0 tool calls).

## 1. Sealed evals
- **In-process:** 28/28 pass, holdouts 4/4 (evals_inprocess.json).
- **Hermes:** 18 tasks run. All runs below are clean: no leaks, 0 wrong ids, 0 skill-id rewrites counted by the scorer.
- **Harness contamination (my fault):** I had left evals_inprocess.json/.txt in the round folder, the parent of he/.
  - coin_scale_sealed and validate_renders_on_pass read them (scorer leak=True).
  - I moved the files out and reran both tasks; the clean reruns are in the table. The contaminated runs are kept as `*_attempt2_leak_harness`.
  - In the leaked coin run the agent also read `plugins/photo-to-part/scripts/make_fixture.py`, which ships with the plugin.

| task | r10 calls (plugin) / min | r11 calls (plugin) / min | r11 outcome |
|---|---|---|---|
| box_matches_spec | 7 (3) / 0.4 | 9 (3) / 0.4 | ok, stops at "every check passed" |
| box_dimension_error | 19 (3) / 0.7 | 15 (6) / 1.0 | ok, fails validation as intended |
| hinge_five_knuckles | 11 (4) / 0.7 | 14 (7) / 1.0 | **wrong: spec knuckles=4.** The agent passed `knuckles: 5` at the top level instead of in `params`. The template silently ignored it and used its default of 4, and the agent kept 4 per the prompt. r10 got 5. |
| countersink_deeper_than_sheet | 22 (1) / 2.1 | 10 (0) / 0.9 | ok, rejected |
| thin_wall_warning | 15 (5) / 0.8 | 10 (4) / 1.0 | ok |
| print_in_place_gap | 16 (5) / 0.8 | 19 (8) / 2.1 | ok |
| worse_version_reverts (holdout) | 33 (5) / 1.8 | 20 (6) / 1.0 | ok, reverted to v1 |
| template_default_name | 4 (3) / 0.2 | 7 (3) / 0.3 | ok |
| best_version_filled | 20 (8) / 1.7 | 14 (7) / 1.8 | ok |
| checklist_bool_answered | 20 (6) / 1.3 | 15 (6) / 1.2 | ok |
| bores_not_genus | 24 (16) / 2.7 | 36 (19) / 12.8 | ok, but slow |
| thin_l_bracket | 14 (5) / 1.4 | 20 (5) / 2.2 | ok, 6 through holes |
| thread_no_thin_wall | 25 (10) / 1.6 | 23 (16) / 2.9 | ok |
| thread_from_script_no_thin_wall | 18 (9) / 2.1 | 32 (12) / 4.2 | ok |
| validate_renders_on_pass (clean rerun) | 12 (2) / 0.9 | 20 (7) / 1.7 | ok |
| real_photo_overlay (holdout) | 25 (6) / 5.0 | 22 (9) / 10.0 | ok, all four criteria |
| overlay_low_confidence | 12 (0) / 0.8 | 15 (5) / 1.5 | ok |
| coin_scale_sealed (clean rerun) | 15 (2) / 1.4 | 19 (3) / 2.8 | ok, but the stage again has no photo, so the agent drew its own fixture. It also listed r10 dirs looking for one. |

**Result: 17/18 correct.** hinge_five_knuckles is wrong, so its pass is spec-consistent but not what was asked.

**Scorer:** the new `skill_id_rewritten` counter reports 0 on every run. But 4 of the 8 photo sessions called `skill_view("plugin:photo-to-part:…")`, and the scorer reports those as wrong_skill_ids=0 and rewritten=0. So the rewrite counter undercounts.

## 2. Real-photo cases, r10 → r11

| case | r10 | **r11** | file | dims (mm) | WT/shells | calls (plugin) | min | hook/real | notes | src reads | measure | spec edits | score | checklist | seg/overall (IoU, trusted) | rows | wrong id |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gear | PASS, z 23 (assumed hub) | **PASS** ✓ | spur_gear_v2 | 45×45×**20** (user face width kept; no hub added) | y/1 | 28 (11) | 30.5 | 28/28 | 60 | 0 | 3 | 0 | 100 | 5/5 | medium/medium (0.66, **trusted**); r10 low (null) | holes 1=1 | 0 |
| bottle cap | PASS | **PASS** | cap_v3 | 33×33×17 | y/1 | 37 (15) | 14.0 | 35/37 | 60, 80 | 0 | 4 | 0 | 100 | 4/4 | high/medium (0.87, trusted) | – | 1 |
| strap hinge | PASS, 1 spec edit (knuckles) | **PASS** ✓ | strap_hinge_400_v3 | 400×70×4 | y/1 | 33 (10) | 19.0 | 33/33 | 60, 80 | 0 | 0 | **0** | 95 | 4/4, one answered "no" (rivet holes) | medium/medium (0.39, trusted) | knuckles 0=0 ("7 by rings, 0 cylinders", warning only) | 1 |
| M3 screw | PASS, 0.70 thin wall on copy | **PASS** ✓ | i_screw_v2 | 6.9×6.9×11.2 | y/1 | 36 (13) | 18.5 | 36/36 | 60, 80 | 0 | 3 | 0 | 100 | 3/3 | medium/**low** (0.17, trusted) | 0 holes | 0 |
| T9 PIP hinge | PASS, holes 0 vs 2 shown as a warning | **PASS** | teardrop_piano_hinge_v4 | 100×50×6 | y/2 | 39 (11) | 21.4 | 38/39 | 60, 80 | 0 | 0 | 1 (template default 4 → user's 5 knuckles, with reason) | 100 | 6/6 | low/low (0.40, **untrusted**) | knuckles **5=5** ✓; pin bore spec'd as a hole, with "Bore: none" warning | 1 |
| T7 bracket | PASS, 125×25×125 bent | **PASS** | l_plate_v1 | 125×125×1.5: modelled as a flat L plate (matches the photo; r10 modelled a 90° bend) | y/1 | 27 (7) | 25.7 | 27/27 | 60 | 0 | 2 | 0 | 100 | **0/0** (no checklist written) | low/low (0.16, untrusted) | holes 6=6 | 1 |
| T8 coin peg | PASS | **PASS** | minipeg_leg_v1 | 26.1×6.0×3.8 | y/1 | 26 (9) | 18.1 | 24/26 | none | 0 | 5 | 0 | 100 | 4/4 | low/low (0.16, untrusted) | holes 1=1 | 0 |
| T10 glass pull | PASS, M5 false positive | **PASS** | glass_drawer_pull_v4 | 45×45×50 | y/1 | 33 (11) | 12.9 | 33/33 | 60, 80 | 0 | 1 | **1** (hole_count 1 → 2) | 100 | 4/4 | low/low (0.44, untrusted) | holes 2=2 | 0 |

**Totals:**
- **8/8 PASS** (r10: 8/8). All runs exit 0, so 0 turn-cap hits.
- Source reads 0 (r10: 1).
- Spec edits 2 (r10: 1).
- Wrong skill id in 4/8 runs (r10: 2/8). The 4 are the cap, strap hinge, T9 and T7, by my count from the session records.
- Hook budget counts match the real calls within 0–2.
- No 3MF was written in any case (none was asked for), so the 3MF thread metadata is untested.
- "Pixel" probes are image-size reads (`Image.open(...).size`), with 0–3 per case. None of them is hand measurement.

## 3. Specific checks
- **The offline T9 regression (holes 1/2, knuckles 1/5, score 66.7) does not show up live.**
  - The live v4 mesh detects knuckles 5=5 and validates ok at 100.
  - The live spec has no hole_count row. The pin bore is given as one explicit hole, and the bore detector reports "Bore: none" as a warning.
  - The offline failure came from r10's mesh and spec (knuckles 5, hole_count 2) under the 0.1.12 detectors. The new detectors are stricter on that geometry.
  - Bore detection inside print-in-place knuckles is still not working; it shows only as a warning.
- **Copied-screw thin-wall: fixed.**
  - The r11 screw copy (STL plus spec, no sidecar) gives no thin-wall warning.
  - The r10 screw copy still warned 0.70 mm under 0.1.12, so geometric thread detection works on r11's mesh but not on r10's.
- **Cap/T7 score drops: an artifact of my copy check.**
  - On copies, the checklist answers are missing, because they live in the agent's validation sidecar and not in spec.json.
  - Unanswered items cost points: the r10 cap copy had 0/6 answered → 80, and T7 had 3 of 5 unanswered → 84.
  - In live runs both score 100.
  - The same effect explains the r11 copies: screw 80 (0/3 answered), T8 80 (0/4). T9's copy failure ("2 shells") is only because I didn't pass expected_shells.
  - Recorded in offline_copycheck_r11.jsonl.
- **Gear tolerance warning:** not triggered, because the agent kept z=20 and added no assumed hub. The warning itself is untested live.
- **T10 standards:** no M5-vs-rosette warning ✓.
  - New false positive instead: the circle-fit bore detector counts the 23.5 mm decorative rosette dish as a bore, so the agent edited hole_count from 1 to 2, with a reason.
- **Strap hinge:** the cylinder knuckle detector gives 0, so no spec edit ✓. The legacy ring probe still says 7 but is downgraded to a warning.
- **Overlay:** IoU is now always reported, with `iou_trusted`.
  - Trusted: gear 0.66, cap 0.87, strap hinge 0.39, screw 0.17.
  - Untrusted: T7 0.16, T8 0.16, T9 0.40, T10 0.44.
  - r10 had IoU null on gear, T7 and T8. The ECC refinement field was not present in the manifests I read.

## 4. Wins and regressions
**Wins:**
- Gear keeps the user's 20 mm.
- Strap hinge needs no spec edit.
- T10 standards false positive is gone.
- T9 knuckles 5/5.
- The copied-screw thin-wall warning is gone.
- IoU is always reported with a trust flag, and the gear and cap now have trusted fits.
- 0 source reads.

**Regressions:**
1. hinge_five_knuckles: the template silently ignores a top-level `knuckles` argument, so the agent got the 4-knuckle default. r10 got 5. The template should reject unknown top-level parameters or pick them up.
2. The circle-fit bore detector counts a decorative dish on T10 as a bore, which led to a spec edit.
3. Wrong skill ids in 4/8 photo runs (r10: 2), and the scorer's new rewrite counter reports 0.
4. bores_not_genus took 12.8 min (r10: 2.7) and real_photo_overlay 10 min (r10: 5).
5. The coin_scale_sealed stage still ships no photo, so the agent fabricates its own fixture.
6. Still open: T9 pin bore "Bore: none"; low IoU on T7, T8 and T10.

## Recommendation
**v0.1.12 is at least as good as v0.1.11 on the real photos and can be pinned.**
- Real photos: 8/8 vs 8/8, and every targeted 0.1.12 fix that I could exercise holds live.
- Sealed evals: 17/18 correct vs 18/18 in r10. The one miss (hinge_five_knuckles) comes from the template silently dropping a misplaced argument, which is worth fixing in 0.1.13.
- If you want strict parity on the sealed evals, hold the pin until that is fixed.

Files: summary.png (photo | iso | overlay), collected.jsonl, scorer_photo.txt, he_scores.txt, he/*/score.json, offline_v0112_on_r10_meshes.jsonl, offline_copycheck_r11.jsonl, attempt1_auth401/.
