# Agent handoff: hermes-photo-to-part

## What this is
A Hermes Agent plugin that turns photos, measurements or 3D scans into printable parts (STL/STEP). Skill id `photo-to-part:photo-to-printable-part`. It registers 6 tools and hooks `pre_tool_call`, `post_tool_call` and `transform_tool_result` (4 hook registrations in total). Current release: **v0.1.16** at `17556b836b56013c70004fafbe4ebe5fffcda495` (PR #20).

## Repo layout (v0.1.16)
- `plugin/`: the installable plugin (install with subdir `plugin`).
- `plugin.yaml` (root): a refusal stub so a root install fails clearly.
- `evals/`: eval runner and tasks (`python -m evals.runner`).
- `tests/`: unit tests, incl. `tests/regression` meshes.
- `docs/test-rounds/`: per-round reports, [summary table](docs/test-rounds/README.md), [harness](docs/test-rounds/harness/).
- `docs/research/`: research notes.

## Set up a Hermes test home from scratch
1. Install Hermes Agent v0.21.7.
2. `export HERMES_HOME=<dir>`
3. `hermes plugins install mojomast/hermes-photo-to-part/plugin --ref <sha> --yes-deps --enable`
4. `hermes plugins doctor photo-to-part` and expect 6 tools, 4 hooks.
5. Model: `deepseek-v4.1-flash`, provider `opencode-go`, base_url `https://opencode.ai/zen/go/v1`. Put **your own** key in `$HERMES_HOME/.env` as `OPENCODE_GO_API_KEY=...`. Never commit or print it.

## Tests and evals (from repo root)
- `python -m unittest discover -s tests` (175 tests)
- `python -m evals.runner` (24/24, plus 4/4 holdouts with `--include-holdout`)

## How a round works
- 8 real-photo cases: gear, bottle cap, strap hinge, M3 screw, T9 print-in-place hinge, T7 bracket, T8 coin peg, T10 glass pull. Plus 18 sealed evals (staged with `evals.runner --stage`, only the prompt is staged).
- Each run: `timeout 2400 hermes chat --query-file prompt.txt --image <img> --oneshot --yolo --max-turns 40`.
- `export PHOTOPART_BUILD_APPROVAL=allow`: `--yolo`/oneshot can't answer prompts, and Hermes `--yolo` auto-approves anyway.
- Launch detached with `setsid nohup ... &`.
- Never read the Hermes session DB (`state.db`) while runs are live (it can kill leases).
- Keep harness scripts and eval code outside the agents' reachable dirs.
- Relaunch a case only once, and only for infra failures (auth, DNS, provider stalls).
- Compare per case against the current pin and write `REPORT.md` + `summary.png`.

## Release process
1. A cloud agent or dev opens a PR, waits for CI (`gh pr checks --watch`), squash-merges, tags `vX`, and publishes the release.
2. Install on the test box, run doctor, run a round, compare per case.
3. Pin the catalog only if the new version is at least as good as the current pin.

## Catalog
- PR https://github.com/NousResearch/hermes-agent/pull/148018 from fork branch `catalog/photo-to-part-v0.1.0` on `mojomast/hermes-agent`, file `plugin-catalog/photo-to-part.yaml`.
- Currently pinned v0.1.16 (sha 17556b8..., `subdir: plugin`, `provides_hooks` listed). Awaiting maintainer merge.
- To update: edit the yaml sha/version/URLs, curl-check every URL returns 200, PUT via `gh api repos/mojomast/hermes-agent/contents/plugin-catalog/photo-to-part.yaml` with the file's current blob sha, then `gh pr edit 148018 --repo NousResearch/hermes-agent` for title and body.

## Open items for v0.1.17
- T8 overlay marked trusted at IoU 0.0 (trust-flag bug).
- T10 produced no overlay in r15.
- Bottle cap template outer diameter needs a spec edit.
- T9 pin-bore misses.
- Low overlay IoU on T7/T10.
- Validator counts the cap's blind cavity as a bore.
- `bores_not_genus` eval is slow (~6.8 min).
- Approval gate is bypassed by Hermes `--yolo` by design.
- Terminal-build detector misses obfuscated or kernel-free scripts.
- Read guard fails open on hook exceptions.
- Subdir installs drop `.git`, so `hermes plugins update` needs a reinstall with `--force`.

## Owner preferences
- Token-conscious: don't spawn unnecessary agents or optional work without asking.
- Never print keys.
- Ask before public or catalog submissions of other projects.
