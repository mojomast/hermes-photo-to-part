# photo-to-part: best-practice research for v0.1.12 (2026-11-03)
Input: r10 REPORT (v0.1.11, 6ab3e1d), RESEARCH_v0111.md (not repeated). Code read at /workspace/hermes-p2p/plugins/photo-to-part (6ab3e1d). I re-ran the plugin's own functions on r10 meshes with the install venv. Nothing in the repo was changed.

## Findings from the code (before the fixes)
- **T9 holes (issue 3): root cause found.** `spec.py` is unchanged since 0.1.10 (`git log -- photopart/spec.py`), so the code did not regress. The r10 mesh is different: the agent's `build_hinge.py` uses `SECTIONS = 160` for the barrels. `_section_polygons` snaps section points to a 0.05 mm grid. On a 1.9 mm bore with 0.075 mm segments, that turns the circle into a staircase. The perimeter grows by about 10% and `_circularity` drops to **0.825**, under the 0.85 cut in `_circular_interiors`. Measured on v3 at x=±25: raw 0.825, after `simplify(0.05)` 0.989–0.991, with the convex-hull perimeter 0.983. The bore area is correct (11.39 mm² = π·1.9²). The ray path (`_bores_from_rays`) can't help, because the pin shell fills the bore and leaves only a 0.4 mm annular clearance, so no void column runs through.
- **IoU null (issue 5):** the IoU is computed but hidden. `overlay._alignment` sets `iou = None` whenever `segmentation_confidence == "low"`. All three cases were low because of the gate reason "mask touches two or more roi borders" (gear, T7, T8), and the gear also had "stability 0.00". `fit` was still computed: gear IoU 0.35 / chamfer 7.7 mm, T7 0.26 / 24.6 mm, T8 0.37 / 1.65 mm. So the foreground mask leaks into the background or the ROI is too tight, and the pose search can't correct perspective.
- **Wrong skill id (small item):** it's a scorer artifact. In the cap and strap-hinge runs, `.photopart/calls.jsonl` shows `rewrite_from: "plugin:photo-to-part:photo-to-printable-part"`, and the very next tool result is `{"success": true, ...}`. The v0.1.11 hook rewrote the id and nothing was lost. The scorer counts the original argument.
- **Standards (issue 1):** `standards.check_standard` pulls designations from the whole spec text (`_spec_text` → `_designations`). `_check_metric` then compares `_cross_section(report)` (the part bbox) with the nearest of major dia, hex, socket and flange. A 45 mm rosette that mentions an M5 screw gets matched to the 11.4 mm flange.
- **Knuckles (issue 2):** `spec.count_knuckles` samples rings of radius up to 0.48 × the smallest cross-section around the **bbox centre**. It counts occupied runs along the axis. A 4 mm-thick flat scroll plate is "occupied" wherever the scroll links cross the centre line, which gave 7 runs. Nothing checks that the material is a cylinder.

---
## 1. Standards false positive: gate on role and size
**Best practice**
- Feature recognition in CAD/CAM classifies a feature (hole, thread, boss) before it applies a standard. Dimensions are checked per feature, never per part envelope. See STEP AP224 machining features and the hole/thread callouts in ASME Y14.5 / ISO 1101 (drawings attach a fastener callout to a specific feature): https://www.asme.org/codes-standards/find-codes-standards/y14-5-dimensioning-tolerancing
- Use tolerance bands relative to nominal from the governing standard: ISO 4759-1 product grades A/B for head dimensions, ISO 965 for threads. ISO 4162's dc is a max only, so accept ≤ dc_max, and ≥ dw_min for the bearing face: https://www.nufast.co.uk/uploads/ISO4162.pdf · https://studbolts.com/dimensions/iso/4162/

**Fix (`photopart/standards.py`)**
1. Match a designation only when it is bound to a role. Bound means one of:
   - the spec has a `fasteners: [{"designation":"M5","role":"screw|nut|clearance_hole|tapped_hole|thread","feature":"hole 0"}]` entry;
   - a tagged thread region exists (`features` regions or `.faces.json` `regions`);
   - the designation sits next to a role word in a named dim (`flange_mm`, `head_mm`, `thread`, `bolt`, `screw` as the **part** name).
   Text such as "mounts with an M5 screw" or "for M5" is a **hole/clearance** role. Compare it to `report["holes"]`/bore diameters against ISO 273 (fine/medium/coarse), never to the bbox.
