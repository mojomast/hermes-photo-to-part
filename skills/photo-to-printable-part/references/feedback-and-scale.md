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

Pass `coin` plus `diameter_px` or two `points` across the coin. A ruler is `ruler_mm` plus two points. The scale is for features in that same plane. A straight-on photo is required unless you pass `quad` (TL, TR, BR, BL) with `width_mm`, `height_mm`, and `image`. That writes a rectified PNG. Then measure on the rectified image.

## Outline overlay

Pass `photo_scale` (pixels per millimetre) to `photo_part_render` along with `photo`. The tool writes `overlay.png`: the silhouette contour of the front view, not the facet edges. It also writes `overlay_diff.png` and `overlay_iou`, and the side-by-side `compare_front.png`. Default placement (`overlay_fit: center`) puts the model center on the image center. `overlay_fit: auto` scales and translates that contour onto the part segmented from a straight-on photo. `overlay_origin` is `[x, y]`, the image pixel of the model's minimum corner, with y growing downward.

`--photo-scale` and `overlay_fit` assume a straight-on photo. Skip the overlay when the photo is angled, unless `photo_part_measure` already rectified it, and say why: perspective moves the far edge, so the outline will not sit on the part. `auto` uses the largest object unless you pass `roi` (`x, y, w, h`), `seed` (one pixel on the part), or `exclude_roi`. Passing the measure JSON excludes `reference_bbox` (the coin or the ruler). The result warns when `overlay_iou` is below 0.5 or `angled` is set, and it names the blob.

A single straight-on photo does not show thickness or depth. Say those dimensions are unobserved. Ask, or mark them assumed. Do not copy an in-plane width into thickness.

On 2 mm grid paper, `photo_scale` is the pixel width of one square divided by 2. Do not write an overlay script. The tool is the overlay.

## Hard dimensions

A sentence like "the original is 60.6 mm tall by 51 mm wide; yours is bigger" becomes `--size` and the matching parameters. Map their words onto X Y Z explicitly and show them the mapping. Do not assume which axis is "tall" if the mesh is rotated. `--allow-axis-swap` only checks that the three sizes exist. It does not prove orientation.

## Batch the pass

When they point out a missing feature, ask whether anything else is missing. Put every answer into the next version. Say, in the version log, which note each parameter change came from.
