"""Orthographic previews and a scaled outline overlay.

Faces above the preview cap are quadric-decimated. The picture is a z-buffer,
so coplanar faces do not streak and dropped faces are not left as holes.
Axes are fitted to the part. The longest axis is up unless the caller picks one.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw, ImageFont

from photopart.flow import OVERLAY_LOW_STEP, attach_flow, failed, step_render
from photopart.io import DEFAULT_MAX_BYTES, load_mesh, resolve_file
from photopart.paths import absolute_path
from photopart.stamp import stamp_status
from photopart.status import status
from photopart.units import add_unit_arguments, attach_units, prepare_mesh

PREVIEW_FACE_CAP = 8000
FULL_RASTER_LIMIT = 200_000
_VIEWS = ("front", "side", "top", "iso")
_AXIS = {"x": 0, "y": 1, "z": 2}
_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def choose_axes(extents, up: str | None = None, front_axis: str | None = None) -> dict[str, str]:
    """Pick up, front, and side from the part's extents.

    Up is the longest axis. The front camera looks along the shortest remaining
    axis, which is the thin direction of a plate and the depth of an upright peg.
    Ties take the earlier of x, y, z.
    """
    ext = np.asarray(extents, dtype=float).reshape(3)
    names = ("x", "y", "z")
    if up is not None and up not in names:
        raise ValueError(f"up must be x, y, or z, got {up!r}")
    if front_axis is not None and front_axis not in names:
        raise ValueError(f"front axis must be x, y, or z, got {front_axis!r}")
    if up is None:
        if front_axis is None:
            up_i = int(np.argmax(ext))
        else:
            front_i = names.index(front_axis)
            rest = [i for i in range(3) if i != front_i]
            up_i = rest[int(np.argmax(ext[rest]))]
    else:
        up_i = names.index(up)
    if front_axis is None:
        rest = [i for i in range(3) if i != up_i]
        front_i = rest[int(np.argmin(ext[rest]))]
    else:
        front_i = names.index(front_axis)
    if front_i == up_i:
        raise ValueError("front axis and up axis must be different")
    side_i = next(i for i in range(3) if i not in (up_i, front_i))
    return {
        "up": names[up_i],
        "front_axis": names[front_i],
        "side_axis": names[side_i],
        "top_axis": names[up_i],
    }


def _ortho_map(view: str, axes: dict[str, str]) -> tuple[tuple[int, float], tuple[int, float], tuple[int, float]]:
    """Horizontal, vertical, and depth axes. Larger depth is farther from the camera."""
    up = _AXIS[axes["up"]]
    front = _AXIS[axes["front_axis"]]
    side = _AXIS[axes["side_axis"]]
    if view == "front":
        return (side, 1.0), (up, 1.0), (front, 1.0)
    if view == "side":
        return (front, 1.0), (up, 1.0), (side, 1.0)
    if view == "top":
        return (side, 1.0), (front, 1.0), (up, -1.0)
    if view == "back":
        return (side, -1.0), (up, 1.0), (front, -1.0)
    if view == "right":
        return (front, -1.0), (up, 1.0), (side, -1.0)
    if view == "bottom":
        return (side, 1.0), (front, -1.0), (up, 1.0)
    raise ValueError(f"unknown view {view}")


def _publish_poses(report: dict) -> dict:
    """Keep 30° and 60° views in the search, and list them only when one wins.

    The orthographic set stays ``front``, ``side``, and ``top`` otherwise, so
    a rectangle that prefers an earlier view is not reported as five poses.
    """
    winner = report.get("overlay_view") or "front"
    poses = list(report.get("overlay_poses") or [])
    if winner in {"front", "side", "top"}:
        poses = [row for row in poses if row.get("view") in {"front", "side", "top"}]
        report = dict(report)
        report["overlay_poses"] = poses
        report["overlay_top_poses"] = poses[:3]
    return report


def _elevate(vertices: np.ndarray, axes: dict[str, str], degrees: float) -> np.ndarray:
    """Rotate around the front view's horizontal axis so the camera looks down."""
    horizontal, _vertical, _depth = _ortho_map("front", axes)
    axis = np.zeros(3, dtype=float)
    axis[horizontal[0]] = 1.0
    theta = math.radians(float(degrees))
    k = axis / np.linalg.norm(axis)
    cross = np.array(
        [
            [0.0, -k[2], k[1]],
            [k[2], 0.0, -k[0]],
            [-k[1], k[0], 0.0],
        ],
        dtype=float,
    )
    rotation = np.eye(3) + math.sin(theta) * cross + (1.0 - math.cos(theta)) * (cross @ cross)
    return np.asarray(vertices, dtype=float) @ rotation.T


