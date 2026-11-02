# Print tolerances

Load this when the user names a printer technology or a mating fit.

Model the **measured nominal size**. Clearance is a change to specific mating faces, recorded in the parameter table. Do not scale the whole part "for shrinkage" unless the user measured a systematic error on a previous print.

These are published starting points, not a guarantee for their printer, resin, or filament. The fit test is the check that matters.

## Resin (Formlabs Form 4 / 4L class MSLA)

Formlabs' Form 4 design guide and Form 4L design specifications, Grey resin, accessed 2026-11-02:

- Minimum supported and unsupported wall: **0.2 mm** recommended. Thin walls can still warp from peel forces or from a long IPA wash.
- Minimum clearance between moving features: **0.4 mm** recommended. Formlabs reports parts may fuse below that.
- Typical XY tolerance on Form 4L, Grey Resin V5, 100 µm: about **±0.15%** for 1–30 mm features (floor ±0.02 mm), and **±0.3%** for 31–150 mm features (floors ±0.06 mm and ±0.15 mm). Form 4's published band for 31–80 mm is slightly tighter (±0.2%).

Sources:

- https://formlabs.com/blog/design-guide-form4/
- https://formlabs.com/support/Design-specifications-for-3D-models-Form-4L-generation/

Consumer MSLA printers are often less repeatable than a Form 4. If the user did not name a printer, use 0.2 mm walls and 0.3–0.4 mm clearance as a conservative resin start, and say that you did.

## FDM (Prusa-class, 0.4 mm nozzle)

Prusa's modeling guide and FAQ, accessed 2026-11-02:

- A 0.4 mm nozzle extrudes about **0.45 mm** wide. One perimeter is not a 0.4 mm wall. Two perimeters are about 0.9 mm, three about 1.35 mm. Walls thinner than one perimeter do not print.
- A well-assembled Original Prusa is about **0.1 mm** in Z and **0.3 mm** in X/Y, and can be nearer 0.05 mm after extrusion calibration. They also describe accuracy of at least **0.2 mm** before material shrink.
- Movable fits: start at **at least 0.3 mm** clearance. There is no universal number. Holes tend to print small.

Sources:

- https://help.prusa3d.com/article/modeling-with-3d-printing-in-mind_164140
- https://help.prusa3d.com/article/faq-frequently-asked-questions_1932

For a 0.4 mm nozzle, prefer walls of at least two perimeters (about 0.9 mm) and three when the part is structural. Add clearance on the hole or the slot, not by growing the whole body.

## What to tell the user

State which faces got clearance and by how much. Ask them to judge the stacked print, not the render. Support nubs are a print artifact. Sand them or move the supports. Do not model them.
