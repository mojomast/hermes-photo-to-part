# photo-to-part round 15: v0.1.16 (17556b8) vs r14 (v0.1.15) and r13 (v0.1.14)
**Setup:**
- Installed plugin is plugin-only; the dev checkout is at /workspace/hermes-p2p-dev/hermes-photo-to-part, same sha.
- Same model and the same `timeout 2400 hermes chat … --oneshot --yolo --max-turns 40` run.sh with `PHOTOPART_BUILD_APPROVAL=allow`.
- All 26 runs were launched detached (setsid nohup) at 20:00 EST, evals 6 at a time. The session DB was read only after all had exited (20:22 EST).
- The run scripts were kept in /tmp during the runs (copied to harness/ afterwards), because r14 agents read he/run.sh.
- Eval stages came from the dev runner's `--stage`, which writes only prompts and input fixtures. No eval source is in the round folder.
- In-process (dev checkout): **28/28, holdouts 4/4, 6 tools** (/tmp/r15inproc).
- No infra failures and no relaunches. Every run exited 0. Repo and catalog PR unchanged.

## Sealed evals: 18/18 correct, 0 leaks (r14: 18 correct / 2 leaks; r13: 18/18)
- **No reads of eval or scorer source:** no tool call in any session touched `evals/`, `tests/regression`, `runner.py` or the dev checkout.
- **One near miss:** one eval agent ran `ls /workspace` and saw `hermes-p2p-dev`, but never opened it.
- **coin_scale_sealed:** quarter 18.21×10.12, loonie 22.30×12.16, euro 16.46×8.36, all in band, via `photo_part_measure`.
- **hinge_five_knuckles:** knuckles=5.
- **Skill ids:** the scorer's rewrite counts (1 on 6 evals) match the hook's rows. wrong_skill_ids=0.

| task | r14 calls / min | r15 calls (plugin) / min |
|---|---|---|
| box_matches_spec | 13 / 0.9 | 9 (3) / 0.7 |
| box_dimension_error | 13 / 1.0 | 16 (6) / 0.9 |
| hinge_five_knuckles | 8 / 0.5 | 9 (4) / 0.4 |
| countersink_deeper_than_sheet | 10 / 0.8 | 8 (1) / 1.0 |
| thin_wall_warning | 10 / 0.5 | 9 (4) / 0.4 |
| print_in_place_gap | 11 / 0.8 | 17 (9) / 1.0 |
| worse_version_reverts | 18 / 2.3 | 20 (9) / 1.2 |
| template_default_name | 6 / 0.3 | 9 (3) / 0.3 |
| best_version_filled | 15 / 1.4 | 14 (7) / 1.0 |
| checklist_bool_answered | 16 / 1.8 | 22 (9) / 2.5 |
| bores_not_genus | 29 / 4.0 | 29 (16) / 2.8 |
| thin_l_bracket | 22 / 3.3 | 18 (8) / 1.7 |
| thread_no_thin_wall | 27 / 1.9 (leak) | 37 (10) / 1.8 |
| thread_from_script_no_thin_wall | 38 / 3.3 (leak) | 37 (16) / 4.3 |
| validate_renders_on_pass | 16 / 2.0 | 21 (8) / 1.1 |
| real_photo_overlay | 22 / 2.5 | 24 (10) / 8.0 |
| overlay_low_confidence | 29 / 4.2 | 26 (6) / 1.8 |
| coin_scale_sealed | 19 / 2.5 | 21 (8) / 5.4 |

## Gate behaviour
- **Terminal builds in r15:** none.
  - Of 153 terminal calls, 0 match a build pattern (`python x.py`, cadquery, build123d, `.export(`).
  - Replaying every terminal and execute_code call from the session records through `photopart.build_gate.terminal_build_approval` with the variable unset: **0 would have been flagged** (terminal_builds.jsonl is empty).
  - Agents used `photo_part_build` for every build. The r14 bypass (strap hinge running `python build.py`) did not recur.
- **Blocked-read events:** 0, because no agent attempted such a read.
  - Offline check of the `pre_tool_call` hook: it returns `block` for read_file on `…/evals/runner.py`, for `cat …/tests/regression/…`, and for `python -c "from evals.runner import …"`, and nothing for normal reads.