def _project(vertices: np.ndarray, view: str, axes: dict[str, str]) -> tuple[np.ndarray, np.ndarray]:
    if view == "iso":
        xy = np.column_stack(
            (
                vertices[:, 0] * 0.86 - vertices[:, 1] * 0.50,
                vertices[:, 2] + vertices[:, 0] * 0.35 + vertices[:, 1] * 0.40,
            )
        )
        depth = vertices[:, 0] * 0.2 + vertices[:, 1] * 0.3 + vertices[:, 2] * 0.1
        return xy, depth
    if view == "iso2":
        xy = np.column_stack(
            (
                -vertices[:, 0] * 0.86 + vertices[:, 1] * 0.50,
                vertices[:, 2] - vertices[:, 0] * 0.35 + vertices[:, 1] * 0.40,
            )
        )
        depth = -vertices[:, 0] * 0.2 - vertices[:, 1] * 0.3 + vertices[:, 2] * 0.1
        return xy, depth
    horizontal, vertical, depth_axis = _ortho_map(view, axes)
    xy = np.column_stack(
        (
            vertices[:, horizontal[0]] * horizontal[1],
            vertices[:, vertical[0]] * vertical[1],
        )
    )
    depth = vertices[:, depth_axis[0]] * depth_axis[1]
    return xy, depth


def _view_direction(view: str, axes: dict[str, str]) -> np.ndarray:
    """Direction from the camera into the scene, matching ``_project`` depth."""
    direction = np.zeros(3, dtype=float)
    if view == "iso":
        direction[:] = (0.2, 0.3, 0.1)
        direction /= np.linalg.norm(direction)
        return direction
    _horizontal, _vertical, depth_axis = _ortho_map(view, axes)
    direction[depth_axis[0]] = depth_axis[1]
    return direction


def _quantize(mesh: trimesh.Trimesh, pitch: float) -> trimesh.Trimesh:
    vertices = np.round(np.asarray(mesh.vertices, dtype=float) / pitch) * pitch
    trial = trimesh.Trimesh(vertices=vertices, faces=np.array(mesh.faces, copy=True), process=False)
    trial.merge_vertices()
    if len(trial.faces):
        trial.update_faces(trial.unique_faces() & trial.nondegenerate_faces())
    trial.remove_unreferenced_vertices()
    return trial


def _cluster_preview(mesh: trimesh.Trimesh, target_faces: int) -> trimesh.Trimesh:
    """Collapse nearby vertices until the face count fits. This keeps a surface.

    It is the fallback for a mesh too large to rasterize when quadric
    decimation is unavailable. It does not drop every Nth face.
    """
    longest = float(np.max(np.asarray(mesh.extents, dtype=float)))
    if longest <= 0 or len(mesh.faces) <= target_faces:
        return mesh
    lo = longest / 100_000.0
    hi = longest / 2.0
    best: trimesh.Trimesh | None = None
    for _ in range(16):
        pitch = (lo + hi) / 2.0
        trial = _quantize(mesh, pitch)
        count = len(trial.faces)
        if count == 0:
            hi = pitch
            continue
        if count > target_faces:
            lo = pitch
        else:
            best = trial
            hi = pitch
    if best is None:
        best = _quantize(mesh, max(hi, lo))
    return best if len(best.faces) else mesh


def _preview_mesh(mesh: trimesh.Trimesh) -> tuple[trimesh.Trimesh, dict]:
    count = int(len(mesh.faces))
    info = {
        "source_faces": count,
        "preview_faces": count,
        "decimated_for_preview": False,
        "decimation": "none",
    }
    if count <= PREVIEW_FACE_CAP:
        return mesh, info
    error = None
    try:
        simple = mesh.simplify_quadric_decimation(face_count=PREVIEW_FACE_CAP)
    except Exception as exc:
        simple = None
        error = str(exc)
    if simple is not None and len(simple.faces) > 0 and len(simple.faces) < count:
        info["preview_faces"] = int(len(simple.faces))
        info["decimated_for_preview"] = True
        info["decimation"] = "quadric"
        if error:
            info["decimation_error"] = error
        return simple, info
    if error:
        info["decimation_error"] = error
    if count <= FULL_RASTER_LIMIT:
        info["decimation"] = "full"
        return mesh, info
    clustered = _cluster_preview(mesh, PREVIEW_FACE_CAP)
    info["preview_faces"] = int(len(clustered.faces))
    info["decimated_for_preview"] = info["preview_faces"] < count
    info["decimation"] = "vertex_cluster"
    return clustered, info


def _shade(normals: np.ndarray) -> np.ndarray:
    light = np.array([0.35, -0.45, 0.82], dtype=float)
    light /= np.linalg.norm(light)
    length = np.linalg.norm(normals, axis=1)
    length[length == 0] = 1.0
    unit = normals / length[:, None]
    lambert = np.clip(unit @ light, 0.0, 1.0)
    tone = 0.28 + 0.72 * lambert
    color = np.column_stack(
        (
            0.45 + 0.35 * tone,
            0.55 + 0.30 * tone,
            0.62 + 0.25 * tone,
        )
    )
    return np.clip(color * 255.0, 0, 255).astype(np.uint8)


