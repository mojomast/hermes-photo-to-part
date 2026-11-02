"""v0.1.5 part B: spur gear, spiral scroll, and overlay pose for flat parts."""

from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

from photopart.features import spiral_centerline, spiral_scroll, spur_gear, strap_hinge
from photopart.overlay import raster_model, search_alignment
from photopart.parts import build_shape
from photopart.render import choose_axes, render_views
from photopart.tools import template_tool


def _radii(mesh: trimesh.Trimesh) -> np.ndarray:
    vertices = np.asarray(mesh.vertices, dtype=float)
    return np.hypot(vertices[:, 0], vertices[:, 1])


def _one_shell(test: unittest.TestCase, mesh: trimesh.Trimesh, label: str) -> None:
    test.assertTrue(mesh.is_watertight, label)
    test.assertGreater(float(mesh.volume), 0.0, label)
    test.assertEqual(len(mesh.split(only_watertight=False)), 1, label)


def _tooth_count(mesh: trimesh.Trimesh) -> int:
    """Dominant angular frequency of the outer silhouette."""
    radii = _radii(mesh)
    scale = 110.0 / float(radii.max())
    points = np.asarray(mesh.vertices[:, :2], dtype=float)
    mask, minimum, maximum = raster_model(points, np.asarray(mesh.faces), scale)
    ys, xs = np.nonzero(mask)
    x = minimum[0] + xs / scale
    y = maximum[1] - ys / scale
    angle = np.arctan2(y, x) % (2.0 * math.pi)
    radius = np.hypot(x, y)
    bins = 720
    hist = np.zeros(bins)
    index = (angle / (2.0 * math.pi) * bins).astype(int) % bins
    for bin_index, value in zip(index, radius):
        if value > hist[bin_index]:
            hist[bin_index] = value
    known = np.flatnonzero(hist > 0)
    filled = np.interp(np.arange(bins), known, hist[known], period=bins)
    kernel = np.ones(5) / 5.0
    smoothed = np.convolve(np.r_[filled[-2:], filled, filled[:2]], kernel, mode="valid")
    spectrum = np.abs(np.fft.rfft(smoothed - smoothed.mean()))
    low, high = 6, min(140, len(spectrum) - 1)
    return low + int(np.argmax(spectrum[low : high + 1]))


def _hole_extents(mesh: trimesh.Trimesh, scale: float = 8.0) -> tuple[float, float]:
    points = np.asarray(mesh.vertices[:, :2], dtype=float)
    mask, minimum, maximum = raster_model(points, np.asarray(mesh.faces), scale)
    background = ~mask
    height, width = mask.shape
    seen = np.zeros_like(mask)
    stack = [(0, x) for x in range(width)] + [(height - 1, x) for x in range(width)]
    stack += [(y, 0) for y in range(height)] + [(y, width - 1) for y in range(height)]
    while stack:
        y, x = stack.pop()
        if y < 0 or x < 0 or y >= height or x >= width or seen[y, x] or not background[y, x]:
            continue
        seen[y, x] = True
        stack.extend(((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)))
    hole = background & ~seen
    ys, _xs = np.nonzero(hole)
    y = maximum[1] - ys / scale
    return float(y.min()), float(y.max())


def _angle_distance(found: float, target: float) -> float:
    return abs((found - target + 180.0) % 360.0 - 180.0)


def _silhouette_photo(mesh: trimesh.Trimesh, view: str, axes: dict, photo_scale: float, angle_deg: float) -> Image.Image:
    from photopart.render import _project

    points, _depth = _project(np.asarray(mesh.vertices, dtype=float), view, axes)
    mask, _minimum, _maximum = raster_model(points, np.asarray(mesh.faces), photo_scale)
    height, width = mask.shape
    canvas = np.full((height + 48, width + 48, 3), 255, np.uint8)
    ys, xs = np.nonzero(mask)
    canvas[ys + 24, xs + 24] = (20, 24, 28)
    image = Image.fromarray(canvas, mode="RGB")
    if angle_deg:
        image = image.rotate(
            angle_deg,
            resample=Image.Resampling.NEAREST,
            expand=True,
            fillcolor=(255, 255, 255),
        )
    return image


