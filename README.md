# photo-to-part

Hermes plugin that turns photos, a few measurements, or a messy 3D scan into a parametric part you can print or edit. The agent writes the solid in code, checks that the mesh is watertight and the right size, and renders views you can hold next to the original.

It is a community plugin by [Kyle Durepos](https://github.com/mojomast). It is not a Nous Research product. The method is inspired by Michael Lydick's video [I'm an Engineer. This ChatGPT Test Scared Me.](https://www.youtube.com/watch?v=TUqScwjnO_k) The sample in this repo is a generic plate with a hook, not a copy of the object in that video.

![Catalog banner](docs/catalog-banner.png)

## What you get

One skill, `photo-to-part:photo-to-printable-part`, and four local scripts:

| Script | Job |
| --- | --- |
| `make_template.py` | Write a watertight sample plate (STL, OpenSCAD, parameters). |
| `export_validate.py` | Check watertightness, one shell, and the bounding box against target millimetres. |
| `render_views.py` | Front, side, top, and iso previews, plus a side-by-side with a photo. |
| `heal_scan.py` | Weld, fill holes, and keep the largest shell of a scan. Flat caps are not a finished surface. |

`register()` does not add tools, hooks, or middleware. Enabling the plugin installs the Python packages in `pyproject.toml` into the Hermes environment after you accept them. CadQuery, build123d, and OpenSCAD are not installed for you. Use one of those in the working directory when you want fillets or a STEP file.

## Disclosure

The scripts read the mesh and image paths you give them and write the output paths you give them. They do not open network connections, read credentials, talk to a printer, or update themselves. Photos you attach in a Hermes chat still go to your model provider. That is Hermes, not an extra upload from this plugin. Details are in [SECURITY.md](SECURITY.md).

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
python skills/photo-to-printable-part/scripts/heal_scan.py scan.stl --out healed.stl
```

The checkers print JSON on stdout. Exit `0` passes, `2` means the mesh loaded but a check failed, `1` means the command could not run. STL files are millimetres. 3MF, which records that unit, needs the optional `lxml` extra: `pip install -e ".[threemf]"`.

## Sample

![Four views of the sample plate](docs/screenshot-views.png)

The checked-in sample is `examples/plate-clip/`. Overall size **51 × 72.6 × 6 mm**. The picture beside the front view is a grid drawn by the script, labeled as synthetic.

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
