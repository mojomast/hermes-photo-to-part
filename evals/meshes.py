"""Meshes shared by the v0.1.9 checks and the fixture generator.

These are built here, not taken from the hinge template. The template hinge
bridges intrude into the bore, so that bore is not a circle and its genus is
not 4.
"""

from __future__ import annotations

import manifold3d

from photopart.parts import _as_mesh, _cube, _cylinder_x, _cylinder_z, _difference, _union_many


def thin_l_bracket():
    """1.5 mm L-bracket with six Ø5 holes through the legs.

    Three holes pass through the horizontal leg along Z and three through the
    vertical leg along X. Stations at 25/50/75 percent of the whole part miss
    both legs, which is the T7 failure.
    """
    length, width, height, thickness = 80.0, 24.0, 60.0, 1.5
    horiz = _cube(length, width, thickness)
    vert = _cube(thickness, width, height)
    holes = [_cylinder_z(2.5, thickness + 0.8, x, width / 2.0, -0.4) for x in (30.0, 50.0, 68.0)]
    holes.extend(_cylinder_x(2.5, thickness + 0.8, -0.4, width / 2.0, z) for z in (16.0, 32.0, 48.0))
    return _as_mesh(_difference(_union_many([horiz, vert]), holes))


def six_hole_bracket():
    """L-bracket with six holes along the foot.

    The holes run the length of the foot, so the 25/50/75 percent stations on
    X each cut a circle. Holes only in the thin upright miss those stations.
    """
    length, width, height, thickness = 80.0, 24.0, 40.0, 4.0
    horiz = _cube(length, width, thickness)
    vert = _cube(thickness, width, height)
    holes = [
        _cylinder_x(1.15, length + 0.6, -0.3, y, thickness / 2.0)
        for y in (3.2, 6.6, 10.0, 13.4, 16.8, 20.2)
    ]
    return _as_mesh(_difference(_union_many([horiz, vert]), holes))


def bore_hinge():
    """One shell, genus 4: two knuckle bores and two square through-holes.

    The bores sit on knuckle indexes 1 and 3. Each is seen on only one of the
    three cross-section stations, so ``count_bores`` reports them as blind.
    The square holes are through, and their circularity stays under 0.85.
    """
    plate = _cube(50.0, 20.0, 4.0)
    squares = [
        _cube(3.2, 3.2, 6.0).translate((8.0, 8.4, -1.0)),
        _cube(3.2, 3.2, 6.0).translate((34.0, 8.4, -1.0)),
    ]
    body = _union_many([plate, _knuckle(12.5), _knuckle(37.5)])
    return _as_mesh(_difference(body, squares))


def _knuckle(center_x: float, length: float = 5.0):
    """Bored tube along X, fused to the plate, with the hole clear of the plate."""
    x0 = center_x - length / 2.0
    outer = _cylinder_x(3.2, length, x0, 10.0, 6.2, segments=48)
    inner = _cylinder_x(2.0, length + 1.2, x0 - 0.6, 10.0, 6.2, segments=40)
    return _difference(outer, [inner])


def blind_tap():
    """Ø16 x 12 mm puck with a blind Ø5 hole opening on the top face."""
    body = _cylinder_z(8.0, 12.0, 0.0, 0.0, 0.0, segments=48)
    cutter = _cylinder_z(2.5, 8.0, 0.0, 0.0, 4.0, segments=40)
    return _as_mesh(_difference(body, [cutter]))


def washer_mesh():
    """Ø20 / Ø8 x 2 mm washer with a rim notch so the pose is not a free spin."""
    outer = manifold3d.Manifold.cylinder(2.0, 10.0, 10.0, 72, False)
    inner = manifold3d.Manifold.cylinder(3.0, 4.0, 4.0, 48, False).translate((0.0, 0.0, -0.5))
    notch = manifold3d.Manifold.cube((3.2, 2.6, 3.0), False).translate((7.6, -1.3, -0.5))
    body = manifold3d.Manifold.batch_boolean([outer, inner, notch], manifold3d.OpType.Subtract)
    return _as_mesh(body)
