"""v0.1.17: honest overlay trust, photo context, and closed caps to size."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

from evals.meshes import blind_tap
from photopart.io import load_mesh
from photopart.measure import measure
from photopart.overlay import _alignment
from photopart.parts import _as_mesh, _cylinder_z, _difference, build_shape, write_shape
from photopart.spec import _points_inside, apply_spec, openings
from photopart.tools import render_tool, validate_tool


class OverlayTrustTests(unittest.TestCase):
    def test_good_segmentation_cannot_make_a_misplaced_overlay_trusted(self):
        foreground = np.zeros((128, 128), dtype=bool)
        foreground[20:60, 20:60] = True
        placed = np.zeros_like(foreground)
        placed[75:115, 75:115] = True
        image = np.full((128, 128, 3), 230, dtype=np.uint8)
        image[foreground] = 30
        gate = {"segmentation_confidence": "high", "stability": 1.0, "reason": "stable mask"}
        with patch("photopart.overlay._segmentation_gate", return_value=gate):
            bad = _alignment(image, placed, foreground, None, None, None, 4.0)
            good = _alignment(image, foreground, foreground, None, None, None, 4.0)
        self.assertEqual(bad["iou"], 0.0)
        self.assertEqual(bad["overall_confidence"], "low")
        self.assertFalse(bad["iou_trusted"])
        self.assertIn("fit", bad["iou_trust_reason"])
        self.assertTrue(good["iou_trusted"])
        self.assertIsNone(good["iou_trust_reason"])
        gate["segmentation_confidence"] = "low"
        gate["reason"] = "unstable foreground"
        with patch("photopart.overlay._segmentation_gate", return_value=gate):
            uncertain = _alignment(image, foreground, foreground, None, None, None, 4.0)
        self.assertEqual(uncertain["iou"], 1.0)
        self.assertFalse(uncertain["iou_trusted"])
        self.assertIn("unstable foreground", uncertain["iou_trust_reason"])


class CapTests(unittest.TestCase):
    def test_cap_matches_user_envelope_and_has_a_closed_top(self):
        params = {"diameter_mm": 27.4, "pitch_mm": 2.7, "length_mm": 17,
                  "outer_diameter_mm": 33, "knurl_count": 60, "top_thickness_mm": 1.2}
        with tempfile.TemporaryDirectory() as tmp:
            output = write_shape(Path(tmp), "bottle_cap", params, write_3mf=False)
            mesh = load_mesh(output["stl"])
            self.assertTrue(mesh.is_watertight)
            self.assertEqual(len(mesh.split()), 1)
            np.testing.assert_allclose(mesh.extents, [33, 33, 17], atol=0.05)
            np.testing.assert_allclose(output["expected_extents_mm"], [33, 33, 17], atol=0.05)
            # Test interior material, not the surface: the floor is at z=15.8.
            occupied = _points_inside(mesh, np.array([[0.3, 0.2, 0.3], [0.3, 0.2, 15.7],
                                                      [0.3, 0.2, 15.9], [0.3, 0.2, 16.9]]), 2)
            self.assertEqual(occupied.tolist(), [False, False, True, True])
            # Knurl roots must not intrude into the thread's clear minor bore.
            angles = np.arange(60) * (2.0 * np.pi / 60)
            interior = np.column_stack([12.0 * np.cos(angles), 12.0 * np.sin(angles), np.full(60, 8.0)])
            self.assertFalse(np.any(_points_inside(mesh, interior, 2)))
            found = openings(mesh)
            self.assertEqual(found["bores"], [])
            self.assertEqual(len(found["cavities"]), 1)
            self.assertFalse(found["cavities"][0]["through"])
            failures, rows = apply_spec(mesh, spec={"x": 33, "y": 33, "z": 17, "hole_count": 0})
            self.assertEqual(failures, [])
            hole = next(row for row in rows if row["name"] == "hole_count")
            self.assertIn("cavity", hole["cavity_note"])

    def test_invalid_cap_floor_and_insufficient_thread_wall_are_rejected(self):
        for params in ({"top_thickness_mm": 8}, {"top_thickness_mm": 0},
                       {"diameter_mm": 25.8, "outer_diameter_mm": 26}):
            with self.subTest(params=params), self.assertRaises(ValueError):
                build_shape("bottle_cap", params)

    def test_broad_through_hole_and_small_blind_tap_remain_bores(self):
        body = _cylinder_z(16.5, 17, 0, 0, 0, segments=64)
        cutter = _cylinder_z(13.7, 19, 0, 0, -1, segments=64)
        for mesh, through in ((_as_mesh(_difference(body, [cutter])), True), (blind_tap(), False)):
            with self.subTest(through=through):
                found = openings(mesh)
                self.assertEqual(len(found["bores"]), 1)
                self.assertEqual(found["bores"][0]["through"], through)
                self.assertEqual(found["cavities"], [])

    def test_broad_blind_bore_in_thick_stock_is_not_a_cap_cavity(self):
        body = _cylinder_z(8, 12, 0, 0, 0, segments=64)
        cutter = _cylinder_z(6, 9, 0, 0, 4, segments=64)
        found = openings(_as_mesh(_difference(body, [cutter])))
        self.assertEqual(len(found["bores"]), 1)
        self.assertFalse(found["bores"][0]["through"])
        self.assertEqual(found["cavities"], [])


class PhotoContextTests(unittest.TestCase):
    def test_user_dimension_keeps_the_part_in_the_overlay_and_render_reuses_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            photo = project / "part.png"
            image = Image.new("RGB", (128, 128), "white")
            ImageDraw.Draw(image).rectangle((44, 24, 83, 103), fill="black")
            image.save(photo)
            report = measure({"image": str(photo), "diameter_mm": 10, "points": [[44, 64], [84, 64]],
                              "reference_is_part": True, "roi": [32, 12, 64, 104], "seed": [64, 64],
                              "out_dir": str(project)})
            self.assertAlmostEqual(report["px_per_mm"], 4.0)
            self.assertIsNone(report["reference_bbox"])
            self.assertTrue(report["reference_is_part"])
            output = write_shape(project, "plate", {"height_mm": 20, "width_mm": 10, "thickness_mm": 2, "holes": []},
                                 write_3mf=False)
            checked = json.loads(validate_tool({"mesh": str(output["stl"]), "render": False,
                                                "spec": {"x": 10, "y": 20, "z": 2, "shells": 1}}))
            self.assertTrue(checked["ok"], checked)
            # Neither cwd nor out_dir is the project. The mesh identifies its measurement.
            rendered = json.loads(render_tool({"mesh": str(output["stl"]), "out_dir": str(project / "renders"),
                                               "overlay_fit": "auto", "response_format": "detailed"}))
            self.assertTrue(rendered["ok"], rendered)
            self.assertTrue(Path(rendered["overlay"]).is_file())
            self.assertGreater(rendered["alignment"]["iou"], 0.7)
            self.assertEqual(rendered["photo_scale_source"], "user_part_dimension")
            self.assertEqual(rendered["overlay_iou_label"], "guide_only")
            other = project / "other.png"
            Image.new("RGB", (128, 128), "white").save(other)
            unrelated = json.loads(render_tool({"mesh": str(output["stl"]), "out_dir": str(project / "other-renders"),
                                                "photo": str(other), "overlay_fit": "auto"}))
            self.assertTrue(unrelated["ok"], unrelated)
            self.assertIsNone(unrelated["overlay"])
            self.assertEqual(unrelated["overlay_status"], "missing_scale")

    def test_missing_photo_scale_is_explicit_and_has_an_actionable_next_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            photo = project / "part.png"
            Image.new("RGB", (48, 48), "white").save(photo)
            output = write_shape(project, "plate", write_3mf=False)
            checked = json.loads(validate_tool({"mesh": str(output["stl"]), "render": True, "photo": str(photo),
                                                "spec": {"x": 40, "y": 30, "z": 4, "shells": 1}}))
            self.assertTrue(checked["ok"], checked)
            rendered = checked["render"]
            self.assertIsNone(rendered["overlay"])
            self.assertEqual(rendered["overlay_status"], "missing_scale")
            self.assertIn("photo_part_measure", rendered["next_step"])


if __name__ == "__main__":
    unittest.main()
