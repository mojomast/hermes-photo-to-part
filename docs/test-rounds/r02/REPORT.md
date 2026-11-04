# photo-to-part v0.1.1 (a0e96d0), round-2 test in Hermes

Tested 2026-11-02 (America/Toronto). Hermes Agent v0.21.7 with an isolated home `HERMES_HOME=/workspace/hermes-p2p`, model deepseek-v4.1-flash via opencode-go. The plugin was moved to a0e96d0 in place (`git checkout` in the plugin dir, then `hermes plugins update`). Doctor reports `photo-to-part 0.1.1`, **4 tools**, 0 hooks (doctor.log).
Runs: `hermes chat --query-file prompt.txt --image <photo> --oneshot --yolo --max-turns 40`. Seven runs went in parallel, one folder each (prompt.txt, hermes.log, time.txt). The tester supplied every dimension except T7 and T8, which were read from the photo.

## Results
| Test | Stress case | Time | Budget | Plugin tools used | Final file | Watertight / shells | Extents vs target | Verdict |
|---|---|---|---|---|---|---|---|---|
| T5 knob | rotational, 24 ribs, D-bore | 19.8 min | hit 40 | yes (7) | knob_v3.stl (+STEP) | yes / 1 | 28.00×28.00×20.00 vs 28×28×20 (Δ0) | **PASS** (overlay poor, see B2) |
| T6 L-bracket 4×4 cm | holes + countersinks | 9.8 min | hit 40 | **no** | bracket.stl | **no**: 428 non-manifold edges, 215 comps (degenerate laminae) | 40×40×16 (Δ0) | **FAIL**. The agent also caught my impossible countersink (8.5 mm on a 4.5 mm hole in 2 mm sheet) |
| T7 gray bracket, perspective, wood bg | perspective, low contrast | 12.3 min | hit 40 | **no** | **none** (analysis/ scripts only) | – | est. 13±1 mm strip, 3 holes/leg | **FAIL**: spent every turn on hand-written vanishing-point code, which crashed on `ndarray.ptp` (NumPy 2) |
| T8 mini peg + 1€ coin | coin scale | 16.1 min | hit 40 | yes (5) | clothespin_jaw_half.stl | yes / 1 | 7.55×26.23×3.10. Its px/mm was 34.1 (coin 793 px). Tester segmentation: peg ≈862 px ≈ 25.3 mm, so the length is ~+3.6 % | **PASS (approx)**. The overlay is a filled black blob, offset from the peg |
| T9 print-in-place hinge | 2 bodies, clearances | 20.6 min | hit 40 | yes (8, via scripts) | hinge_pip.stl | yes / **2** (by design) | 100×50×6 (Δ0) | **PASS** (validator says FAIL on 2 shells, which is expected). The overlay is meaningless (perspective photo) |
| T10 glass rosette pull | organic, revolved + scallops | 11.3 min | hit 40 | yes (6) | glass_pull_v2.stl | yes / 1 | 45.00×45.00×50.01 vs 45×45×50 | **PASS**. Compare is side-by-side only, no scale given. Vision calls timed out twice (120 s) |
| T11 Utah teapot mesh (inches, 4 open shells, 160 open edges) | units + holey | 6.8 min | 83 calls, finished | yes (6) | teapot_healed_mm.stl | yes / 1 | 163.42×101.6×80.01 mm = 6.434×4×3.15 in ×25.4 | **PASS**. The agent had to union the shells itself (heal has no union) |
| (script) Stanford armadillo `--units m` | implausible size | – | – | – | – | – | 151 307 mm, warns, but `ok: true` | warn OK, see B5 |

Summary: 5/7 produce a usable part, 1 invalid mesh, 1 no part. **6 of 7 runs used up the 40-turn budget** (round 1 was the same). Dimensional accuracy is exact whenever the user gives numbers. When the agent reads the photo with a coin, it is within ~4 %.

