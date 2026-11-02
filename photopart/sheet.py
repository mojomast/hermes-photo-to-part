"""Eight-view contact sheet. Previous version in red, current in green.

Six orthographic views and two isometric views. A dimension table is drawn
under the pictures and returned as ``dimension_errors``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw

from photopart.render import _font, _frame, _project, _rasterize, _to_pixels, choose_axes

SHEET_VIEWS = ("front", "back", "side", "right", "top", "bottom", "iso", "iso2")


def render_sheet(
    mesh: trimesh.Trimesh,
    destination: Path,
    *,
    previous: trimesh.Trimesh | None = None,
    rows: list[dict] | None = None,
    pixels: int = 160,
) -> dict:
    axes = choose_axes(mesh.extents)
    tiles = []
    for view in SHEET_VIEWS:
        anchor = previous if previous is not None else mesh
        current = _tint(mesh, view, axes, pixels, (30, 150, 70), align_to=anchor)
        if previous is not None:
            older = _tint(previous, view, axes, pixels, (190, 40, 40), align_to=mesh)
            current = _over(older, current)
        tiles.append(current)
    errors = dimension_rows(mesh, previous, rows)
    sheet = _layout(tiles, errors, pixels)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination, format="PNG")
    return {
        "sheet": str(destination.resolve()),
        "sheet_views": list(SHEET_VIEWS),
        "dimension_errors": errors,
    }


def dimension_rows(mesh, previous, rows: list[dict] | None) -> list[dict]:
    found = []
    extents = np.asarray(mesh.extents, dtype=float)
    names = ("x", "y", "z")
    if rows:
        for row in rows:
            if not isinstance(row, dict) or row.get("name") not in names:
                continue
            actual = float(row.get("actual") if row.get("actual") is not None else extents[names.index(row["name"])])
            value = float(row["value"])
            found.append(
                {
                    "name": row["name"],
                    "value": value,
                    "actual": round(actual, 4),
                    "error_mm": round(actual - value, 4),
                    "ok": bool(row.get("ok")),
                }
            )
    elif previous is not None:
        other = np.asarray(previous.extents, dtype=float)
        for index, name in enumerate(names):
            delta = float(extents[index] - other[index])
            found.append(
                {
                    "name": name,
                    "value": round(float(other[index]), 4),
                    "actual": round(float(extents[index]), 4),
                    "error_mm": round(delta, 4),
                    "ok": abs(delta) <= 0.3,
                }
            )
    return found


def _tint(mesh, view, axes, pixels, rgb, align_to=None) -> np.ndarray:
    source = align_to if align_to is not None else mesh
    vertices = np.asarray(mesh.vertices, dtype=float)
    points, depth = _project(vertices, view, axes)
    base_points, _base_depth = _project(np.asarray(source.vertices, dtype=float), view, axes)
    mins, maxs = _frame(np.vstack([points, base_points]))
    faces = np.asarray(mesh.faces)
    colors = np.tile(np.array(rgb, dtype=np.uint8), (len(faces), 1))
    pix = _to_pixels(points, mins, maxs, pixels, pixels)
    return _rasterize(pix, depth, faces, colors, pixels, pixels)


def _over(older: np.ndarray, current: np.ndarray) -> np.ndarray:
    image = np.full_like(current, 255)
    old_fg = np.any(older < 250, axis=2)
    new_fg = np.any(current < 250, axis=2)
    image[old_fg] = older[old_fg]
    image[new_fg] = current[new_fg]
    return image


def _layout(tiles: list[np.ndarray], errors: list[dict], pixels: int) -> Image.Image:
    cols = 4
    rows = 2
    label = 18
    gap = 6
    table = 16 + 14 * max(1, len(errors))
    width = cols * pixels + (cols + 1) * gap
    height = rows * (pixels + label) + (rows + 1) * gap + table
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)
    font = _font(12)
    for index, (name, tile) in enumerate(zip(("front", "back", "side", "right", "top", "bottom", "iso", "iso2"), tiles)):
        column, row = index % cols, index // cols
        x = gap + column * (pixels + gap)
        y = gap + row * (pixels + label + gap)
        draw.text((x, y), name, fill=(28, 36, 48), font=font)
        canvas.paste(Image.fromarray(tile, mode="RGB"), (x, y + label))
    y = gap + rows * (pixels + label + gap)
    if not errors:
        draw.text((gap, y), "no dimension delta", fill=(28, 36, 48), font=font)
    for error in errors:
        draw.text(
            (gap, y),
            f"{error['name']}: actual {error['actual']} target {error['value']} err {error['error_mm']} mm",
            fill=(20, 90, 40) if error.get("ok") else (160, 30, 30),
            font=font,
        )
        y += 14
    return canvas
