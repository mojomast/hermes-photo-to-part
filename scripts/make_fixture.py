"""Write the CC0 washer photo used by the real-photo overlay eval.

The image is generated here. It is not a third-party photograph. Run from the
repository root:

    python scripts/make_fixture.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.meshes import washer_mesh  # noqa: E402
from photopart.overlay import raster_model  # noqa: E402
from photopart.render import _project, choose_axes  # noqa: E402

OUT = ROOT / "evals" / "fixtures"
PX_PER_MM = 4.0
ANGLE_DEG = 18.0
COIN_MM = 23.25


def main() -> None:
    mesh = washer_mesh()
    axes = choose_axes(mesh.extents)
    points, _depth = _project(np.asarray(mesh.vertices, dtype=float), "front", axes)
    mask, _minimum, _maximum = raster_model(points, np.asarray(mesh.faces), PX_PER_MM)
    sprite = Image.fromarray(np.where(mask, np.uint8(255), np.uint8(0)), mode="L")
    turned = sprite.rotate(ANGLE_DEG, resample=Image.Resampling.NEAREST, expand=True, fillcolor=0)
    turned_mask = np.asarray(turned) > 127
    pad = 36
    coin_d = int(round(COIN_MM * PX_PER_MM))
    height = turned_mask.shape[0] + pad * 2
    width = turned_mask.shape[1] + pad * 2 + coin_d + 16
    canvas = _wood(height, width)
    y0, x0 = pad, pad
    _paint_metal(canvas, turned_mask, y0, x0)
    coin_cx = width - pad - coin_d // 2
    coin_cy = height // 2
    _paint_coin(canvas, coin_cx, coin_cy, coin_d / 2.0)
    image = Image.fromarray(canvas, mode="RGB").filter(ImageFilter.GaussianBlur(radius=0.6))
    truth = np.zeros((height, width), dtype=np.uint8)
    truth[y0 : y0 + turned_mask.shape[0], x0 : x0 + turned_mask.shape[1]] = np.where(turned_mask, np.uint8(255), np.uint8(0))
    OUT.mkdir(parents=True, exist_ok=True)
    photo = OUT / "washer_photo.jpg"
    image.save(photo, format="JPEG", quality=80, optimize=True)
    Image.fromarray(truth, mode="L").save(OUT / "washer_mask.png", format="PNG", optimize=True)
    payload = {
        "license": "CC0-1.0",
        "note": "Self-made synthetic photo of a washer and a coin disc. No third-party bytes.",
        "px_per_mm": PX_PER_MM,
        "angle_deg": ANGLE_DEG,
        "up": axes["up"],
        "front_axis": axes["front_axis"],
        "offset_xy": [x0, y0],
        "coin_mm": COIN_MM,
        "coin_diameter_px": coin_d,
        "coin_center_px": [coin_cx, coin_cy],
        "coin_points": [[coin_cx - coin_d / 2.0, coin_cy], [coin_cx + coin_d / 2.0, coin_cy]],
        "part_roi": [8, 8, x0 + turned_mask.shape[1] + 20, height - 16],
        "photo": "washer_photo.jpg",
        "mask": "washer_mask.png",
    }
    (OUT / "fixture.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {photo} ({photo.stat().st_size} bytes)")


def _wood(height: int, width: int) -> np.ndarray:
    rng = np.random.default_rng(18)
    y = np.linspace(0.0, 1.0, height)[:, None]
    grain = 18.0 * np.sin((y * 9.0 + rng.normal(0, 0.01, size=(height, 1))) * np.pi)
    base = np.array([92.0, 64.0, 38.0], dtype=float)
    canvas = base + grain[:, :, None] + rng.normal(0.0, 6.0, size=(height, width, 3))
    return np.clip(canvas, 0, 255).astype(np.uint8)


def _paint_metal(canvas: np.ndarray, mask: np.ndarray, y0: int, x0: int) -> None:
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return
    shade = 150.0 + (xs.astype(float) - xs.min()) / max(1.0, float(xs.max() - xs.min())) * 40.0
    color = np.stack([shade, shade + 4.0, shade + 8.0], axis=1)
    canvas[ys + y0, xs + x0] = np.clip(color, 0, 255).astype(np.uint8)


def _paint_coin(canvas: np.ndarray, cx: float, cy: float, radius: float) -> None:
    height, width = canvas.shape[:2]
    yy, xx = np.mgrid[0:height, 0:width]
    disk = (xx - cx) ** 2 + (yy - cy) ** 2 <= radius ** 2
    canvas[disk] = (168, 138, 64)


if __name__ == "__main__":
    main()
