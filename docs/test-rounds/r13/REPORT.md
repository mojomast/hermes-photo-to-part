# photo-to-part round 13: v0.1.14 (729216b) vs r10 (v0.1.11) and r12 (v0.1.13)
- Setup: Hermes home /workspace/hermes-p2p, deepseek-v4.1-flash via opencode-go, `timeout 2400 hermes chat … --oneshot --yolo --max-turns 40`.
- Every run was launched detached with setsid nohup at 16:34 EST; evals ran 6 at a time; load stayed at 2–3.
- The Hermes session DB was read only after all 26 runs had exited (last at 17:03 EST).
- In-process results are in /tmp/r13inproc, outside the round folder: **28/28, holdouts 4/4, 6 tools**.
- **No infra failures:** no 401s, lease kills or stalls, so there are no attemptN_ folders. Repo and catalog PR unchanged.

## Sealed evals: 18/18 correct (r10 18/18, r12 17/18)
- No leaks.
- **coin_scale_sealed:** the agent used `photo_part_measure` 7 times on the staged photos, with 0 cv2/PIL calls.
  - quarter 18.21×10.12 (truth 18×10)
  - loonie 22.30×12.16 (truth 22×12; r12 was 13.68, **fixed**)
  - euro 16.46×8.36 (truth 16×8 at 8% tolerance)
  - All within tolerance.
- **hinge_five_knuckles:** knuckles=5 ✓.
- **Scorer's skill-id counts now match reality.**
  - `skill_id_rewritten`=1 on exactly the three evals with one `plugin:`-form call and one hook `rewrite_from` row (countersink, overlay_low_confidence, thin_wall_warning).
  - 0 elsewhere; wrong_skill_ids=0 everywhere.
  - r12 reported 9/11 rewrites on runs that had none.

| task | r10 min | r12 min | r13 calls (plugin) / min |
|---|---|---|---|
| box_matches_spec | 0.4 | 1.0 | 9 (3) / 0.5 |
| box_dimension_error | 0.7 | 1.7 | 11 (3) / 0.5 |
| hinge_five_knuckles | 0.7 | 1.2 | 10 (4) / 0.6 |
| countersink_deeper_than_sheet | 2.1 | 1.3 | 10 (1) / 1.1 |
| thin_wall_warning | 0.8 | 1.1 | 16 (8) / 0.8 |
| print_in_place_gap | 0.8 | 1.1 | 17 (7) / 1.1 |
| worse_version_reverts | 1.8 | 1.3 | 22 (8) / 1.3 |
| template_default_name | 0.2 | 0.5 | 8 (3) / 0.3 |
| best_version_filled | 1.7 | 4.0 | 21 (10) / 1.6 |
| checklist_bool_answered | 1.3 | 0.9 | 18 (7) / 1.3 |
| bores_not_genus | 2.7 | 3.8 | 30 (18) / 6.8 |
| thin_l_bracket | 1.4 | 1.8 | 11 (5) / 1.1 |
| thread_no_thin_wall | 1.6 | 6.1 | 29 (9) / 2.7 |
| thread_from_script_no_thin_wall | 2.1 | 3.2 | 39 (20) / 5.8 |
| validate_renders_on_pass | 0.9 | 4.1 | 13 (2) / 1.6 |
| real_photo_overlay | 5.0 | 7.7 | 21 (6) / 5.1 |
| overlay_low_confidence | 0.8 | 3.1 | 28 (6) / 5.1 |
| coin_scale_sealed | 1.4 (no photo) | 6.5 (loonie wrong) | 15 (5) / 3.7 |

## Real photos: 8/8 delivered and validated ok (r10 8/8, r12 7/8)

