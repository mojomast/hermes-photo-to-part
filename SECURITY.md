# Security policy

Report vulnerabilities through GitHub private vulnerability reporting if it is enabled. Otherwise open a short issue that asks for a private channel. Do not include exploit details in a public issue.

This plugin is trusted in-process Python, the same as any other Hermes plugin. Review the source before you enable it.

What it does:

- `register()` only calls `ctx.register_skill`. It does not register tools, hooks, or middleware, and it does not read the environment.
- The helper scripts read the mesh and image paths you pass them and write the output paths you pass them. They refuse to overwrite an input with the healed output.
- They do not open sockets, spawn shells, read `.env` files, or read Hermes credential stores.
- There is no telemetry and no self-updater.

Photos you attach in a Hermes chat are still sent to whatever model provider you use. This plugin does not add a second upload. A mesh you point the scripts at stays on disk.

Enabling the plugin asks Hermes to install the Python packages listed in `pyproject.toml` from PyPI. Those packages are not vendored here. CadQuery, build123d, OpenSCAD, and PyMeshLab are not installed by the plugin.