## Regression status of the 10 round-1 bugs
| # | Round-1 bug | v0.1.1 status |
|---|---|---|
| 1 | deps unreachable from system python | **Partly fixed**. The tools work inside Hermes, but **the script launcher is broken** (B1): `python3 scripts/*.py` dies with `No module named numpy`. Agents worked around it by calling the venv python by its full path (T6) or by `sys.path` hacks (T11) |
| 2 | skill id `plugin:` doesn't resolve | **Doc fixed, behaviour not**. In 5/7 runs the first `skill_view` call used `plugin:photo-to-part:…` and failed. The note sits inside SKILL.md, which the agent cannot read until the skill has loaded |
| 3 | stdout not pure JSON | **Fixed**. `json.load` works and ok/FAILED go to stderr |
| 4 | no units for heal | **Fixed**. `--units m` gives a 155.7 mm bunny. Without units, `unit_warning` is set |
| 5 | render speckle / streaks | **Fixed** (bunny and peg render cleanly with the z-buffer) |
| 6 | front view fixed to X–Y | **Fixed** (longest axis is up; `--up`/`--front-axis` work) |
| 7 | no overlay | **Present but low quality** (B2): outline is noisy facet edges, drawn dark, centred on the image instead of the part |
| 8 | "No network" / CAD installs | Fixed in docs. Agents still probed for CadQuery and OpenSCAD and tried `sudo apt` (T5, T6, T10) |
| 9 | heal report counts | **Fixed** (`fan_requested`, `fan_used`, `fan_fallback` and `repair_fragments_removed` are all clear) |
| 10 | agent ran out of turns | **Not fixed**: 6/7 hit 40. Hermes ignored the per-version budget in SKILL.md |

T1/T2 regression: bracket_v2 validates exactly. The T2 clip still FAILs (y 11.5 vs 12): that is the round-1 model, and it shows the validator is still strict.

## Prioritized enhancement list
### Bugs
- **B1 (P0) The launcher re-execs into the wrong interpreter.** Repro: `HERMES_HOME=/workspace/hermes-p2p python3 <skill>/scripts/export_validate.py --help` gives `ModuleNotFoundError: numpy`. Cause: `candidate_pythons()` calls `.resolve()` on `venv/bin/python`, which follows the symlink to the shared base interpreter (`~/.hermes/tools/python-3.14…/bin/python3.14`). Started by that path, Python never reads `pyvenv.cfg`, so site-packages are missing. `pick_reexec` resolves as well. Fix: dedupe on the unresolved path (or `os.path.abspath`) and exec the venv's `bin/python` as it is. Add a test with a symlinked venv. Also check the import in the child before exec, or fall back with a clear error.
- **B2 (P1) The overlay is unusable for comparison.** Repro: `render_views.py peg_v2.stl --photo peg.jpg --photo-scale 6.5 --up y --front-axis x` gives scattered dashes (regress/t3_r2/overlay.png). T8 gives a solid black blob beside the part, and T5 gives hatching. Causes: (a) silhouette edges are taken from every adjacent-face sign flip, so a finely tessellated curved surface yields thousands of interior and back edges; (b) the line colour is near-black at 2–8 px width; (c) with no origin the part is centred on the *image* centre. Fix: rasterize the front view with the existing z-buffer to a mask, trace the outer contour (`skimage.measure.find_contours` or PIL), and draw a 2 px magenta/cyan outline at ~60 % alpha. Add `--overlay-fit auto`, which segments the photo foreground and registers the outline by bbox centre (optionally scale and rotation), and report the IoU in the JSON. An IoU number gives the agent a real pass/fail signal.
- **B3 (P1) The validator message contradicts itself.** T6 printed `not watertight (0 boundary edges)` with 428 non-manifold edges and 215 components. Fix: lead with the cause ("428 non-manifold edges, 482 zero-area faces, 215 shells; likely coplanar or degenerate boolean caps"). Also have `photo_part_heal` (or a `--repair` on validate) offer `merge_vertices + remove_degenerate + manifold3d` round-trip as the suggested fix.
- **B4 (P2) `--units m` warning text is wrong after conversion.** With `--units m` on a mm file it still says "If the file is metres… pass --units m". Fix: when units were passed, say "after --units m the part is 151 m; the file is probably already mm, drop --units".
- **B5 (P2) An implausible size still returns `ok: true`.** Validate and heal pass at 0.16 mm or 151 m. Fix: `ok:false` (or `--allow-implausible`) when `unit_warning` is set and no `--size` was given. Echo the warning to stderr.
- **B6 (P2) A print-in-place part fails validation by design.** T9 is 2 shells. Fix: in SKILL.md, tell the agent to pass `--allow-multi-shell` for print-in-place and assemblies, and expose `expected_shells: N` on the tool.