class SpurGearTests(unittest.TestCase):
    def test_diameters_tooth_count_and_bore_options(self):
        module = 1.25
        teeth = 16
        gear = spur_gear(module=module, teeth=teeth, pressure_angle=20, face_width=5)
        _one_shell(self, gear, "plain")
        radii = _radii(gear)
        self.assertAlmostEqual(float(radii.max()) * 2.0, module * (teeth + 2), delta=0.08)
        self.assertAlmostEqual(float(radii.min()) * 2.0, module * (teeth - 2.5), delta=0.08)
        self.assertAlmostEqual(float(gear.extents[2]), 5.0, delta=0.05)
        self.assertEqual(_tooth_count(gear), teeth)
        coarser = spur_gear(module=1.0, teeth=25, pressure_angle=20, face_width=4)
        self.assertEqual(_tooth_count(coarser), 25)
        shallow = spur_gear(module=module, teeth=teeth, pressure_angle=14.5, face_width=5)
        steep = spur_gear(module=module, teeth=teeth, pressure_angle=25, face_width=5)
        self.assertGreater(abs(float(shallow.volume) - float(steep.volume)), 1.0)

        bored = spur_gear(module=2.0, teeth=18, face_width=5, bore=8)
        keyed = spur_gear(module=2.0, teeth=18, face_width=5, bore=8, keyway_width=2.5, keyway_depth=1.4)
        flat = spur_gear(module=2.0, teeth=18, face_width=5, bore=8, d_flat=6.5)
        for mesh, label in ((bored, "bore"), (keyed, "keyway"), (flat, "d-flat")):
            _one_shell(self, mesh, label)
        self.assertLess(float(keyed.volume), float(bored.volume))
        self.assertGreater(float(flat.volume), float(bored.volume))
        round_low, round_high = _hole_extents(bored)
        flat_low, flat_high = _hole_extents(flat)
        key_low, key_high = _hole_extents(keyed)
        self.assertAlmostEqual(round_high, 4.0, delta=0.35)
        self.assertAlmostEqual(round_low, -4.0, delta=0.35)
        self.assertAlmostEqual(flat_high, 6.5 - 4.0, delta=0.4)
        self.assertAlmostEqual(flat_low, -4.0, delta=0.4)
        self.assertGreater(key_high, 5.0)
        hub = spur_gear(
            module=1.0,
            teeth=16,
            face_width=5,
            bore=5,
            hub_diameter=10,
            hub_length=9,
        )
        _one_shell(self, hub, "hub")
        self.assertAlmostEqual(float(hub.extents[2]), 9.0, delta=0.08)
        self.assertLess(float(hub.bounds[0, 2]), -0.5)
        with self.assertRaises(ValueError):
            spur_gear(module=2.0, teeth=18, face_width=5, bore=8, keyway_width=2.5, keyway_depth=1.0, d_flat=6.5)

    def test_template_shape_records_the_standard_diameters(self):
        mesh, doc = build_shape(
            "spur_gear",
            {"module_mm": 1.5, "teeth": 12, "pressure_angle_deg": 20, "face_width_mm": 4, "bore_diameter_mm": 5},
        )
        _one_shell(self, mesh, "template")
        self.assertEqual(doc["shells"], 1)
        self.assertAlmostEqual(doc["parameters"]["outer_diameter_mm"], 1.5 * 14, delta=1e-6)
        self.assertAlmostEqual(doc["parameters"]["root_diameter_mm"], 1.5 * (12 - 2.5), delta=1e-6)
        with tempfile.TemporaryDirectory() as tmp:
            summary = json.loads(
                template_tool(
                    {
                        "out_dir": str(Path(tmp) / "gear"),
                        "shape": "spur_gear",
                        "no_3mf": True,
                        "params": {"module_mm": 1.0, "teeth": 14, "face_width_mm": 4},
                    }
                )
            )
        self.assertTrue(summary["ok"], summary)
        self.assertEqual(summary["shape"], "spur_gear")
        self.assertEqual(summary["shells"], 1)
        self.assertTrue(summary["watertight"])


