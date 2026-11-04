# Evals

Twenty-eight tasks from the photo-to-part test rounds. Inputs are synthetic meshes and one self-made CC0 washer photo in `fixtures/`. `photos.json` names openly licensed photos for an optional Hermes session. Those files are not downloaded and their bytes are not in this repo. `coin_scale_sealed` stages three synthetic coin photos (`us_quarter.png`, `cad_loonie.png`, `euro_1.png`: US quarter 24.26 mm, CAD loonie 26.5 mm, €1 23.25 mm) and the in-process check measures those same scenes. It is a stand-in: real caliper photos are not in this repo. Pass is the part box within ±5%, or ±8% when the peg is tilted about 20°.

Eval marker p2p-canary-7f3a9c2e-6b14-4d88-a1e0-9c5d2f8b4a17


`worse_version_reverts`, `frozen_edit_needs_reason`, and `real_photo_overlay` are held out of `results` unless `--include-holdout`. They still run, and a failure fails the suite. `--stage DIR --task ID` copies that task's prompt and its `inputs` to a directory outside this repo. Answer files (`fixture.json`, truth masks, and anything listed under `answers`) stay here for the scorer. `overlay_low_confidence` is `scripted`, so staging writes the prompt only. A transcript leaks when it reads this repo's `evals/` files (`tasks.json`, `runner.py`, `fixtures/`, and the other eval modules) or their absolute paths. A lookalike directory such as `hevals/` does not count. `tool_calls` counts session records, not prose mentions. `wrong_skill_ids` counts a `skill_view` or `skills_list` argument that is not the exact id, including a slash or `plugin:` form inside a `tool_call` `{calls:[...]}` list. A `rewrite_from` row in `.photopart/calls.jsonl` is `skill_id_rewritten` instead.

## In-process suite

These files stay at the repository root. They are not part of the Hermes plugin install (`plugin/`). From the repository root, with `plugin/` installed:

```bash
python -m evals.runner
```

Exit 0 means every task met its expectation and `register(ctx)` registered all six tools. Fewer than six tools prints `plugin registration failed: register(ctx) yielded N tools, expected 6` and exits 1. The JSON report has, for the suite and for each task:

- `passed`
- `dim_error_mm` when a spec row has an actual and a target
- `tool_calls`
- `minutes`
- `wrong_skill_ids` (a `plugin:photo-to-part:photo-to-printable-part` id used as a skill)
- `deleted_files`

No model key is required. The runner does not open a socket.

## Against Hermes

1. Install this plugin and enable it. Start a new session.
2. Paste one `prompt` from `evals/tasks.json`. The agent should call `photo_part_*` tools. The skill id is `photo-to-part:photo-to-printable-part`. `plugin:photo-to-part:photo-to-printable-part` is not a skill name.
3. Save the transcript, including timestamps if the client writes them (`2026-11-02T22:00:00`).
4. Score it:

```bash
python -m evals.runner --transcript session.txt
python -m evals.runner --hermes-session SESSION_ID --hermes-home "$HERMES_HOME"
python -m evals.runner --hermes-session ./session.jsonl
```

`--hermes-session` reads a Hermes v0.21.7 session directly. A session id is looked up in `$HERMES_HOME/state.db` (table `messages`, column `tool_calls`) and in `$HERMES_HOME/sessions` (`<id>.json`, `<id>.jsonl`, `session_<id>.json`, `session_<id>.jsonl`). A path scores that file. The export format is one session object per JSONL line, with a `messages` list. A live transcript is one message dict per line. Assistant `tool_calls` are the count. The matching `role=tool` row is not a second call. A text export of the form `<timestamp> TOOLCALL name {args}` counts every name on those lines, including `terminal`. `calls_source` is `state.db`, `jsonl`, `json`, or `transcript`. A missing session returns `ok: false` and `tool_calls: 0`.

The transcript section counts the same records. A sentence that only mentions a tool is not a call. `plugin_calls` is the `photo_part_*` subset. It also reports minutes between the first and last timestamp, lines that delete an `.stl` or `.3mf`, and uses of the mistaken `plugin:` skill id. A line that only says that string is not a skill name is ignored.

The in-process suite still runs, so a green transcript score does not replace a failing task. Hold out `worse_version_reverts` and `frozen_edit_needs_reason` when you want a pair the agent has not just been shown.

When a prompt needs a real photograph, use a URL in `photos.json` and keep the file outside the repo. The quarter is a public-domain US Mint photograph. The school rulers are CC0. The ruler drawing is CC BY-SA 4.0 and needs attribution if you redistribute it.
