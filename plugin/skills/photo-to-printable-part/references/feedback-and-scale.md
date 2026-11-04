# Feedback and scale

Load this when a photo is marked up, or when the part is on grid paper.

## Marked-up photos

Treat circles and arrows as instructions, not as geometry to copy. A note such as "radius", "flat face", or "remove this" changes the parameter or the feature it points at. If two notes conflict, ask before regenerating.

Ignore pen strokes, glue shine, and cracks unless the note says they are real surfaces.

## 2 mm grid paper

Printed squares are 2 mm only if the printer did not scale the page. Ask them to check one square with a ruler the first time.

Count squares on a photo taken **straight on**, with the part flat. Perspective makes the far edge look short. A phone held at an angle is not a measurement.

Convert a count with `millimetres = squares × 2`. Write the count in the parameter table next to the result, for example "26 squares × 2 mm = 52 mm, grid photo".

When a caliper number and a grid count disagree, keep the caliper number and say so.

Use the grid to estimate a curve: how many squares a radius spans, and where a straight run starts. Then put a single radius or a polyline in the script. Do not trace the photo pixel by pixel.

`photo_part_render` with `grid_mm: 2` draws a 2 mm grid on the orthographic previews so you can compare counts. The grid is in model millimetres. It does not prove the photo's printer was calibrated. The iso view has no metric grid, because its axes are not millimetres.

## Coin or ruler

Call `photo_part_measure`. Do not write perspective code. Nominal diameters, millimetres:

| Coin | mm |
| --- | --- |
| euro_1 | 23.25 |
| euro_2 | 25.75 |
| euro_50c | 24.25 |
| us_quarter | 24.26 |
| us_penny | 19.05 |
| us_nickel | 21.21 |
| us_dime | 17.91 |
| us_half | 30.61 |
| gbp_1 | 23.43 |
| cad_quarter | 23.88 |
| cad_loonie | 26.5 |

Pass `coin` plus `diameter_px` or two `points` across the coin. A ruler is `ruler_mm` plus two points. The scale is for features in that same plane. A straight-on photo is required unless you pass `quad` (TL, TR, BR, BL) with `width_mm`, `height_mm`, and `image`. That writes a rectified full-photo PNG and saves its transform and output `px_per_mm`. With a quad, give measurement endpoints and selection hints in the original image coordinates; the tool transforms them together. A bare `length_px` cannot describe a perspective-corrected span. `measurement_coordinate_frame` identifies the result frame.

Render can reuse the original photo or the saved rectified PNG from the same project. Saved hints are moved into the appropriate frame; explicitly supplied render hints belong to the photo you pass. The saved PNG is not warped twice. Rectified overlays report `photo_coordinate_frame: rectified` and the transform/canvas/scale. Padding is not photo evidence. If a photo was edited, its scale conflicts with the saved rectification, or an old context has only a matrix, run `photo_part_measure` again. A coin ellipse alone is a guide-only tilt hint, not a calibrated plane transform.

`reference_px`, `coin_px`, and `reference_bbox` describe the original source-image evidence. When a quad is used, do not divide arbitrary original-image pixel spans by the returned rectified scale; supply their endpoints in `measurements` instead. You can pass the complete measurement JSON or `last_measure.json` to render as either an object or file path to carry the calibration explicitly.

## Outline overlay

Pass `photo_scale` (pixels per millimetre) to `photo_part_render` along with `photo`. The tool writes `overlay.png`: the silhouette contour, not the facet edges. It also writes `overlay_diff.png` and `overlay_iou`, and the side-by-side `compare_front.png`. Default placement (`overlay_fit: center`) puts the model center on the image center. `overlay_fit: auto` tries the front, side, and top silhouettes. It searches rotation at 15°, then at 1°, and tries a mirror. The JSON reports `overlay_rotation_deg`, `overlay_mirror`, `overlay_view`, and `overlay_poses`. `overlay_origin` is `[x, y]`, the image pixel of the model's minimum corner, with y growing downward.

`auto` uses the largest object unless you pass `roi` (`x, y, w, h`), `seed` (one pixel on the part), or `exclude_roi`. Passing the measure JSON excludes `reference_bbox` (the coin or the ruler). If the ROI touches the silhouette, the tool expands it and warns; `overlay_roi_expanded` is true. The result warns when `overlay_iou` is below 0.5, and it names the blob. An angled photo is still fitted. `overlay_iou_label` is then `guide_only`: perspective moves the far edge, so quote the IoU as a guide unless `photo_part_measure` already rectified the photo.

A single straight-on photo does not show thickness or depth. Say those dimensions are unobserved. Ask, or mark them assumed. Do not copy an in-plane width into thickness.

On 2 mm grid paper, `photo_scale` is the pixel width of one square divided by 2. Do not write an overlay script. The tool is the overlay.

## Hard dimensions

A sentence like "the original is 60.6 mm tall by 51 mm wide; yours is bigger" becomes `--size` and the matching parameters. Map their words onto X Y Z explicitly and show them the mapping. Do not assume which axis is "tall" if the mesh is rotated. `--allow-axis-swap` only checks that the three sizes exist. It does not prove orientation.

## Batch the pass

When they point out a missing feature, ask whether anything else is missing. Put every answer into the next version. Say, in the version log, which note each parameter change came from.
