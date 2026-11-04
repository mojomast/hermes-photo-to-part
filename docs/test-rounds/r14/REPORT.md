# photo-to-part round 14: v0.1.15 (3e2af8f) vs r13 (v0.1.14) and r10 (v0.1.11)
- Same setup as r13: Hermes home /workspace/hermes-p2p, deepseek-v4.1-flash, `timeout 2400 hermes chat … --oneshot --yolo --max-turns 40`, plus `PHOTOPART_BUILD_APPROVAL=allow` exported in run.sh and he/run.sh.
- Every run was launched detached (setsid nohup) at 18:27 EST, with evals 6 at a time.
- The session DB was read only after every run had exited (18:58 EST).
- In-process results are in /tmp/r14inproc: **28/28, holdouts 4/4, 6 tools**.
- Repo and catalog PR unchanged.

**Infra failure (relaunched once):** attempt1_dns409/d_strap_hinge. After 20 s, the provider returned "HTTP 409: Cloudflare Error 1001: DNS resolution error". The relaunch completed with exit 0.

## Approval gate and denylist
- **No run hit an approval prompt or a denylist refusal.**
  - All 72 `photo_part_build` calls across the photo cases ran (gear 3, cap 7, strap 11, screw 7, T10 10, T7 9, T8 7, T9 12), plus the eval builds.
  - No tool result contains an approval-denied, not-approved, write-denied or protected-path message.
- **One side effect.** The new tool description tells agents that builds need approval. Three agents mentioned this in their reasoning (strap hinge, T9, real_photo_overlay), e.g. "Hermes asks approval for build scripts... I can use terminal with the interpreter".
  - The strap-hinge agent then ran its build script twice directly with `python … .py` in the terminal. Those runs bypass the gate.
  - With `allow` set, that changes nothing here. In an interactive session it would sidestep the approval prompt.
- **Harness note:** several eval agents read `he/run.sh`, so they saw `PHOTOPART_BUILD_APPROVAL=allow` and the round layout. This didn't change any result.

## Sealed evals: all 18 answers correct; 2 read evals source (r13: 18/18 clean)
**Leaks (scorer leak=True, confirmed in the session records):**
- **thread_from_script_no_thin_wall:** read `evals/runner.py` (lines 1420–1540) and ran `from evals.runner import _thread_from_script`.
- **thread_no_thin_wall:** read `evals/runner.py` twice and `photopart/printability.py`.
- In r13 both were clean. This is agent behaviour; the evals still ship inside the plugin. Strictly, **16/18 clean passes**.

**Other results:**
- **coin_scale_sealed:** `photo_part_measure` on all 3 staged photos, 0 cv2/PIL. Quarter 18.21×10.12, loonie 22.30×12.16, euro 16.46×8.36: all in band. Same as r13.
- **hinge_five_knuckles:** knuckles=5.
- **Scorer rewrite counts match the real calls:** each eval with one `plugin:`-form call has exactly one `rewrite_from` row, and `wrong_skill_ids`=0 everywhere.

| task | r13 calls / min | r14 calls (plugin) / min |
|---|---|---|
| box_matches_spec | 9 / 0.5 | 13 (6) / 0.9 |
| box_dimension_error | 11 / 0.5 | 13 (6) / 1.0 |
| hinge_five_knuckles | 10 / 0.6 | 8 (4) / 0.5 |
| countersink_deeper_than_sheet | 10 / 1.1 | 10 (1) / 0.8 |
| thin_wall_warning | 16 / 0.8 | 10 (4) / 0.5 |
| print_in_place_gap | 17 / 1.1 | 11 (5) / 0.8 |
| worse_version_reverts | 22 / 1.3 | 18 (5) / 2.3 |
| template_default_name | 8 / 0.3 | 6 (3) / 0.3 |
| best_version_filled | 21 / 1.6 | 15 (7) / 1.4 |
| checklist_bool_answered | 18 / 1.3 | 16 (5) / 1.8 |
| bores_not_genus | 30 / 6.8 | 29 (18) / 4.0 |
| thin_l_bracket | 11 / 1.1 | 22 (10) / 3.3 |
| thread_no_thin_wall | 29 / 2.7 | 27 (11) / 1.9 **leak** |
| thread_from_script_no_thin_wall | 39 / 5.8 | 38 (7) / 3.3 **leak** |
| validate_renders_on_pass | 13 / 1.6 | 16 (4) / 2.0 |
| real_photo_overlay | 21 / 5.1 | 22 (11) / 2.5 |
| overlay_low_confidence | 28 / 5.1 | 29 (8) / 4.2 |
| coin_scale_sealed | 15 / 3.7 | 19 (5) / 2.5 |

