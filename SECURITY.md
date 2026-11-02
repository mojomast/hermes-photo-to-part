# Security policy

Report vulnerabilities through GitHub private vulnerability reporting if it is enabled. Otherwise open a short issue that asks for a private channel. Do not include exploit details in a public issue.

This plugin is trusted in-process Python, the same as any other Hermes plugin. Review the source before you enable it.

What it does:

- `register()` calls `ctx.register_skill` and `ctx.register_tool` for `photo_part_validate`, `photo_part_render`, `photo_part_heal`, `photo_part_template`, `photo_part_measure`, and `photo_part_build`. It does not register hooks or middleware, and it does not read credentials. A colon cannot appear in a skill name, so the `plugin:` form of the skill id is not registered as an alias. The skill description and each tool description state the real id.
- The tools and helper scripts read the mesh and image paths you pass them and write the output paths you pass them. They refuse paths under `HERMES_HOME/cache`. Template and heal refuse to replace an existing output unless you pass `--overwrite`. Heal still refuses to overwrite its input.
- `photo_part_build` runs one local `.py` file you pass, with the plugin interpreter, a timeout of at most 300 seconds, and a captured argument list. It does not use a shell string. It does not open a socket of its own and it does not add credentials. The script itself is code you or the agent wrote. After a successful script, overlapping shells in a new STL or 3MF are unioned locally. The failure text is the script's exception.
- A tool that replaces an existing STL or 3MF copies the previous bytes into `.p2p_history/` beside that file. The copy is content-addressed. The tool does not delete the output. `spec.json` and `--dim` are read from the paths you pass and are not uploaded. `<file>.validate.json` stays beside the mesh. A new validation appends the previous record to `history` in that file. GrabCut, ArUco and AprilTag detection, and an optional PyMeshFix repair run in this process on the files you pass. They do not upload those files.
- They do not open sockets, read `.env` files, or read Hermes credential stores.
- If a helper script is started with a Python that cannot import trimesh, it re-executes itself with the plugin environment's Python. It finds that interpreter from `HERMES_HOME` install metadata (`facts.json` and the install venv layout). It does not run a shell string and it does not install packages.
- There is no telemetry and no self-updater.

Photos you attach in a Hermes chat are still sent to whatever model provider you use. This plugin does not add a second upload. A mesh you point the tools at stays on disk.

Enabling the plugin asks Hermes to install the Python packages listed in `pyproject.toml` from PyPI, after you accept that install. Those packages are not vendored here. CadQuery, build123d, OpenSCAD, and PyMeshLab are not installed by the plugin. Installing CadQuery or build123d yourself, in a project environment, is a separate download and can take several minutes.