### Skill-instruction improvements
- **S1 (P0) Turn budget.** 6/7 runs hit 40. Time went to custom image-measurement code (T7: ~10 scripts; T5: `_measure.py`; T8: vertex winding debug) and CAD-backend probing. Fix in SKILL.md: a hard order of operations (1 build ≤ 8 calls → 1 validate → 1 render → report), "never write your own photo-measurement/rectification code; estimate by eye from the image and the scale reference, state ±", and "use trimesh + manifold3d in the plugin env (already installed); do not probe for OpenSCAD/CadQuery unless STEP is required".
- **S2 (P0) Skill discoverability.** Put the correct id in the plugin/skill *description* that `skills_list` shows, or register an alias for `plugin:photo-to-part:photo-to-printable-part`, because that is the form Hermes agents guess first.
- **S3 (P1) Always use the tools, not the scripts.** T6, T7 and T9 never called a `photo_part_*` tool. Say plainly: "Call photo_part_validate / photo_part_render tools. Scripts are for humans."
- **S4 (P1) Perspective and scale guidance.** Add a short reference: how to get px/mm from a coin (common coin diameters table) or ruler, the fact that `--photo-scale` assumes an orthographic, fronto-parallel photo, and an instruction to skip the overlay (and say why) for oblique photos like T7 and T9.
- **S5 (P2) Detect inconsistent user numbers early.** The agent did well on T6 (countersink geometry) and in round-1 T2. Make it a required first step ("check the dims are geometrically possible before modelling").
- **S6 (P2) Vision timeouts.** Two 120 s vision timeouts (T5, T10). Advise one vision call per render set on contact.png, not one per view.

### New features
- **F1 (P1) `photo_part_build` / primitives library.** Every run hand-rolled extrude, revolve, fillet and countersink code in trimesh/manifold3d, which caused T6's non-manifold countersink. Ship a small parametric helper module (plate with holes, countersink, revolve profile, rib pattern, L-bracket, print-in-place hinge) with tested manifold output.
- **F2 (P1) `photo_part_measure` tool.** Given a photo, a reference (coin type or ruler two-point pixel coordinates) and object pixel points, return mm. Optionally do a 4-point homography rectification for perspective shots (would have rescued T7).
- **F3 (P2) `photo_part_heal --union`.** Boolean-union the shells after a keep-all heal (T11 needed a manual union).
- **F4 (P2) Overlay IoU and a contour diff in the render JSON**, so the agent can iterate on numbers rather than by eye (pairs with B2).
- **F5 (P3) Feature checks.** Validate hole diameter and position lists (`--holes`), not only the bbox. Round 1 and T6 both wrote custom hole-check scripts.

## Files
- summary.png: rows T5–T11, columns photo | overlay/compare | iso. The T6 render was made by the tester because the agent produced none.
- regress/: round-1 regression outputs (t3_r, t3_r2 overlays; t4 bunny with `--units m`).
- photos/sources.json: sources and licences.
- t*/: per-test prompt, Hermes log, time, and the agent's model files.

## Sources
- T5 Plastic control knob with metal cap, Mercado Viagens, CC BY 2.0. https://commons.wikimedia.org/wiki/File:Plastic_control_knob_with_metal_cap_(14478221552).jpg
- T6 Bronze angle bracket 4×4 cm A, Fructibus, CC0. https://commons.wikimedia.org/wiki/File:Bronze_angle_bracket_-_4_x_4_cm_-_A.jpg
- T7 Gray angle bracket 12.5 cm WA, Fructibus, CC0. https://commons.wikimedia.org/wiki/File:Gray_angle_bracket_-_12.5_cm_-_WA.jpg
- T8 Miniklammer, Grey Geezer, CC0. https://commons.wikimedia.org/wiki/File:Miniklammer.jpg
- T9 Teardrop plastic piano hinge, Wikiwerks (en.wikibooks), public domain. https://commons.wikimedia.org/wiki/File:Teardrop_plastic_piano_hinge.jpg
- T10 Drawer Pull, The Met (Open Access), CC0. https://commons.wikimedia.org/wiki/File:Drawer_Pull_MET_DP236494.jpg
- T11 Utah teapot (Newell 1975; digitised from a real teapot, not a laser scan), via alecjacobson/common-3d-test-models. Freely redistributed, no licence stated.
- Armadillo (units check), Stanford 3D Scanning Repository, research use with credit.
Not covered: a real *laser scan* in inches, and a gear. No open, licensed gear photo of usable quality turned up quickly. The knob ribs partly cover the toothed case.
