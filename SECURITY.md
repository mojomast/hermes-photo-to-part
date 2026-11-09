# Security policy

Report vulnerabilities through GitHub private vulnerability reporting if it is enabled. Otherwise open a short issue that asks for a private channel. Do not include exploit details in a public issue.

This plugin is trusted in-process Python, the same as any other Hermes plugin. Review the source before you enable it.

What it does:

- `register()` calls `ctx.register_skill` and `ctx.register_tool` for `photo_part_validate`, `photo_part_render`, `photo_part_heal`, `photo_part_template`, `photo_part_measure`, and `photo_part_build`. It registers `pre_tool_call` (a skill-id rewrite, which also blocks reads of eval scoring files, and a second callback that asks for Hermes approval before `photo_part_build` or a terminal build runs), `post_tool_call`, and `transform_tool_result`. It does not register middleware, and it does not read credentials. A colon cannot appear in a skill name, so the `plugin:` form of the skill id is not registered as an alias. The skill description and each tool description state the real id.
- The tools and helper scripts read the mesh and image paths you pass them and write the output paths you pass them. They refuse paths under `HERMES_HOME/cache` and paths that Hermes's write denylist refuses (`agent.file_safety.get_write_denied_error`, skipped when that module is not installed). The rectified PNG from measure must end in `.png` and is not replaced unless you pass `overwrite`. Template and heal refuse to replace an existing output unless you pass `--overwrite`. Heal still refuses to overwrite its input. `<file>.validate.json` is checked against that denylist before it is written.
- `photo_part_build` asks for Hermes approval, then runs one local `.py` file you pass, with the plugin interpreter, a timeout of at most 300 seconds, and a captured argument list. It does not use a shell string. It does not open a socket of its own and it does not add credentials. The script itself is code you or the agent wrote. After a successful script, overlapping shells in a new STL or 3MF are unioned locally. The failure text is the script's exception. `help` and `describe` return signatures and do not run a script, so they are not prompted. `PHOTOPART_BUILD_APPROVAL=allow` (also `yes`, `true`, `1`, `off`, `skip`) skips the prompt for a test or a sealed eval. That environment variable is separate from Hermes `--yolo`. The default is to ask, and Hermes fails closed when nobody can approve. Hermes `--yolo` (and `HERMES_YOLO_MODE`) auto-approves the `action: approve` result. The plugin still returns that action. It does not detect or block `--yolo`. In a session that is not running `--yolo`, an unanswered prompt still blocks the build.
- The same approval (`action: approve`, `rule_key: photo_part_build`) is returned from that second `pre_tool_call` when the tool is a terminal or a code tool and the command looks like a photo-to-part build. `ls`, `cat`, `echo`, `rg`, and `pytest` do not. See the limits below. The skill and the tool description tell the agent to call `photo_part_build` instead of the terminal.
- A tool that replaces an existing STL or 3MF copies the previous bytes into `.p2p_history/` beside that file. The copy is content-addressed. The tool does not delete the output. `spec.json` and `--dim` are read from the paths you pass and are not uploaded. `<file>.validate.json` stays beside the mesh. A new validation appends the previous record to `history` in that file. GrabCut, ArUco and AprilTag detection, and an optional PyMeshFix repair run in this process on the files you pass. They do not upload those files.
- They do not open sockets, read `.env` files, or read Hermes credential stores.
- If a helper script is started with a Python that cannot import trimesh, it re-executes itself with the plugin environment's Python. It finds that interpreter from `HERMES_HOME` install metadata (`facts.json` and the install venv layout). It does not run a shell string and it does not install packages.
- There is no telemetry and no self-updater.

Photos you attach in a Hermes chat are still sent to whatever model provider you use. This plugin does not add a second upload. A mesh you point the tools at stays on disk.

Enabling the plugin asks Hermes to install the Python packages listed in `pyproject.toml` from PyPI, after you accept that install. Those packages are not vendored here. CadQuery, build123d, OpenSCAD, and PyMeshLab are not installed by the plugin. Installing CadQuery or build123d yourself, in a project environment, is a separate download and can take several minutes.

## What Hermes installs

