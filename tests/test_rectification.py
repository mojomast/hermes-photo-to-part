"""Metric rectification stays consistent across files, landmarks and overlays."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from photopart.measure import load_last_measure, load_measure_hints, measure
from photopart.overlay import _alignment, _prepare_photo, _zero_rect, paint_auto_views, paint_overlay
from photopart.rectify import map_points, plan, warp_image
from photopart.parts import write_shape
from photopart.tools import render_tool, validate_tool


class RectificationTests(unittest.TestCase):
    def scene(self, root):
        image = np.full((180, 220, 3), 235, dtype=np.uint8)
        image[70:110, 80:130] = 25
        image[30:65, 150:185] = 40
        photo = root / "photo.png"
        Image.fromarray(image).save(photo)
        return photo, image

    def calibrate(self, photo, **extra):
        return measure({"image": str(photo), "quad": [[20, 20], [120, 20], [120, 120], [20, 120]],
                        "width_mm": 20, "height_mm": 10, "roi": [60, 20, 135, 110],
                        "seed": [100, 90], **extra})

    def test_saved_map_and_measurements_have_one_isotropic_scale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            photo, image = self.scene(root)
            report = self.calibrate(photo, measurements=[
                {"name": "width", "points": [[80, 90], [130, 90]]},
                {"name": "height", "points": [[100, 70], [100, 110]]},
            ], part_seed=[100, 90], part_roi={"x": 65, "y": 55, "w": 80, "h": 70}, reference_is_part=True)
            record = report["rectification"]
            saved = load_last_measure(root, image=photo)
            self.assertEqual(record, saved["rectification"])
            self.assertEqual(saved["homography"], record["matrix"])
            self.assertEqual(report["px_per_mm"], record["px_per_mm"])
            corners = map_points(record["matrix"], [[20, 20], [120, 20], [120, 120]])
            self.assertAlmostEqual(np.linalg.norm(corners[1] - corners[0]) / record["px_per_mm"], 20)
            self.assertAlmostEqual(np.linalg.norm(corners[2] - corners[1]) / record["px_per_mm"], 10)
            np.testing.assert_allclose([r["mm"] for r in report["measurements"]], [10, 4], atol=1e-6)
            np.testing.assert_allclose(report["part_bbox_mm"], [10, 4], atol=0.25)
            expected, _ = warp_image(image, record)
            np.testing.assert_array_equal(np.asarray(Image.open(report["rectified"])), expected)
            self.assertGreater(expected.shape[1], 150)  # Full image, not just the reference quad.

    def test_source_and_saved_rectified_photo_produce_the_same_overlay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            photo, _ = self.scene(root)
            report = self.calibrate(photo)
            points = np.array([[0, 0], [10, 0], [10, 4], [0, 4]], dtype=float)
            faces = np.array([[0, 1, 2], [0, 2, 3]])
            outputs = []
            for index, path in enumerate((photo, Path(report["rectified"]))):
                context = load_last_measure(root, image=path)
                excluded, angled = load_measure_hints(context)
                outputs.append(paint_auto_views(
                    [("front", points, faces)], path, root / f"overlay{index}.png", root / f"diff{index}.png",
                    photo_scale=context["px_per_mm"], roi=context["roi"], seed=context["seed"],
                    exclude=excluded, angled=angled, measure=context,
                ))
            for output in outputs:
                self.assertEqual(output["photo_coordinate_frame"], "rectified")
                self.assertGreater(output["overlay_iou"], 0.85)
            self.assertFalse(outputs[0]["rectification"]["already_rectified"])
            self.assertTrue(outputs[1]["rectification"]["already_rectified"])
            np.testing.assert_array_equal(np.asarray(Image.open(root / "overlay0.png")),
                                          np.asarray(Image.open(root / "overlay1.png")))
            for fit, origin in (("center", None), ("auto", (80, 110))):
                output = paint_overlay(points, faces, photo, root / f"{fit}.png", root / f"{fit}-diff.png",
                                       photo_scale=report["px_per_mm"], origin=origin, fit=fit, measure=report)
                self.assertEqual(output["photo_coordinate_frame"], "rectified")
                with Image.open(root / f"{fit}.png") as painted:
                    self.assertEqual(list(painted.size), report["rectification"]["size"])

    def test_seed_exclusion_and_padding_follow_a_perspective_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            photo, image = self.scene(root)
            record = plan(photo, image.shape, [[30, 30], [190, 20], [170, 150], [45, 160]], 20, 10, 6)
            roi, seed, exclusion = [60, 20, 135, 110], [100, 90], [150, 30, 35, 35]
            prepared, moved_roi, moved_seed, excluded, frame, valid = _prepare_photo(
                image, photo, {"rectification": record}, record["px_per_mm"], roi, seed, [exclusion])
            self.assertLess(valid.mean(), 0.99)
            np.testing.assert_allclose(moved_seed, map_points(record["matrix"], [seed])[0])
            allowed = np.ones(valid.shape, dtype=bool)
            for item in excluded:
                _zero_rect(allowed, item)
            target = np.rint(map_points(record["matrix"], [[165, 45]])[0]).astype(int)
            self.assertFalse(allowed[target[1], target[0]])
            target = np.rint(moved_seed).astype(int)
            self.assertTrue(allowed[target[1], target[0]])
            self.assertFalse(np.any(allowed & ~valid))
            self.assertTrue(np.all(prepared[~valid] == 235))
            # Padding is never a trusted match, even with matching masks.
            result = _alignment(prepared, ~valid, ~valid, None, None, excluded, 6, valid=valid)
            self.assertFalse(result["iou_trusted"])
            self.assertIn("padding", result["iou_trust_reason"])

    def test_observed_border_pixels_are_not_erased_as_padding(self):
        with tempfile.TemporaryDirectory() as tmp:
            photo = Path(tmp) / "photo.png"
            image = np.zeros((100, 140, 3), dtype=np.uint8)
            image[:, :] = (10, 20, 30)
            image[0, -1] = (0, 255, 0)
            Image.fromarray(image).save(photo)
            quad = [[20, 15], [110, 18], [108, 80], [22, 84]]
            record = plan(photo, image.shape, quad, 30, 12, 4)
            warped, valid = warp_image(image, record)
            mapped = map_points(record["matrix"], [[image.shape[1] - 1, 0]])[0]
            x = int(np.floor(mapped[0] + 0.5))
            y = int(np.floor(mapped[1] + 0.5))
            self.assertTrue(valid[y, x])
            self.assertEqual(warped[y, x].tolist(), [0, 255, 0])
            self.assertLess(float(valid.mean()), 0.99)
            self.assertTrue(np.any(~valid))
            self.assertTrue(np.all(warped[~valid] == (10, 20, 30)))

    def test_round_coin_ellipse_is_not_tilt_and_a_flat_one_does_not_stretch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = np.full((160, 160, 3), 240, dtype=np.uint8)
            image[50:110, 40:120] = 20
            photo = root / "photo.png"
            Image.fromarray(image).save(photo)
            points = np.array([[0, 0], [16, 0], [16, 12], [0, 12]], dtype=float)
            faces = np.array([[0, 1, 2], [0, 2, 3]])
            for ratio, label in ((0.99, "measured"), (0.70, "guide_only")):
                with self.subTest(ratio=ratio):
                    output = paint_auto_views(
                        [("front", points, faces)],
                        photo,
                        root / f"{ratio}.png",
                        root / f"{ratio}-diff.png",
                        photo_scale=5,
                        measure={"coin_ellipse": {"ratio": ratio, "major_px": 40, "minor_px": 40 * ratio, "angle_deg": 10}},
                    )
                    self.assertEqual(output["overlay_iou_label"], label)
                    self.assertEqual(output["photo_coordinate_frame"], "source")
                    with Image.open(root / f"{ratio}.png") as painted:
                        self.assertEqual(painted.size, (160, 160))
                    angled = any("angled" in item.lower() for item in output["overlay_warnings"])
                    self.assertEqual(angled, label == "guide_only")

    def test_canvas_cap_preserves_calibrated_landmark_distances(self):
        with tempfile.TemporaryDirectory() as tmp:
            photo, image = self.scene(Path(tmp))
            quad = [[20, 20], [120, 20], [120, 120], [20, 120]]
            record = plan(photo, image.shape, quad, 20, 10, 10000)
            self.assertLessEqual(max(record["size"]), 4000)
            self.assertLess(record["px_per_mm"], 10000)
            mapped = map_points(record["matrix"], quad)
            self.assertAlmostEqual(np.linalg.norm(mapped[1] - mapped[0]) / record["px_per_mm"], 20)
            self.assertAlmostEqual(np.linalg.norm(mapped[3] - mapped[0]) / record["px_per_mm"], 10)

    def test_invalid_legacy_stale_or_conflicting_calibration_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            photo, image = self.scene(Path(tmp))
            report = self.calibrate(photo)
            record = report["rectification"]
            prepare = lambda context, scale=record["px_per_mm"]: _prepare_photo(
                image, photo, context, scale, None, None, [])
            with self.assertRaisesRegex(ValueError, "legacy"):
                prepare({"homography": np.eye(3).tolist()})
            with self.assertRaisesRegex(ValueError, "differs"):
                prepare(report, 2)
            with self.assertRaisesRegex(ValueError, "invalid rectification"):
                prepare({"rectification": {**record, "matrix": np.zeros((3, 3)).tolist()}})
            with self.assertRaisesRegex(ValueError, "degenerate"):
                plan(photo, image.shape, [[0, 0], [10, 0], [20, 0], [30, 0]], 20, 10, 6)
            Image.new("RGB", (220, 180), "white").save(photo)
            with self.assertRaisesRegex(ValueError, "photo changed"):
                prepare(report)

    def test_rectified_context_maps_reference_exclusion_as_a_polygon(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            photo, _ = self.scene(root)
            report = self.calibrate(photo, ruler_mm=7, points=[[150, 40], [185, 40]])
            saved = load_last_measure(root, image=report["rectified"])
            self.assertIsNone(saved["reference_bbox"])
            self.assertEqual(len(saved["reference_polygon"]), 4)
            excluded, _ = load_measure_hints(saved)
            self.assertIn("polygon", excluded[0])

    def test_explicit_measure_json_file_and_object_preserve_the_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            photo, _ = self.scene(root)
            report = self.calibrate(photo)
            context_file = root / "calibration.json"
            (root / "last_measure.json").rename(context_file)
            context = json.loads(context_file.read_text())
            output = write_shape(root / "model", "plate", {"width_mm": 10, "height_mm": 4,
                                 "thickness_mm": 1, "holes": []}, write_3mf=False)
            checked = json.loads(validate_tool({"mesh": str(output["stl"]), "render": False,
                                               "spec": {"x": 10, "y": 4, "z": 1, "shells": 1}}))
            self.assertTrue(checked["ok"], checked)
            for index, payload in enumerate((context, str(context_file))):
                with self.subTest(index=index):
                    rendered = json.loads(render_tool({"mesh": str(output["stl"]), "photo": report["rectified"],
                        "measure_json": payload, "out_dir": str(root / f"views{index}"),
                        "overlay_fit": "auto", "response_format": "detailed"}))
                    self.assertTrue(rendered["ok"], rendered)
                    self.assertEqual(rendered["photo_coordinate_frame"], "rectified")
                    self.assertTrue(rendered["rectification"]["already_rectified"])
                    self.assertEqual(rendered["photo_scale_px_per_mm"], report["px_per_mm"])
                    self.assertGreater(rendered["overlay_iou"], 0.85)
            legacy = json.loads(render_tool({"mesh": str(output["stl"]), "photo": str(photo),
                "measure_json": {"homography": np.eye(3).tolist()}, "out_dir": str(root / "legacy")}))
            self.assertFalse(legacy["ok"])
            self.assertIn("legacy", legacy["error"])


if __name__ == "__main__":
    unittest.main()