2. Plausibility gate before comparing: a feature is only a candidate if `0.5 × nominal ≤ measured ≤ 2 × the largest standard dimension for that row` (M5: 2.5–22.8 mm). Otherwise record it in `checked` as `skipped: "size 45.0 mm is not plausible for M5 (flange max 11.4)"`, with no warning.
3. Use the part-envelope path in `_cross_section` only when the spec's `part`/name is itself a fastener (`screw|bolt|nut|washer|standoff`, regex on `spec["part"]`). Exclude it when the spec has `decorative: true` or a role of `handle|pull|knob|rosette`.
4. Bands: `_tolerance(standard)` becomes per-dimension. Use major dia −0.25/+0.05 mm (ISO 965 6g ballpark), hex s per the row's min/max, flange ≤ dc_max + 0.3 (printing), and holes per ISO 273 class. Keep max(0.3 mm, 8%) only as the fallback.

**Acceptance**
- r10 T10 glass pull: no standards warning. `checked` lists M5 as skipped or as a clearance-hole check against its bore.
- The r10 M3 screw (flange 7.0) produces no warning.
- A synthetic M5 flange bolt with an 8.1 mm flange warns.
- Unit test: a spec "rosette 45 mm, M5 mounting screw" plus a 5.5 mm bore → clearance check passes (ISO 273 medium 5.5).

## 2. Knuckle detection: find cylinders, don't count rings
**Best practice**
- Detect primitives from surface normals. In Efficient RANSAC (Schnabel et al. 2007), a cylinder is an axis + radius, inliers must pass a distance and normal test, and each shape is a connected component. https://onlinelibrary.wiley.com/doi/10.1111/j.1467-8659.2007.01016.x · https://doc.cgal.org/latest/Shape_detection/index.html · https://doc.cgal.org/latest/Shape_detection/classCGAL_1_1Shape__detection_1_1Cylinder.html
- Region growing on mesh faces (Lafarge & Mallet, in the same CGAL page) works for tessellated CAD meshes.

**Fix (`photopart/spec.py`)**
1. `detect_knuckles(mesh, axis_hint=None)`:
   - Use face normals of faces whose normal is ⊥ to a candidate axis (|n·a| < 0.15).
   - Find the axis as the smallest eigenvector of Σ nnᵀ over those faces, or take the hint.
   - Project the face centroids onto the plane ⊥ axis and fit circles (Kåsa/Taubin algebraic fit), then RANSAC clusters by (centre, r).
   - A knuckle is a connected component of inlier faces covering ≥ 240° of arc, with r ≥ max(1.0 mm, 0.6 × leaf thickness) and length ≥ 1.5 × r. RMS residual must be < 3% of r.
   - Knuckles count only when ≥ 2 segments share one axis (coaxial: centre distance < 0.2 mm, axis angle < 2°) and there are gaps between them. Report `knuckles: n, axis, radius, segments:[x0,x1]`.
2. `count_knuckles` stays as a cross-check. A mismatch becomes a **warning**, not a failure (same pattern as `holes._probe_warning`).
3. Run the check only when the spec declares knuckles **and** the part is a hinge (`part`/template in `hinge|pip_hinge|piano`). The `strap_hinge` template's defaults (`_TEMPLATE_CHECKS` in `spec.py:985`, catalog entry) must not add `knuckles` when the user says "one flat piece / no pivot". In `catalog.py strap_hinge`, set the `knuckles` default to None unless `pivot=true`.
4. Validate output: when a check fails because the detector found no cylinder (`knuckles=7 by rings, 0 cylinders`), say "knuckle probe is unreliable here; the check is reported as a warning". The agent then has no reason to edit the spec (freeze.json stays at 0 edits).

**Acceptance**
- The r10 strap hinge v2 with its original spec (knuckles from the template) → 0 cylinders, warning only, no failure.
- `hinge_five_knuckles` eval still passes with 5.
- The T9 teardrop hinge → 5 coaxial segments.
- Synthetic: a flat plate with 7 rounded links → 0. A single long rod → 1 segment, which fails the "≥2 with gaps" rule, so the count is 0 or 1 and gets reported as such.

