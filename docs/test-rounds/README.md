# Test rounds

Live tests of the plugin in Hermes v0.21.7 with deepseek-v4.1-flash (opencode-go), `--oneshot --yolo --max-turns 40`. Each `rNN/` folder holds the round's `REPORT.md` and `summary.png`. Harness scripts are in [`harness/`](harness/). Every fact below comes from the round reports; "–" means the report has no single number for it.

| Round | Version | Main SHA | Real photos | Sealed (Hermes-driven) evals | Notable regressions / fixes | Pin decision |
|---|---|---|---|---|---|---|
| [r02](r02/REPORT.md) | v0.1.1 | a0e96d0 | 7 runs (T5–T11); T6 non-manifold, T7 no file | – | 4 tools, 0 hooks; plugin tools often unused | – |
| [r03](r03/REPORT.md) | v0.1.2 | 05f2056 | same 7 cases re-run | – | export_validate `--help` fixed (B1); heal hint for broken meshes (B3) | – |
| [r04](r04/REPORT.md) | v0.1.3 | a939851 | 13 runs (9 new cases a–i + T7–T10) | – | bottle cap 1789 shells; 6 tools | – |
| [r05](r05/REPORT.md) | v0.1.4 | 4002dfd | 6 targeted re-runs | – | bottle cap fixed (IoU 0.88); knuckle probe misses real knuckles (T9) | – |
| [r06](r06/REPORT.md) | v0.1.7 | 7b38c38 | 5 pass, 1 weak pass, 2 partial | 7 tasks run; in-process 16/16 | 4/8 hit turn cap; v0.1.6 `output_schema` blocker | – |
| [r07](r07/REPORT.md) | v0.1.8 | 436cf87 | 4–5/8 (per r9) | 15 tasks; several read evals source | turn-cap hits 4/8 → 5/8 | – |
| [r08](r08/REPORT.md) | v0.1.9 | b31f963 | 7/8 (per r9) | 15/16 correct, 1 leak | sealed staging; budget hints | Pin v0.1.9 |
| [r09](r09/REPORT.md) | v0.1.10 | e64fbc6 | 7/8 | 16/16 | best_version_filled leak | Pin v0.1.10 |
| [r10](r10/REPORT.md) | v0.1.11 | 6ab3e1d | 8/8 | 18/18 | T8 uses measure, 0 pixel probes | Pin v0.1.11 |
| [r11](r11/REPORT.md) | v0.1.12 | 7f65735 | 8/8 | 17/18 | hinge_five_knuckles wrong (template dropped arg) | Can pin; hold for strict sealed parity |
| [r12](r12/REPORT.md) | v0.1.13 | b68fdfa | 7/8 | 17/18, 0 leaks | T9 knuckle detector merges coaxial knuckles | Do not pin; keep v0.1.11 |
| [r13](r13/REPORT.md) | v0.1.14 | 729216b | 8/8 | 18/18 | fixes r12 regressions; T10 hit turn cap | Pin v0.1.14 |
| [r14](r14/REPORT.md) | v0.1.15 | 3e2af8f | 8/8 | 18/18 correct, 2 leaks (16/18 clean) | T7 hit turn cap, IoU 0.06 | – (see report) |
| [r15](r15/REPORT.md) | v0.1.16 | 17556b8 | 8/8 | 18/18, 0 leaks | leaks fixed | Pin v0.1.16 |