def _rasterize(
    points: np.ndarray,
    depth: np.ndarray,
    faces: np.ndarray,
    colors: np.ndarray,
    width: int,
    height: int,
) -> np.ndarray:
    """Paint triangles with a z-buffer. Smaller depth is closer to the camera."""
    image = np.full((height, width, 3), 255, dtype=np.uint8)
    zbuf = np.full((height, width), np.inf, dtype=np.float64)
    for index, face in enumerate(faces):
        tri = points[face]
        zed = depth[face]
        minx = max(int(math.floor(float(np.min(tri[:, 0])))), 0)
        maxx = min(int(math.ceil(float(np.max(tri[:, 0])))), width - 1)
        miny = max(int(math.floor(float(np.min(tri[:, 1])))), 0)
        maxy = min(int(math.ceil(float(np.max(tri[:, 1])))), height - 1)
        if minx > maxx or miny > maxy:
            continue
        xs = np.arange(minx, maxx + 1)
        ys = np.arange(miny, maxy + 1)
        xx, yy = np.meshgrid(xs, ys)
        x0, y0 = float(tri[0, 0]), float(tri[0, 1])
        x1, y1 = float(tri[1, 0]), float(tri[1, 1])
        x2, y2 = float(tri[2, 0]), float(tri[2, 1])
        denom = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(denom) < 1e-12:
            continue
        w0 = ((y1 - y2) * (xx - x2) + (x2 - x1) * (yy - y2)) / denom
        w1 = ((y2 - y0) * (xx - x2) + (x0 - x2) * (yy - y2)) / denom
        w2 = 1.0 - w0 - w1
        mask = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        if not np.any(mask):
            continue
        zz = w0 * float(zed[0]) + w1 * float(zed[1]) + w2 * float(zed[2])
        closer = mask & (zz < zbuf[miny : maxy + 1, minx : maxx + 1])
        ys_hit, xs_hit = np.nonzero(closer)
        if ys_hit.size == 0:
            continue
        zbuf[miny + ys_hit, minx + xs_hit] = zz[ys_hit, xs_hit]
        image[miny + ys_hit, minx + xs_hit] = colors[index]
    return image


def _frame(points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mins = points.min(axis=0)
    maxs = points.max(axis=0)
    span = np.maximum(maxs - mins, 1e-9)
    pad = np.maximum(span * 0.08, float(np.max(span)) * 0.02)
    return mins - pad, maxs + pad


def _fit(mins: np.ndarray, maxs: np.ndarray, width: int, height: int) -> tuple[float, float, float]:
    """One scale for both axes, so a 6 mm edge is not stretched into a square."""
    span = np.maximum(maxs - mins, 1e-9)
    scale = min((width - 1) / float(span[0]), (height - 1) / float(span[1]))
    used_w = float(span[0]) * scale
    used_h = float(span[1]) * scale
    origin_x = ((width - 1) - used_w) / 2.0
    origin_y = ((height - 1) - used_h) / 2.0
    return scale, origin_x, origin_y


def _to_pixels(points: np.ndarray, mins: np.ndarray, maxs: np.ndarray, width: int, height: int) -> np.ndarray:
    scale, origin_x, origin_y = _fit(mins, maxs, width, height)
    px = origin_x + (points[:, 0] - mins[0]) * scale
    py = origin_y + (maxs[1] - points[:, 1]) * scale
    return np.column_stack((px, py))


def _font(size: int) -> ImageFont.ImageFont:
    if Path(_FONT).is_file():
        return ImageFont.truetype(_FONT, size=size)
    return ImageFont.load_default()


def _grid_step(span: float, requested: float) -> float:
    if requested <= 0 or span <= 0:
        return requested
    count = span / requested
    if count <= 40:
        return requested
    return requested * math.ceil(count / 40.0)


def _draw_grid(
    image: np.ndarray,
    mins: np.ndarray,
    maxs: np.ndarray,
    grid_mm: float,
) -> float:
    height, width = image.shape[:2]
    span = np.maximum(maxs - mins, 1e-9)
    step = _grid_step(float(np.max(span)), grid_mm)
    if step <= 0:
        return step
    scale, origin_x, origin_y = _fit(mins, maxs, width, height)
    background = np.all(image >= 250, axis=2)
    canvas = Image.fromarray(image.copy(), mode="RGB")
    draw = ImageDraw.Draw(canvas)
    # Grid lines cover the whole frame at the same millimetre scale as the part.
    left = float(mins[0]) - origin_x / scale
    right = left + (width - 1) / scale
    top = float(maxs[1]) + origin_y / scale
    bottom = top - (height - 1) / scale
    start_x = math.floor(left / step) * step
    start_y = math.floor(bottom / step) * step
    x = start_x
    guard = 0
    while x <= right + step * 0.01 and guard < 80:
        px = origin_x + (x - float(mins[0])) * scale
        if 0 <= px <= width - 1:
            draw.line((px, 0, px, height - 1), fill=(213, 224, 230), width=1)
        x += step
        guard += 1
    y = start_y
    guard = 0
    while y <= top + step * 0.01 and guard < 80:
        py = origin_y + (float(maxs[1]) - y) * scale
        if 0 <= py <= height - 1:
            draw.line((0, py, width - 1, py), fill=(213, 224, 230), width=1)
        y += step
        guard += 1
    lined = np.asarray(canvas)
    # Keep the grid behind the part so lines do not streak across faces.
    image[background] = lined[background]
    return step


def render_view(
    mesh: trimesh.Trimesh,
    view: str,
    destination: Path,
    *,
    grid_mm: float | None,
    axes: dict[str, str],
    length_unit: str,
    pixels: int = 720,
    samples: int | None = None,
) -> dict:
    if samples is None:
        samples = 2 if len(mesh.faces) <= 2000 else 1
    samples = max(1, int(samples))
    vertices = np.asarray(mesh.vertices, dtype=float)
    points, depth = _project(vertices, view, axes)
    mins, maxs = _frame(points)
    faces = np.asarray(mesh.faces)
    colors = _shade(np.asarray(mesh.face_normals, dtype=float))
    scale = samples
    pix = _to_pixels(points, mins, maxs, pixels * scale, pixels * scale)
    buffer = _rasterize(pix, depth, faces, colors, pixels * scale, pixels * scale)
    if scale > 1:
        buffer = (
            buffer.reshape(pixels, scale, pixels, scale, 3).mean(axis=(1, 3)).astype(np.uint8)
        )
    drawn_step = None
    if grid_mm and grid_mm > 0 and view != "iso":
        drawn_step = _draw_grid(buffer, mins, maxs, grid_mm)
    header = 40
    canvas = Image.new("RGB", (pixels, pixels + header), "white")
    canvas.paste(Image.fromarray(buffer, mode="RGB"), (0, header))
    # Iso axes are a projection, not millimetres, so the title does not claim a scale.
    title = view if view == "iso" else f"{view}  ·  {length_unit}"
    ImageDraw.Draw(canvas).text((12, 10), title, fill=(28, 36, 48), font=_font(18))
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination, format="PNG")
    return {"grid_step_mm": drawn_step, "view": view}


