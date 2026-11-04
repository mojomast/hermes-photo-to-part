# Pipeline improvement research after v0.1.17

Researched **2026-11-04** against release `51cd47104ab0c1c9dc564ac944f33db97a97075b`.
Inputs: `RESEARCH.md`, the handoff, research notes for v0.1.8/v0.1.11/v0.1.12,
and the round history through r15 on `origin/docs/test-rounds-and-handoff`.
The sources below were opened directly; recommendations are our engineering
conclusions, not performance guarantees from those sources.

## Decision

Prioritize **calibration-preserving overlays and explicit coordinate frames**.
Better image overlap is useful only if the comparison still preserves the
dimensions being checked. Keep geometry, photo evidence, and agent efficiency
as separate acceptance criteria.

The first development patch in this branch makes `_select_pose` use a fixed-scale
IoU fallback, with regressions for under/oversized models and correct-size controls.
Regression investigation also corrected half-pixel raster placement and a pose
tie-break that could discard a better-aligned asymmetric feature.
The rectification contract described below is also implemented on this branch.
The remaining refinement, uncertainty, and recognition items are proposed work. This document does not establish
live-photo improvement over r15 or announce a new release.

## 1. Reproduced defects and implementation findings

### P0: overlap fallback can hide incorrect size — first patch implemented

`overlay._search_chamfer` preserves the calibrated model raster, but
`search_alignment` used `_place`'s default area-matching scale. `_select_pose`
could therefore choose a resized model when the edge-based path was unavailable
or lost the pose comparison.

**Released-code reproduction:** a 96-pixel-wide square model compared with an
80-pixel-wide square foreground, RGB 216 on a 235 background, produced:

| Quantity | v0.1.17 result |
| --- | --- |
| Model width error | +20% |
| Selected silhouette area / input area | 0.694444 |
| IoU | 1.0 |
| Boundary IoU | 1.0 |
| Overall confidence | high |
| `iou_trusted` | true |

No segmentation-confidence threshold can fix this: the model was shrunk to
fit before measurement. A first 40-versus-80-pixel probe did **not** reproduce
a trusted fit; the failure depends on the fallback and rasterization, not on
every size mismatch. The committed regression covers widths 64/65, 96/97, and
160/161 against 80, and checks actual placed width, area, and expected IoU.

**Patch:** pass `scale_mode="fixed"` through the coarse search, fine search,
full-resolution placement, and mirror comparison used by `_select_pose`.
Keep explicit shape-only `search_alignment` behavior available separately.
All production photo overlays enter through the calibrated selector.

**Regression findings while applying the patch:**

- A fixed-scale raster with odd pixel counts centered on an even-pixel foreground
  lands at half-pixel coordinates. `np.rint` rounds ties to even, collapsing
  alternate rows/columns instead of translating them uniformly. That made a
  straight rectangle prefer 179 degrees. Placement now uses consistent
  `floor(coordinate + 0.5)` nearest-pixel rounding. A solid 41×81 raster must
  retain all 3321 pixels after a half-pixel translation.
- The old selector preferred an upright pose whenever edge scores differed by
  less than 0.35 px, even when the rotated pose had materially better overlap.
  On the notched washer, the fixed upright candidate had IoU 0.779 / edge
  distance 0.664 px, versus 0.807 / 0.406 px at the correct -18 degrees.
  The first patch therefore failed that pose eval despite high overlap.
  Upright preference now also requires an overlap tie (the existing 0.01 IoU
  tolerance). A candidate that improves both metrics must keep that evidence.

**Next acceptance:** an independently calibrated wrong-size model must remain
wrong-size even if segmentation is perfect, edges disappear, or the photo is
resized with its calibration updated. Check rotated/asymmetric parts too.

### P0: rectified image, hints, and scale did not share one coordinate frame — implemented

Two related findings require a coordinated change:

1. `paint_auto_views` warps the image via `_rectify_for_measure`, then sends the
   original `roi`, `seed`, and `exclude` coordinates into segmentation and scoring.
   A translation probe moved the part seed from `(20,30)` to `(100,60)`; the
   original coordinate then addressed the black warp border, not the part.
2. `measure._stored_homography` maps the reference quad onto its **pixel bounding
   box**, ignoring the known physical aspect ratio. The generated rectified PNG
   uses a different mapping. For a 100×100-pixel quad representing 20×10 mm,
   `quad_px_per_mm` returns 7.5, but the stored transform yields **5 px/mm in X
   and 10 px/mm in Y**. Using 7.5 for both axes is inconsistent.

