# photo-to-part v0.1.3 (a939851), round-4 test in Hermes

Tested 2026-11-02 (America/Toronto). Setup: Hermes v0.21.7, `HERMES_HOME=/workspace/hermes-p2p`, deepseek-v4.1-flash via opencode-go, `--oneshot --yolo --max-turns 40`, 13 runs in parallel.

**Install.** `git checkout a939851`, then `hermes plugins update` and `hermes plugins validate --install-deps` (Validation passed). Doctor shows **0.1.3, 6 tools**, and `plugins list` shows one photo-to-part.

**Inputs.** 9 new tests (a–i) from 10 new photos, plus re-runs of round-3 T7, T8, T9 and T10 with the same prompts. I wrote every dimension in the prompts as a plausible user, except in i (read from the ruler). The gear's 45 mm OD follows from m(z+2) = 2.5 × 18. Coat hook: Hermes attaches only one `--image`, so view B sat in the folder and the prompt named it.

## Results
"Tool calls" counts all of a session's calls; the budget is 40 iterations. Extents are my own re-validation of the newest STL. "Stale/overwrite" covers sidecar and overwrite behaviour.
| Test | Case | Result | Extents (mm) vs target | Tool calls | Min | Plugin tool calls | photo_part_build | Wrong id | Overlay IoU (last) | Stale / overwrite |
|---|---|---|---|---|---|---|---|---|---|---|
| a gear | spur gear, caliper in photo | **PASS** | 45×45×20, exact; 1 shell | 33, finished | 13.0 | measure, build, render, validate, render | yes | 0 | 0.19 (oblique face) | – |
| b bottle cap | internal thread + knurl | **FAIL** | 33×33×17, but **1789 shells**, not watertight (thread ribs not unioned) | 44, budget | 4.8 | build ×5 (3 failed), validate (fail) | yes | 1 | – | – |
| c hose nozzle | B&W, cluttered (hard) | **PASS** | 50 A/F hex (57.7 corners) × 150, exact; 1 shell | 37, finished | 17.1 | template, build ×6, validate ×3, render | yes | 0 | 0.33 | – |
| d strap hinge | scrolls, organic | **FAIL** | 400×70×4, **9 shells, 14 non-manifold edges** | 45, budget | 13.2 | build ×3, validate ×2 (fail) | yes | 0 | – | deleted its own v1 with `rm` |
| e battery lid | tabs + latch | **PASS** | 69.5×42×3 (62 + tabs + latch), 1 shell | 30, finished | 15.9 | measure, build ×2, validate, render ×4 | yes | 0 | **0.88** | – |
| f coat hook, 2 views | multi-view | **PASS (soft)** | 66×21.7×160, 1 shell. v3 was never validated by the agent | 47, budget | 31.5 | build, validate, measure, render ×4 | yes | 0 | 0.08 (mirrored view) | `rm` of an STL |
| g washers in bag | shiny bag (hard) | **PASS** | 47×17×0.5 sheet (5×2 on a 10 mm grid), 1 shell; ref washer 7×7×0.5 | 27, finished | 7.8 | build ×4, validate ×2, measure, render ×3 | yes | 0 | 0.61 | – |
| h hex standoff | small threaded | **PASS** | 5.5 A/F × 16 (10 + 6 male), 1 shell | 44, budget | 15.1 | template, build ×3, validate ×4, render | yes | 0 | (none reported) | **stale_validation flagged** once, then re-validated |
| i M3 screw + ruler | ruler scale | **FAIL, no STL** | measured 5.40 A/F, 7.44 flange, 2.53 head, 4.96 thread at 36.3 px/mm (plausible for M3) | 44, budget | 10.9 | template, measure, build ×3 (all failed) | yes | 1 | – | – |
| **re-run T7** angled bracket | perspective | **PASS** (R2/R3: no part) | 125×20×125, 1 shell, validated | 42, budget | 17.7 | build ×2, validate ×3, render | yes | 0 | 0.01 (outline not rotated 45°) | sidecar stale=false |
| **re-run T8** peg + coin | coin scale, ROI | **PASS** (R3 weak) | 6.9×25.37×4.0 (R3 4.5 wide; tester ~6.8×25.3) | 41, finished | 11.7 | measure, template, build ×3, validate, render ×2 | yes | 1 | **0.74** (R3 0.10) | `rm` of an STL |
| **re-run T9** hinge | print-in-place | **FAIL (spec)** | 100×50×4.5, 2 shells, valid mesh, but **4 knuckles and a 3 mm plate, no teardrop** vs 5 knuckles and 6 mm OD | 44, budget | 15.4 | template, build ×4, validate ×2, render ×2 | yes | 0 | – | `rm` of an STL |
| **re-run T10** glass pull | organic | **PASS** (R3 broken) | 45×45×50, 1 shell, v1–v4 kept | 39, finished | 9.5 | build ×8, validate ×5, render ×3 | yes | 0 | – (compare only) | versioned correctly |