class SpiralScrollTests(unittest.TestCase):
    def test_archimedean_and_log_strips_and_the_strap(self):
        for kind in ("archimedean", "log"):
            frame = spiral_centerline(width=6, turns=1.5, end_radius=32, kind=kind)
            mesh = spiral_scroll(width=6, thickness=3, turns=1.5, end_radius=32, kind=kind)
            _one_shell(self, mesh, kind)
            self.assertAlmostEqual(float(mesh.extents[2]), 3.0, delta=0.05)
            center = np.array(frame["center"])
            points = frame["points"]
            self.assertAlmostEqual(float(np.linalg.norm(center)), 32.0, delta=0.05)
            vectors = points - center
            angle = np.unwrap(np.arctan2(vectors[:, 1], vectors[:, 0]))
            self.assertAlmostEqual(abs(float(angle[-1] - angle[0])) / (2.0 * math.pi), 1.5, delta=0.04)
            outer = np.hypot(mesh.vertices[:, 0] - center[0], mesh.vertices[:, 1] - center[1])
            self.assertLess(float(outer.max()), 32.0 + 6.0 / 2.0 + 0.8)
            self.assertGreater(float(outer.max()), 32.0 + 1.0)
        arch = spiral_centerline(width=6, turns=1.5, end_radius=32, kind="archimedean")
        log = spiral_centerline(width=6, turns=1.5, end_radius=32, kind="log")
        self.assertGreater(abs(arch["inner_radius"] - log["inner_radius"]), 0.2)
        attached = spiral_scroll(width=6, thickness=3, turns=1.25, end_radius=20, strap_length=40)
        _one_shell(self, attached, "strap")
        self.assertGreater(float(attached.extents[0]), 40.0)
        hinge = strap_hinge(length=80, width=8, thickness=3, turns=1.25, end_radius=16, ends=2)
        _one_shell(self, hinge, "hinge")
        self.assertGreater(float(hinge.extents[0]), 80.0)
        self.assertGreater(float(hinge.extents[1]), 8.0)
        self.assertAlmostEqual(float(hinge.extents[2]), 3.0, delta=0.05)
        single = strap_hinge(length=60, width=8, thickness=3, turns=1.0, end_radius=14, kind="log", ends=1)
        _one_shell(self, single, "one end")
        scroll, scroll_doc = build_shape("scroll", {"spiral": "log", "turns": 1.25, "end_radius_mm": 22, "width_mm": 5})
        _one_shell(self, scroll, "scroll shape")
        self.assertEqual(scroll_doc["parameters"]["spiral"], "log")
        strap, strap_doc = build_shape("strap_hinge")
        _one_shell(self, strap, "strap shape")
        self.assertEqual(strap_doc["shells"], 1)
        self.assertEqual(strap_doc["parameters"]["ends"], 2)
        with self.assertRaises(ValueError):
            spiral_scroll(width=8, thickness=3, turns=3, end_radius=12)


