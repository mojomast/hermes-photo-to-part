# photo-to-part round 6 on v0.1.7 (7b38c38), Hermes v0.21.7, deepseek-v4.1-flash, --max-turns 40

## 1. Install and registration
- The plugin checkout is at 7b38c38. One copy is installed. `validate --install-deps` passes. `doctor` reports **0.1.7, 6 tools**, registration OK.
- The plugin env imports `photopart` from the installed plugin-sources copy, which is the 0.1.7 code with the signature check. rtree 1.4.1 and cv2 4.11.0 (with ArUco) both import.
- Live probe (probe2_session.txt): `tool_search` shows source `photo-to-part` with 6 tools, and the agent listed all six.
- **Verdict:** the 0.1.6 failure was real. Hermes's `register_tool` has no `output_schema` parameter (REPORT_v016_blocker.md). Most likely the /tmp-clone doctor warning was stale-env noise: doctor imports `photopart` from the installed env, which was still on 0.1.6 at that point. I did not re-test the /tmp clone.

## 2. Evals
**In-process (`python -m evals.runner`):** 16/16 passed, 23 calls, 0 wrong skill ids, 0 deleted files (evals_inprocess_v017.json).

**Hermes-driven:** I ran the 7 tasks that need no fixture through `hermes chat`, then scored each with `runner --transcript` (hevals/*/score.json).

| task | outcome | runner calls | min | wrong id* |
|---|---|---|---|---|
| box_matches_spec | stopped on next_step=stop | 14 | 0.4 | 0 |
| box_dimension_error | reported the error, spec untouched | 20 | 0.8 | 0 |
| hinge_five_knuckles | built and validated with 5 knuckles | 21 | 4.7 | 0 |
| countersink_deeper_than_sheet | rejected, no STL | 13 | 2.6 | 1* |
| thin_wall_warning | "under 0.8 mm" warning raised | 13 | 0.5 | 0 |
| print_in_place_gap | "under 0.3 mm" warning raised | 22 | 1.7 | 0 |
| worse_version_reverts | built its own v1/v2, then "Revert to part_v1" (v2 42 vs v1 80) | 36 | 4.1 | 1* |

\* These are false positives. The agents read evals/README.md and runner.py, which contain the `plugin:` string, and the scorer counted it. Two related problems: the agents read the eval source (task leakage), and the counter double-counts (i_screw had 1 real wrong id and the scorer reported 2).

## 3. Real-photo cases, r5 (or r4) vs r6
I re-checked dims on copies in /tmp/r6v, so the agent sidecars are untouched.

| case | r5 | **r6** | re-checked dims (mm) | WT / shells | calls (all / plugin) | min | best version delivered? | spec frozen / edits | printability warnings | IoU r5→r6 | wrong id | deleted |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| a spur gear | PASS | **PASS**, used spur_gear template | 45×45×20 | yes/1 | 29/5 | 10.2 | only v1; output named `name_v1.stl` | frozen, 0 edits | none | 0.37→0.42 (photo is only a partial gear) | 0 | none |
| b bottle cap | PASS | **PASS** | 33×33×17 | yes/1 | 38/10 | 9.7 | v2 (v1 never validated) | frozen, 0 | min wall 0.46 (thread crest) | 0.88→0.76 (outline barely visible) | 0 | rm of probe .py only |
| d strap hinge | PARTIAL (81.4 wide, round eyes) | **PASS**, strap_hinge template, real spirals | 400×70×4 | yes/1 | 46/10 | 25.6 | v2 | frozen, 0 | none | 0.26→0.19 | 0 | none |
| i M3 screw | PASS (no render) | **PARTIAL**, budget hit, no render | 7.2×7.2×8.15 (r5 6.4×6.4×7.78) | yes/1 | 44/5 | 14.8 | v2 | frozen, 0 | min wall 0.06 (thread tips) | – | **1** | none |
| T9 PIP hinge | PASS (knuckle check removed) | **PASS**, knuckles=5 kept in spec | 100×50×6 | yes/2 | 48/9 | 18.7 (budget) | v4 (80 > v3 48) | 1 edit with reason (hole_count 2→4, genus) | none (gap 0.353 OK) | – (no overlay) | 0 | none |
| T7 bracket | PASS | **PASS** | 125×16×125 | yes/1 | 36/7 | 16.8 | v2 (80 > v1 30) | 2 edits with reasons (hole probes) | none | 0.17→0.17 (overlay misaligned) | 0 | none |
| R3 T8 peg+coin | PASS (r4, 0.74) | **PASS / weak overlay** | 3.15×24.9×2.6, one jaw half | yes/1 | 44/7 | 17.0 (budget) | v1 | frozen, 0 | none | 0.74→0.23, then 0.045 | 0 | none (r4 had an rm) |
| R3 T10 glass pull | PASS | **PARTIAL**, budget hit before render | 45×45×50 | yes/1 | 43/8 | 9.7 | v3 (80 > v2 52 > v1 47) | frozen, 0 | none | – | 0 | none |

Overall: 5 pass, 1 weak pass (T8), 2 partial (M3 screw and glass pull, both ran out of turns before rendering). No STL was deleted and every edit to a frozen spec carried a reason. Each delivery was the highest-scoring validated version, but `best_version` / `revert_to` were null in every sidecar: the revert hint only fires when the newest version is worse.

**Evals vs real photos:** mostly agree on the mechanics: spec freeze with reasons, knuckle check, printability warnings, versioning and no deletes. They disagree on cost. Eval tasks finish in 13–36 calls, while real photos take 36–48 and 4 of 8 hit the 40-turn budget. The evals have no real-photo overlay task, so they cannot catch the IoU drop on T8 or the misalignment on T7 and the bottle cap.

## 4. Remaining issues, ranked
1. **Turn budget.** 4 of 8 runs hit 40 turns, and 2 never rendered. The agents spend about 30–40% of calls on terminal/execute_code/vision probes. Suggested fixes: make photo_part_render part of the validate→stop path (one call to validate and render), and have the skill tell the agent to render immediately after the first validation passes.
2. **Overlay alignment is still weak on real photos.** T8 got worse (0.74→0.045). T7 stays at 0.17, and the bottle cap's 0.76 shows no visible outline. GrabCut picks the wrong region when the part is small or partial. Suggested fixes: force the agent to pass `--roi` from the measure step, and report low confidence instead of a number.
3. **Template default name.** The spur_gear and l_bracket templates produce `name_v1.stl`, a placeholder name. Derive the name from the shape or spec `part`.
4. **The spec checklist is never answered.** Every sidecar has `answered: false` on all items, the score is capped at 75–80, and nothing pushes the agent to answer. Either make next_step ask for answers, or drop the cap.
5. **The hole-count check counts genus.** T9 and T7 both edited the spec to fit mesh genus. Count through-bores, or report "genus" and "bores" separately.
6. **Thread-tip min-wall false positives.** The screw (0.06 mm) and cap (0.46 mm) are flagged on thread crests. Exclude crests, or make thin-wall a warning only when the thin area exceeds some threshold.
7. **Eval hygiene.** Agents read evals/ and runner.py from the plugin folder. The wrong-skill-id scorer counts quoted strings and double-counts. Add a real-photo overlay task with an IoU floor to the evals.
8. One real wrong skill id this round (i_screw: `plugin:` prefix tried first, then the correct id).

Files: summary.png (photo | iso | overlay), collected.jsonl, */transcript.txt, */score.json, hevals/.
