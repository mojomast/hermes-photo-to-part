"""Watertight building blocks for photo_part_build scripts.

Import them from a build script. Each function returns one watertight
trimesh, in millimetres, or raises ``ValueError``.

    from photopart.features import (
        external_thread, internal_thread, knurl, revolve_profile,
        sweep_path, hex_screw, hex_standoff, bottle_cap,
        spur_gear, spiral_scroll, strap_hinge,
    )

Threads are a helical ridge unioned with a core through manifold3d, so the
result is one shell. A bottle cap is an internal coarse thread with knurl
ridges on the outside wall, also one shell.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import trimesh

# diameter, pitch, hex across-flats, head height. ISO coarse.
_ISO = {
    "M3": (3.0, 0.5, 5.5, 2.0),
    "M4": (4.0, 0.7, 7.0, 2.8),
    "M5": (5.0, 0.8, 8.0, 3.5),
    "M6": (6.0, 1.0, 10.0, 4.0),
    "M8": (8.0, 1.25, 13.0, 5.3),
    "M10": (10.0, 1.5, 16.0, 6.4),
    "M12": (12.0, 1.75, 18.0, 7.5),
}
_TOOTH = 0.541266  # 5/8 of the ISO fundamental triangle height


def external_thread(
    *,
    designation: str = "M3",
    diameter: float | None = None,
    pitch: float | None = None,
    length: float = 8.0,
    segments_per_turn: int = 12,
) -> trimesh.Trimesh:
    """One external ISO metric thread. ``length`` is the cylinder length."""
    nominal, step = _thread_size(designation, diameter, pitch)
    mesh = _external_mesh(nominal, step, length, segments_per_turn)
    _tag_thread_crest(mesh, nominal, step, z_max=length + 0.1)
    return mesh


def internal_thread(
    *,
    designation: str = "M3",
    diameter: float | None = None,
    pitch: float | None = None,
    length: float = 8.0,
    outer_diameter: float | None = None,
    wall: float = 2.0,
    segments_per_turn: int = 12,
) -> trimesh.Trimesh:
    """A cylinder with an internal thread. The hole breaks both ends."""
    nominal, step = _thread_size(designation, diameter, pitch)
    if wall <= 0:
        raise ValueError("wall must be positive")
    outer = float(outer_diameter) if outer_diameter else nominal + 2.0 * float(wall)
    if outer <= nominal + 0.4:
        raise ValueError("outer_diameter must leave a wall outside the thread")
    length = _positive("length", length)
    # Cutter is a slightly larger external thread, longer than the nut.
    cutter = _external_solid(
        nominal + 0.12 * step,
        step,
        length + 2.0 * step,
        segments_per_turn,
    )
    cutter = cutter.translate((0.0, 0.0, -step))
    outer_body = _cylinder(length, outer / 2.0, segments=48)
    mesh = _as_one(_difference(outer_body, [cutter]))
    _tag_thread_crest(mesh, nominal, step, z_max=length + step, internal=True)
    return mesh


def knurl(
    style: str = "straight",
    *,
    diameter: float = 10.0,
    length: float = 8.0,
    count: int = 20,
) -> trimesh.Trimesh:
    """Straight ribs or a diamond (two opposite helices) on a core cylinder."""
    kind = (style or "straight").strip().lower()
    if kind not in ("straight", "diamond"):
        raise ValueError("knurl style must be straight or diamond")
    radius = _positive("diameter", diameter) / 2.0
    length = _positive("length", length)
    count = int(count)
    if count < 6 or count > 60:
        raise ValueError("knurl count must be from 6 to 60")
    core = _cylinder(length, radius, segments=48)
    if kind == "straight":
        ribs = _straight_ribs(radius, length, count, tooth=max(0.35, radius * 0.08), thickness=max(0.4, radius * 0.12))
        mesh = _as_one(_union([core, *ribs]))
    else:
        tooth = max(0.3, radius * 0.07)
        step = max(length * 0.55, radius * 1.4)
        left = _ridge_solid(radius * 0.94, radius + tooth, step, length, segments_per_turn=10, hand=1)
        right = _ridge_solid(radius * 0.94, radius + tooth, step, length, segments_per_turn=10, hand=-1)
        mesh = _as_one(_union([core, left, right]))
    _tag_knurl(mesh, radius)
    return mesh


def revolve_profile(points, *, segments: int = 48) -> trimesh.Trimesh:
    """Revolve a 2D profile around Y. X is the radius and must stay >= 0."""
    ring = [[float(point[0]), float(point[1])] for point in points]
    if len(ring) < 3:
        raise ValueError("revolve profile needs at least 3 points")
    if any(point[0] < -1e-6 for point in ring):
        raise ValueError("revolve profile X must be >= 0 (it is the radius)")
    if segments < 8:
        raise ValueError("segments must be at least 8")
    import manifold3d

    section = manifold3d.CrossSection([ring])
    body = manifold3d.Manifold.revolve(section, circular_segments=int(segments))
    return _as_one(body)


def sweep_path(path, *, radius: float = 1.5, segments: int = 12) -> trimesh.Trimesh:
    """Sweep a circle along a polyline. Used for scrolls and hooks.

    The path must not fold tightly enough to self-intersect. ``radius`` is the
    tube radius in millimetres.
    """
    pts = np.asarray(path, dtype=float).reshape(-1, 3)
    if len(pts) < 2:
        raise ValueError("sweep path needs at least 2 points")
    radius = _positive("radius", radius)
    segments = int(segments)
    if segments < 6:
        raise ValueError("segments must be at least 6")
    frames = _parallel_frames(pts)
    circle = []
    for origin, normal, binormal in frames:
        ring = []
        for index in range(segments):
            angle = 2.0 * math.pi * index / segments
            ring.append(origin + radius * (math.cos(angle) * normal + math.sin(angle) * binormal))
        circle.append(ring)
    vertices = [point for ring in circle for point in ring]
    faces = []
    stations = len(circle)
    for station in range(stations - 1):
        for index in range(segments):
            nxt = (index + 1) % segments
            a = station * segments + index
            b = station * segments + nxt
            c = (station + 1) * segments + nxt
            d = (station + 1) * segments + index
            faces.append([a, b, c])
            faces.append([a, c, d])
    start_center = len(vertices)
    vertices.append(pts[0])
    end_center = len(vertices)
    vertices.append(pts[-1])
    for index in range(segments):
        nxt = (index + 1) % segments
        faces.append([start_center, nxt, index])
        base = (stations - 1) * segments
        faces.append([end_center, base + index, base + nxt])
    mesh = trimesh.Trimesh(vertices=np.asarray(vertices, dtype=float), faces=np.asarray(faces, dtype=np.int64), process=False)
    return _as_one(_ingest(mesh))


def hex_screw(
    *,
    designation: str = "M3",
    length: float = 12.0,
    head_height: float | None = None,
    across_flats: float | None = None,
    diameter: float | None = None,
    pitch: float | None = None,
) -> trimesh.Trimesh:
    """Hex-head bolt. ``length`` is the thread under the head."""
    nominal, step, flats, head = _fastener(designation, diameter, pitch, across_flats, head_height)
    length = _positive("length", length)
    thread = _external_solid(nominal, step, length + 0.45, segments_per_turn=12).translate((0.0, 0.0, -0.15))
    cap = _hex_prism(flats, head + 0.35).translate((0.0, 0.0, length - 0.3))
    mesh = _as_one(_union([thread, cap]))
    _tag_thread_crest(mesh, nominal, step, z_max=length - 0.15)
    return mesh


def hex_standoff(
    *,
    designation: str = "M3",
    body_length: float = 10.0,
    thread_length: float = 6.0,
    across_flats: float | None = None,
    diameter: float | None = None,
    pitch: float | None = None,
) -> trimesh.Trimesh:
    """Hex body, blind bore, and a male thread on the +Z end. One shell."""
    nominal, step, flats, _head = _fastener(designation, diameter, pitch, across_flats, None)
    body_length = _positive("body_length", body_length)
    thread_length = _positive("thread_length", thread_length)
    if body_length < step * 3:
        raise ValueError("body_length is too short for a bore and a male thread")
    body = _hex_prism(flats, body_length)
    bore = _external_solid(nominal, step, body_length - step, segments_per_turn=10).translate((0.0, 0.0, -0.4))
    male = _external_solid(nominal, step, thread_length + 0.6, segments_per_turn=12).translate(
        (0.0, 0.0, body_length - 0.45)
    )
    bored = _difference(body, [bore])
    return _as_one(_union([bored, male]))


def hook_path() -> list[tuple[float, float, float]]:
    """A straight stem and a loose quarter-curl. Default sweep for a strap or a hook."""
    pts = [(float(i * 3), 0.0, 0.0) for i in range(8)]
    for index in range(1, 7):
        angle = index * (math.pi / 2.0) / 6.0
        pts.append((21.0 + 10.0 * math.sin(angle), 10.0 * (1.0 - math.cos(angle)), 0.0))
    return pts


def bottle_cap(
    *,
    diameter: float = 20.0,
    pitch: float = 3.0,
    length: float = 8.0,
    outer_diameter: float = 26.0,
    knurl_count: int = 16,
) -> trimesh.Trimesh:
    """Coarse internal thread with straight knurl ridges. One shell, not a stack of ribs."""
    cap = internal_thread(
        diameter=diameter,
        pitch=pitch,
        length=length,
        outer_diameter=outer_diameter,
        segments_per_turn=10,
    )
    outer_r = float(outer_diameter) / 2.0
    ribs = _straight_ribs(
        outer_r * 0.92,
        length * 0.82,
        int(knurl_count),
        tooth=max(0.6, outer_r * 0.08),
        thickness=max(0.7, outer_r * 0.1),
    )
    # Drop the ribs onto the cap wall. internal_thread starts at z=0.
    shifted = [rib.translate((0.0, 0.0, length * 0.09)) for rib in ribs]
    mesh = _as_one(_union([_ingest(cap), *shifted]))
    # Include the thread runout at both ends. Those crests are not a wall.
    _tag_thread_crest(mesh, diameter, pitch, z_max=length + 1.0, internal=True)
    _tag_knurl(mesh, outer_diameter / 2.0)
    return mesh


def spur_gear(
    *,
    module: float,
    teeth: int,
    pressure_angle: float = 20.0,
    face_width: float,
    bore: float | None = None,
    keyway_width: float | None = None,
    keyway_depth: float | None = None,
    d_flat: float | None = None,
    hub_diameter: float | None = None,
    hub_length: float | None = None,
) -> trimesh.Trimesh:
    """One involute spur gear, axis on Z, centred on XY.

    Full-depth teeth: addendum is one module and dedendum is 1.25 modules.
    Tip diameter is ``module * (teeth + 2)``. Root diameter is
    ``module * (teeth - 2.5)``. ``pressure_angle`` is in degrees (default 20).
    ``bore`` is the through-hole diameter. Add either a keyway
    (``keyway_width`` and ``keyway_depth``, depth measured out from the bore
    wall) or a D-flat (``d_flat`` is the distance from the flat to the far
    side of the bore), not both. ``hub_diameter`` and ``hub_length`` add a
    boss; length is the hub's full axial size, and any extra past
    ``face_width`` sticks out on -Z.
    """
    module = _positive("module", module)
    face_width = _positive("face_width", face_width)
    count = _tooth_count(teeth)
    angle = _pressure_angle(pressure_angle)
    polygon, dims = _gear_polygon(module, count, angle)
    section = _cross_section(polygon)
    blank = section.extrude(face_width)
    z0 = 0.0
    z1 = face_width
    if hub_diameter is not None or hub_length is not None:
        if hub_diameter is None or hub_length is None:
            raise ValueError("hub_diameter and hub_length are set together")
        hub_d = _positive("hub_diameter", hub_diameter)
        hub_l = _positive("hub_length", hub_length)
        if hub_d >= dims["root_diameter"] - 0.3:
            raise ValueError("hub_diameter must be smaller than the root diameter")
        if hub_l > face_width + 1e-6:
            z0 = face_width - hub_l
        hub = _cylinder(hub_l, hub_d / 2.0, segments=64).translate((0.0, 0.0, face_width - hub_l))
        blank = _union([blank, hub])
        z1 = face_width
    if bore is not None:
        hole = _positive("bore", bore)
        if hole >= dims["root_diameter"] - 0.8:
            raise ValueError("bore must be smaller than the root diameter")
        if hub_diameter is not None and hole >= float(hub_diameter) - 0.4:
            raise ValueError("bore must be smaller than the hub diameter")
        blank = _difference(blank, [_bore_cutter(hole, z0, z1, keyway_width, keyway_depth, d_flat, dims["root_diameter"])])
    elif any(value is not None for value in (keyway_width, keyway_depth, d_flat)):
        raise ValueError("a keyway or D-flat needs a bore")
    mesh = _as_one(blank)
    _tag_teeth(mesh, float(dims["root_diameter"]) / 2.0)
    return mesh


def spiral_centerline(
    *,
    width: float,
    turns: float,
    end_radius: float,
    kind: str = "archimedean",
    inner_radius: float | None = None,
    tongue: float = 0.0,
) -> dict:
    """Archimedean or log spiral in the attach frame.

    The outer end of the centreline is the origin and its tangent points +X.
    A ``tongue`` continues along +X so a strap can overlap it. The spiral
    centre is in ``center``. ``inner_radius`` is the centreline radius at the
    start of the curl. Turns run from the inside out. Adjacent turns stay
    apart by more than ``width``.
    """
    return _spiral_frame(
        width=_positive("width", width),
        turns=_turns(turns),
        end_radius=_positive("end_radius", end_radius),
        kind=_spiral_kind(kind),
        inner_radius=None if inner_radius is None else _positive("inner_radius", inner_radius),
        tongue=0.0 if tongue in (None, 0, 0.0) else _positive("tongue", tongue),
    )


def spiral_scroll(
    *,
    width: float,
    thickness: float,
    turns: float,
    end_radius: float,
    kind: str = "archimedean",
    inner_radius: float | None = None,
    tongue: float = 0.0,
    strap_length: float = 0.0,
) -> trimesh.Trimesh:
    """One spiral strip, in millimetres, extruded by ``thickness``.

    ``width`` is the in-plane strip width. ``kind`` is ``archimedean`` or
    ``log``. The outer centreline radius is ``end_radius``. The curl sits in
    -X / +Y and a tongue runs along +X. ``strap_length`` unions a straight
    strap of the same width and thickness onto that tongue, still one body.
    """
    width = _positive("width", width)
    thickness = _positive("thickness", thickness)
    strap = 0.0 if strap_length in (None, 0, 0.0) else _positive("strap_length", strap_length)
    tongue_length = 0.0 if tongue in (None, 0, 0.0) else _positive("tongue", tongue)
    if strap > 0 and tongue_length <= 0:
        tongue_length = min(width, strap)
    if strap > 0 and tongue_length > strap + 1e-6:
        raise ValueError("tongue is longer than strap_length")
    frame = _spiral_frame(
        width=width,
        turns=_turns(turns),
        end_radius=_positive("end_radius", end_radius),
        kind=_spiral_kind(kind),
        inner_radius=None if inner_radius is None else _positive("inner_radius", inner_radius),
        tongue=tongue_length,
    )
    body = _strip_solid(frame["points"], width, thickness)
    if strap > 0:
        strap_body = _box(strap, width, thickness).translate((0.0, -width / 2.0, 0.0))
        body = _union([body, strap_body])
    return _as_one(body)


def strap_hinge(
    *,
    length: float,
    width: float,
    thickness: float,
    turns: float = 1.25,
    end_radius: float = 16.0,
    kind: str = "archimedean",
    ends: int = 2,
) -> trimesh.Trimesh:
    """A straight strap with a spiral scroll on one or both ends. One shell.

    ``length`` is the straight section. Each scroll uses the strap's width
    and thickness, and overlaps the strap so the union stays one body.
    """
    length = _positive("length", length)
    width = _positive("width", width)
    thickness = _positive("thickness", thickness)
    count = int(ends)
    if count not in (1, 2):
        raise ValueError("ends must be 1 or 2")
    tongue = min(width, length / count)
    if length <= tongue * count + 0.2:
        raise ValueError("length is too short for the scroll tongue")
    frame = _spiral_frame(
        width=width,
        turns=_turns(turns),
        end_radius=_positive("end_radius", end_radius),
        kind=_spiral_kind(kind),
        inner_radius=None,
        tongue=tongue,
    )
    right = frame["points"].copy()
    right[:, 0] *= -1.0
    right[:, 0] += length
    bodies = [
        _box(length, width, thickness).translate((0.0, -width / 2.0, 0.0)),
        _strip_solid(right, width, thickness),
    ]
    if count == 2:
        left = right.copy()
        left[:, 0] = length - left[:, 0]
        left[:, 1] *= -1.0
        bodies.append(_strip_solid(left, width, thickness))
    return _as_one(_union(bodies))


def _thread_size(designation: str, diameter: float | None, pitch: float | None) -> tuple[float, float]:
    nominal, step, _flats, _head = _lookup(designation, diameter is not None and pitch is not None)
    if diameter is not None:
        nominal = _positive("diameter", diameter)
    if pitch is not None:
        step = _positive("pitch", pitch)
    if step >= nominal * 0.8:
        raise ValueError("pitch must be smaller than the diameter")
    return nominal, step


def _fastener(designation, diameter, pitch, across_flats, head_height):
    nominal, step, flats, head = _lookup(designation, False)
    if diameter is not None:
        nominal = _positive("diameter", diameter)
    if pitch is not None:
        step = _positive("pitch", pitch)
    if across_flats is not None:
        flats = _positive("across_flats", across_flats)
    if head_height is not None:
        head = _positive("head_height", head_height)
    if flats <= nominal:
        raise ValueError("across_flats must be wider than the thread")
    return nominal, step, flats, head


def _lookup(designation: str, allow_blank: bool) -> tuple[float, float, float, float]:
    key = (designation or "").strip().upper()
    if key in _ISO:
        return _ISO[key]
    if allow_blank and not key:
        return (3.0, 0.5, 5.5, 2.0)
    known = ", ".join(sorted(_ISO))
    raise ValueError(f"unknown thread {designation!r}. Known designations: {known}. Or pass diameter and pitch.")


def _external_mesh(diameter: float, pitch: float, length: float, segments_per_turn: int) -> trimesh.Trimesh:
    return _as_one(_external_solid(diameter, pitch, length, segments_per_turn))


def _external_solid(diameter: float, pitch: float, length: float, segments_per_turn: int):
    length = _positive("length", length)
    pitch = _positive("pitch", pitch)
    major = diameter / 2.0
    tooth = _TOOTH * pitch
    minor = major - tooth
    if minor <= pitch * 0.15:
        minor = major * 0.72
    core_r = minor + tooth * 0.28
    root_r = core_r * 0.96
    ridge = _ridge_solid(root_r, major, pitch, length, segments_per_turn=segments_per_turn, hand=1)
    core = _cylinder(length, core_r, segments=40)
    return _union([core, ridge])


def _ridge_solid(root_r, crest_r, pitch, length, *, segments_per_turn: int, hand: int):
    mesh = _helix_ridge(root_r, crest_r, pitch, length, segments_per_turn, hand)
    return _ingest(mesh)


def _helix_ridge(root_r, crest_r, pitch, length, seg_per_turn, hand) -> trimesh.Trimesh:
    """Triangular helical prism. Axial width stays under one pitch so turns do not meet."""
    half = min(abs(pitch) * 0.22, length * 0.12)
    span = length - 2.0 * half
    if span <= abs(pitch) * 0.25:
        raise ValueError("thread length is too short for the pitch")
    turns = span / abs(pitch)
    n = max(12, int(math.ceil(turns * max(6, int(seg_per_turn)))))
    n = min(n, 900)
    z_values = half + np.linspace(0.0, span, n, endpoint=False)
    thetas = (z_values - half) / abs(pitch) * 2.0 * math.pi * (1 if hand >= 0 else -1)
    profile = ((root_r, -half), (crest_r, 0.0), (root_r, half))
    vertices = np.zeros((n * 3, 3), dtype=float)
    for index, (theta, z_mid) in enumerate(zip(thetas, z_values)):
        cos_t = math.cos(float(theta))
        sin_t = math.sin(float(theta))
        for corner, (radius, dz) in enumerate(profile):
            vertices[index * 3 + corner] = (radius * cos_t, radius * sin_t, z_mid + dz)
    faces = []
    for index in range(n - 1):
        for corner in range(3):
            nxt = (corner + 1) % 3
            a = index * 3 + corner
            b = index * 3 + nxt
            c = (index + 1) * 3 + nxt
            d = (index + 1) * 3 + corner
            faces.append([a, b, c])
            faces.append([a, c, d])
    # Caps. Side faces wind with the profile; the start cap is the other way.
    faces.append([2, 1, 0])
    last = (n - 1) * 3
    faces.append([last, last + 1, last + 2])
    return trimesh.Trimesh(vertices=vertices, faces=np.asarray(faces, dtype=np.int64), process=False)


def _straight_ribs(radius, length, count, *, tooth, thickness):
    ribs = []
    for index in range(count):
        angle = 360.0 * index / count
        # Overlaps the core: the box starts inside the radius.
        rib = _box(radius * 0.55 + tooth, thickness, length).translate((radius * 0.72, -thickness / 2.0, 0.0))
        ribs.append(rib.rotate((0.0, 0.0, angle)))
    return ribs


def _hex_prism(across_flats: float, height: float):
    # Manifold's 6-gon cylinder uses the circumradius. Across-flats = R * sqrt(3).
    radius = float(across_flats) / math.sqrt(3.0)
    return _cylinder(height, radius, segments=6)


def _parallel_frames(pts: np.ndarray):
    count = len(pts)
    tangents = np.zeros_like(pts)
    for index in range(count):
        if index == 0:
            tangent = pts[1] - pts[0]
        elif index == count - 1:
            tangent = pts[-1] - pts[-2]
        else:
            tangent = pts[index + 1] - pts[index - 1]
        norm = float(np.linalg.norm(tangent))
        if norm < 1e-8:
            raise ValueError("sweep path has a zero-length step")
        tangents[index] = tangent / norm
    helper = np.array([0.0, 0.0, 1.0]) if abs(float(tangents[0][2])) < 0.9 else np.array([1.0, 0.0, 0.0])
    normal = np.cross(tangents[0], helper)
    normal = normal / np.linalg.norm(normal)
    binormal = np.cross(tangents[0], normal)
    frames = [(pts[0], normal, binormal)]
    for index in range(1, count):
        previous = tangents[index - 1]
        current = tangents[index]
        axis = np.cross(previous, current)
        axis_len = float(np.linalg.norm(axis))
        normal, binormal = frames[-1][1], frames[-1][2]
        if axis_len >= 1e-8:
            axis = axis / axis_len
            angle = math.atan2(axis_len, float(np.dot(previous, current)))
            normal = _rodrigues(normal, axis, angle)
            binormal = np.cross(current, normal)
            binormal_norm = float(np.linalg.norm(binormal))
            if binormal_norm < 1e-8:
                raise ValueError("sweep path folded back on itself")
            binormal = binormal / binormal_norm
            normal = np.cross(binormal, current)
        frames.append((pts[index], normal, binormal))
    return frames


def _rodrigues(vector, axis, angle):
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    return vector * cos_a + np.cross(axis, vector) * sin_a + axis * float(np.dot(axis, vector)) * (1.0 - cos_a)


def _tooth_count(teeth) -> int:
    try:
        count = int(teeth)
    except (TypeError, ValueError) as exc:
        raise ValueError("teeth must be an integer") from exc
    if abs(float(teeth) - count) > 1e-6:
        raise ValueError("teeth must be an integer")
    if count < 6 or count > 120:
        raise ValueError("teeth must be from 6 to 120")
    return count


def _pressure_angle(degrees: float) -> float:
    try:
        angle = float(degrees)
    except (TypeError, ValueError) as exc:
        raise ValueError("pressure_angle must be a number of degrees") from exc
    if not np.isfinite(angle) or angle < 10.0 or angle > 35.0:
        raise ValueError("pressure_angle must be from 10 to 35 degrees")
    return angle


def _gear_polygon(module: float, teeth: int, pressure_deg: float) -> tuple[list, dict]:
    """Closed CCW involute profile. Tip and root radii are exact."""
    alpha = math.radians(pressure_deg)
    pitch_radius = module * teeth / 2.0
    tip_radius = module * (teeth + 2) / 2.0
    root_radius = module * (teeth - 2.5) / 2.0
    if root_radius <= module * 0.4:
        raise ValueError("root diameter is too small for this module and tooth count")
    base_radius = pitch_radius * math.cos(alpha)
    involute_alpha = math.tan(alpha) - alpha
    beta = math.pi / (2.0 * teeth) + involute_alpha

    def flank(radius: float) -> float:
        if radius <= base_radius * (1.0 + 1e-9):
            return beta
        phi = math.acos(min(1.0, base_radius / radius))
        return beta - (math.tan(phi) - phi)

    tip_half = flank(tip_radius)
    if tip_half <= math.radians(0.2):
        raise ValueError("that pressure angle leaves a pointed tooth; use fewer degrees or more teeth")
    start_radius = base_radius if root_radius < base_radius else root_radius
    points: list[tuple[float, float]] = []
    flank_steps = 12
    for index in range(teeth):
        center = 2.0 * math.pi * index / teeth
        radii = [root_radius]
        if start_radius > root_radius + 1e-6:
            radii.append(start_radius)
        radii.extend(np.linspace(max(start_radius, root_radius), tip_radius, flank_steps).tolist())
        clean: list[float] = []
        for radius in radii:
            if not clean or radius > clean[-1] + 1e-8:
                clean.append(float(radius))
        for radius in clean:
            ang = center - flank(radius)
            points.append((radius * math.cos(ang), radius * math.sin(ang)))
        a0 = center - tip_half
        a1 = center + tip_half
        tip_angles = [a0 + (a1 - a0) * step / 6.0 for step in range(1, 6)]
        tip_angles.append(center)
        for ang in sorted(tip_angles):
            points.append((tip_radius * math.cos(ang), tip_radius * math.sin(ang)))
        for radius in reversed(clean):
            ang = center + flank(radius)
            points.append((radius * math.cos(ang), radius * math.sin(ang)))
        next_center = 2.0 * math.pi * ((index + 1) % teeth) / teeth
        b0 = center + flank(root_radius)
        b1 = next_center - flank(root_radius)
        while b1 <= b0:
            b1 += 2.0 * math.pi
        if b1 - b0 < 1e-4:
            raise ValueError("teeth overlap at the root; use a smaller pressure angle or fewer teeth")
        for step in range(1, 4):
            ang = b0 + (b1 - b0) * step / 4.0
            points.append((root_radius * math.cos(ang), root_radius * math.sin(ang)))
    dims = {
        "tip_diameter": 2.0 * tip_radius,
        "root_diameter": 2.0 * root_radius,
        "pitch_diameter": 2.0 * pitch_radius,
        "base_diameter": 2.0 * base_radius,
    }
    return points, dims


def _cross_section(points):
    import manifold3d

    ring = []
    for point in points:
        pair = [float(point[0]), float(point[1])]
        if ring and abs(pair[0] - ring[-1][0]) < 1e-7 and abs(pair[1] - ring[-1][1]) < 1e-7:
            continue
        ring.append(pair)
    if len(ring) >= 2 and abs(ring[0][0] - ring[-1][0]) < 1e-7 and abs(ring[0][1] - ring[-1][1]) < 1e-7:
        ring.pop()
    area = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        area += x1 * y2 - x2 * y1
    if area < 0.0:
        ring.reverse()
    section = manifold3d.CrossSection([ring])
    if section.is_empty() or section.area() <= 0:
        raise ValueError("profile was not a solid outline")
    return section


def _bore_cutter(diameter, z0, z1, keyway_width, keyway_depth, d_flat, root_diameter):
    radius = diameter / 2.0
    height = (z1 - z0) + 1.2
    cutter = _cylinder(height, radius, segments=64).translate((0.0, 0.0, z0 - 0.6))
    has_key = keyway_width is not None or keyway_depth is not None
    has_flat = d_flat is not None
    if has_key and has_flat:
        raise ValueError("use a keyway or a D-flat, not both")
    if has_key:
        if keyway_width is None or keyway_depth is None:
            raise ValueError("keyway_width and keyway_depth are set together")
        width = _positive("keyway_width", keyway_width)
        depth = _positive("keyway_depth", keyway_depth)
        if width >= diameter * 0.95:
            raise ValueError("keyway_width must be narrower than the bore")
        if radius + depth >= root_diameter / 2.0 - 0.25:
            raise ValueError("keyway_depth breaks through the root")
        pocket = _box(width, depth + 0.2, height).translate((-width / 2.0, radius - 0.15, z0 - 0.6))
        cutter = _union([cutter, pocket])
    if has_flat:
        flat_across = _positive("d_flat", d_flat)
        if not radius < flat_across < diameter - 1e-6:
            raise ValueError("d_flat must be between the bore radius and the bore diameter")
        flat_y = flat_across - radius
        # Drop the cap past the flat so the hole is a D, not a full circle.
        cap = _box(diameter + 2.0, radius - flat_y + 1.0, height).translate(
            (-(diameter + 2.0) / 2.0, flat_y, z0 - 0.6)
        )
        cutter = _difference(cutter, [cap])
    return cutter


_SPIRAL_GAP = 0.45


def _turns(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("turns must be a number") from exc
    if not np.isfinite(number) or number < 0.5 or number > 6.0:
        raise ValueError("turns must be from 0.5 to 6")
    return number


def _spiral_kind(kind: str) -> str:
    name = (kind or "archimedean").strip().lower()
    if name not in ("archimedean", "log"):
        raise ValueError("spiral kind must be archimedean or log")
    return name


def _spiral_frame(*, width, turns, end_radius, kind, inner_radius, tongue) -> dict:
    pitch_target = width + _SPIRAL_GAP
    if inner_radius is None:
        inner = _default_inner_radius(kind, turns, end_radius, pitch_target, width)
    else:
        inner = inner_radius
        if inner >= end_radius - width * 0.5:
            raise ValueError("inner_radius must sit inside end_radius by more than the strip")
    theta_max = turns * 2.0 * math.pi
    samples = max(32, int(round(48 * turns)))
    theta = np.linspace(0.0, theta_max, samples)
    if kind == "archimedean":
        pitch = (end_radius - inner) / turns
        if pitch <= width:
            raise ValueError("turns collide; increase end_radius or inner gap, or reduce width or turns")
        radius = inner + (end_radius - inner) * (theta / theta_max)
    else:
        growth = math.log(end_radius / inner) / theta_max
        # Tightest gap is the inner turn.
        inner_gap = inner * (math.exp(2.0 * math.pi * growth) - 1.0)
        if inner_gap <= width:
            raise ValueError("log spiral turns collide; increase end_radius or reduce width or turns")
        radius = inner * np.exp(growth * theta)
    raw = np.column_stack((radius * np.cos(theta), radius * np.sin(theta)))
    end = raw[-1]
    tangent = end - raw[-2]
    tangent = tangent / np.linalg.norm(tangent)
    rotation = math.atan2(float(tangent[1]), float(tangent[0]))
    cosine = math.cos(-rotation)
    sine = math.sin(-rotation)
    matrix = np.array([[cosine, -sine], [sine, cosine]])
    shifted = (raw - end) @ matrix.T
    center = (-end) @ matrix.T
    points = shifted
    if tongue > 0:
        extra = np.column_stack((np.linspace(0.0, tongue, 8)[1:], np.zeros(7)))
        points = np.vstack((points, extra))
    return {
        "points": points,
        "center": (float(center[0]), float(center[1])),
        "inner_radius": float(inner),
        "end_radius": float(end_radius),
        "kind": kind,
        "turns": float(turns),
        "tongue": float(tongue),
    }


def _default_inner_radius(kind: str, turns: float, end_radius: float, target: float, width: float) -> float:
    floor = max(0.8, width * 0.35)
    if kind == "archimedean":
        inner = end_radius - target * turns
        if inner <= floor:
            raise ValueError(
                f"end_radius {end_radius:g} cannot hold {turns:g} turns at width {width:g}. "
                "Increase end_radius or reduce turns or width."
            )
        return float(inner)
    ratio = target / end_radius
    if ratio >= 0.98:
        raise ValueError(
            f"end_radius {end_radius:g} is too small for a {width:g} mm strip. "
            "Increase end_radius or reduce width."
        )

    def gap_ratio(growth):
        return (growth - 1.0) / growth**turns

    if turns <= 1.0 + 1e-9:
        low = 1.0001
        high = 2.0
        while gap_ratio(high) < ratio:
            high *= 1.6
            if high > 1e6:
                raise ValueError("log spiral does not fit in that end radius")
        for _ in range(60):
            mid = 0.5 * (low + high)
            if gap_ratio(mid) < ratio:
                low = mid
            else:
                high = mid
        growth = 0.5 * (low + high)
    else:
        peak = turns / (turns - 1.0)
        if gap_ratio(peak) < ratio:
            raise ValueError(
                f"end_radius {end_radius:g} cannot hold {turns:g} log turns at width {width:g}. "
                "Increase end_radius or reduce turns or width."
            )
        low, high = 1.0001, peak
        for _ in range(60):
            mid = 0.5 * (low + high)
            if gap_ratio(mid) < ratio:
                low = mid
            else:
                high = mid
        growth = 0.5 * (low + high)
    inner = end_radius / growth**turns
    if inner <= floor:
        raise ValueError(
            f"log spiral inner radius would be {inner:.2f} mm. "
            "Increase end_radius or reduce turns or width."
        )
    return float(inner)


def _strip_solid(points: np.ndarray, width: float, thickness: float):
    from shapely.geometry import LineString

    line = LineString([(float(point[0]), float(point[1])) for point in points])
    polygon = line.buffer(width / 2.0, cap_style="flat", join_style="round", quad_segs=3)
    if polygon.geom_type != "Polygon" or (not polygon.is_valid) or polygon.area <= 0:
        raise ValueError(
            "spiral strip intersects itself. Increase end_radius or reduce width or turns."
        )
    ring = [[float(x), float(y)] for x, y in list(polygon.exterior.coords)[:-1]]
    section = _cross_section(ring)
    return section.extrude(float(thickness))


def _positive(name: str, value: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not np.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be positive")
    return number


def _cylinder(height, radius, segments=32):
    import manifold3d

    return manifold3d.Manifold.cylinder(float(height), float(radius), float(radius), int(segments), False)


def _box(x, y, z):
    import manifold3d

    return manifold3d.Manifold.cube((float(x), float(y), float(z)), center=False)


def _union(bodies):
    import manifold3d

    bodies = list(bodies)
    if len(bodies) == 1:
        return bodies[0]
    return manifold3d.Manifold.batch_boolean(bodies, manifold3d.OpType.Add)


def _difference(base, cutters):
    import manifold3d

    return manifold3d.Manifold.batch_boolean([base, *cutters], manifold3d.OpType.Subtract)


def _ingest(mesh: trimesh.Trimesh):
    from photopart.manifold_util import to_manifold

    if mesh.volume < 0:
        mesh.invert()
    body = to_manifold(mesh)
    if body.is_empty():
        raise ValueError("thread ridge was not a manifold solid")
    return body


def _as_one(body) -> trimesh.Trimesh:
    from photopart.manifold_util import as_mesh, union_components

    try:
        mesh = as_mesh(body)
    except ValueError as exc:
        raise ValueError("feature helper produced an empty solid") from exc
    if (not mesh.is_watertight) or len(mesh.split(only_watertight=False)) != 1:
        merged, applied = union_components(mesh)
        if applied:
            mesh = merged
    shells = len(mesh.split(only_watertight=False))
    if not mesh.is_watertight or shells != 1 or mesh.volume <= 0:
        raise ValueError(f"feature helper produced {shells} shells, watertight={bool(mesh.is_watertight)}")
    return mesh


def _tag_thread_crest(mesh: trimesh.Trimesh, diameter: float, pitch: float, *, z_max: float, internal: bool = False) -> None:
    """Mark helical crest faces so thickness rays do not start on a thread."""
    major = float(diameter) / 2.0
    tooth = _TOOTH * float(pitch)
    centers = np.asarray(mesh.triangles_center, dtype=float)
    radius = np.hypot(centers[:, 0], centers[:, 1])
    # The whole tooth, from the root out to the crest. The core under the
    # root stays a ray source so a real thin wall is still measured.
    if internal:
        band = (radius < major + tooth * 0.35) & (radius > max(0.15, major - tooth * 1.05))
    else:
        band = radius > max(0.2, major - tooth * 1.05)
    mask = band & (centers[:, 2] < z_max) & (centers[:, 2] > -0.5)
    _store_tags(mesh, thread=np.flatnonzero(mask))
    if internal:
        r_min = max(0.15, major - tooth * 1.05)
        r_max = major + tooth * 0.35
    else:
        r_min = max(0.2, major - tooth * 1.05)
        r_max = major + tooth * 0.25
    _remember_region(
        mesh,
        {
            "kind": "thread",
            "axis": [0.0, 0.0, 1.0],
            "origin": [0.0, 0.0, 0.0],
            "r_min": float(r_min),
            "r_max": float(r_max),
            "z0": -0.5,
            "z1": float(z_max),
            "pitch": float(pitch),
        },
    )


def _tag_knurl(mesh: trimesh.Trimesh, core_radius: float) -> None:
    centers = np.asarray(mesh.triangles_center, dtype=float)
    radius = np.hypot(centers[:, 0], centers[:, 1])
    # Ribs stand off the core. Keep the core wall as a ray source and drop the tips.
    mask = radius > float(core_radius) * 0.88
    _store_tags(mesh, knurl=np.flatnonzero(mask))
    bounds = np.asarray(mesh.bounds, dtype=float)
    _remember_region(
        mesh,
        {
            "kind": "knurl",
            "axis": [0.0, 0.0, 1.0],
            "origin": [0.0, 0.0, 0.0],
            "r_min": float(core_radius) * 0.88,
            "r_max": float(radius.max()) + 0.05 if radius.size else float(core_radius) * 1.3,
            "z0": float(bounds[0, 2]) - 0.05,
            "z1": float(bounds[1, 2]) + 0.05,
            "pitch": None,
        },
    )


def _tag_teeth(mesh: trimesh.Trimesh, root_radius: float) -> None:
    centers = np.asarray(mesh.triangles_center, dtype=float)
    radius = np.hypot(centers[:, 0], centers[:, 1])
    mask = radius > float(root_radius) * 1.02
    _store_tags(mesh, teeth=np.flatnonzero(mask))
    bounds = np.asarray(mesh.bounds, dtype=float)
    _remember_region(
        mesh,
        {
            "kind": "teeth",
            "axis": [0.0, 0.0, 1.0],
            "origin": [0.0, 0.0, 0.0],
            "r_min": float(root_radius) * 1.02,
            "r_max": float(radius.max()) + 0.05 if radius.size else float(root_radius) * 1.4,
            "z0": float(bounds[0, 2]) - 0.05,
            "z1": float(bounds[1, 2]) + 0.05,
            "pitch": None,
        },
    )


def tag_faces(mesh: trimesh.Trimesh, *, thread=None, knurl=None, teeth=None, path=None) -> dict:
    """Mark faces the wall check should skip, and write ``<path>.faces.json``.

    Call this after the final boolean. ``thread``, ``knurl``, and ``teeth``
    are face indices into ``mesh.faces``. Omit a kind to leave tags already
    stored on the mesh. Helpers also store a geometric region (axis, origin,
    radius range, z range, pitch) on ``mesh.metadata["feature_regions"]`` so
    the wall check can find the feature again after a union renumbers faces.
    STL export drops metadata, so pass ``path`` or export to a filesystem
    path after importing this module. The export hook writes the sidecar,
    including those regions.
    """
    kinds = {}
    if thread is not None:
        kinds["thread"] = thread
    if knurl is not None:
        kinds["knurl"] = knurl
    if teeth is not None:
        kinds["teeth"] = teeth
    if kinds:
        _store_tags(mesh, **kinds)
    if path is not None:
        write_face_tags(mesh, path)
    stored = mesh.metadata.get("face_tags") if isinstance(getattr(mesh, "metadata", None), dict) else None
    tags = stored if isinstance(stored, dict) else {}
    return {key: [int(item) for item in (tags.get(key) or [])] for key in ("thread", "knurl", "teeth")}


def write_face_tags(mesh: trimesh.Trimesh, stl_path) -> None:
    """Store face indices and geometric regions beside an STL. STL itself drops them."""
    meta = mesh.metadata if isinstance(getattr(mesh, "metadata", None), dict) else {}
    tags = meta.get("face_tags")
    payload = {}
    if isinstance(tags, dict):
        for key in ("thread", "knurl", "teeth"):
            payload[key] = [int(item) for item in (tags.get(key) or [])]
    else:
        for key in ("thread", "knurl", "teeth"):
            payload[key] = []
    regions = meta.get("feature_regions")
    if isinstance(regions, list) and regions:
        payload["regions"] = regions
    if not any(payload.get(key) for key in ("thread", "knurl", "teeth")) and not payload.get("regions"):
        return
    path = Path(str(stl_path) + ".faces.json")
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_face_tags(stl_path) -> dict | None:
    path = Path(str(stl_path) + ".faces.json")
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    if not isinstance(loaded, dict):
        return None
    found = {
        key: [int(item) for item in (loaded.get(key) or [])]
        for key in ("thread", "knurl", "teeth")
    }
    regions = loaded.get("regions")
    found["regions"] = list(regions) if isinstance(regions, list) else []
    return found


def _install_tag_export() -> None:
    """Write ``<path>.faces.json`` when a tagged mesh is exported to a path."""
    current = trimesh.Trimesh.export
    if getattr(current, "_p2p_wrapped", False):
        return

    def export(self, file_obj=None, file_type=None, **kwargs):
        result = current(self, file_obj=file_obj, file_type=file_type, **kwargs)
        if isinstance(file_obj, (str, Path)):
            try:
                write_face_tags(self, file_obj)
            except OSError:
                pass
        return result

    export._p2p_wrapped = True
    trimesh.Trimesh.export = export


def _remember_region(mesh: trimesh.Trimesh, region: dict) -> None:
    """Append one geometric feature. A later boolean drops this; the sidecar keeps a copy."""
    existing = mesh.metadata.get("feature_regions") if isinstance(mesh.metadata, dict) else None
    regions = list(existing) if isinstance(existing, list) else []
    regions.append(region)
    mesh.metadata["feature_regions"] = regions


def _store_tags(mesh: trimesh.Trimesh, **kinds) -> None:
    tags = {"thread": [], "knurl": [], "teeth": []}
    existing = mesh.metadata.get("face_tags") if isinstance(mesh.metadata, dict) else None
    if isinstance(existing, dict):
        for key in tags:
            tags[key] = [int(item) for item in (existing.get(key) or [])]
    for key, value in kinds.items():
        tags[key] = [int(item) for item in np.asarray(value, dtype=int).tolist()]
    mesh.metadata["face_tags"] = tags


_install_tag_export()
