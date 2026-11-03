# photo-to-part

Hermes plugin that turns photos, a few measurements, or a messy 3D scan into a parametric part you can print or edit. The agent writes the solid in code, checks that the mesh is watertight and the right size, and renders views you can hold next to the original.

It is a community plugin by [Kyle Durepos](https://github.com/mojomast). It is not a Nous Research product. The method is inspired by Michael Lydick's video [I'm an Engineer. This ChatGPT Test Scared Me.](https://www.youtube.com/watch?v=TUqScwjnO_k) The sample in this repo is a generic plate with a hook, not a copy of the object in that video.

![Catalog banner](docs/catalog-banner.png)

## What you get

One skill and six tools. The skill id is `photo-to-part:photo-to-printable-part`. Load it with `skill_view("photo-to-part:photo-to-printable-part")`. That is the whole id. `plugin:photo-to-part:photo-to-printable-part` is not a skill name. A `plugin:` prefix in Hermes docs is a placeholder, and a skill name cannot contain a colon, so that string is not registered as an alias.

A Hermes session has about 40 tool calls in total. Pass `calls_used` on each tool. `PHOTO_PART_MAX_CALLS` overrides that cap. `photo_part_template` and `photo_part_build` with `help` or `describe` return parameters and an example script, so the source files do not need to be opened. `evals/` and `tests/` are excluded from the Python package (see `pyproject.toml` and `MANIFEST.in`). Hermes installs this plugin from git and copies the whole tree, so those directories can still sit on disk next to the skill. Do not read them.

| Tool | Job |
| --- | --- |
| `photo_part_template` | A watertight block: sample plate, plate with holes, countersink, revolved profile, radial ribs, L-bracket, print-in-place hinge, thread, knurl, sweep, hex screw, hex standoff, bottle cap, spur gear, spiral scroll, or strap hinge. Try one of these before a custom script. |
| `photo_part_build` | Runs one local `.py` file with the plugin interpreter (`interpreter` in the JSON). The script can `import` `photopart.features` (`spur_gear`, `spiral_scroll`, `strap_hinge`, and the thread helpers). Overlapping shells are unioned. Working directory, timeout, captured output. No shell. On failure, `error` is the exception. |
| `photo_part_validate` | Watertightness, shell count, bounding box, circular bores, printability (wall, overhang, bed contact, body gap), and a `spec.json` or `--dim` check. A frozen checklist needs `--reason` to change. Booleans and `--answer` fill the checklist. A passing validate that was given a spec also writes the render sheet. The sidecar keeps `history` and a score out of 100. |
| `photo_part_render` | Front, side, top, and iso previews fitted to the part, an eight-view comparison sheet, a side-by-side, and a silhouette overlay. `overlay_fit: auto` tries all three orthographic views, searches rotation at 15° then 1° plus a mirror, and reports the IoU, `overlay_poses`, and the top 3 poses. `--roi` or `--seed` seeds GrabCut. An angled photo is still scored with `overlay_iou_label` `guide_only`. An `--roi` that crops the silhouette is expanded. A render of `name_vN` with no fresh sidecar is refused (`unvalidated: true`). `final` delivers the best validated version. `stale_validation` is true when the file changed after validate. |
| `photo_part_heal` | Weld, fill holes, and keep the largest shell of a scan. `--union` merges overlapping shells. `--engine meshfix` uses PyMeshFix when that package is installed. Flat caps are not a finished surface. Refuses to replace an existing file unless `--overwrite`. |
| `photo_part_measure` | Pixels per millimetre from a coin, a ruler, or an ArUco/AprilTag marker. Each value is tagged `in_plane` or `out_of_plane` with `uncertainty_mm`. Returns `reference_bbox` and an optional four-point rectified image. |

The same jobs are available as scripts under `skills/photo-to-printable-part/scripts/` for a person at a shell. Hermes should call the tools. The tools already run where trimesh and manifold3d are installed. A system `python script.py` re-execs into that environment without resolving the venv interpreter symlink. `photo_part_build` uses that same unresolved interpreter and returns it as `interpreter`. Do not pip install into the system Python.

`spur_gear` is an involute gear. Parameters are module, tooth count, pressure angle (default 20°), and face width, plus an optional bore with either a keyway or a D-flat, and an optional hub. The tip diameter is module × (teeth + 2). The root diameter is module × (teeth − 2.5), from a 1.25-module dedendum. `scroll` is an Archimedean or log spiral strip (`spiral_scroll`: width, thickness, turns, end radius). `strap_hinge` fastens one or two of those scrolls onto a straight strap. Each of those shapes is one watertight body. A build script imports the same functions from `photopart.features`.

Templates write `<shape>_v1.stl` unless spec.json names a `part`. `plate_clip.stl` stays as it is. Write the next edit as `name_vN.stl` and do not overwrite it. Tool results include `budget` (`max_calls`, `calls_used`, `remaining`, `plugin_calls`) and, for a template or build, `bodies`, `bores`, and `sections_mm2`. Do not write a probe script for those. Deliver as soon as validate passes. At about 60% and 80% of the call cap, `next_step` says to deliver now. An overlay whose segmentation is unstable reports low confidence, a null IoU, and a next step that asks for a seed point or a region box. A passing validate draws that overlay from the last measure step when a photo and scale were recorded. `last_measure.json` is written in the project directory, not the plugin directory. Hole count is the circular bore count, including holes in the legs of a thin L-bracket; genus is separate. When bores are zero and genus is positive or unreliable, the status is `undetected` instead of a failed count. Thread and knurl faces are not wall-thickness sources.

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
.venv/bin/python -m evals.runner
```

`evals/README.md` says how to score a Hermes transcript with the same tasks. The runner itself stays on this machine and does not download the photos named in `evals/photos.json`.

CI runs that on Ubuntu for 3.11 and 3.12. The date cut is a three-day quarantine, the same idea as the Hermes dependency guidance. [RESEARCH.md](RESEARCH.md) records the catalog rules, the skill format, and the CAD sources behind the defaults.

## License

[MIT](LICENSE). Copyright 2026 Kyle Durepos.