**Totals:** 9/13 pass (new: 6/9; re-runs: 3/4). 6/13 finished under the budget (R3: 1/7). Median 13.2 min. Every run used the plugin tools and photo_part_build. Wrong skill-id attempts: 3/13 (R3: 3/7).

## v0.1.3 features checked
- photo_part_build: used in 13/13, and it reports stderr. Runs no longer hunt for the venv.
- Outputs land in the working folder, and `_vN` naming was used in most runs.
- `next_step` hints: present, and they helped (T10 and a followed build → validate → render).
- The stale_validation sidecar fired correctly once (h).
- ROI/seed overlays: big gain on T8 (0.10 → 0.74) and e (0.88).
- The `--overwrite` refusal never fired, because **agents bypass it with `rm` in the shell** (d, f, T8, T9).

## Remaining issues, ranked
1. **Threads, knurls and many-body unions produce non-manifold meshes (b, d, i).** Agents hand-write helical ribs, swept scrolls and revolves with trimesh, and get thousands of loose shells, or `fix_normals` crashes. Fix: add template shapes or helpers for `thread` (internal/external, ISO/PCO pitch), `knurl`, `sweep_path(width(t))` and `revolve` that return a manifold, union via manifold3d, and run a final `manifold3d` union/heal automatically in photo_part_build when the output has more than the expected shells.
2. **The overlay can't rotate or mirror.** T7 (bracket at 45°) scored 0.01 and f (mirrored view) 0.08, even with good models. Fix: in `--overlay-fit auto`, search rotation (and a mirror flag) together with scale and translation, and report the best angle. Optionally run a 2-point "axis" hint from photo_part_measure.
3. **Agents delete or overwrite versions through the shell.** Fix: in SKILL.md, add "never rm an STL". photo_part_build could snapshot outputs (`.history/`) or refuse to start if the previous `_vN` has gone missing.
4. **The spec drifts silently (T9).** The agent changed the knuckle count, thickness and profile without saying so prominently. Fix: have validate accept the user's key dimensions (`--expect key=value` from params.json) and fail on drift. In SKILL.md, require a "deviations from your numbers" section.
5. **Unvalidated final versions (f v3).** Fix: the final summary should cite the sidecar, and the next_step from build should insist on validate.
6. **Budget.** 7/13 still hit 40, mostly on build/debug loops. Points 1 and 4 would cut most of these.
7. **Wrong skill id is still tried** (3/13). This needs a Hermes-side alias.
8. **Two sidecar names** (`x.stl.validate.json` and `x.validate.json` from `--json-out`) confuse agents. Pick one.
9. **Minor:** the build error string appends "Skill id: …" boilerplate to `error`. Put the stderr tail there instead.

Not done: no open laser scan in metres or inches was found quickly, so none was tested this round.

## Files
summary.png (13 rows: photo | overlay_diff or compare | iso). photos/sources.json. Per-test folders hold prompt.txt, hermes.log, time.txt and the agent's outputs. metrics.txt has the per-session tool-call list. Tester renders are in b/d `renders_tester`. My independent validate runs also wrote `.validate.json` sidecars next to the final STLs.
