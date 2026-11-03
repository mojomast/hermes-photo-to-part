# Evals

Twenty-six tasks from the photo-to-part test rounds. Inputs are synthetic meshes and one self-made CC0 washer photo in `fixtures/`. `photos.json` names openly licensed photos for an optional Hermes session. Those files are not downloaded and their bytes are not in this repo.

`worse_version_reverts`, `frozen_edit_needs_reason`, and `real_photo_overlay` are held out of `results` unless `--include-holdout`. They still run, and a failure fails the suite. `--stage DIR --task ID` copies that task's prompt and its `inputs` to a directory outside this repo. Answer files (`fixture.json`, truth masks, and anything listed under `answers`) stay here for the scorer. `overlay_low_confidence` is `scripted`, so staging writes the prompt only. A transcript leaks when it reads this repo's `evals/` files (`tasks.json`, `runner.py`, `fixtures/`, and the other eval modules) or their absolute paths. A lookalike directory such as `hevals/` does not count. `tool_calls` counts session records, not prose mentions. `wrong_skill_ids` counts only `skill_view` arguments.

## In-process suite

From the repository root, with the package installed:

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
```

The transcript section counts tool-call records (JSON `tool_calls` / `function_call`, a `name` with `arguments`, and a timestamped call such as `skill_view` or `photo_part_validate`). A sentence that only mentions a tool is not a call. `plugin_calls` is the `photo_part_*` subset. It also reports minutes between the first and last timestamp, lines that delete an `.stl` or `.3mf`, and uses of the mistaken `plugin:` skill id. A line that only says that string is not a skill name is ignored.

The in-process suite still runs, so a green transcript score does not replace a failing task. Hold out `worse_version_reverts` and `frozen_edit_needs_reason` when you want a pair the agent has not just been shown.

When a prompt needs a real photograph, use a URL in `photos.json` and keep the file outside the repo. The quarter is a public-domain US Mint photograph. The school rulers are CC0. The ruler drawing is CC BY-SA 4.0 and needs attribution if you redistribute it.