def _contact(out_dir: Path, destination: Path) -> None:
    images = [Image.open(out_dir / f"{view}.png").convert("RGB") for view in _VIEWS]
    width, height = images[0].size
    label = 28
    gap = 12
    canvas = Image.new("RGB", (width * 2 + gap, (height + label) * 2 + gap), "white")
    draw = ImageDraw.Draw(canvas)
    font = _font(16)
    for index, (view, image) in enumerate(zip(_VIEWS, images)):
        column, row = index % 2, index // 2
        x = column * (width + gap)
        y = row * (height + label + gap)
        draw.text((x + 8, y + 4), view, fill=(28, 36, 48), font=font)
        canvas.paste(image, (x, y + label))
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination, format="PNG")


def side_by_side(photo: Path, render_path: Path, destination: Path) -> None:
    """Place a reference image on the left and the front render on the right."""
    left = Image.open(photo).convert("RGB")
    right = Image.open(render_path).convert("RGB")
    height = 720

    def scale(image: Image.Image) -> Image.Image:
        ratio = height / image.height
        return image.resize((max(1, int(image.width * ratio)), height), Image.Resampling.LANCZOS)

    left_s = scale(left)
    right_s = scale(right)
    gap = 24
    canvas = Image.new("RGB", (left_s.width + gap + right_s.width, height + 48), "white")
    canvas.paste(left_s, (0, 40))
    canvas.paste(right_s, (left_s.width + gap, 40))
    draw = ImageDraw.Draw(canvas)
    draw.text((12, 12), "reference", fill=(28, 36, 48), font=_font(18))
    draw.text((left_s.width + gap + 12, 12), "model front", fill=(28, 36, 48), font=_font(18))
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination, format="PNG")