## 3. T9 holes undetected
**Cause:** see Findings. The 0.05 mm grid snap plus fine tessellation inflates the perimeter, so circularity reads 0.825 < 0.85. Bores filled by a pin aren't visible to the ray probe.
**Best practice:** measure circularity on a smoothed or simplified contour, or use a circle-fit residual instead of 4πA/P². P² is very sensitive to perimeter noise, and roundness is properly the radial deviation from a fitted circle (ISO 12181 least-squares circle; standard text not linked). OpenCV contour features (`approxPolyDP`, `minEnclosingCircle`): https://docs.opencv.org/4.x/dd/d49/tutorial_py_contour_features.html · Shapely `simplify` (Douglas-Peucker): https://shapely.readthedocs.io/en/stable/reference/shapely.simplify.html
**Fix (`photopart/spec.py`)**
1. `_circularity(hole)`: compute on `hole.simplify(grid)`, with grid = the snap grid (0.05). Better: replace it with `_roundness(hole)`. Do a least-squares circle fit on the ring vertices and pass when the RMS radial residual is < max(0.03 mm, 4% of r) and the area matches πr² within 5%. Keep 4πA/P² on the simplified ring as a secondary score.
2. `_section_polygons`: make the snap grid relative, min(0.05, 0.01 × the bbox's smallest extent). Also snap with `shapely.set_precision` instead of rounding each endpoint.
3. Clearance (annular) bores: in `_bores_from_sections`, also accept an interior ring that contains a separate inner polygon (the pin) with a radial gap ≥ 0.2 mm. Report `kind: "pin_clearance"` and `clearance_mm`. Section each shell separately (`mesh.split(only_watertight=False)`) so the pin shell doesn't merge into the sleeve's section.
4. Eval: add `pip_hinge_fine_tessellation` (sections=160) to `evals/meshes.py`, with hole_count=2.
**Acceptance**
- r10 T9 v3 → 2 bores of Ø3.8 (kind pin_clearance, clearance 0.4).
- The r8 mesh still → 2.
- `bores_not_genus` and T7 6=6 are unchanged.
- A 0.5 mm-staircase square hole is still not a bore (roundness fails).

## 4. Thread markers that travel with the mesh
**Options**
- **3MF Triangle Sets** (Core 1.3+): named groups of triangle indices in namespace `http://schemas.microsoft.com/3dmanufacturing/trianglesets/2021/07`. Consumers MAY ignore them, and they do not change geometry. https://raw.githubusercontent.com/3MFConsortium/spec_core/master/3MF%20Core%20Specification.md · https://github.com/3MFConsortium/spec_core/releases · lib3mf support: https://github.com/3MFConsortium/lib3mf/pull/404
- **3MF custom metadata**: `<metadata name="photopart:regions">` in a declared namespace, holding a JSON string of the geometric regions (axis, r range, z range, pitch). Same core spec, plus https://3mf.io/spec/core-v1-3-0/
- 3MF per-triangle `pid/p1` base materials: slicers would read these as **materials/colours** and change the print. Avoid.
- STL attribute bytes: the 16-bit colour field is non-standard (VisCAM/SolidView vs Materialise conventions disagree), and most tools zero it on save. Not robust. https://en.wikipedia.org/wiki/STL_(file_format)
- Re-detection from geometry on validate: needs no metadata and survives any format, copy, or re-export (Quaoar thickness notes; periodicity approach in RESEARCH_v0111 §2).
**Recommendation:** make **geometric re-detection on validate** primary, because only it survives a copied STL or a slicer round-trip. Write 3MF metadata plus a Triangle Set (`photopart-thread`) as a portable hint when the output is 3MF. Keep the sidecar, keyed by mesh hash, as a cache.
**Fix**
- `printability.detect_periodic_regions(mesh)` (planned in v0111, evidently not used on validate. The r10 copied screw without `.faces.json` warned 0.70 mm):
  - Fit a cylinder axis per shell (same circle-fit code as §2).
  - Ray-sample the radius on a θ×z grid, then FFT along z.
  - A thread is a peak at pitch 0.35–3 mm with amplitude ≥ 0.15 mm and a phase that drifts linearly with θ (helix). A knurl is ≥ 12 periods in θ.
  - Validate should call it in `printability.check_printability` whenever `face_tags` is None. The report shows `tags_source: sidecar|3mf|detected|none`.
- `io.py` 3MF export: write `<metadata name="photopart:regions">` and a `t:trianglesets` block. Read both in `features.load_face_tags` before the sidecar. trimesh's 3MF exporter won't emit these, so post-process the zip (ElementTree insert) after `trimesh.exchange.threemf.export_3MF`.
- Sidecar: add `"mesh_sha256"` and ignore the sidecar when the hash differs (it's stale).
**Acceptance**
- r10 screw and cap STLs copied without the sidecar → no thin-wall warning, `tags_source: detected`, pitch 0.5 ± 0.05 on the screw.
- A 3MF round-trip through trimesh load keeps the metadata.
- Opening the 3MF in PrusaSlicer/Orca loads without error or extra materials (manual check).
- A negative case (thin flange beside the thread) still warns.

## 5. Overlay fit on hard photos (gear, T7 perspective, T8 small part)
**Best practice**
- Rectify the plane first. With a coin/ruler/quad, a homography to a fronto-parallel view removes perspective before silhouette matching (`measure.homography` and `_rectify` already exist).
- Coarse-to-fine registration:
  1. Coarse: a pose grid (rotation, mirror, plus camera elevation for 3D parts), scored by chamfer distance on distance transforms.
  2. Refine: ECC (`cv2.findTransformECC`, MOTION_AFFINE or HOMOGRAPHY) on blurred silhouettes, or 2D ICP on contour points. ECC needs a rough initialization, and bounded homographies keep projective terms from blowing up. https://docs.opencv.org/3.4.20/dc/d6b/group__video__track.html · https://learnopencv.com/image-alignment-ecc-in-opencv-c-python/ · chamfer matching: https://github.com/kipr/opencv/blob/master/modules/contrib/src/chamfermatching.cpp
- Segmentation for gray-on-gray parts: GrabCut seeded with a probable-foreground rectangle plus the user seed, and grow the ROI when the mask touches the borders. https://docs.opencv.org/4.x/d8/d83/tutorial_py_grabcut.html
**Fix (`photopart/overlay.py`)**
1. Always report `fit.iou` and the chamfer values. Rename the hidden headline field so `_alignment` returns `iou` (fit) and `iou_trusted: false` with the gate reason when segmentation is low. The score/overall logic stays (overall = min(seg, fit)).
2. Gate "mask touches ≥2 ROI borders": in `_foreground_for_overlay`, loop `_grow_roi` up to 2 times (×1.5) and re-run `grabcut_mask`. Pick the mask that is stable under `_mean_pairwise_iou` and doesn't touch the borders. For T7/T8, use `measure`'s `part_seed`/coin exclusion (already in `last_measure.json`) as the seed and the exclude list.
3. Perspective: if `last_measure.json` holds a quad/homography or a coin ellipse (axis ratio < 0.95 means tilt), warp the photo with `measure.apply_homography` before `search_alignment`. For a coin only: estimate tilt from the ellipse axes (cos θ = minor/major) and pre-scale along the minor axis.
4. Refinement step after `_search_chamfer`: run `cv2.findTransformECC(model_float, fg_float, warp, MOTION_AFFINE)` on Gaussian-blurred masks, then optionally MOTION_HOMOGRAPHY. Reject the result if the scale changes > 15%, shear > 0.1, or |h31|,|h32| > 1e-3. Keep it only if chamfer improves.
5. 3D parts (gear seen at an angle, bracket): add elevation views (0°, 30°, 60°) to `paint_auto_views` and pick the best chamfer score.
**Acceptance**
- On r10 gear, T7 and T8, `iou` is non-null in every overlay report.
- After ROI growth plus rectify/ECC: T7 IoU ≥ 0.6 and chamfer ≤ 5 mm, T8 IoU ≥ 0.6, gear ≥ 0.6, or the result is honestly "low" with `iou_trusted:false`.
- Unit test: a synthetic rectangle warped by a known homography (10° tilt) → after refinement the IoU goes from < 0.7 to ≥ 0.9.
- `overlay_low_confidence` eval still reports low.

## Smaller items
- **Gear z=23 vs a stated 20 mm face width:** in `spec.py`, mark user-given dims `source: "user"` (the freeze/probe already distinguishes "given" from "assumed"). Validate warns when an assumed feature makes a user dim exceed its tolerance: "z 23.0 > user 20.0; assumed hub boss adds 3.0". Also suggest putting the hub within the face width. Acceptance: the r10 gear spec warns, and the T9 spec (all given) does not.
- **Wrong skill id 2/8:** the hook already rewrote both (see Findings). In `evals/runner.py` / `sessions.py`, count `rewrite_from` rows from `calls.jsonl` as `skill_id_rewritten` and leave them out of `wrong_skill_id`. Acceptance: rescoring r10 gives wrong_skill_id 0, rewritten 2. Keep the docs silent on the `plugin:` form so agents are not encouraged to use it.
- **Strap hinge:** the first `photo_part_template` direct call returned "Tool 'photo_part_template' does not exist" (transcript line 18). The model called the plugin tool outside the `tool_call` wrapper. Check that the SKILL.md example call form matches how Hermes v0.21.7 exposes plugin tools (via `tool_call`), and say so in the first lines.
- **Harness:** launch real-photo runs detached (`setsid nohup`) and poll (REPORT §0).

## Suggested v0.1.12 order
- **P0:** §3 roundness fix (one-line cause, regression test), §1 standards role gating, the scorer rewrite count.
- **P1:** §2 cylinder-based knuckles plus template defaults, §4 detection on validate plus the sidecar hash, §5 show IoU and grow the ROI.
- **P2:** §4 3MF metadata/trianglesets, §5 rectify/ECC refinement and elevation views, the user-dim warning.
- **Re-run:** r10's 8 real-photo cases. Targets: 0 standards false positives, 0 spec edits, T9 2=2, no thin-wall warnings on copied STLs without a sidecar, IoU non-null everywhere, wrong_skill_id 0.
