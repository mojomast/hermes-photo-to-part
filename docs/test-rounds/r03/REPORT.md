# photo-to-part v0.1.2 (05f2056), round-3 test in Hermes

Tested 2026-11-02 (America/Toronto). Setup is the same as round 2: Hermes v0.21.7, `HERMES_HOME=/workspace/hermes-p2p`, deepseek-v4.1-flash via opencode-go, `--max-turns 40`, 7 runs in parallel, and the same prompt.txt and photos as round 2.

## Install
- The duplicate-member clash came from the stray clone `/tmp/p2p-v012`. The failed receipt is `logs/update_receipts/pm_20261102T181548Z…`: "Two workspace members are both named hermes-photo-to-part", with `plugin-sources/p2p-v012-…` alongside `photo-to-part-…`. No persistent registration was left behind (grep across HERMES_HOME found it only in the logs, and its temp env was already gone). I deleted `/tmp/p2p-v012`.
- `git checkout 05f2056` in `plugins/photo-to-part`, then `hermes plugins update` and `hermes plugins validate <dir> --install-deps`: Validation passed, and the latest receipt reads `ok`.
- Doctor: **photo-to-part 0.1.2, 5 tools**, 0 hooks. `plugins list` shows one photo-to-part (0.1.2, enabled).

## Quick regressions
- B1 repro (`python3 <skill>/scripts/export_validate.py --help` with system python): **fixed**.
- Round-1 T1 bracket_v2: ok, 130×130×13.
- Round-2 T6 broken mesh, revalidated: the message now names the cause ("428 non-manifold edges, 482 degenerate faces. Run photo_part_heal…; 215 shells… pass --expected-shells N"). **B3 fixed.**

## Round 2 vs round 3
Tester re-validation of each test's final file. "Turns" means tool calls; the budget is 40 iterations.
| Test | R2 result | R3 result | R3 extents vs target | Turns R2 → R3 | Min R2 → R3 | Plugin tools R2 → R3 (R3 calls) | Wrong skill-id R2 → R3 | Overlay IoU R3 |
|---|---|---|---|---|---|---|---|---|
| T5 knob | PASS | **PASS** | 28×28×20 exact, 1 shell, +STEP | 93 (budget) → 85 (budget) | 19.8 → 6.9 | yes → yes (validate, measure, render ×2, validate) | 1 → 1 | 0.39 (oblique photo; photo mask caught mostly the gold cap) |
| T6 L-bracket | FAIL (non-manifold) | **PASS** | 40×16×40 (axis-swapped) exact, watertight, 1 shell | 87 → 83 (budget) | 9.8 → 6.9 | no → **barely** (1 validate, ok:false on v1; never re-validated or rendered) | 1 → 0 | – (no render) |
| T7 perspective bracket | FAIL, no part | **FAIL, no part** | none. Guessed a 30 mm strip ±5 (R2: 13 ±1; likely ~15–20) | 82 → 91 (budget) | 12.3 → 14.1 | no → yes (measure ×4, quad mode) | 1 → 1 | – |
| T8 mini peg + coin | PASS approx | **WEAK** | 3.14×4.5×26.12. Length matches R2 (26.1 vs about 25.3 by tester estimate). The 4.5 mm jaw width is too thin: R2 had 7.55, and measure itself read 6.67 | 86 → 83 (budget) | 16.1 → 8.9 | yes → yes (measure, template; **no validate/render**) | 1 → 1 | 0.10 tester run: auto-fit **locked onto the coin** |
| T9 hinge | PASS (2 bodies) | **FAIL (marginal)** | 100×50×**7.0** vs 6 (+1 mm); 2 shells as expected | 90 → 84 (budget) | 20.6 → 13.5 | yes → yes (validate ×2, render) | 1 → 0 | – (compare only) |
| T10 glass pull | PASS | **FAIL** | 45×44.9×50, but **137 shells, 272 non-manifold edges**. A valid version was overwritten after validation, and the stale validate.json still says ok | 89 → 85 (budget) | 11.3 → 18.6 | yes → yes (6) | 0 → 0 | 0.0099 (one render; no useful fit) |
| T11 teapot (in, holey) | PASS | **PASS** | 163.42×80.01×101.6, 1 shell, watertight; used `heal --union` | 83 → **37** (finished) | 6.8 → **3.7** | yes → yes (validate, heal, validate, render) | 0 → 0 | – |