def outline_segments(mesh: trimesh.Trimesh, view: str, axes: dict[str, str]) -> np.ndarray:
    """Projected outline: boundary edges plus silhouette edges for this view.

    A watertight solid has no boundary. Its outline is the set of edges where
    one neighbor faces the camera and the other faces away.
    """
    if len(mesh.faces) == 0:
        return np.zeros((0, 2, 2), dtype=float)
    unique = np.asarray(mesh.edges_unique)
    inverse = np.asarray(mesh.edges_unique_inverse)
    counts = np.bincount(inverse) if inverse.size else np.zeros(0, dtype=int)
    chosen: list[np.ndarray] = []
    if counts.size:
        boundary = np.flatnonzero(counts == 1)
        if boundary.size:
            chosen.append(boundary)
    direction = _view_direction(view, axes)
    try:
        adjacency = np.asarray(mesh.face_adjacency)
        adjacency_edges = np.asarray(mesh.face_adjacency_edges)
        if adjacency.size and adjacency_edges.size:
            facing = np.asarray(mesh.face_normals, dtype=float) @ direction
            front = facing < 0
            flip = front[adjacency[:, 0]] != front[adjacency[:, 1]]
            if np.any(flip):
                chosen.append(adjacency_edges[flip])
    except Exception:
        pass
    if not chosen:
        return np.zeros((0, 2, 2), dtype=float)
    edge_index = np.unique(np.concatenate(chosen))
    segments_3d = unique[edge_index]
    points, _depth = _project(np.asarray(mesh.vertices, dtype=float), view, axes)
    return points[segments_3d]


def overlay_outline(
    mesh: trimesh.Trimesh,
    photo: Path,
    destination: Path,
    *,
    view: str,
    axes: dict[str, str],
    photo_scale: float,
    origin: tuple[float, float] | None = None,
    fit: str = "center",
    roi: tuple[float, float, float, float] | None = None,
    seed: tuple[float, float] | None = None,
    exclude: list | None = None,
    angled: bool = False,
) -> dict:
    """Draw the silhouette contour onto a copy of the photo.

    ``photo_scale`` is pixels per millimetre. ``center`` puts the model center
    on the image center. ``auto`` scales and translates that silhouette onto
    the part segmented from the photo. ``origin`` is the image pixel of the
    model's minimum corner (image y grows downward) and overrides fit.
    ``roi`` and ``seed`` pick the part. ``exclude`` drops a coin or ruler.
    The line is the contour of the z-buffer mask, not the facet edges.
    """
    if photo_scale <= 0 or not np.isfinite(photo_scale):
        raise ValueError("photo scale must be a positive number of pixels per millimetre")
    from photopart.overlay import paint_overlay

    points, _depth = _project(np.asarray(mesh.vertices, dtype=float), view, axes)
    return paint_overlay(
        points,
        np.asarray(mesh.faces),
        photo,
        destination,
        destination.with_name("overlay_diff.png"),
        photo_scale=photo_scale,
        origin=origin,
        fit=fit,
        roi=roi,
        seed=seed,
        exclude=exclude,
        angled=angled,
    )