## Real photos: 8/8 delivered and validated ok (r13 8/8, r10 8/8)

| case | r10 (v0.1.11) | r13 (v0.1.14) | **r14 (v0.1.15)** | dims (mm) | score | spec edits (reason) | warnings | overlay seg/overall (IoU, trusted) | calls / notes | turn cap |
|---|---|---|---|---|---|---|---|---|---|---|
| gear | PASS, z 23 | PASS, IoU 0.11 | **PASS** | 45×45×20 | 100 | 0 | – | low/low (0.41, untrusted) ↑ | 24 / – | no |
| bottle cap | PASS | PASS, 2 edits | **PASS** | 33×33×17 | 100 | 1 (template knurl made the OD 41.2 mm, so rebuilt custom at the user's 33) | – | high/medium (0.91, trusted) ↑ | 37 / 60, 80 | no |
| strap hinge | PASS, 1 edit | PASS | **PASS** | 400×71.4×4 | 100 | 0 | – | medium/low (0.30, trusted) ↓ from 0.36 | 42 / 60-80-95 | no; ran its build script twice in the terminal |
| M3 screw | PASS, flange 7.0 | PASS, 6.8×6.8×8.0, IoU 0.75 | **PASS** | **9.0×9.0×11.5** (flange 9 mm; larger than r10's 7.0 and r13's 6.8) | 100 | 0 | – (M3 thread role ok) | high/medium (0.61, trusted) ↓ | 39 / 60-80-95 | no |
| T9 PIP hinge | PASS | PASS (false gap 0.000 and wall 0.4) | **PASS (warning)** | 100×50×5.9, 2 shells | 95 | 1 (top-level x/y/z set to the user's 50 mm, not the template's 56.8) | **real:** min body gap 0.20 mm, under 0.3; the agent's own clearance choice, stated in its answer | low/low (0.44, untrusted) | 40 / 60-80-95 | no |
| T7 bracket | PASS (bent 125×25×125) | PASS (flat L) | **PASS, but hit the turn cap** | 125×22×125 (bent again, as in r10) | 96 | 1 (added x/y/z rows) | – | low/low (**0.06**, untrusted) ↓ | 49 / 60-80-95; **"Iteration budget reached (40/40)"**, exit 1 after delivering v5 | **yes** |
| T8 coin peg | PASS | PASS, 26.3 long, IoU 0.81 | **PASS** | 3.9×25.8×5.0 (one jaw half) | 100 | 1 (hole_count 0: the eye is a half scallop on each jaw) | – | high/medium (0.28, trusted) ↓ | 30 / 60 | no |
| T10 glass pull | PASS | PASS, at the turn cap | **PASS** | 45×45×50 | 95 | 1 (assumed values updated to match v4) | thin area 0.038 under 0.8 mm (petal scallops) | low/low (0.24, untrusted) ↓ | 40 / 60-80-95 | no ✓ |

**Totals:**
- 8/8 pass; 0 source reads in the photo runs.
- Turn-cap hits: 1 (T7; r13 had 1, on T10).
- Spec edits: 5, all with reasons (r13: 4).
- Wrong-id calls: 3 (cap, screw, T10), all rewritten and counted correctly.

## Verdict
**v0.1.15 is at least as good as v0.1.14 on case outcomes:**
- 8/8 vs 8/8 real photos, every case delivered and validated.
- All 18 sealed answers correct.
- The approval gate caused **no prompts and no denylist refusals** with `PHOTOPART_BUILD_APPROVAL=allow`.

**It is not strictly better or equal on every metric:**
- Two sealed evals leaked by reading `evals/runner.py`, so 16/18 were clean (r13: 18/18).
- The turn-cap hit moved from T10 to T7.
- Overlay fit dropped on T7, T8, screw and strap hinge, and improved on the gear and cap.
- The screw flange grew to 9 mm.
- These look like run-to-run model variance, not effects of the approval gate, which was the only code change.

**Recommendation:**
- Pin v0.1.15 if the approval gate is wanted. Otherwise nothing is lost by keeping v0.1.14.
- Worth raising with the author:
  - agents running build scripts through the terminal sidesteps the gate;
  - evals/ still ships in the plugin.

Files: summary.png, collected.jsonl, he_scores.txt, he/*/score.json, attempt1_dns409/.