class OverlayFlatTests(unittest.TestCase):
    def test_fine_rotation_is_about_one_degree(self):
        photo = np.zeros((120, 120), dtype=bool)
        photo[30:90, 46:74] = True
        angle = 7.0
        ys, xs = np.nonzero(photo)
        theta = math.radians(angle)
        cosine, sine = math.cos(theta), math.sin(theta)
        cx = (photo.shape[1] - 1) / 2.0
        cy = (photo.shape[0] - 1) / 2.0
        dx = xs - cx
        dy = ys - cy
        rotated = np.zeros_like(photo)
        px = np.rint(cx + cosine * dx - sine * dy).astype(int)
        py = np.rint(cy + sine * dx + cosine * dy).astype(int)
        keep = (px >= 0) & (py >= 0) & (px < photo.shape[1]) & (py < photo.shape[0])
        rotated[py[keep], px[keep]] = True
        found = search_alignment(photo, rotated)
        self.assertLess(_angle_distance(found["rotation_deg"], angle), 1.6, found["rotation_deg"])
        self.assertGreater(found["iou"], 0.7)

    def test_l_bracket_at_45_degrees_uses_the_top_view(self):
        bracket, _doc = build_shape(
            "l_bracket",
            {"length_mm": 50, "width_mm": 18, "height_mm": 36, "thickness_mm": 4, "hole_diameter_mm": 4},
        )
        axes = choose_axes(bracket.extents, up="y")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            photo = root / "l.png"
            _silhouette_photo(bracket, "top", axes, 3.0, 45).save(photo)
            manifest = render_views(
                bracket,
                root / "views",
                photo=photo,
                photo_scale=3.0,
                overlay_fit="auto",
                overlay_angled=True,
                up="y",
                pixels=48,
                samples=1,
            )
        self.assertEqual(manifest["overlay_view"], "top")
        self.assertEqual(manifest["overlay_iou_label"], "guide_only")
        self.assertIsNotNone(manifest["overlay_iou"])
        self.assertGreater(manifest["overlay_iou"], 0.7)
        distance = min(
            _angle_distance(manifest["overlay_rotation_deg"], 45),
            _angle_distance(manifest["overlay_rotation_deg"], 315),
        )
        self.assertLess(distance, 2.5, manifest["overlay_rotation_deg"])
        self.assertTrue(any("angled" in item.lower() for item in manifest["overlay_warnings"]))
        self.assertTrue(any("guide_only" in item for item in manifest["overlay_warnings"]))
        self.assertEqual(len(manifest["overlay_poses"]), 3)
        self.assertEqual(manifest["overlay_poses"][0]["view"], "top")
        self.assertEqual({row["view"] for row in manifest["overlay_poses"]}, {"front", "side", "top"})
        self.assertFalse(manifest["overlay_roi_expanded"])

    def test_gear_overlay_recovers_rotation_and_expands_a_cropping_roi(self):
        gear = spur_gear(module=1.0, teeth=16, face_width=4)
        axes = choose_axes(gear.extents)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            photo_path = root / "gear.png"
            turned = _silhouette_photo(gear, "front", axes, 4.0, 20)
            turned.save(photo_path)
            manifest = render_views(
                gear,
                root / "turned",
                photo=photo_path,
                photo_scale=4.0,
                overlay_fit="auto",
                pixels=64,
                samples=1,
            )
            self.assertEqual(manifest["overlay_view"], "front")
            self.assertEqual(manifest["overlay_iou_label"], "measured")
            self.assertGreater(manifest["overlay_iou"], 0.45)
            pitch = 360.0 / 16.0
            found = float(manifest["overlay_rotation_deg"])
            distance = min(
                _angle_distance(found, sign * 20.0 + step * pitch)
                for sign in (1.0, -1.0)
                for step in range(-16, 17)
            )
            self.assertLess(distance, 2.0, manifest["overlay_rotation_deg"])
            straight = _silhouette_photo(gear, "front", axes, 4.0, 0)
            pixels = np.asarray(straight)
            dark = np.where(pixels[:, :, 0] < 128)
            y0, y1 = int(dark[0].min()), int(dark[0].max())
            x0, x1 = int(dark[1].min()), int(dark[1].max())
            cut = x0 + int(0.55 * (x1 - x0))
            roi = (x0 - 4, y0 - 4, cut - (x0 - 4), (y1 - y0) + 8)
            straight.save(root / "straight.png")
            cropped = render_views(
                gear,
                root / "cropped",
                photo=root / "straight.png",
                photo_scale=4.0,
                overlay_fit="auto",
                overlay_roi=roi,
                pixels=64,
                samples=1,
            )
        self.assertTrue(cropped["overlay_roi_expanded"])
        self.assertTrue(any("cropped" in item.lower() for item in cropped["overlay_warnings"]))
        self.assertGreater(cropped["overlay_iou"], 0.5)
        self.assertEqual(cropped["overlay_view"], "front")


if __name__ == "__main__":
    unittest.main()