def render_views(
    mesh: trimesh.Trimesh,
    out_dir: Path,
    *,
    grid_mm: float | None = None,
    photo: Path | None = None,
    photo_scale: float | None = None,
    overlay_origin: tuple[float, float] | None = None,
    overlay_fit: str = "center",
    overlay_roi: tuple[float, float, float, float] | None = None,
    overlay_seed: tuple[float, float] | None = None,
    overlay_exclude: list | None = None,
    overlay_angled: bool = False,
    up: str | None = None,
    front_axis: str | None = None,
    pixels: int = 720,
    samples: int | None = None,
    length_unit: str = "millimetres",
    unit_meta: dict | None = None,
    measure: dict | None = None,
) -> dict:
    if photo_scale is not None and photo is None:
        raise ValueError("--photo-scale needs --photo")
    if overlay_origin is not None and photo_scale is None:
        raise ValueError("--overlay-origin needs --photo-scale")
    if overlay_fit not in ("center", "auto"):
        raise ValueError("overlay fit must be center or auto")
    if overlay_fit == "auto" and (photo is None or photo_scale is None):
        raise ValueError("--overlay-fit auto needs --photo and --photo-scale")
    out_dir = absolute_path(out_dir)
    axes = choose_axes(mesh.extents, up=up, front_axis=front_axis)
    preview, info = _preview_mesh(mesh)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    grid_step = None
    for view in _VIEWS:
        path = out_dir / f"{view}.png"
        details = render_view(
            preview,
            view,
            path,
            grid_mm=grid_mm,
            axes=axes,
            length_unit=length_unit,
            pixels=pixels,
            samples=samples,
        )
        if view == "front":
            grid_step = details["grid_step_mm"]
        written.append(str(path))
    contact = out_dir / "contact.png"
    _contact(out_dir, contact)
    written.append(str(contact))
    compare = None
    if photo is not None:
        compare_path = out_dir / "compare_front.png"
        side_by_side(photo, out_dir / "front.png", compare_path)
        compare = str(compare_path)
        written.append(compare)
    overlay = None
    overlay_report: dict = {
        "overlay_fit": None,
        "overlay_iou": None,
        "overlay_iou_label": None,
        "overlay_diff": None,
        "overlay_fit_note": None,
        "overlay_blob": None,
        "overlay_warnings": [],
        "overlay_rotation_deg": 0.0,
        "overlay_mirror": False,
        "overlay_view": "front",
        "overlay_poses": [],
        "overlay_top_poses": [],
        "overlay_roi_expanded": False,
    }
    if photo is not None and photo_scale is not None:
        overlay_path = out_dir / "overlay.png"
        if overlay_fit == "auto" and overlay_origin is None:
            from photopart.overlay import paint_auto_views

            vertices = np.asarray(mesh.vertices, dtype=float)
            faces = np.asarray(mesh.faces)
            view_sets = []
            for view_name in ("front", "side", "top"):
                projected, _depth = _project(vertices, view_name, axes)
                view_sets.append((view_name, projected, faces))
            for degrees, name in ((30.0, "elev30"), (60.0, "elev60")):
                spun = _elevate(vertices, axes, degrees)
                projected, _depth = _project(spun, "front", axes)
                view_sets.append((name, projected, faces))
            overlay_report = paint_auto_views(
                view_sets,
                photo,
                overlay_path,
                overlay_path.with_name("overlay_diff.png"),
                photo_scale=photo_scale,
                roi=overlay_roi,
                seed=overlay_seed,
                exclude=overlay_exclude,
                angled=overlay_angled,
                measure=measure,
            )
            overlay_report = _publish_poses(overlay_report)
        else:
            overlay_report = overlay_outline(
                mesh,
                photo,
                overlay_path,
                view="front",
                axes=axes,
                photo_scale=photo_scale,
                origin=overlay_origin,
                fit=overlay_fit,
                roi=overlay_roi,
                seed=overlay_seed,
                exclude=overlay_exclude,
                angled=overlay_angled,
            )
        overlay = str(overlay_path)
        written.append(overlay)
        if overlay_report.get("overlay_diff"):
            written.append(overlay_report["overlay_diff"])
    manifest = {
        **info,
        "grid_mm": grid_mm,
        "grid_step_mm": grid_step,
        "views": written,
        "compare_front": compare,
        "overlay": overlay,
        "overlay_fit": overlay_report.get("overlay_fit"),
        "overlay_iou": overlay_report.get("overlay_iou"),
        "overlay_iou_label": overlay_report.get("overlay_iou_label"),
        "overlay_diff": overlay_report.get("overlay_diff"),
        "overlay_fit_note": overlay_report.get("overlay_fit_note"),
        "overlay_blob": overlay_report.get("overlay_blob"),
        "overlay_warnings": overlay_report.get("overlay_warnings") or [],
        "overlay_rotation_deg": overlay_report.get("overlay_rotation_deg", 0.0),
        "overlay_mirror": bool(overlay_report.get("overlay_mirror", False)),
        "overlay_view": overlay_report.get("overlay_view") or "front",
        "overlay_poses": overlay_report.get("overlay_poses") or [],
        "overlay_top_poses": (overlay_report.get("overlay_top_poses") or overlay_report.get("overlay_poses") or [])[:3],
        "overlay_roi_expanded": bool(overlay_report.get("overlay_roi_expanded", False)),
        "alignment": overlay_report.get("alignment"),
        "photo_scale_px_per_mm": photo_scale,
        "view_axes": axes,
        "units": length_unit,
        "length_unit": length_unit,
    }
    if unit_meta is not None:
        attach_units(manifest, unit_meta)
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def _parse_pair(text: str, label: str) -> tuple[float, float]:
    parts = text.split(",")
    if len(parts) != 2:
        raise ValueError(f"{label} must be x,y in image pixels")
    try:
        pair = (float(parts[0]), float(parts[1]))
    except ValueError as exc:
        raise ValueError(f"{label} must be x,y in image pixels") from exc
    if not np.isfinite(pair).all():
        raise ValueError(f"{label} must be finite")
    return pair


def _parse_origin(text: str) -> tuple[float, float]:
    return _parse_pair(text, "--overlay-origin")


def _parse_rect(text: str) -> tuple[float, float, float, float]:
    parts = text.split(",")
    if len(parts) != 4:
        raise ValueError("--roi and --exclude-roi must be x,y,w,h in image pixels")
    try:
        rect = (float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]))
    except ValueError as exc:
        raise ValueError("--roi and --exclude-roi must be x,y,w,h in image pixels") from exc
    if not np.isfinite(rect).all() or rect[2] <= 0 or rect[3] <= 0:
        raise ValueError("roi width and height must be positive")
    return rect


