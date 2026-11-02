# Changelog

## 0.1.1 — 2026-11-02

- Register `photo_part_validate`, `photo_part_render`, `photo_part_heal`, and `photo_part_template`. Hermes runs them inside the plugin environment, so a check no longer depends on system Python.
- Helper scripts re-exec into that environment when the current Python cannot import trimesh. They do not ask you to pip install into an externally managed interpreter.
- Document the skill id as `photo-to-part:photo-to-printable-part`. `plugin:photo-to-part:photo-to-printable-part` is not a skill name.
- Checker stdout is one JSON object. `ok` and `FAILED` go to stderr.
- `--units` and `--scale` convert a mesh to millimetres. Sizes under 1 mm or over 2 m warn, and nothing is rescaled automatically. Renders fit the frame to the part.
- Previews quadric-decimate above 8,000 faces and rasterize with a z-buffer, so a scan is not a sprinkle of dropped faces and a flat face does not streak.
- The front view uses the longest axis as up. `--up` and `--front-axis` override it.
- `--photo-scale` (pixels per millimetre) draws an outline overlay on the reference photo. The skill tells the agent to use it instead of writing a script.
- Heal reports `fan_requested`, `fan_used`, and `fan_fallback` separately. `shells_dropped` counts input shells only. Pieces created by the repair are `repair_fragments_removed`.
- The skill states a per-version tool budget, says not to delete a file the user skipped, and says not to claim a fit test the user did not accept.
- A STEP solid still needs CadQuery or build123d in the project environment. The install is pinned, it downloads packages, and it can take several minutes.

## 0.1.0 — 2026-11-02

- First public release of the photo-to-part Hermes plugin.
- Skill `photo-to-printable-part`: rebuild a part from photos and measurements, or clean up a scan, and iterate with fit tests.
- Helper scripts for a parametric sample plate, watertightness and bounding-box checks, orthographic previews, and scan healing.
- Local only. No network calls, credentials, telemetry, or printer connection.