**Proposed contract:** persist a single rectification record containing the
source image identity, source-to-rectified matrix, destination size, destination
px/mm, coordinate-frame name, and valid-pixel mask. Produce the image and all
transformed hints from that record. A destination rectangle must have physical
aspect ratio `width_mm / height_mm` at an isotropic output scale.

- Transform seeds as points and ROIs/exclusions as polygons or warped masks;
  an axis-aligned bounding rectangle is only a conservative approximation.
- Exclude padding from segmentation and metrics. A black border is not a part.
- Prevent double rectification when the caller already supplies the rectified image.
- Label a coin-ellipse stretch as an approximation with a same-plane assumption;
  a single ellipse is not a general calibrated perspective solution for a 3D part.
- Apply a plane homography only to evidence on that plane. Out-of-plane features
  require another view or an independent measurement.

**Acceptance:** known quad with unequal axis scales; shifted quad; coin exclusion
after transformation; valid-pixel padding; direct and saved-context rendering;
already-rectified input; invalid/singular transform. Assert physical landmark
distances and mask locations, not merely a high self-fit score. [1]

**Implementation:** `plugin/photopart/rectify.py` now owns the full-photo metric
map, integer canvas, isotropic scale, image hashes, mask warp, and valid-pixel
coverage. Reference landmarks map to exact continuous metric coordinates; canvas
rounding does not redefine their scale. The 4000-pixel canvas cap rescales the
matrix and calibration together. The original and generated images share the
same persisted record in `last_measure.json`.

Measurement endpoints are transformed before computing millimetres; source
part masks are warped before bounding-box measurement. Overlays transform seeds,
origins and exclusion masks. ROIs use conservative mapped bounding boxes as
segmentation initializers; saved reference exclusions on a rectified input use
polygons. Invalid padding is masked from segmentation and image edges, and a fit
touching unobserved padding is untrusted. Already-rectified input is identified
by path/hash and is not warped again. Matrix-only legacy contexts and conflicting
explicit scales produce a remeasurement error. A foreshortened coin ellipse no longer
applies an uncalibrated image stretch; that overlay remains a guide. A nearly circular
coin is not treated as tilt. Observed photo-border pixels stay in the valid mask, and
chamfer sampling uses the same half-pixel rounding as placement.

Seven new regression tests cover metric landmarks and measured dimensions, identical
overlays from source/saved images, center/origin paths, source-to-rectified seed and
exclusion movement, padding, capped canvases, stale/invalid/legacy calibration,
rectified reference polygons, and explicit calibration JSON as both an object and
file path. The 100×100-pixel / 20×10-mm reference now has
7.5 px/mm on both rectified axes; a 50×40-pixel source part measures about 10×4 mm.
Focused checks passed **20/20**, and offline evals passed **28/28**, including
**4/4** regression holdouts. The final combined unit/integration suite passed
**193/193** in 296.613 seconds, including archived mesh regressions and Hermes
validation/doctor. Evidence is under `/tmp/opencode/photo-to-part-baseline/logs/`:
`rectification-suite-final.log`, `rectification-context-final.log`, and
`rectification-evals-final.json`. These are development-branch checks, not a live
photo round or a newly installed release.

### P1: the normalized edge score makes the ECC skip condition ineffective

`_edge_field` sets `tau = 0.03 * diagonal`. Both edge-chamfer paths truncate
every distance at tau, then divide the mean by that same diagonal. Consequently
`chamfer_norm <= 0.03` whenever the metric exists. `_ecc_pose` skips refinement
at `chamfer_norm <= 0.05`, so normal finite scores always take that skip.
The probe returned 5.0912 px / 0.03 normalized. This is an algebraic bound,
not evidence that all placements are close. `_select_pose` also uses the 0.05
threshold when choosing the chamfer candidate.

**Do not just lower the threshold:** the currently skipped refinement permits
affine scaling and homography, including up to 15% axis-scale variation.
Turning it on can conceal dimensional error again.

**Proposed fix:** retain a truncated objective for robust pose search, but use
the existing untruncated symmetric contour distances and boundary agreement
for fit assessment. For a calibrated plane, use translation/Euclidean ECC
(rotation and translation), bounded by a pose budget and accepted only when
the independently computed fit improves. Estimate perspective from the reference
or camera model. If a flexible shape-fit view is useful, label it guide-only
and report its transform separately from calibrated metrics. [1,2,3]