| case | r10 (v0.1.11) | r12 (v0.1.13) | **r13 (v0.1.14)** | dims (mm) | score | spec edits | warnings | overlay seg/overall (IoU, trusted) | calls / budget notes | other |
|---|---|---|---|---|---|---|---|---|---|---|
| gear | PASS, z 23 (assumed hub) | PASS, IoU 0.13 | **PASS** | 45×45×20 ✓ | 100 | 0 | – | low/low (0.11, untrusted), same as r10/r12 | 39 / 60-80-95 | 8 PIL size or pixel probes; 1 id rewrite |
| bottle cap | PASS | PASS, thin-wall 0.011 warning | **PASS** | 33×33×17 | 100 | **2**: renamed slug; hole_count 0→1 (blind cavity counted as a bore) | **no thin-wall** ✓ | low/low (0.79, untrusted) | 40 / 60-80-95 (at the 40 cap) | – |
| strap hinge | PASS, 1 edit (knuckles) | PASS | **PASS** | 400×66.2×4 | 100 | 0 ✓ | – | high/medium (0.36, trusted) | 35 / 60-80 | holes 4=4; 1 rewrite |
| M3 screw | PASS | PASS, min wall 0.75 warning | **PASS** | 6.8×6.8×8.0 | 100 | 0 | **no thin-wall** ✓ | medium/medium (**0.75**, trusted), best yet | 41 / 60-80-95 | 11 PIL/numpy pixel probes (r10: 0); 1 rewrite |
| T9 PIP hinge | PASS | **FAIL**, knuckles 2/5 | **PASS** | 100×50×6, 2 shells | 90 | 0 | **false positives:** "gap between bodies 0.000 mm" and "min wall 0.400 mm". The agent measured a 0.40 mm body gap itself and checked that the hinge rotates. | none (no overlay) | 33 / 60-80 | knuckles **5=5** ✓, holes 1=1 |
| T7 bracket | PASS (bent 125×25×125) | PASS (flat) | **PASS** | 125×125×1.5 flat L | 100 | 1 (rebuilt flat to match the photo, with reason) | – | high/low (0.20, trusted) | 30 / 60 | holes 6=6 |
| T8 coin peg | PASS (3.2×26.1×3.0) | PASS?, 21.4 long | **PASS** | 8.5×26.3×3.0 ✓ | 100 | 1 (hole y frame origin, no mesh change) | – | high/medium (**0.81**, trusted) | 25 / 60 | measure ×2, 0 pixel probes |
| T10 glass pull | PASS (M5 false positive) | PASS | **PASS, but hit the turn cap** | 45×45×50 | 95 | 0 ✓ | "bed contact 0.00 mm²" (stood on a point or curved face) | medium/low (0.49, trusted) | 43 / 60-80-95; **"Iteration budget reached (40/40)"**, exit 1 after it had delivered v5 | holes 1=1; shape fidelity weak in the render (rosette barely visible) |

**Totals:**
- 8/8 pass; 0 source reads.
- Turn-cap hits: **1** (T10; r10 had 0).
- Spec edits: 4 (cap 2, T7 1, T8 1), all with reasons and none to dodge a failure (r10: 1, r12: 0).
- Wrong-id calls: 4 photo runs, all rewritten by the hook.

## Changes vs r12
**Fixed:**
- T9 knuckles 5=5 and the case passes.
- Thin-wall false positives on the cap and screw are gone.
- The coin_scale loonie height is in band.
- The scorer's rewrite counts are correct.
- T8 is back to 26.3 mm long.
- Eval minutes are down on best_version_filled, thread_no_thin_wall and validate_renders_on_pass.

**New or remaining:**
- T9 validator false positives: body gap 0.000 and min wall 0.4 mm. The gap probe reads the coplanar knuckle end faces.
- T10 hit the 40-turn cap.
- T10 warns "bed contact 0".
- The cap needed a hole-count edit (blind cavity counted as a bore).
- bores_not_genus is 6.8 min (r12 3.8).
- Screw and gear runs made pixel probes.

## Verdict
**On outcomes, v0.1.14 matches v0.1.11 on every case:**
- 8/8 real photos pass vs 8/8, and 18/18 sealed evals vs 18/18.
- It is better than v0.1.11 on the gear (20 mm kept), strap hinge (no edit), screw (IoU 0.75), T8 (IoU 0.81) and T10 (no standards false positive).

**It is not strictly equal on process for two cases:**
- T10 hit the 40-turn cap (v0.1.11: none) but still delivered a validated part.
- T9 passes with two validator false-positive warnings (gap 0.000, wall 0.4).

**Recommendation:** pin v0.1.14 over v0.1.11. It has no case-level regressions and fixes every r12 regression. Fixes for 0.1.15:
- the gap and min-wall probe on print-in-place knuckle end faces;
- the T10 call budget;
- counting blind cavities as bores on the cap.

Files: summary.png (photo | iso | overlay), collected.jsonl, he_scores.txt, he/*/score.json.
