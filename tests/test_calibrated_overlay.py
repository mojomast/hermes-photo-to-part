"""Calibrated pose searches must preserve physical size, including fallbacks."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

from photopart.overlay import _place, _select_pose


class CalibratedOverlayTests(unittest.TestCase):
    def test_half_pixel_translation_preserves_a_solid_calibrated_raster(self):
        model = np.ones((41, 81), dtype=bool)
        foreground = np.zeros((160, 160), dtype=bool)
        foreground[50:90, 30:110] = True
        placed = _place(model, foreground, 0, False, close=False, scale_mode="fixed")
        ys, xs = np.nonzero(placed)
        self.assertEqual(int(placed.sum()), 41 * 81)
        self.assertEqual(int(np.ptp(xs) + 1), 81)
        self.assertEqual(int(np.ptp(ys) + 1), 41)

    def test_upright_preference_cannot_override_better_edges_and_overlap(self):
        mask = np.zeros((80, 80), dtype=bool)
        mask[20:60, 20:60] = True
        image = np.zeros((80, 80, 3), dtype=np.uint8)
        upright = {"placed": mask, "rotation_deg": 0, "mirror": False,
                   "iou": 0.65, "note": "upright"}
        turned = {"placed": mask, "rotation_deg": 25, "mirror": False,
                  "iou": 0.90, "chamfer_px": 1.1, "chamfer_norm": 0.01, "note": "turned"}
        # Upstream searches can disagree: subpixel edge gains can still resolve
        # an asymmetric feature. Orientation preference must not erase that evidence.
        with patch("photopart.overlay.search_alignment", return_value=upright), \
             patch("photopart.overlay._search_chamfer", return_value=turned), \
             patch("photopart.overlay._chamfer_of_placed",
                   return_value={"chamfer_px": 1.3, "chamfer_norm": 0.012}):
            pose = _select_pose(mask, mask, image, None)
        self.assertEqual(pose["rotation_deg"], 25)
        self.assertEqual(pose["iou"], 0.90)

    def test_low_contrast_fallback_preserves_wrong_model_size(self):
        foreground = np.zeros((220, 220), dtype=bool)
        foreground[70:150, 70:150] = True
        image = np.full((220, 220, 3), 235, dtype=np.uint8)
        # Visible to color segmentation, but below Canny's strong-edge threshold.
        image[foreground] = 216
        for width in (64, 65, 96, 97, 160, 161):
            with self.subTest(width=width):
                model = np.zeros((width + 8, width + 8), dtype=bool)
                model[4:-4, 4:-4] = True
                pose = _select_pose(model, foreground, image, None)
                ys, xs = np.nonzero(pose["placed"])
                self.assertAlmostEqual(float(np.ptp(xs) + 1), width, delta=1)
                self.assertAlmostEqual(float(np.ptp(ys) + 1), width, delta=1)
                self.assertAlmostEqual(float(pose["placed"].sum()), width ** 2, delta=0.03 * width ** 2)
                expected_iou = min(width, 80) ** 2 / max(width, 80) ** 2
                self.assertAlmostEqual(pose["iou"], expected_iou, delta=0.03)

    def test_matching_size_aligns_with_and_without_strong_edges(self):
        model = np.zeros((88, 88), dtype=bool)
        model[4:84, 4:84] = True
        foreground = np.zeros((220, 220), dtype=bool)
        foreground[90:170, 110:190] = True
        for intensity in (25, 216):
            with self.subTest(intensity=intensity):
                image = np.full((220, 220, 3), 235, dtype=np.uint8)
                image[foreground] = intensity
                pose = _select_pose(model, foreground, image, None)
                self.assertGreater(pose["iou"], 0.97)


if __name__ == "__main__":
    unittest.main()
