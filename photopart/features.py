"""Watertight building blocks for photo_part_build scripts.

Import them from a build script. Each function returns one watertight
trimesh, in millimetres, or raises ``ValueError``.

    from photopart.features import (
        external_thread, internal_thread, knurl, revolve_profile,
        sweep_path, hex_screw, hex_standoff, bottle_cap,
    )

Threads are a helical ridge unioned with a core through manifold3d, so the
result is one shell. A bottle cap is an internal coarse thread with knurl
ridges on the outside wall, also one shell.
"""

from __future__ import annotations

import math

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
    return _external_mesh(nominal, step, length, segments_per_turn)


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
    return _as_one(_difference(outer_body, [cutter]))


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
        return _as_one(_union([core, *ribs]))
    tooth = max(0.3, radius * 0.07)
    step = max(length * 0.55, radius * 1.4)
    left = _ridge_solid(radius * 0.94, radius + tooth, step, length, segments_per_turn=10, hand=1)
    right = _ridge_solid(radius * 0.94, radius + tooth, step, length, segments_per_turn=10, hand=-1)
    return _as_one(_union([core, left, right]))


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
    return _as_one(_union([thread, cap]))


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
    return _as_one(_union([_ingest(cap), *shifted]))


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