**Acceptance:** an imperfect translated silhouette actually reaches refinement;
translation improves while size is preserved; wrong-size geometry cannot be
rescued by a warp; a good fit skips work; nonconvergence returns the prior pose.
The existing direct `refine_silhouette` test does not exercise the selector's
skip condition.

## 2. Measurement evidence and uncertainty

The current `_measurements` assigns `max(1 px, 2% of span) / px_per_mm` and
multiplies it by three out of plane. This is a heuristic, not a propagated
measurement uncertainty. Coin-scale uncertainty exists elsewhere in the report
but is not combined into these per-feature numbers.

Following NIST's propagation method [4], model `length_mm = span_px / scale`.
For independent span and scale estimates:

`u(length)^2 = (u(span)/scale)^2 + (span*u(scale)/scale^2)^2`.

Shared endpoints or a scale taken from the same feature introduce covariance;
do not claim independence in that case. Distinguish user/caliper values,
independent references, and dimensions inferred from the part itself. Persist
the reference provenance, coordinate frame, uncertainty method, and assumptions.
Use unknown/not-measurable for unsupported out-of-plane dimensions rather than
making an arbitrary multiplier look like calibrated confidence.

The v0.1.17 `reference_is_part` and guide-only labeling are a useful foundation.
Keep the original user specification authoritative: an overlay-derived estimate
should not silently replace it.

**Acceptance:** scale uncertainty increases reported dimension uncertainty;
a self-calibrated dimension is not independently verified; image resize plus
scale adjustment preserves millimetres; out-of-plane uncertainty is explicit.

## 3. Bore, cavity, and hinge recognition

CGAL's primary documentation describes primitive detection using geometric
distance, normal compatibility, and connected support. CAD/CAM recognition then
uses topology to interpret those primitives. A cylinder fit alone does not
establish a through-bore, and part names do not establish geometry. [5,6]

Keep v0.1.17's cap test as an explicit heuristic. Its 70% transverse span,
centering, and thin closed-end rules are not universal definitions of a cap.
The next recognition increment should expose evidence before changing counts:

- axis and diameter, angular coverage and fitting residual;
- connected surface/shell support;
- sampled axial void intervals and closed-end thickness;
- `through`, `blind`, `pin_clearance`, `cap_like_cavity`, or ambiguous;
- method, resolution limits, and an explanation when classification is uncertain.

Use mesh evidence to validate feature tags rather than accepting tags as truth.
For B-rep inputs, analytic faces/topology can provide stronger evidence, but
adding a required CAD kernel is not justified by this research alone.

**Acceptance:** broad blind bore in thick stock, thin cap, off-center pocket,
through-hole, pin-filled annulus, coaxial disjoint hinge segments, partial cylinder,
and remeshed/rotated variants. Preserve the 24 archived mesh regressions and
their original specs. Profile `openings` before choosing an optimization.
The r15 report lists `bores_not_genus` at **2.8 minutes**; an older 6.8-minute
number in the handoff should not be treated as the r15 baseline.

## 4. Agent workflow and evaluation best practice

Anthropic's tool/evaluation guidance emphasizes final environment outcomes,
transcript inspection, useful error recovery, isolated trials, and cost/latency
measurement. CADCodeVerify supports render-and-review iteration, but its results
do not prove dimensional or manufacturing correctness for this plugin. [7,8,9]

### Workflow

- Keep the existing combined validate/render path and concise tool results.
- Return the next action with its reason: calibration missing, segmentation
  uncertain, pose uncertain, mesh/spec failed, or ready to deliver.
- Reuse an unchanged render only when mesh, photo, calibration, and parameters
  match; file existence alone is insufficient.
- Ask for the measurement or second view that resolves a specific ambiguity.
- Separate mesh/spec validity, visual agreement, and manufacturing assumptions.
  The current 100-point `compute_score` can be reached without photo evidence;
  it must not be presented as a photo-reconstruction accuracy score.

### Evaluation

- Keep the eight original cases and 18 live sealed tasks as the official r15
  comparison. The existing 28 in-process tasks are a different test layer.
- Grade delivered geometry and files with an external scorer. The session
  scorer's call/leak/budget report alone does not establish artifact correctness.
