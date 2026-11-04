# photo-to-part v0.1.4 (4002dfd), round-5 targeted test in Hermes

Tested 2026-11-02 (America/Toronto). Setup: `HERMES_HOME=/workspace/hermes-p2p`, Hermes v0.21.7, deepseek-v4.1-flash, `--oneshot --yolo --max-turns 40`, 6 runs in parallel, with the same prompts and photos as round 4.

**Install.** `git checkout 4002dfd`, then `plugins update` and `validate --install-deps` (Validation passed). Doctor shows 6 tools; `plugins list` shows one copy, **0.1.4**, enabled.

## Round 4 vs round 5
I re-checked dims by validating a copy of each newest `_vN.stl`. "Calls" counts all tool calls in the session; the budget is 40 iterations.
| Test | R4 | **R5** | Re-checked dims (mm) | Watertight / shells | Calls (R4 → R5) | Min (R4 → R5) | New helpers used | Agent's spec check | IoU (R4 → R5) | rm / overwrite |
|---|---|---|---|---|---|---|---|---|---|---|
| b bottle cap (thread + knurl) | FAIL (1789 shells) | **PASS** | 32.98×32.98×17.0 (target 33×33×17) | yes / 1 | 44 → 41, finished | 4.8 → 6.9 | bottle_cap / thread / knurl in build | `--spec` ok (x, y, z, shells) | – → **0.88** | none |
| d strap hinge (scrolls) | FAIL (9 shells) | **PARTIAL** | 400×81.4×4.0. Width 81.4 against the stated 70 mm scroll. Scrolls simplified to round eyes, not spirals | yes / 1 | 45 → 34, finished | 13.2 → 11.1 | sweep | **never validated.** Rendered twice anyway (non-final renders are allowed) | – → 0.26, then 0.08 | none; v1–v4 kept |
| i M3 screw + ruler | FAIL (no STL) | **PASS** | 6.4×6.4×7.78. Measured at 36.55 px/mm: 5.5 A/F, 6.4 flange, 2.65 head, 5.0 thread | yes / 1 | 44 → 43, budget | 10.9 → 14.0 | template hex_screw + thread | `--spec` ok | – (no render; budget ran out) | none |
| T9 print-in-place hinge | FAIL (4 knuckles, 4.5 thick) | **PASS** | 100×50×6.0. I counted the knuckles from the mesh: body A has 3, B has 2, so **5**, with 0.5 mm gaps | yes / **2** (expected) | 44 → 45, budget | 15.4 → 11.8 | template hinge, then a custom build | `--spec` ok, but the agent **removed the knuckle check** from spec.json because the plugin's knuckle probe can't see knuckles (see issue 1) | – | none |
| a spur gear (regression) | PASS, IoU 0.19 | **PASS** | 45×45×20, 25 mm bore checked by `--spec` hole | yes / 1 | 33 → 47, budget | 13.0 → 4.8 | sweep (gear profile hand-built; no gear helper) | `--spec` ok, including a hole check | 0.19 → **0.37** | none |
| T7 angled bracket (regression) | PASS, IoU 0.01 | **PASS** | 125×15×125, 1.5 thick (R4 20 wide; ~15 looks right) | yes / 1 | 42 → 46, finished | 17.7 → 21.7 | template l_bracket | `--spec` ok | 0.01 → agent passed `--angled`, so no overlay. **Tester auto-fit: 0.17** (rot 75°, view "side", no mirror) | none |

**Summary:** all 4 round-4 failures are fixed or improved. b, i and T9 now **pass**; d produces a valid mesh but simplifies the scrolls and was never validated. Both regressions pass. No agent ran `rm` on an STL, and versions were kept. Wrong skill-id attempts: 1/6 (a). 3/6 runs still hit the 40 budget.

Note: before I switched to copies, my first re-check validated the files in place. That rewrote each newest STL's `.validate.json` sidecar at about 16:32 Toronto time. The agents' own validate results above were taken from the Hermes session DB.

## Remaining issues, ranked
1. **The knuckle probe misses real knuckles (T9).** It samples a ring of r = 0.9 mm around the bbox centre, which lies inside the solid 3 mm pin for the whole length, so it reports no knuckles. The agent then deleted the knuckle check from its spec to pass. Fix: probe at r = (pin_r + knuckle_r)/2 on the detected axis, or count gaps from the hinge parameters. Also have validate warn when a spec key the template emitted goes missing, so a spec can't quietly be weakened.
2. **A render can run without validation, and the final summary can skip validate (d).** Only `--final` is gated, so d delivered with no validation at all. Fix: refuse every render of a `_vN` with no fresh sidecar (or mark its JSON `unvalidated: true`), and make the next_step after build always "validate".
3. **Overlay pose is still weak for in-plane shapes.** T7 auto-fit picked the "side" view and 75° (IoU 0.17); the true pose is the front/top plane at ~45° or 135°. On the gear, the ROI clipped the part, so IoU measured only a band. Fix: try all three views with a finer rotation search (5°, or PCA initialisation), score against the full ROI mask, and log the top 3 poses. `--angled` should still run the fit and report IoU as advisory instead of skipping it.
4. **Organic sweeps need a spiral helper (d).** `sweep` was used, but the agent fell back to round eyes. Add `spiral_scroll(r_outer, turns, width)`. Also check spec drift on width: the user's 70 mm scroll came out as 81.4 overall, and nothing caught it because no spec was written. Make writing spec.json from the prompt numbers the first step.
5. **Budget.** a, i and T9 hit 40. The gear spent ~10 failed builds hand-rolling an involute. Add a `spur_gear(module, teeth, pa, width, bore)` template (gear came up in 2 rounds).
6. **Sidecar overwrite by any validate call.** A plain `export_validate.py` run by someone else replaces the agent's sidecar. Minor: keep the history in `.p2p_history/`, or only write the sidecar from the tool.
7. **Wrong skill id** is still tried occasionally (1/6). This needs a Hermes-side alias.

## Files
summary.png (photo | overlay_diff or compare | iso; T7 uses the tester overlay). Per-test folders hold prompt.txt, hermes.log, time.txt, outputs and spec.json. Tester renders are in `*/renders_tester`.
