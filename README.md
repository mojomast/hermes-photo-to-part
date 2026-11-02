# photo-to-part

Hermes plugin that turns photos, a few measurements, or a messy 3D scan into a parametric part you can print or edit. The agent writes the solid in code, checks that the mesh is watertight and the right size, and renders views you can hold next to the original.

It is a community plugin by [Kyle Durepos](https://github.com/mojomast). It is not a Nous Research product. The method is inspired by Michael Lydick's video [I'm an Engineer. This ChatGPT Test Scared Me.](https://www.youtube.com/watch?v=TUqScwjnO_k) The sample in this repo is a generic plate with a hook, not a copy of the object in that video.

![Catalog banner](docs/catalog-banner.png)

## What you get

One skill and six tools. The skill id is `photo-to-part:photo-to-printable-part`. That is the whole id. `plugin:photo-to-part:photo-to-printable-part` is not a skill name. A `plugin:` prefix in Hermes docs is a placeholder, and a skill name cannot contain a colon, so that string is not registered as an alias.

| Tool | Job |
| --- | --- |
| `photo_part_template` | A watertight block: sample plate, plate with holes, countersink, revolved profile, radial ribs, L-bracket, print-in-place hinge, thread, knurl, sweep, hex screw, hex standoff, or bottle cap. Try one of these before a custom script. |
| `photo_part_build` | Runs one local `.py` file with the plugin interpreter (`interpreter` in the JSON). The script can `import` `photopart.features`. Overlapping shells are unioned. Working directory, timeout, captured output. No shell. On failure, `error` is the exception. |
| `photo_part_validate` | Watertightness, shell count (`expected_shells` for a print-in-place part), bounding box, holes, and a `spec.json` or `--dim name=value±tol` check (bbox, shells, knuckles, hole count). A check the template emitted must stay in the spec. A longest side under 1 mm or over 2 m fails unless `allow_size` is set. The only sidecar is `<file>.validate.json`, with the mesh hash. Each run appends the previous record to `history`. |
| `photo_part_render` | Front, side, top, and iso previews fitted to the part, a side-by-side, and a silhouette overlay. `overlay_fit: auto` searches rotation and mirror, picks a view, and reports the IoU. `--roi`, `--seed`, and a measure JSON keep a coin from winning. A render of `name_vN` with no fresh sidecar is refused (`unvalidated: true`). `stale_validation` is true when the file changed after validate. |
| `photo_part_heal` | Weld, fill holes, and keep the largest shell of a scan. `--union` merges overlapping shells. Flat caps are not a finished surface. Refuses to replace an existing file unless `--overwrite`. |
| `photo_part_measure` | Pixels per millimetre from a coin or a ruler, a `reference_bbox` for that object, and an optional four-point rectified image. |

The same jobs are available as scripts under `skills/photo-to-printable-part/scripts/` for a person at a shell. Hermes should call the tools. The tools already run where trimesh and manifold3d are installed. A system `python script.py` re-execs into that environment without resolving the venv interpreter symlink. `photo_part_build` uses that same unresolved interpreter and returns it as `interpreter`. Do not pip install into the system Python.

Write `name_vN.stl` and do not overwrite it. Do not delete an STL or 3MF. A replaced file is copied into `.p2p_history/` first. Pass absolute paths in the project. The tools refuse `$HERMES_HOME/cache`. Each tool JSON includes `next_step`. A build's `next_step` is always validate, including when the script fails. From one flat photo, thickness and depth are unobserved: ask, or mark them assumed. Write the user's dimensions to `spec.json` before modelling and pass that file to validate. Template and build warn when `spec.json` is missing. The deliver step validates the final file, lists spec deviations, then renders it with `final` set.

`register()` adds those tools and the skill. It does not add hooks or middleware, and it does not read secrets. Enabling the plugin installs the packages in `pyproject.toml` from PyPI after you accept them. CadQuery, build123d, and OpenSCAD are not installed for you. Installing one in the project environment, when you want a STEP file, downloads packages and can take several minutes. The pinned lines are in the skill's `references/cad-backends.md`.

## Disclosure

The tools and scripts read the mesh and image paths you give them and write the output paths you give them. They do not open network connections, read credentials, talk to a printer, or update themselves. `photo_part_build` runs a local Python file with a timeout and does not add a socket or a credential. If a script is started with a Python that cannot import trimesh, it re-executes itself with the plugin environment's Python. That interpreter path comes from `HERMES_HOME`. Photos you attach in a Hermes chat still go to your model provider. That is Hermes, not an extra upload from this plugin. Details are in [SECURITY.md](SECURITY.md).

## Install

Until a maintainer lists it in the Hermes catalog, install from git and leave it disabled until you have read the code:

```bash
hermes plugins install mojomast/hermes-photo-to-part --no-enable
hermes plugins enable photo-to-part
```

Start a new Hermes session after enabling. Ask for a replacement part, a fit-test print, or a scan turned into a solid. The skill's description is what makes the agent load it. You can also load it by name:

```text
skill_view("photo-to-part:photo-to-printable-part")
```

After catalog acceptance, the reviewed install is `hermes plugins install photo-to-part`. Do not assume the catalog name works just because this README exists. The pin, when there is one, is a full commit SHA in `NousResearch/hermes-agent`, not this branch tip.

## Use it from a shell

From a checkout, with the dependencies installed (`pip install -e .`):

```bash
python skills/photo-to-printable-part/scripts/make_template.py --out-dir ./part-v1 --ascii
python skills/photo-to-printable-part/scripts/export_validate.py ./part-v1/plate_clip.stl --size 51 72.6 6
python skills/photo-to-printable-part/scripts/render_views.py ./part-v1/plate_clip.stl --out-dir ./renders --grid-mm 2
python skills/photo-to-printable-part/scripts/heal_scan.py scan.stl --out healed.stl --units m
```

Each checker prints one JSON object on stdout. `ok` and `FAILED` go to stderr. Exit `0` passes, `2` means the mesh loaded but a check failed, `1` means the command could not run. Pass `--units m`, `cm`, or `in` when the file is not millimetres. If that conversion is already applied and the part is still implausible, drop the flag. `--allow-size` is the only way to accept a part under 1 mm or over 2 m. `--expected-shells 2` is the print-in-place hinge. `--photo-scale` is pixels per millimetre and writes `overlay.png` plus an IoU when `--overlay-fit auto` is set. STL files are millimetres after that conversion. 3MF, which records that unit, needs the optional `lxml` extra: `pip install -e ".[threemf]"`.

## Sample

![Four views of the sample plate](docs/screenshot-views.png)

The checked-in sample is `examples/plate-clip/`. Overall size **51 × 72.6 × 6 mm**. The picture beside the front view is a grid drawn by the script, labeled as synthetic. The views are fitted to the part, and the front view looks along the thin axis.

![Synthetic reference beside the front view](examples/plate-clip/renders/compare_front.png)

Regenerate both with:

```bash
python -m photopart.showcase
```

## Development

Python 3.11 or 3.12.

```bash
uv venv .venv
uv pip install --python .venv/bin/python --exclude-newer 2026-10-30 -e ".[dev]"
.venv/bin/python -m unittest discover -s tests -v
```

CI runs that on Ubuntu for 3.11 and 3.12. The date cut is a three-day quarantine, the same idea as the Hermes dependency guidance. [RESEARCH.md](RESEARCH.md) records the catalog rules, the skill format, and the CAD sources behind the defaults.

## License

[MIT](LICENSE). Copyright 2026 Kyle Durepos.