- Record dimension error, missing/extra features, shell/watertightness checks,
  overlay availability, calibrated boundary error, spec edits, and delivery.
  Also record total/plugin calls, errors, wall time, and tokens/cost when available.
- Retain per-case results. An aggregate improvement cannot hide a failed case.
- Keep provider/model, Hermes version, prompts, tool budget, and plugin SHA
  comparable; archive the actual runtime identifiers with each round.
- Launch detached, read the session database only after all runs exit, and
  isolate the agent filesystem from the dev checkout, graders, and harness.
  An unusual directory name or plugin read guard is not filesystem isolation.
- Budget optional repeatability trials explicitly; do not report best-of-N as
  a one-shot result. Current repeatedly inspected holdouts are regression
  holdouts, not a fresh unseen estimate. Acquire any new locked holdouts before
  tuning against them and with owner approval for the additional work.

## 5. Delivery order and release gate

### Verification of the first calibrated-fallback patch

- Full unit/integration suite: **186/186 passed**, including archived mesh
  regressions and the Hermes CLI validation/doctor check (296.385 seconds).
- Focused overlay, pose, and photo-context checks: **21/21 passed**.
- Offline evals: **28/28 passed**, including **4/4 regression holdouts**.
- The initial fixed-scale-only patch failed the straight-rectangle pose test
  and notched-washer pose eval; both passed after the rounding/tie-break fixes.
- Logs are under `/tmp/opencode/photo-to-part-baseline/logs/`:
  `calibrated-overlay-suite-final.log`, `calibrated-overlay-focused.log`, and
  `calibrated-overlay-evals-final.json`.

These results cover the development branch, not a newly installed release or
a live DeepSeek/Hermes photo round.

### Planned sequence

1. **Calibrated fallback:** this branch's focused implementation and regressions.
2. **Rectification contract:** implemented; image, hints, padding mask, and metric scale share one frame.
3. **Refinement:** replace the ineffective skip rule together with scale-preserving
   registration; evaluate pose selection on known-error fixtures.
4. **Evidence:** measurement uncertainty and feature-classification explanations.
5. **Efficiency:** profile and optimize measured hot paths; compare calls/time
   only after correctness is maintained.

For a release, follow PR → green CI → squash merge → tag/release → exact-SHA
install → doctor → eight photos plus 18 sealed live tasks → per-case r15 report.
The original eight photos are still unavailable locally. Live parity and a
catalog re-pin remain blocked on that round; catalog submission needs approval.
The supplemental candidate list remains a separate, unqualified research set.

## Sources

1. OpenCV, [homography tutorial](https://docs.opencv.org/4.x/d9/dab/tutorial_homography.html):
   planar correspondences, perspective correction, and camera/plane assumptions.
2. OpenCV, [findTransformECC documentation](https://docs.opencv.org/4.x/dc/d6b/group__video__track.html):
   translation/Euclidean/affine/homography motion models, initialization,
   inverse-map application, and nonconvergence.
3. Cheng et al., [Boundary IoU](https://arxiv.org/abs/2103.16562), 2021:
   why region IoU alone misses boundary errors. Boundary metrics already exist here.
4. NIST, [combining uncertainty components](https://physics.nist.gov/cuu/Uncertainty/combination.html):
   first-order propagation including covariance.
5. CGAL, [Shape Detection manual](https://doc.cgal.org/latest/Shape_detection/index.html):
   Efficient RANSAC and region growing, primitives and their support.
6. CAD Exchanger, [blind-hole recognition](https://cadexsoft.com/feature-recognition/blind-hole):
   B-rep manufacturing-feature interpretation. Vendor overview, not a published
   algorithm or evidence for this plugin's thresholds.
7. Anthropic, [Demystifying evals for AI agents](https://www.anthropic.com/research/demystifying-evals-for-ai-agents), 2026.
8. Anthropic, [Writing effective tools for agents](https://www.anthropic.com/research/writing-tools-for-agents), 2025.
9. Alrashedy et al., [Generating CAD Code with Vision-Language Models for 3D Designs](https://arxiv.org/abs/2410.05340),
   revised 2025: CADCodeVerify's iterative visual verification approach.

Local reproduction evidence: detached developer probe
`/tmp/opencode/photo-to-part-baseline/harness/research-v0118.py` and its
`logs/research-v0118.json` output; pre-fix regression failures in
`logs/calibrated-overlay-before.log`. These are developer probes, not live Hermes
trials. Keep the harness and this research out of test-agent accessible installs.