Totals: R2 had 5 pass / 2 fail. R3 has 3 pass (T5, T6, T11), 1 weak (T8) and 3 fail (T7, T9, T10). Wrong skill-id attempts fell from 5/7 to 3/7. 6/7 runs still use the full 40-turn budget, but they are faster (median 8.9 min vs 16.1). No `$HERMES_HOME`-wide installs and no apt or CadQuery probing were seen, except one `which openscad` in T10.

## Round-2 issues verified fixed
B1 launcher, B3 cause-naming, B4/B5 (unit warnings; size failure unless `--allow-size`, seen in the help and in T10's first ok:false), B6 `--expected-shells` (it works, see T9 revalidation), F3 `heal --union` (T11), F2 `photo_part_measure` (coin and quad modes work and return mm), overlay IoU and overlay_diff.png are produced. S1: no custom vision-rectification code this time (T7 used the measure tool). S6: fewer vision calls (T5 R2 11 → R3 0 timeouts).

## Still broken / new
1. **Overlay auto-fit picks the wrong object (P0 for B2/F4).** On T8 it registered to the coin, the largest foreground blob (IoU 0.10). On T5 it registered to the cap highlight. Fix: add `--overlay-roi x0,y0,x1,y1` or `--overlay-seed x,y` (the agent already knows where the part is), exclude the measure reference (the coin circle from photo_part_measure), and report which blob was used. Warn when IoU < 0.5 and the photo is oblique.
2. **Agents end their turns without a final validate and render (P0).** T6, T8 and T10 left files unvalidated, and T10 overwrote a good STL with a broken one after validating. Fix: in SKILL.md, write `name_vN.stl` and never overwrite. Better, make photo_part_render refuse (or flag) a mesh whose mtime is newer than its last validate. Have validate write `<stl>.validate.json` next to the file.
3. **No sanctioned way to run the agent's own build script inside the plugin env (P1).** T7 wrote build_bracket.py and then gave up: "system Python has no trimesh, and the plugin's private venv would not import from my probe". T6 found the venv path by hand. Fix: add a `photo_part_build` tool that runs a given .py inside the plugin env with a time limit, or print the interpreter path in `photo_part_template` output and SKILL.md. Also steer toward `photo_part_template shape=l_bracket`, which T7 never tried.
4. **Templates and measure write to `$HERMES_HOME/cache/scratch`, not the working folder (P1).** T8's plate_clip.stl and T7's rectified PNGs landed there. Fix: default the output to the cwd, or require `out_dir`.
5. **The skill id is still guessed with `plugin:` (P2).** 3/7 runs, 1 wasted call each. Fix: Hermes-side alias, or the skill name in the plugin description shown by `tools search`.
6. **Thickness from a single front photo (P2).** T8 used 3.14 mm "thickness" read from an in-plane width, and the jaw came out a sliver. In SKILL.md, require stating which dimensions are not visible and pick a default with a ±.
7. **Turn budget (P2).** 6/7 still exhaust 40. T11 shows the ideal flow takes ~37 calls. Consider stating "≤ 25 calls per version" in SKILL.md and having the tool outputs say "next step:".

## Files
summary.png (photo | overlay_diff/compare | iso per test), regress/, t*/ (prompt, hermes.log, time.txt, outputs). Tester renders: t6/t8/t10 renders_tester. Round-2 folder left untouched (size in r2size.txt).
