"""Orthographic previews of a mesh for a side-by-side fit check.

Renders are previews. Above a face cap, faces are sampled evenly so a scan
still produces a picture. The picture is not a boolean simplification.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import trimesh
from matplotlib.patches import Polygon as MplPolygon
from PIL import Image, ImageDraw

from photopart.io import DEFAULT_MAX_BYTES, load_mesh, resolve_file

PREVIEW_FACE_CAP = 8000
_VIEWS = ("front", "side", "top", "iso")


def _project(vertices: np.ndarray, view: str) -> tuple[np.ndarray, np.ndarray]:
    """Return 2D points and a depth used only to sort faces.

    The part stands in XY and is thick along Z. Front is the silhouette.
    """
    if view == "front":
        return vertices[:, [0, 1]], vertices[:, 2]
    if view == "side":
        return vertices[:, [2, 1]], vertices[:, 0]
    if view == "top":
        return vertices[:, [0, 2]], -vertices[:, 1]
    if view == "iso":
        xy = np.column_stack(
            (
                vertices[:, 0] * 0.86 - vertices[:, 1] * 0.50,
                vertices[:, 2] + vertices[:, 0] * 0.35 + vertices[:, 1] * 0.40,
            )
        )
        depth = vertices[:, 0] * 0.2 + vertices[:, 1] * 0.3 + vertices[:, 2] * 0.1
        return xy, depth
    raise ValueError(f"unknown view {view}")


def _preview_mesh(mesh: trimesh.Trimesh) -> tuple[trimesh.Trimesh, dict]:
    count = len(mesh.faces)
    info = {
        "source_faces": int(count),
        "preview_faces": int(count),
        "decimated_for_preview": False,
    }
    if count <= PREVIEW_FACE_CAP:
        return mesh, info
    chosen = np.linspace(0, count - 1, PREVIEW_FACE_CAP).astype(int)
    preview = trimesh.Trimesh(
        vertices=mesh.vertices.copy(),
        faces=mesh.faces[chosen].copy(),
        process=False,
    )
    info["preview_faces"] = int(len(preview.faces))
    info["decimated_for_preview"] = True
    return preview, info


def _shade(normals: np.ndarray) -> np.ndarray:
    light = np.array([0.35, -0.45, 0.82], dtype=float)
    light /= np.linalg.norm(light)
    length = np.linalg.norm(normals, axis=1)
    length[length == 0] = 1.0
    unit = np.round(normals / length[:, None], 4)
    lambert = np.clip(unit @ light, 0.0, 1.0)
    tone = 0.28 + 0.72 * lambert
    color = np.column_stack(
        (0.45 + 0.35 * tone, 0.55 + 0.30 * tone, 0.62 + 0.25 * tone)
    )
    return np.clip(color, 0.0, 1.0)


def render_view(mesh: trimesh.Trimesh, view: str, destination: Path, *, grid_mm: float | None) -> None:
    points, depth = _project(np.asarray(mesh.vertices, dtype=float), view)
    faces = np.asarray(mesh.faces)
    normals = np.asarray(mesh.face_normals, dtype=float)
    order = np.argsort(depth[faces].mean(axis=1))
    colors = _shade(normals)
    fig, ax = plt.subplots(figsize=(6.2, 6.2), dpi=120)
    for index in order:
        polygon = points[faces[index]]
        color = colors[index]
        # A same-color stroke covers the hairline matplotlib leaves between triangles.
        ax.add_patch(
            MplPolygon(
                polygon,
                closed=True,
                facecolor=color,
                edgecolor=color,
                linewidth=0.8,
                joinstyle="round",
            )
        )
    mins = points.min(axis=0)
    maxs = points.max(axis=0)
    span = np.maximum(maxs - mins, 1e-6)
    pad = span * 0.08
    ax.set_xlim(mins[0] - pad[0], maxs[0] + pad[0])
    ax.set_ylim(mins[1] - pad[1], maxs[1] + pad[1])
    ax.set_aspect("equal", adjustable="box")
    if grid_mm and grid_mm > 0 and view != "iso":
        ax.set_axisbelow(True)
        start_x = np.floor((mins[0] - pad[0]) / grid_mm) * grid_mm
        start_y = np.floor((mins[1] - pad[1]) / grid_mm) * grid_mm
        ax.set_xticks(np.arange(start_x, maxs[0] + pad[0] + grid_mm, grid_mm), minor=True)
        ax.set_yticks(np.arange(start_y, maxs[1] + pad[1] + grid_mm, grid_mm), minor=True)
        ax.set_xticks(np.arange(np.floor(mins[0] / 10) * 10, maxs[0] + 10, 10))
        ax.set_yticks(np.arange(np.floor(mins[1] / 10) * 10, maxs[1] + 10, 10))
        ax.grid(True, which="minor", color="#d5e0e6", linewidth=0.4)
        ax.grid(True, which="major", color="#b7c6d0", linewidth=0.6)
        ax.tick_params(labelsize=7)
    else:
        ax.set_xticks([])
        ax.set_yticks([])
    ax.set_title(f"{view}  ·  millimetres", fontsize=11, color="#1c2430")
    for spine in ax.spines.values():
        spine.set_color("#d5dde3")
    fig.tight_layout()
    destination.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destination, facecolor="white")
    plt.close(fig)


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
    draw.text((12, 12), "reference", fill="#1c2430")
    draw.text((left_s.width + gap + 12, 12), "model front", fill="#1c2430")
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination, format="PNG")


def render_views(
    mesh: trimesh.Trimesh,
    out_dir: Path,
    *,
    grid_mm: float | None = None,
    photo: Path | None = None,
) -> dict:
    preview, info = _preview_mesh(mesh)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for view in _VIEWS:
        path = out_dir / f"{view}.png"
        render_view(preview, view, path, grid_mm=grid_mm)
        written.append(str(path))
    contact = out_dir / "contact.png"
    fig, axes = plt.subplots(2, 2, figsize=(10, 10), dpi=110)
    for axis, view in zip(axes.ravel(), _VIEWS):
        image = plt.imread(out_dir / f"{view}.png")
        axis.imshow(image)
        axis.set_title(view, fontsize=11)
        axis.axis("off")
    fig.tight_layout()
    fig.savefig(contact, facecolor="white")
    plt.close(fig)
    written.append(str(contact))
    compare = None
    if photo is not None:
        compare_path = out_dir / "compare_front.png"
        side_by_side(photo, out_dir / "front.png", compare_path)
        compare = str(compare_path)
        written.append(compare)
    manifest = {
        **info,
        "grid_mm": grid_mm,
        "views": written,
        "compare_front": compare,
        "units": "millimeters",
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render front, side, top, and iso views.")
    parser.add_argument("mesh")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--photo", help="Reference image placed beside the front view.")
    parser.add_argument("--grid-mm", type=float, help="Draw a square grid of this size, in mm.")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    args = parser.parse_args(argv)
    out_dir = Path(args.out_dir).expanduser().resolve()
    if out_dir.exists() and any(out_dir.iterdir()) and not args.force:
        print(f"error: {out_dir} is not empty. Pass --force.", flush=True)
        return 1
    try:
        mesh = load_mesh(args.mesh, max_bytes=args.max_bytes)
        photo = None
        if args.photo:
            photo = resolve_file(args.photo, max_bytes=args.max_bytes, label="photo")
        manifest = render_views(mesh, out_dir, grid_mm=args.grid_mm, photo=photo)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", flush=True)
        return 1
    print(json.dumps(manifest, indent=2, sort_keys=True))
    print("ok", flush=True)
    return 0