Install `mojomast/hermes-photo-to-part/plugin`. Hermes v0.21.7 sparse-checks out that subdirectory, so `evals/`, `tests/` (the scorer, fixtures, and `tests/regression` meshes), and the repository README are not published. `photopart` does not import `evals`.

`hermes plugins install mojomast/hermes-photo-to-part` with no `/plugin` clones the whole tree. The `plugin.yaml` at the repository root sets `requires_hermes: ">=999.0.0"` and `manifest_version: 99`. Hermes v0.21.7 refuses that manifest in `manifest_version_error` before it publishes files. Two caveats:

- A Hermes that both reports a version `>=999.0.0` and supports `manifest_version` 99 would install the root and would copy `evals/` and `tests/`.
- If that stub is removed, an empty manifest still publishes the whole clone, including the scorer.

A subdirectory install replaces only `plugin/` and drops `.git`. `hermes plugins update` cannot update that install. Reinstall with `--force`. Run `hermes plugins validate . --install-deps` and `hermes plugins doctor .` from `plugin/`, not from the repository root. The root manifest is the refusal stub, so validating the root fails on purpose.

A developer checkout still has `evals/` on disk. `pre_tool_call` blocks `read_file` and `search_files` when the path is an eval scoring file (`evals/runner.py`, `tasks.json`, `meshes.py`, `photos.json`, `fixtures`, `evals/__init__.py`, `evals/README.md`) or anything under `tests/regression`, and it blocks a terminal command that reads those paths, imports `evals`, or contains the eval canary. `photo_part_*` tools are not blocked. `pytest`, `python -m pytest`, and `python -m unittest` are not blocked, so a test run can import the scorer. That is intentional.

## Limits of the terminal build check

The check looks at the command text. It does not execute it. For a `.py` path that is readable, not named `test_*`, not under `tests/` or `evals/`, and at most 256KB, it also reads the first 64KB. A build is:

- the command name `photo-part-build`, `cadquery`, `build123d`, or `cq`
- `python -m photopart.build_run` or `python -m photopart.stamp`, or a path ending in `photopart/build_run.py` or `photopart/stamp.py`
- a script whose basename is `build.py`
- Python source that imports `photopart.build_run` or `photopart.stamp`
- Python source that mentions cadquery, build123d, or OCP and also exports or names a `.stl`, `.step`, `.stp`, or `.3mf`
- Python source that mentions `photopart.features`, `photopart.geometry`, or `photopart.parts` and also writes one of those meshes
- `python some.py` with a mesh suffix in the arguments
- a mesh suffix in a command whose working directory is the session's part folder, when that command also runs a `.py` file or names a CAD kernel

`python build.py` is asked about even in a project that is not a photo-to-part session. `cadquery` and `build123d` as the command name are asked about even for `--help`.

It does not see:

- `exec`, `base64`, or another encoding that hides the import and the mesh suffix
- `python make_hinge.py` when that file is missing, unreadable, or its first 64KB never mentions the build modules, a CAD kernel, `photopart.features` / `geometry` / `parts`, or a mesh suffix, and the command line has no mesh suffix
- `import cadquery` in `execute_code` with no export and no mesh suffix
- a shell function or an alias that wraps the build

`ls`, `cat`, `head`, `rg`, `grep`, `echo`, `git`, and `pytest` are not treated as builds. `cat build.py` is not a build. `echo import photopart.build_run` is not a build. `python -c 'print(1)'` followed by that echo is not a build. Quotes around a `python -c` body are kept, including a newline inside the quotes.

## Limits of the eval read block

`cat evals/runner.py` and `read_file` of that path are blocked. `ls evals` is not, because the directory name alone is not a scoring file. `search_files` of `.` is not, so a repo-wide content search can still surface eval text. `cat README.md` is not. If the first `pre_tool_call` hook raises, it retries the read check. A protected eval or `tests/regression` path stays blocked. A normal read, including `README.md`, still proceeds. `pytest` and `unittest` stay allowed. The approval callback does not use that wrapper. Hermes still fail-closes when the approval action is returned and nobody approves, the gate errors, or the prompt times out. Hermes `--yolo` auto-approves that action before the timeout. The plugin does not change that Hermes behavior.
