# photo-to-part round 12: v0.1.13 (b68fdfa) vs r11 (v0.1.12)
- Setup: Hermes home /workspace/hermes-p2p, deepseek-v4.1-flash via opencode-go, --max-turns 40, detached (setsid nohup) launches.
- Evals ran 6 at a time; load stayed at 2–4.
- The in-process eval results are in /tmp/r12inproc, outside the round folder: **28/28, holdouts 4/4, 6 tools**.
- Repo and catalog PR unchanged.

## Failed or redone attempts
- **attempt1_lease/** (strap hinge, T7, T8, first launch): all three were interrupted together at 14:15:24–26 EST, after about 24.5 min, with exit 130.
  - Hermes printed "Session turn lease could not be refreshed; stopping to protect the transcript."
  - In `agent/turn_facade_lease.py`, the lease refresher hits a SQLite lock on state.db and keeps failing through the 300 s lease TTL, then interrupts the turn.
  - From 14:11 to 14:15 I was running the eval scorer (`--hermes-session`) and my transcript dump, one after the other, against the same state.db. **This was caused by my harness, not by v0.1.13.**
  - All three were relaunched at 14:21 and completed with exit 0. Lesson: don't read state.db while runs are live.
- **he/thread_from_script_no_thin_wall_attempt1_truncated:** exit 1. The model hit its output-token limit on a tool call, and Hermes retried 4 times and refused to run it. That is the model or provider, not the plugin. The rerun passed.

## 1. Sealed evals (18 tasks)

| task | r11 calls / min | r12 calls (plugin) / min | r12 outcome |
|---|---|---|---|
| box_matches_spec | 9 / 0.4 | 13 (5) / 1.0 | ok |
| box_dimension_error | 15 / 1.0 | 16 (7) / 1.7 | ok |
| hinge_five_knuckles | 14 / 1.0 | 14 (7) / 1.2 | **ok: knuckles=5** (r11 got 4) |
| countersink_deeper_than_sheet | 10 / 0.9 | 11 (1) / 1.3 | ok, rejected |
| thin_wall_warning | 10 / 1.0 | 12 (5) / 1.1 | ok |
| print_in_place_gap | 19 / 2.1 | 18 (8) / 1.1 | ok |
| worse_version_reverts | 20 / 1.0 | 16 (8) / 1.3 | ok |
| template_default_name | 7 / 0.3 | 6 (3) / 0.5 | ok |
| best_version_filled | 14 / 1.8 | 30 (15) / 4.0 | ok, slower |
| checklist_bool_answered | 15 / 1.2 | 13 (4) / 0.9 | ok |
| bores_not_genus | 36 / 12.8 | 24 (13) / **3.8** | ok, **faster** |
| thin_l_bracket | 20 / 2.2 | 16 (5) / 1.8 | ok |
| thread_no_thin_wall | 23 / 2.9 | 35 (8) / 6.1 | ok |
| thread_from_script_no_thin_wall | 32 / 4.2 | 17 (8) / 3.2 (rerun) | ok |
| validate_renders_on_pass | 20 / 1.7 | 13 (3) / 4.1 | ok |
| real_photo_overlay | 22 / 10.0 | 31 (7) / **7.7** | ok, faster |
| overlay_low_confidence | 15 / 1.5 | 22 (8) / 3.1 | ok, no mesh change |
| coin_scale_sealed | 19 / 2.8 (no photo) | 19 (5) / 6.5 | see below: **wrong on the loonie height** |

**Result: 17/18 correct**, with 0 leaks across all 18.

**coin_scale_sealed:**
- The stage now ships `us_quarter.png`, `cad_loonie.png` and `euro_1.png`. The agent called `photo_part_measure` on each staged photo (auto plus a part_seed), with no cv2 and no drawn fixture. Its one PIL call decoded the tool's own part_mask.png.
- The scorer's truth from evals/runner.py (read by me, not the agent) is quarter 18×10 (5%), loonie 22×12 (5%), euro 16×8 at 20° (8%).
- Agent results:
  - quarter 18.21×10.12: ok;
  - euro 16.46×8.36: ok;
  - **loonie 22.30×13.68: +14% on Y, so fail.**
- The agent still claimed everything was "comfortably inside 5%". The overestimate came from the tool's own mask (88×54 px). The in-process version of the same check passes, so this is seed- or mask-dependent.

**Skill-id counting:**
- Actual `plugin:`-form skill_view calls in sessions: 8 evals and 3 photo cases (strap hinge, screw, T8). Each has exactly one matching `rewrite_from` row in its case `.photopart/calls.jsonl` (truth_ids.txt). So the hook now rewrites every wrong id.
- **The scorer in `--hermes-session` mode is wrong.** It reports `skill_id_rewritten` = 9, 1 or 11 on tasks that had 0 or 1 wrong calls. For example, box_matches_spec made 0 wrong calls but scored 9.
  - Cause: `_calls_log()` falls back to the shared `HERMES_HOME/.photopart/calls.jsonl`, which collects rows from every session, instead of the case directory's file.
  - `wrong_skill_ids` is always 0.

## 2. Real photos, r11 → r12

| case | r11 | **r12** | delivered | dims (mm) | WT/shells | calls | hook | notes | spec edits | score / ok | key rows | printability warnings | overlay seg/overall (IoU, trusted) | wrong id → rewritten |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gear | PASS, IoU 0.66 trusted | **PASS** | spur_gear_v2 | 45×45×20 | y/1 | 20 | 20 | – | 0 | 100 | holes 1=1 | – | low/low (0.13, untrusted) ↓ | – |
| bottle cap | PASS | **PASS (warning)** | bottle_cap_v3 | 33×33×17 | y/1 | 38 | 38 | 60, 80 | 0 | 95 | holes 1=1 | **thin area 0.011 >1% under 0.8 mm** (the thread false positive is back) | high/medium (0.89, trusted) | – |
| strap hinge | PASS, 0 edits | **PASS** | strap_hinge_v4 | 400×70×4 | y/1 | 39 (70 in the log) | 39 | 60, 80, 95 | 0 | 100 | holes 6=6 | – | medium/medium (0.38, trusted) | 1 → 1 |
| M3 screw | PASS, no thin-wall | **PASS (warning)** | m3_flange_hex_screw_v2 | 6.8×6.8×8.95 | y/1 | 41 | 41 | 60, 80, 95 | 0 | 95 | – | **min wall 0.750 mm** (false positive back); 10 cv2/PIL pixel probes | medium/low (0.19, trusted) | 1 → 1 |
| T9 PIP hinge | PASS, knuckles 5=5 | **FAIL** | piano_hinge_teardrop_v2 (agent's choice) | 100×50×6 | y/2 | 40 (77 in the log) | 40 | 60, 80, 95 | 0 | **72, ok=false** | **knuckles 2 vs 5** ("ring count 5 disagrees with 2 cylinders"); v4 shows 3 vs 5 | – | none: render refused by the budget; the agent drew views with matplotlib | – |
| T7 bracket | PASS | **PASS** | flat_corner_bracket_125_v1 | 125×125×1.5 | y/1 | 24 | 24 | – | 0 | 100 | holes 6=6 | – | low/low (0.15, untrusted) | – |
| T8 coin peg | PASS, 26.1 long | **PASS?** | peg_leg_v2 | 5.6×21.4×2.2 (shorter than r10/r11's 26.1) | y/1 | 32 | 32 | 60 | 0 | 100 | holes 1=1 | – | high/medium (0.72, trusted) ↑ | 1 → 1 |
| T10 glass pull | PASS, 1 edit (dish counted as a bore) | **PASS** ✓ | glass_rosette_drawer_pull_v6 | 45×45×50 | y/1 | 35 | 35 | 60, 80 | **0** | 100 | **holes 1=1**; M5 role=thread ok | – | no overlay in the final render | – |

**Totals:**
- **7/8 PASS** (r11: 8/8; pinned v0.1.11: 8/8).
- 0 source reads. Every run exits 0 (after the lease reruns).
- Spec edits 0 (r11: 2).
- The hook's call count matches its own record, but the Hermes log reports more tool calls in long runs (77 on T9). The hook counts only top-level calls.

## 3. The v0.1.13 changes
- **Template parameters at the top level: fixed.** hinge_five_knuckles writes knuckles=5.
- **Decorative dish as recess: fixed.** T10 needed no hole-count edit, holes 1=1.
- **Skill-id rewrite: works** in the hook (every wrong id is rewritten). **The scorer's count is wrong** in session mode (shared calls.jsonl), as above.
- **Speed:**
  - bores_not_genus 12.8 → 3.8 min; real_photo_overlay 10.0 → 7.7 min.
  - Slower: best_version_filled (1.8 → 4.0), thread_no_thin_wall (2.9 → 6.1), validate_renders_on_pass (1.7 → 4.1).
- **coin_scale_sealed stages photos:** confirmed, and the agent used measure on them. The loonie height came out 14% over.

## 4. Regressions
1. **T9 fails:** the cylinder knuckle detector merges coaxial knuckles (2–3 found vs 5; the ring count of 5 is right). The agent delivered a version that failed validation. r11 found 5=5 on its mesh.
2. **Thin-wall false positives are back on threaded parts:** cap 0.011, screw 0.75 mm. Both were clean in r11.
3. **coin_scale_sealed:** loonie part height +14%, outside the 5% band, while the agent claimed it was in band.
4. **Scorer's session-mode rewrite count** reads the shared HERMES_HOME calls.jsonl.
5. **Overlay coverage dropped:** gear IoU 0.66 trusted → 0.13 untrusted. T9 and T10 have no overlay; for T9 the render was refused by the budget.
6. The screw run made 10 cv2/PIL pixel probes (r11: 3).

**Wins:** template parameter merge, T10 recess, T8 overlay fit 0.72 trusted, 0 spec edits, faster bores_not_genus and real_photo_overlay, and the hook rewriting every wrong id.

## Recommendation
**Do not pin v0.1.13. Keep v0.1.11.**
- v0.1.13 gets 7/8 real photos and 17/18 sealed evals, against v0.1.11's 8/8 and 18/18.
- It regresses the T9 knuckle count and brings back the thread thin-wall false positives.
- Fixes for 0.1.14:
  - count knuckles by coaxial segments or rings, not merged cylinders;
  - restore thread tagging on validate;
  - make the scorer read the case directory's `.photopart/calls.jsonl`;
  - check the measure mask on the loonie photo.

Files: summary.png, collected.jsonl, he_scores.txt (scorer output; its rewrite column is wrong), truth_ids.txt, he/*/score.json, attempt1_lease/, he/thread_from_script_no_thin_wall_attempt1_truncated/.