def run_render(argv: list[str] | None = None) -> tuple[int, dict]:
    parser = argparse.ArgumentParser(description="Render front, side, top, and iso views.")
    parser.add_argument("mesh")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--photo", help="Reference image. Written beside the front view.")
    parser.add_argument(
        "--photo-scale",
        type=float,
        help="Pixels per millimetre. Draws an outline of the front view on the photo.",
    )
    parser.add_argument(
        "--overlay-origin",
        help="Image pixel x,y of the model's minimum corner. Default: center the model.",
    )
    parser.add_argument(
        "--overlay-fit",
        choices=("center", "auto"),
        default="center",
        help="center keeps the outline on the image center. auto tries front, side, and top at 15° then 1°, plus a mirror, and reports IoU.",
    )
    parser.add_argument("--roi", help="Part region x,y,w,h in image pixels. Limits auto-fit.")
    parser.add_argument("--seed", help="One pixel x,y on the part. auto-fit uses that object.")
    parser.add_argument(
        "--exclude-roi",
        action="append",
        default=[],
        help="Rectangle x,y,w,h to ignore, such as a coin. Repeatable.",
    )
    parser.add_argument(
        "--measure-json",
        help="photo_part_measure JSON. Uses reference_bbox and angled.",
    )
    parser.add_argument(
        "--angled",
        action="store_true",
        help="The photo is not straight-on. The fit still runs and labels IoU guide_only.",
    )
    parser.add_argument("--grid-mm", type=float, help="Draw a square grid of this size, in mm.")
    parser.add_argument("--up", choices=("x", "y", "z"), help="Axis that points up. Default: the longest side.")
    parser.add_argument(
        "--front-axis",
        choices=("x", "y", "z"),
        help="Axis the front camera looks along. Default: the shortest axis that is not up.",
    )
    parser.add_argument("--force", action="store_true", help="Replace files in a directory that is not empty.")
    parser.add_argument("--overwrite", action="store_true", help="Same as --force.")
    parser.add_argument(
        "--final",
        action="store_true",
        help="Deliver render. Uses the best validated name_vN. Refuses when none is fresh.",
    )
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    add_unit_arguments(parser)
    args = parser.parse_args(argv)
    try:
        out_dir = absolute_path(args.out_dir)
    except ValueError as exc:
        return 1, failed(str(exc))
    if out_dir.exists() and any(out_dir.iterdir()) and not (args.force or args.overwrite):
        return 1, failed(f"{out_dir} is not empty. Pass --overwrite.")
    mesh_path = Path(args.mesh).expanduser()
    if not mesh_path.is_file():
        return 1, failed(f"mesh not found: {mesh_path}")
    mesh_path = mesh_path.resolve()
    requested = mesh_path
    best = None
    if args.final:
        from photopart.score import best_validated

        best = best_validated(mesh_path)
        if best is not None:
            mesh_path = Path(best["path"])
            gate = _own_gate(mesh_path)
        else:
            gate = _validation_gate(requested)
    else:
        gate = _validation_gate(mesh_path)
    versioned = _VERSIONED.match(requested.stem) is not None or _VERSIONED.match(gate["target"].stem) is not None
    if not gate["fresh"] and (args.final or versioned):
        target = gate["target"]
        if args.final:
            error = (
                f"{target.name} has no fresh photo_part_validate sidecar. "
                "Validate that file before a final render."
            )
        else:
            error = (
                f"{target.name} has no fresh photo_part_validate sidecar. "
                "Validate that file before rendering a version. unvalidated is true."
            )
        report = {
            "ok": False,
            "needs_validation": True,
            "unvalidated": True,
            "file": str(mesh_path),
            "validation_target": str(target),
            "sha256": gate["stamp"]["sha256"],
            "stale_validation": gate["stamp"]["stale_validation"],
            "validation_ok": gate["stamp"]["validation_ok"],
            "validation_sidecar": gate["stamp"]["validation_sidecar"],
            "error": error,
        }
        return 2, attach_flow(
            report,
            step_render(str(target), stale=gate["stamp"]["stale_validation"], validation_ok=gate["stamp"]["validation_ok"]),
        )
    try:
        loaded = load_mesh(mesh_path, max_bytes=args.max_bytes)
        mesh, meta = prepare_mesh(loaded, args.units, args.scale)
        photo = None
        if args.photo:
            photo = resolve_file(args.photo, max_bytes=args.max_bytes, label="photo")
        origin = None if args.overlay_origin is None else _parse_origin(args.overlay_origin)
        measure_hint = None
        if args.photo and (args.photo_scale is None or args.roi is None or args.seed is None):
            from photopart.measure import load_last_measure
            from photopart.paths import not_a_project

            photo_path = Path(args.photo).expanduser()
            candidates = [photo_path.resolve().parent, out_dir, Path.cwd()]
            candidates = [item for item in candidates if not not_a_project(item)]
            hint = load_last_measure(*candidates)
            if hint:
                if args.photo_scale is None and hint.get("px_per_mm"):
                    args.photo_scale = float(hint["px_per_mm"])
                if args.roi is None and hint.get("roi"):
                    args.roi = _roi_text(hint["roi"])
                if args.seed is None and hint.get("seed"):
                    args.seed = _pair_text(hint["seed"])
                measure_hint = hint
            else:
                measure_hint = None
        roi = None if args.roi is None else _parse_rect(args.roi)
        seed = None if args.seed is None else _parse_pair(args.seed, "--seed")
        exclude = [_parse_rect(item) for item in args.exclude_roi]
        angled = bool(args.angled)
        if args.measure_json:
            from photopart.measure import load_measure_hints

            payload = json.loads(Path(args.measure_json).expanduser().read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("--measure-json must contain an object")
            extra, flagged = load_measure_hints(payload)
            exclude.extend(extra)
            angled = angled or flagged
        manifest = render_views(
            mesh,
            out_dir,
            grid_mm=args.grid_mm,
            photo=photo,
            photo_scale=args.photo_scale,
            overlay_origin=origin,
            overlay_fit=args.overlay_fit,
            overlay_roi=roi,
            overlay_seed=seed,
            overlay_exclude=exclude,
            overlay_angled=angled,
            measure=measure_hint,
            up=args.up,
            front_axis=args.front_axis,
            length_unit=meta["length_unit"],
            unit_meta=meta,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return 1, failed(str(exc))
    stamp = stamp_status(mesh_path)
    manifest["ok"] = True
    manifest["file"] = str(mesh_path)
    manifest["sha256"] = stamp["sha256"]
    manifest["stale_validation"] = stamp["stale_validation"]
    manifest["validation_sidecar"] = stamp["validation_sidecar"]
    manifest["validation_ok"] = stamp["validation_ok"]
    manifest["needs_validation"] = not gate["fresh"]
    manifest["unvalidated"] = not gate["fresh"]
    manifest["validation_target"] = str(gate["target"])
    manifest["final"] = bool(args.final)
    manifest["requested_file"] = str(requested)
    manifest["best_version"] = None if best is None else best["name"]
    if best is not None and Path(best["path"]) != requested:
        manifest["deliverable"] = str(mesh_path)
    _attach_sheet(manifest, mesh, mesh_path, out_dir)
    step = step_render(
        str(mesh_path),
        stale=stamp["stale_validation"],
        validation_ok=stamp["validation_ok"],
    )
    alignment = manifest.get("alignment") or {}
    if isinstance(alignment, dict) and alignment.get("confidence") == "low":
        step = OVERLAY_LOW_STEP
    attach_flow(manifest, step)
    return 0, manifest


def _pair_text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return f"{float(value['x'])},{float(value['y'])}"
    return f"{float(value[0])},{float(value[1])}"


def _roi_text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return f"{float(value['x'])},{float(value['y'])},{float(value['w'])},{float(value['h'])}"
    return ",".join(str(float(item)) for item in value)


_VERSIONED = re.compile(r"^(?P<prefix>.+)_v(?P<n>\d+)$")


def _latest_version(path: Path) -> Path:
    """The highest ``name_vN`` sibling, or ``path`` when it is not versioned."""
    match = _VERSIONED.match(path.stem)
    if not match:
        return path
    prefix = match.group("prefix")
    suffix = path.suffix
    best = path
    best_n = int(match.group("n"))
    pattern = re.compile(rf"^{re.escape(prefix)}_v(\d+){re.escape(suffix)}$")
    try:
        names = list(path.parent.iterdir())
    except OSError:
        return path
    for candidate in names:
        found = pattern.match(candidate.name)
        if found and candidate.is_file() and int(found.group(1)) > best_n:
            best_n = int(found.group(1))
            best = candidate
    return best


def _validation_gate(path: Path) -> dict:
    """Fresh means the latest version has a matching sidecar with ok true."""
    target = _latest_version(path)
    return _own_gate(target)


def _own_gate(path: Path) -> dict:
    stamp = stamp_status(path)
    fresh = stamp["stale_validation"] is False and stamp["validation_ok"] is True
    return {"target": path, "fresh": fresh, "stamp": stamp}


def _previous_mesh(path: Path):
    match = _VERSIONED.match(path.stem)
    if not match:
        return None
    number = int(match.group(2))
    if number <= 1:
        return None
    previous = path.parent / f"{match.group(1)}_v{number - 1}{path.suffix}"
    if not previous.is_file():
        return None
    try:
        loaded = load_mesh(previous)
        mesh, _meta = prepare_mesh(loaded, None, None)
    except (OSError, ValueError):
        return None
    return mesh


def _attach_sheet(manifest: dict, mesh, path: Path, out_dir: Path) -> None:
    from photopart.sheet import render_sheet
    from photopart.stamp import read_sidecar

    rows = None
    side = read_sidecar(path)
    if isinstance(side, dict) and isinstance(side.get("spec"), list):
        rows = side["spec"]
    try:
        sheet = render_sheet(mesh, out_dir / "sheet.png", previous=_previous_mesh(path), rows=rows, pixels=120)
    except (OSError, ValueError):
        return
    manifest.update(sheet)


def main(argv: list[str] | None = None) -> int:
    code, payload = run_render(argv)
    print(json.dumps(payload, indent=2, sort_keys=True))
    if code == 0:
        status("ok")
    elif payload.get("error"):
        status(f"error: {payload['error']}")
    return code