- **Fail-closed check** (gate_sanity/): with `PHOTOPART_BUILD_APPROVAL` unset, one oneshot `--yolo` run in /tmp/r15gate.
  - **`photo_part_build` ran** (ok, returncode 0, box_v1.stl written).
  - **Terminal `python3 build.py` also ran.** It failed only with ModuleNotFoundError: the system python has no trimesh.
  - No approval prompt and no block message appeared in the log.
  - Offline, the hook does return `{"action":"approve","rule_key":"photo_part_build"}` for both commands, so the plugin side works. **`--yolo` auto-approves the plugin's "approve" request.** The gate does not fail closed under `--yolo`; it only matters in interactive or non-yolo sessions.
  - (Hermes source mentions `--yolo` and HERMES_YOLO_MODE as an explicit approval bypass.)

## Real photos: 8/8 delivered and validated ok (r14 8/8, r13 8/8)

| case | r13 (v0.1.14) | r14 (v0.1.15) | **r15 (v0.1.16)** | dims (mm) | score | spec edits | warnings | overlay seg/overall (IoU, trusted) | calls / notes | turn cap |
|---|---|---|---|---|---|---|---|---|---|---|
| gear | PASS, IoU 0.11 | PASS, IoU 0.41 | **PASS** | 45×45×20 | 92 | 0 | – | high/medium (**0.80**, trusted) ↑ | 30 / 60 | no |
| bottle cap | PASS, 2 edits | PASS, 1 edit, IoU 0.91 | **PASS** | 33×33×17 | 100 | 1 (template made the OD 41.2 mm, so the spec uses the user's 33) | – | medium/medium (0.79, trusted) | 29 / 60 | no |
| strap hinge | PASS, IoU 0.36 | PASS, IoU 0.30 | **PASS** | 400.5×70×4 | 100 | 0 | – | medium/low (0.39, trusted) | 43 / 60-80-95 | no |
| M3 screw | PASS, 6.8×6.8×8.0, IoU 0.75 | PASS, flange 9.0, IoU 0.61 | **PASS** | 6.9×6.9×7.9 (flange back to ≈7) ✓ | 100 | 0 | – | high/medium (**0.79**, trusted) ↑ | 34 / 60-80 | no |
| T9 PIP hinge | PASS, false gap and wall warnings | PASS, real 0.20 gap warning | **PASS, clean** | 100×50×6, 2 shells | 100 | 0 | **none** ✓ | high/medium (**0.58**, trusted) ↑ | 27 / 60 | no; ran 1 `find /` for photopart dirs |
| T7 bracket | PASS (flat) | PASS, at the turn cap, IoU 0.06 | **PASS** | 125×125×1.5 flat L | 92 | 0 | – | medium/low (0.21, trusted) | 27 / 60 | **no** ✓ |
| T8 coin peg | PASS, IoU 0.81 | PASS, IoU 0.28 | **PASS** | 24.9×7.0×3.2 | 100 | 0 | – | high/low (**0.00 but marked trusted**: the overlay was misplaced and the trust flag is wrong) | 37 / 60-80 | no |
| T10 glass pull | PASS, at the turn cap | PASS, thin 0.038 | **PASS** | 45×45×50 | 100 | 0 | – | **no overlay** (renders only) | 45 / 60-80-95 | no |

**Totals:**
- 8/8 pass; **0 turn-cap hits** (r14: 1, r13: 1).
- **Spec edits: 1** (r14: 5).
- 0 eval-source reads; 0 wrong-id calls.

## Regressions and oddities
- T8 overlay IoU 0.0 is reported as `iou_trusted: true`, which is a trust-flag bug. Earlier rounds got 0.28–0.81.
- T10 again produced no overlay (r14 had 0.24).
- Under `--yolo` the approval gate does nothing; that is Hermes design, not a plugin bug.
- One agent saw the dev checkout's name via `ls /workspace`. Consider moving it off /workspace or out of the agents' reach.

## Verdict
**v0.1.16 is at least as good as v0.1.15, and better:**
- 8/8 real photos (same).
- 18/18 sealed evals with **0 leaks** (r14: 2).
- 0 turn-cap hits (r14: 1) and 1 spec edit (r14: 5).
- Better overlay fit on the gear, screw and T9; T9 has no warnings; the screw flange is back to plausible.
- The bypass fix and read-blocking hooks work offline, and nothing in the live runs needed them.

**Caveat:** the build-approval gate is auto-approved by `--yolo`, so it does not fail closed in unattended yolo runs.

**Recommendation:** pin v0.1.16.

Files: summary.png, collected.jsonl, he_scores.txt, he/*/score.json, terminal_builds.jsonl, gate_sanity/, harness/.
