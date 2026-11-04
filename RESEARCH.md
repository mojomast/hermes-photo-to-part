# Research notes

Checked against primary docs on **2 November 2026**. This file is the design record for version 0.1.0. It is not a Hermes guarantee: the catalog page and `plugin-catalog/README.md` win if they move.

## 1. Hermes plugin format

Sources:

- Build a Hermes Plugin (developer guide), accessed 2026-11-02: https://hermes-agent.nousresearch.com/docs/developer-guide/plugins
- Shorter guide, same date: https://hermes-agent.nousresearch.com/docs/guides/build-a-hermes-plugin
- Loader source on `main`, fetched 2026-11-02: https://github.com/NousResearch/hermes-agent/blob/main/hermes_cli/plugins.py and https://github.com/NousResearch/hermes-agent/blob/main/hermes_cli/plugins_content.py
- User-facing plugin page: https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins

A directory plugin needs `plugin.yaml` and an `__init__.py` with `register(ctx)`. Hermes also loads `desktop/plugin.js`, a portable `plugin.json`, or `dashboard/manifest.json`. Through 0.1.15 this repo was a directory plugin at the repository root, which is the layout used by [hermes-session-warmer](https://github.com/mojomast/hermes-session-warmer). As of 0.1.16 the installable tree is `plugin/`, the same idea as [orbit-desktop](https://github.com/mojomast/orbitdesktop), which keeps the plugin in a subdirectory and sets `subdir` in the catalog. [afterforge](https://github.com/ussyverse/afterforge) is a tools-category entry (catalog maintainer `ussyverse`) with the same manifest shape: name, repo, full SHA, capabilities lists. The install identifier is `mojomast/hermes-photo-to-part/plugin`. A catalog entry should set that subdirectory. The `plugin.yaml` at the repository root is a refusal stub (`requires_hermes >=999`, `manifest_version: 99`) so a root install does not publish `evals/` and `tests/`.

Manifest v1 needs `name` and, in practice, `version` and `description`. The published examples also list `provides_tools` and `provides_hooks`. Manifest v2 (`#64165`) is additive. A file without `manifest_version` stays v1 forever. Unknown fields warn and do not refuse to load. v2 fields used here:

| Field | What this plugin sets |
| --- | --- |
| `manifest_version: 2`, `api_version: 1` | File format 2, runtime API generation 1. |
| `python_dependencies` | Ranges with upper bounds, duplicated in `pyproject.toml`. The developer guide says `pyproject.toml` wins when both exist. |
| `license`, `homepage`, `tags` | MIT, this repo, discovery tags. |
| `provides_tools`, `provides_hooks`, `provides_middleware`, `requires_env` | Empty. The plugin does not register those surfaces. |

`requires_plugins`, `config_schema`, `requires_auth`, and `oauth` are unused. There is no config and no secret.

`register_skill(name, path)` namespaces the skill as `photo-to-part:photo-to-printable-part`. The skill is not copied into `~/.hermes/skills/`. The two-argument call is what this plugin uses, so a build whose signature is only `(name, path)` still loads.

**Doc drift, recorded on purpose.** The developer guide still says plugin skills are left out of the system prompt's `<available_skills>` index and must be loaded by name. The `register_skill` docstring on `main` on 2026-11-02 says the opposite: an enabled plugin's skills are listed by `skills_list` and in `<available_skills>`. Pull request [134803](https://github.com/NousResearch/hermes-agent/pull/134803) is the change that started disclosing them. Issue [25052](https://github.com/NousResearch/hermes-agent/issues/25052) and PR [107964](https://github.com/NousResearch/hermes-agent/pull/107964) are the earlier opt-in design (`list_in_awareness`), which the current signature no longer takes. Whether a given install shows the skill in the prompt depends on that Hermes build. The skill text tells the agent the qualified name either way.

Latest stable Hermes release checked the same day: **v0.22.5** (22 October 2026), with a v0.22.6 canary already tagged. https://github.com/NousResearch/hermes-agent/releases/tag/v0.22.5

`requires_hermes` is omitted. Catalog rule 14 says the floor is a SemVer range, never a date, and never newer than the current release, and it must be true. The only runtime call is `ctx.register_skill(name, path)`, which the current guide already documents. This environment did not run `hermes plugins validate` against an older Hermes, so inventing a floor would be a guess. See "Uncertainties" below.

Python dependencies are declared, not imported by `register()`. Hermes asks before it installs them and enables the plugin only after they resolve inside Hermes's own pins. CadQuery, build123d, and OpenSCAD are **not** plugin dependencies. Pulling Open CASCADE into every Hermes environment would be large and easy to conflict. The agent installs a kernel in the working directory only when the user wants a STEP solid.

## 2. Catalog submission

Sources, both accessed 2026-11-02, and they match:

- https://github.com/NousResearch/hermes-agent/blob/main/plugin-catalog/README.md
- https://hermes-agent.nousresearch.com/docs/developer-guide/plugins/catalog-submission
- Entry shape used by the existing listings: `plugin-catalog/hermes-session-warmer.yaml`, `plugin-catalog/orbit-desktop.yaml`, `plugin-catalog/afterforge.yaml`

There is no registry CLI and no self-serve form. An entry is one YAML file added by a pull request to `NousResearch/hermes-agent`, merged by a maintainer. Installs check out the full 40-character `sha`, not a branch or a tag.

Rules that shaped this repo:

1. Human review. The PR has to come from the owner (`mojomast`) or a major contributor. A drive-by is declined.
2. Exact SHA pin. The tag `v0.1.0` is a label. The catalog `sha` is the commit that tag points at.
3. No self-updater, no remote code loader. Updates are a new pin PR plus `hermes plugins update`.
4. Declared capabilities must match `register()`. Empty tool, hook, middleware, and env lists are the match. The catalog schema has no `provides_skills` field; the skill is part of the tree the reviewer reads.
5. `hermes plugins validate --install-deps` is the CI check. `dangerous` fails admission. `caution` is a warning the reviewer reads.
6. No core monkeypatching, no Desktop `plugin.js`, no credential files, no approval bypass.
7. Dependency ranges need an upper bound. A floor sitting on the newest release gets pushed back. Floors here are older than the 2 November 2026 PyPI tips (`trimesh` 5.2.0, `shapely` 2.2.0, `numpy` 2.5.4, `matplotlib` 3.11.2, `pillow` 13.0.0, `mapbox-earcut` 2.1.0, `networkx` 3.7). `lxml` is a dev extra for 3MF, not a plugin dependency, because Hermes already pins shared libraries and a hard `lxml` floor is an easy conflict.
8. Disclose local file reads and writes, PyPI installs, and the fact that chat photos still go to the user's model provider. No telemetry.
9. No committed binaries, bytecode, or opaque archives. The sample STL is ASCII. 3MF is a zip, so the sample does not commit one; the test builds it in a temp directory. PNGs are the catalog images.
10. `version` is quoted. `tier: community`. `category: tools`. Official and verified tiers are set by Nous, not by this PR.
11. README at the pinned commit is what the plugin page renders. Screenshots are optional, up to six, and must be `https` URLs on a GitHub host, pinned to the same commit. A banner is 2:1 (1200×600). `readme: true` is the default.

Before catalog acceptance the install line is a git install, not the catalog name. The session-warmer README uses the same wording. This repo copies that:

```bash
hermes plugins install mojomast/hermes-photo-to-part/plugin --no-enable
hermes plugins enable photo-to-part
```

That `/plugin` suffix is the Hermes v0.21.7 subdirectory form (`owner/repo/subdir`). It sparse-checks out `plugin/` only. The clone used for that install does not keep `.git` in the published tree, so `hermes plugins update` cannot update it. Reinstall with `--force`. `hermes plugins validate . --install-deps` runs inside `plugin/`.

After a maintainer merges the catalog PR:

```bash
hermes plugins install photo-to-part
```

## 3. Skill authoring

Sources, accessed 2026-11-02:

- https://hermes-agent.nousresearch.com/docs/developer-guide/creating-skills
- https://hermes-agent.nousresearch.com/docs/user-guide/features/skills
- https://agentskills.io/specification
- https://github.com/agentskills/agentskills/blob/main/docs/skill-creation/optimizing-descriptions.mdx

Hermes skills follow the Agent Skills layout. `SKILL.md` frontmatter requires `name` (lowercase, hyphens, ≤64 characters, matches the directory) and `description` (1–1024 characters). The description does both jobs: what the skill does, and the words that should trigger it. The body is loaded only after the agent decides the description matches. References, scripts, and assets load only when the body names them.

Practices applied here:

- One skill, under 200 lines. Backend choice, tolerances, grid reading, and scan repair are separate reference files, each opened for one reason.
- Trigger text names STL, 3MF, STEP, resin, FDM, calipers, 2 mm grid paper, marked-up photos, and scans. Those are the phrases a person actually uses.
- Helper scripts are real programs with exit codes, not snippets the agent is supposed to retype. The Agent Skills spec asks for scripts that fail with a useful message.
- Hermes metadata (`metadata.hermes.tags`, `category`, `version`, `license`) is included. `requires_toolsets` is left unset rather than guessed. A wrong toolset name would hide the skill.
- The skill tells the agent to write into the user's project and not into the installed plugin.

Progressive disclosure in Hermes is `skills_list` (name, description, category), then `skill_view(name)`, then `skill_view(name, "references/....md")`. Plugin skills use the qualified name.

## 4. Code CAD from photos

The method, not a transcript: give photos plus a few real measurements, or a scan; ask for a printable file or an editable solid; print and compare side by side and stacked; correct with a marked-up photo, a hard dimension, a 2 mm grid, and any missed feature in one pass. Michael Lydick shows that loop in "I'm an Engineer. This ChatGPT Test Scared Me." (https://www.youtube.com/watch?v=TUqScwjnO_k). The first model in that video copied a glue crack. The skill tells the agent to treat cracks, glue, and wear as damage unless the user says otherwise. Expect several versions. Support marks are a printing artifact.

### Kernels

- **CadQuery** and **build123d** are Python on Open CASCADE. They export STEP and STL, and they can fillet a selected edge. build123d's README describes the export set and the algebraic API: https://github.com/gumyr/build123d
- **OpenSCAD** is a good fit for prisms and holes. It does not write STEP. Current development builds can use the Manifold kernel; the language is still mesh CSG.
- A practitioner write-up of headless build123d (accessed via the search on 2026-11-02) found STL tessellation going non-manifold when two boolean operands shared a coplanar face, while the STEP solid stayed valid. The fix was a 0.1 mm overlap. The template's hook overlaps the plate for the same reason. https://moltbook.com/post/a1e56710-f6ed-48be-9062-e8550f06cc4d is a blog, not a spec. The overlap rule is used because it matches how B-rep tessellation fails, and because the sample in this repo is checked with `trimesh` afterwards.

The plugin's own sample does not use a CAD kernel. Shapely builds the profile, `mapbox-earcut` triangulates it, and `trimesh.creation.extrude_polygon` extrudes it. That path is small enough for CI. `mapbox-earcut` is the engine trimesh prefers; the `triangle` engine is the non-FSF-license fallback and is not used.

### Meshes

`trimesh` 5.2 documents `Trimesh.is_watertight` as "every edge is in two faces", and `fill_holes` as an in-place cap of boundary loops that can be wrong on non-convex holes. https://trimesh.org/trimesh.html

The validator reports watertightness, winding, non-manifold edges (an edge in more than two faces), degenerate faces, shell count, volume, and the axis-aligned extents against a target size. It does not repair the file it was asked to judge.

The heal script does weld vertices, drop degenerate faces, fix normals, fill holes, and optionally keep the largest shell. The report says when a fan was used. PyMeshLab is documented as an optional next step, not a dependency: https://pymeshlab.readthedocs.io/

### STL, STEP, 3MF

- STL is universal and unitless. The scripts treat numbers as millimetres and say so in the JSON.
- STEP is the editable solid for Fusion 360.
- 3MF Core Specification 1.3 (February 2025 PDF on 3mf.io) says producers must set the model unit (default millimetre) and that a model mesh must have manifold edges, consistent orientation, and outward normals. https://3mf.io/specification/ and the v1.3.0 PDF linked from there. trimesh's 3MF writer emits `unit="millimeter"` (see `trimesh/exchange/threemf.py` on `main`). Writing that file needs `lxml`. The sample commit skips 3MF because a 3MF is a zip archive, and catalog rule 17 is happier when reviewers are not asked to trust a committed archive. The unit test builds one in a temp directory.

### Printer tolerances

Used as starting points, with the fit test as the real check. Cited pages were read on 2026-11-02.

- Formlabs Form 4 design guide and Form 4L design specifications: 0.2 mm minimum wall, 0.4 mm minimum clearance, XY bands on the order of ±0.15% to ±0.3% depending on feature size. https://formlabs.com/blog/design-guide-form4/ and https://formlabs.com/support/Design-specifications-for-3D-models-Form-4L-generation/
- Prusa modeling guide: a 0.4 mm nozzle is about 0.45 mm per perimeter; movable fits start at 0.3 mm clearance; a calibrated Original Prusa is on the order of 0.1 mm in Z and 0.3 mm in X/Y. https://help.prusa3d.com/article/modeling-with-3d-printing-in-mind_164140 and https://help.prusa3d.com/article/faq-frequently-asked-questions_1932

The skill models the measured nominal size and adds clearance only on mating faces.

### Scale

A 2 mm grid is a scale only when the page was printed at 100% and the photo is straight on. A caliper measurement wins when the two disagree. The renderer's `--grid-mm 2` draws that spacing in model units so counts can be compared. It does not calibrate the camera.

## 5. How this repo follows the rules

- Manifest v2, empty capability lists, MIT license, version 0.1.0.
- Skill plus four tested scripts: template, validate, render, heal.
- Dependencies are ranges with upper bounds. CI installs them with `uv pip install --exclude-newer 2026-10-30` (three days before this note).
- No network, no secrets, no self-update, no core patching, no vendored binaries.
- Sample geometry is generic. The video is credited as inspiration and is not transcribed into the repo.
- Catalog images are generated by `python -m photopart.showcase` from that geometry, so the pictures match the code.

## 6. Uncertainties

- `hermes plugins validate` was not run here. The Hermes package was not installed in this environment. The entrypoint test only checks that `register()` calls `register_skill` once with the skill path. A maintainer's catalog CI is the real admission test. Command, from the submission guide: `hermes plugins validate /path/to/this/repo --install-deps`.
- Prompt listing of plugin skills depends on the Hermes version, as the doc drift above describes. No `requires_hermes` floor is declared, for the reason in section 1. If review wants a floor, `>=0.22.5` is the newest stable release as of this note and should be set only after someone actually loads the plugin on that release.
- Hermes may already pin `numpy`, `pillow`, or `matplotlib`. The ranges are wide on purpose. If catalog CI reports a resolver conflict, narrow the range to include Hermes's pin rather than forcing an upgrade. Hermes's own pins cannot move.
- `fill_holes` will not rescue an arbitrary scan. The skill says so. A curved rebuild still has to be done in a CAD kernel.
- Printer numbers are vendor design guides, not a calibration of the user's machine.
- The `afterforge` catalog entry used as a formatting reference is maintained by `ussyverse`, not by `mojomast`. `orbit-desktop` and `hermes-session-warmer` are the `mojomast` listings.

## 7. Version 0.1.1

A real session on Hermes v0.21.7 (deepseek-v4.1-flash) spent its turns on three gaps: system Python could not import trimesh, the skill id was given a `plugin:` prefix, and the agent wrote its own photo overlay. v0.1.1 answers those with tools plus a re-exec launcher, the exact skill id, and `--photo-scale`.

`ctx.register_tool(name, toolset, schema, handler, description=...)` is the keyword form of the method on the v0.21.7 plugin context. `provides_tools` lists the four names passed to that call. `requires_hermes` stays unset: this checkout was not passed through `hermes plugins validate`, and a floor we have not watched load would be a guess. The user who hit the bugs was on v0.21.7, which already has `register_tool`.

`fast-simplification` 0.2.0 (uploaded 2026-08-12, under the 2026-10-30 quarantine) is the quadric decimator trimesh calls. The pin is `>=0.1.8,<0.3`. CadQuery 2.8.0 and build123d 0.13.0 were the PyPI tips on 2026-11-02. The documented project-env lines use floors below those tips (`cadquery>=2.6,<2.9`, `build123d>=0.10,<0.14`). Those packages are still not plugin dependencies. The plugin tools do not open sockets. The CAD install does, and the docs say so.

Preview rendering no longer uses matplotlib's tick locator. A z-buffer and a frame fitted to the mesh replaced it. matplotlib stays a dependency because the catalog-image builder uses its font as a fallback. The iso view is still the old projection, with no back-face culling.
