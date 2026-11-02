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

`render_views.py --grid-mm 2` draws a 2 mm grid on the preview so you can compare counts. The preview grid is in model units. It does not prove the photo's printer was calibrated.

## Hard dimensions

A sentence like "the original is 60.6 mm tall by 51 mm wide; yours is bigger" becomes `--size` and the matching parameters. Map their words onto X Y Z explicitly and show them the mapping. Do not assume which axis is "tall" if the mesh is rotated. `--allow-axis-swap` only checks that the three sizes exist. It does not prove orientation.

## Batch the pass

When they point out a missing feature, ask whether anything else is missing. Put every answer into the next version. Say, in the version log, which note each parameter change came from.
