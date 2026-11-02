"""Build the committed sample part, renders, and catalog images.

The sample is generated from the template. Nothing in it is a photograph of
a real object or a copy of a commercial part.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from photopart.geometry import expected_extents, write_template
from photopart.render import render_views
from photopart.validate import evaluate

ROOT = Path(__file__).resolve().parents[1]


def _font(size: int) -> ImageFont.ImageFont:
    try:
        import matplotlib

        path = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans.ttf"
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    except Exception:
        pass
    return ImageFont.load_default()


def synthetic_reference(path: Path) -> None:
    """A labeled stand-in image on a 2 mm grid. Not a photograph."""
    scale = 8  # pixels per millimetre
    width_mm, height_mm = 70, 90
    margin = 16
    image = Image.new(
        "RGB",
        (width_mm * scale + margin * 2, height_mm * scale + margin * 2),
        "#f4f7f8",
    )
    draw = ImageDraw.Draw(image)
    for i in range(0, width_mm * scale + 1, 2 * scale):
        x = margin + i
        draw.line((x, margin, x, margin + height_mm * scale), fill="#d5e0e6")
    for i in range(0, height_mm * scale + 1, 2 * scale):
        y = margin + i
        draw.line((margin, y, margin + width_mm * scale, y), fill="#d5e0e6")
    # A rough plate so the side-by-side layout has something to sit beside.
    # Image Y grows downward. The plate is narrower at the bottom, with a hook.
    body = [
        (margin + 14 * scale, margin + 78 * scale),
        (margin + 54 * scale, margin + 78 * scale),
        (margin + 62 * scale, margin + 22 * scale),
        (margin + 8 * scale, margin + 22 * scale),
    ]
    hook = [
        (margin + 8 * scale, margin + 22 * scale),
        (margin + 8 * scale, margin + 8 * scale),
        (margin + 24 * scale, margin + 8 * scale),
        (margin + 24 * scale, margin + 14 * scale),
        (margin + 14 * scale, margin + 14 * scale),
        (margin + 14 * scale, margin + 22 * scale),
    ]
    draw.polygon(body, fill="#8aa0ad", outline="#1c2430")
    draw.polygon(hook, fill="#8aa0ad", outline="#1c2430")
    draw.rectangle(
        (margin + 34 * scale, margin + 40 * scale, margin + 50 * scale, margin + 54 * scale),
        fill="#f4f7f8",
        outline="#1c2430",
    )
    draw.text(
        (margin, 4),
        "synthetic reference on a 2 mm grid — not a photograph",
        fill="#1c2430",
        font=_font(18),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG")


def write_banner(iso_png: Path, destination: Path) -> None:
    banner = Image.new("RGB", (1200, 600), "#1c2430")
    draw = ImageDraw.Draw(banner)
    draw.text((64, 150), "photo-to-part", fill="#f4f7f8", font=_font(72))
    draw.text(
        (64, 250),
        "Photos and a few measurements",
        fill="#c5d4de",
        font=_font(32),
    )
    draw.text(
        (64, 300),
        "to a checked, printable mesh.",
        fill="#c5d4de",
        font=_font(32),
    )
    draw.text(
        (64, 430),
        "Local mesh checks. No printer connection.",
        fill="#8aa0ad",
        font=_font(22),
    )
    iso = Image.open(iso_png).convert("RGB")
    iso.thumbnail((520, 520))
    banner.paste(iso, (1200 - iso.width - 48, (600 - iso.height) // 2))
    destination.parent.mkdir(parents=True, exist_ok=True)
    banner.save(destination, format="PNG")


def build_showcase(example_dir: Path, docs_dir: Path | None = None) -> dict:
    written = write_template(example_dir, ascii_stl=True, write_3mf=False)
    mesh = written["mesh"]
    extents = expected_extents(written["params"])
    report = evaluate(mesh, target=extents, tolerance=0.05)
    report_path = example_dir / "report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    photo = example_dir / "synthetic_reference.png"
    synthetic_reference(photo)
    manifest = render_views(mesh, example_dir / "renders", grid_mm=2, photo=photo)
    if docs_dir is not None:
        docs_dir.mkdir(parents=True, exist_ok=True)
        contact = Image.open(example_dir / "renders" / "contact.png")
        contact.save(docs_dir / "screenshot-views.png", format="PNG")
        write_banner(example_dir / "renders" / "iso.png", docs_dir / "catalog-banner.png")
    return {"report": report, "manifest": manifest, "stl": str(written["stl"])}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Regenerate the sample part and catalog images.")
    parser.add_argument("--examples", default=str(ROOT / "examples" / "plate-clip"))
    parser.add_argument("--docs", default=str(ROOT / "docs"))
    args = parser.parse_args(argv)
    result = build_showcase(Path(args.examples), Path(args.docs))
    if not result["report"]["ok"]:
        print(json.dumps(result["report"], indent=2, sort_keys=True))
        return 2
    print(json.dumps({"stl": result["stl"], "ok": True}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
