"""Render the Part studio pane twice with the real view model and the real DOM.

Writes mid-run and finished screenshots. The HTML harness only supplies theme
variables; colors inside the pane come from pane.css.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugin"
DESKTOP = PLUGIN / "desktop"
EXAMPLES = ROOT / "examples" / "plate-clip"
CHROME = os.environ.get("CHROME", "google-chrome")


def main() -> None:
    out_dir = Path(os.environ.get("PANE_SHOT_DIR", "/opt/cursor/artifacts"))
    out_dir.mkdir(parents=True, exist_ok=True)
    docs = ROOT / "docs" / "research"
    docs.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as raw:
        home = Path(raw) / "hermes"
        project = Path(raw) / "plate-clip"
        renders = project / "renders"
        renders.mkdir(parents=True)
        os.environ["HERMES_HOME"] = str(home)
        photo, overlay, front = _images(project, renders)
        stl = project / "plate_v2.stl"
        scad = project / "plate.scad"
        threemf = project / "plate_v2.3mf"
        stl.write_bytes(b"solid plate")
        scad.write_text("cube([51, 72.6, 6]);", encoding="utf-8")
        threemf.write_bytes(b"3mf")
        _seed(project, photo, overlay, front, stl, scad, threemf)
        from photopart.pane import view_state
        from photopart.progress import note_start

        mid_path = project / ".photopart" / "pane.json"
        mid_state = json.loads(mid_path.read_text(encoding="utf-8"))
        note_start("photo_part_render", {"mesh": str(stl), "out_dir": str(project)})
        running = json.loads(mid_path.read_text(encoding="utf-8"))
        _shoot(view_state(running), out_dir / "pane-mid-run.png")
        # Restore the pre-start snapshot, then finish the iteration for the second frame.
        mid_path.write_text(json.dumps(mid_state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        from photopart.progress import note_result

        note_result(
            "photo_part_render",
            {
                "ok": True,
                "final": True,
                "mesh": str(stl),
                "stl": str(stl),
                "scad": str(scad),
                "threemf": str(threemf),
                "out_dir": str(project),
                "image": str(photo),
                "overlay": str(overlay),
                "compare_front": str(front),
                "views": [str(front)],
                "overlay_iou": 0.91,
                "overlay_iou_label": "measured",
                "alignment": {"iou": 0.91, "iou_trusted": True, "segmentation_confidence": "high"},
                "extents_mm": {"x": 51, "y": 72.6, "z": 6},
            },
        )
        finished = json.loads(mid_path.read_text(encoding="utf-8"))
        _shoot(view_state(finished), out_dir / "pane-complete.png")
    for name in ("pane-mid-run.png", "pane-complete.png"):
        target = docs / name
        shutil.copyfile(out_dir / name, target)
        print(out_dir / name)
        print(target)


def _images(project: Path, renders: Path) -> tuple[Path, Path, Path]:
    photo = project / "photo.png"
    source = Image.open(EXAMPLES / "synthetic_reference.png").convert("RGB")
    source.thumbnail((720, 720))
    source.save(photo)
    overlay_image = source.copy()
    draw = ImageDraw.Draw(overlay_image)
    box = (36, 28, overlay_image.width - 40, overlay_image.height - 36)
    draw.rounded_rectangle(box, radius=18, outline=(226, 161, 90), width=4)
    overlay = renders / "overlay.png"
    overlay_image.save(overlay)
    front = renders / "front.png"
    render = Image.open(EXAMPLES / "renders" / "front.png").convert("RGB")
    render.thumbnail((720, 720))
    render.save(front)
    return photo, overlay, front


def _seed(project, photo, overlay, front, stl, scad, threemf) -> None:
    from photopart.progress import note_approval, note_result, note_start

    common = {
        "out_dir": str(project),
        "image": str(photo),
        "part": "plate clip",
        "extents_mm": {"x": 51, "y": 72.6, "z": 6},
    }
    note_result(
        "photo_part_measure",
        {
            **common,
            "ok": True,
            "kind": "coin",
            "coin": "us_quarter",
            "px_per_mm": 5.2,
            "scale_uncertainty_pct": 1.8,
            "part_bbox_mm": {"x": 51, "y": 72.6, "z": 6},
        },
    )
    note_approval(str(project), "Run plate.py in the project", "photo_part_build")
    note_start("photo_part_build", {"cwd": str(project), "script": str(project / "plate.py")})
    note_result(
        "photo_part_build",
        {**common, "ok": True, "cwd": str(project), "stl": str(project / "plate_v1.stl"), "outputs": [str(stl)]},
    )
    (project / "plate_v1.stl").write_bytes(b"solid v1")
    note_result(
        "photo_part_validate",
        {**common, "ok": True, "file": str(project / "plate_v1.stl"), "spec": str(project / "spec.json")},
    )
    note_result(
        "photo_part_render",
        {
            **common,
            "ok": True,
            "mesh": str(project / "plate_v1.stl"),
            "overlay": str(overlay),
            "views": [str(front)],
            "overlay_iou": 0.64,
            "overlay_iou_label": "untrusted",
            "alignment": {"iou": 0.64, "iou_trusted": False, "iou_trust_reason": "overlay fit is low"},
            "warnings": ["Wall 0.70 mm is under the 0.80 mm warning line."],
        },
    )
    note_result(
        "photo_part_template",
        {
            **common,
            "ok": True,
            "stl": str(stl),
            "scad": str(scad),
            "threemf": str(threemf),
            "shape": "plate_clip",
        },
    )


def _shoot(run: dict, dest: Path) -> None:
    css = (DESKTOP / "pane.css").read_text(encoding="utf-8")
    dom = (DESKTOP / "pane-dom.js").read_text(encoding="utf-8")
    model = json.dumps({"backend": "ready", "run": run})
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>
:root {{
  --ui-text-secondary: #f4f0e6;
  --ui-text-tertiary: #b7b1a4;
  --ui-text-quaternary: #7d786e;
  --ui-stroke-secondary: rgba(244, 240, 230, 0.16);
  --ui-accent: #e2a15a;
}}
html, body, #root {{ margin: 0; height: 100%; background: #141311; }}
{css}
</style>
</head>
<body>
<div id="root"></div>
<script>
{dom}
mountPane(document.getElementById("root"), {model}, {{}}, null);
</script>
</body>
</html>
"""
    page = dest.with_suffix(".html")
    page.write_text(html, encoding="utf-8")
    profile = Path(tempfile.mkdtemp(prefix=f"p2p-{dest.stem}-"))
    if dest.exists():
        dest.unlink()
    command = [
        CHROME,
        "--headless=new",
        "--no-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--hide-scrollbars",
        "--force-device-scale-factor=1",
        "--remote-debugging-port=0",
        f"--user-data-dir={profile}",
        "--window-size=720,1100",
        f"--screenshot={dest}",
        page.as_uri(),
    ]
    log_path = dest.with_suffix(".log")
    log_file = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(command, stdout=log_file, stderr=subprocess.STDOUT)
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        if dest.is_file() and dest.stat().st_size > 1000:
            time.sleep(0.5)
            break
        time.sleep(0.2)
    subprocess.run(["pkill", "-9", "-f", f"user-data-dir={profile}"], check=False, capture_output=True)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    log_file.close()
    shutil.rmtree(profile, ignore_errors=True)
    if not dest.is_file() or dest.stat().st_size < 1000:
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-1500:]
        raise SystemExit(f"screenshot missing: {dest}\n{tail}")
    page.unlink(missing_ok=True)
    log_path.unlink(missing_ok=True)
    _crop(dest)


def _crop(dest: Path) -> None:
    """Drop the empty window below the last painted pixel."""
    image = Image.open(dest).convert("RGB")
    background = (20, 19, 17)
    pixels = image.load()
    last = 0
    for y in range(image.height):
        for x in range(image.width):
            pixel = pixels[x, y]
            if any(abs(pixel[channel] - background[channel]) > 14 for channel in range(3)):
                last = y
                break
    bottom = min(image.height, last + 28)
    if bottom < image.height:
        image.crop((0, 0, image.width, bottom)).save(dest)


if __name__ == "__main__":
    main()
