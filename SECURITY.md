# Security policy

Report vulnerabilities through GitHub private vulnerability reporting if it is enabled. Otherwise open a short issue that asks for a private channel. Do not include exploit details in a public issue.

This plugin is trusted in-process Python, the same as any other Hermes plugin. Review the source before you enable it.

What it does:

- `register()` calls `ctx.register_skill` and `ctx.register_tool` for `photo_part_validate`, `photo_part_render`, `photo_part_heal`, `photo_part_template`, and `photo_part_measure`. It does not register hooks or middleware, and it does not read credentials. A colon cannot appear in a skill name, so the `plugin:` form of the skill id is not registered as an alias. The skill description states the real id.
- The tools and helper scripts read the mesh and image paths you pass them and write the output paths you pass them. They refuse to overwrite an input with the healed output.
- They do not open sockets, read `.env` files, or read Hermes credential stores.
- If a helper script is started with a Python that cannot import trimesh, it re-executes itself with the plugin environment's Python. It finds that interpreter from `HERMES_HOME` install metadata (`facts.json` and the install venv layout). It does not run a shell string and it does not install packages.
- There is no telemetry and no self-updater.

Photos you attach in a Hermes chat are still sent to whatever model provider you use. This plugin does not add a second upload. A mesh you point the tools at stays on disk.

Enabling the plugin asks Hermes to install the Python packages listed in `pyproject.toml` from PyPI, after you accept that install. Those packages are not vendored here. CadQuery, build123d, OpenSCAD, and PyMeshLab are not installed by the plugin. Installing CadQuery or build123d yourself, in a project environment, is a separate download and can take several minutes.
