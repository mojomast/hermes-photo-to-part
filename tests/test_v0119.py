"""v0.1.19: scale-preserving refinement, user dimensions, and fail-closed reads."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def _iou(left: np.ndarray, right: np.ndarray) -> float:
    union = np.logical_or(left, right).sum()
    if union == 0:
        return 0.0
    return float(np.logical_and(left, right).sum()) / float(union)


class PoseAndRefineTests(unittest.TestCase):
    def test_saturated_chamfer_cannot_replace_a_better_overlap(self):
        from photopart.overlay import _select_pose

        mask = np.zeros((80, 80), dtype=bool)
        mask[20:60, 20:60] = True
        image = np.zeros((80, 80, 3), dtype=np.uint8)
        iou_pose = {
            "placed": mask,
            "rotation_deg": 20,
            "mirror": False,
            "iou": 0.80,
            "note": "overlap",
        }
        chamfer = {
            "placed": mask,
            "rotation_deg": 0,
            "mirror": False,
            "iou": 0.25,
            "chamfer_px": 1.2,
            "chamfer_norm": 0.02,
            "note": "upright",
        }
        with patch("photopart.overlay.search_alignment", return_value=iou_pose), \
             patch("photopart.overlay._search_chamfer", return_value=chamfer), \
             patch("photopart.overlay._chamfer_of_placed",
                   return_value={"chamfer_px": 1.3, "chamfer_norm": 0.02}):
            pose = _select_pose(mask, mask, image, None)
        self.assertEqual(pose["rotation_deg"], 20)
        self.assertEqual(pose["iou"], 0.80)

    def test_shifted_silhouette_refines_without_changing_area(self):
        from photopart.overlay import _ecc_pose, _mask_chamfer

        source = np.zeros((180, 180), dtype=bool)
        source[70:110, 40:140] = True
        target = np.roll(source, 14, axis=1)
        self.assertGreater(_mask_chamfer(source, target), 2.0)
        pose = {
            "placed": source,
            "rotation_deg": 0,
            "mirror": False,
            "iou": _iou(source, target),
            "chamfer_px": 4.0,
            "chamfer_norm": 0.03,
            "note": "shifted",
        }
        image = np.zeros((180, 180, 3), dtype=np.uint8)
        refined = _ecc_pose(pose, target, image, None)
        self.assertIn("ECC refined", refined.get("note") or "")
        self.assertGreater(refined["iou"], pose["iou"])
        area = abs(int(refined["placed"].sum()) - int(source.sum())) / float(source.sum())
        self.assertLessEqual(area, 0.03)

    def test_good_fit_skips_even_when_truncated_chamfer_looks_coarse(self):
        from photopart.overlay import _ecc_pose

        mask = np.zeros((80, 80), dtype=bool)
        mask[20:60, 20:60] = True
        pose = {
            "placed": mask,
            "rotation_deg": 0,
            "mirror": False,
            "iou": 1.0,
            "chamfer_px": 8.0,
            "chamfer_norm": 0.03,
            "note": "already aligned",
        }
        image = np.zeros((80, 80, 3), dtype=np.uint8)
        result = _ecc_pose(pose, mask, image, None)
        self.assertIs(result, pose)
        self.assertNotIn("ECC", result["note"])

    def test_scaled_euclidean_result_is_rejected(self):
        import cv2

        from photopart.overlay import refine_silhouette

        source = np.zeros((160, 160), dtype=bool)
        source[50:110, 30:130] = True
        target = np.roll(source, 12, axis=0)

        def scaled(*_args, **_kwargs):
            return 1.0, np.array([[1.15, 0, 0], [0, 1.15, 0]], dtype=np.float32)

        with patch("cv2.findTransformECC", side_effect=scaled):
            self.assertIsNone(refine_silhouette(source, target))
        self.assertTrue(hasattr(cv2, "MOTION_EUCLIDEAN"))

    def test_ecc_nonconvergence_keeps_the_prior_pose(self):
        import cv2

        from photopart.overlay import _ecc_pose

        source = np.zeros((120, 120), dtype=bool)
        source[40:80, 20:100] = True
        target = np.roll(source, 10, axis=1)
        pose = {
            "placed": source,
            "rotation_deg": 4,
            "mirror": False,
            "iou": 0.4,
            "chamfer_px": 6.0,
            "chamfer_norm": 0.03,
            "note": "prior",
        }

        def fail(*_args, **_kwargs):
            raise cv2.error("ecc did not converge")

        image = np.zeros((120, 120, 3), dtype=np.uint8)
        with patch("cv2.findTransformECC", side_effect=fail):
            result = _ecc_pose(pose, target, image, None)
        self.assertEqual(result["rotation_deg"], 4)
        self.assertIs(result["placed"], source)
        self.assertNotIn("ECC refined", result["note"])

    def test_observed_border_keeps_edges_and_padding_seam_does_not(self):
        from photopart.overlay import _edge_field

        image = np.full((60, 60, 3), 255, dtype=np.uint8)
        image[:, 0] = 0
        observed = np.ones((60, 60), dtype=bool)
        kept, *_rest = _edge_field(image, None, valid=observed)
        self.assertGreater(int(kept[:, :2].sum()), 0)
        padding = observed.copy()
        padding[:, 0] = False
        dropped, *_rest = _edge_field(image, None, valid=padding)
        self.assertEqual(int(dropped[:, 0].sum()), 0)


class StabilityTests(unittest.TestCase):
    def _gate(self, score: float) -> dict:
        from photopart.overlay import _segmentation_gate

        image = np.zeros((40, 40, 3), dtype=np.uint8)
        mask = np.zeros((40, 40), dtype=bool)
        mask[8:32, 8:32] = True
        with patch("photopart.overlay.color_mask", return_value=mask), \
             patch("photopart.overlay.grabcut_mask", return_value=mask), \
             patch("photopart.overlay._mean_pairwise_iou", return_value=score):
            return _segmentation_gate(image, mask, (4, 4, 32, 32), None, None)

    def test_printed_stability_matches_the_comparison(self):
        shown = self._gate(0.849)
        self.assertNotIn("under 0.85", shown["reason"])
        self.assertNotIn("stability 0.85 is under 0.85", shown["reason"])
        low = self._gate(0.844)
        self.assertIn("stability 0.84 is under 0.85", low["reason"])
        self.assertEqual(low["confidence"], "low")

    def test_stable_grabcut_samples_stop_after_two(self):
        from photopart.overlay import _segmentation_gate

        image = np.zeros((40, 40, 3), dtype=np.uint8)
        mask = np.zeros((40, 40), dtype=bool)
        mask[8:32, 8:32] = True
        calls = []

        def grab(*_args, **kwargs):
            calls.append(kwargs.get("iterations"))
            return mask

        with patch("photopart.overlay.color_mask", return_value=None), \
             patch("photopart.overlay.grabcut_mask", side_effect=grab):
            _segmentation_gate(image, mask, (4, 4, 32, 32), None, None)
        self.assertEqual(calls, [1, 3])


class UserDimensionTests(unittest.TestCase):
    def test_measured_length_cannot_replace_the_user_number(self):
        import trimesh

        from photopart.validate import run_validate

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trimesh.creation.box(extents=(80, 62.3, 4)).export(root / "hinge_v1.stl")
            spec = root / "spec.json"
            spec.write_text(json.dumps({"x": 80, "y": 70, "z": 4, "tolerance": 0.5}))
            _code, first = run_validate(str(root / "hinge_v1.stl"), spec=str(spec), tolerance=0.5)
            freeze_path = Path(str(spec.resolve()) + ".freeze.json")
            frozen = json.loads(freeze_path.read_text(encoding="utf-8"))
            self.assertEqual(frozen["user_axes"]["y"], 70)
            original_hash = frozen["sha256"]
            spec.write_text(json.dumps({"x": 80, "y": 62.3, "z": 4, "tolerance": 0.5}))
            (root / "last_measure.json").write_text(json.dumps({
                "px_per_mm": 10,
                "part_bbox_mm": [62.3, 8.0],
                "project": str(root.resolve()),
            }))
            _code, second = run_validate(
                str(root / "hinge_v1.stl"),
                spec=str(spec),
                spec_reason="measured from the photo",
                tolerance=0.5,
            )
            text = " ".join(second["failures"])
            self.assertFalse(second["ok"])
            self.assertIn("70", text)
            self.assertIn("62.3", text)
            y_row = next(row for row in second["spec"] if row["name"] == "y")
            self.assertEqual(y_row["value"], 70)
            self.assertFalse(y_row["ok"])
            kept = json.loads(freeze_path.read_text(encoding="utf-8"))
            self.assertEqual(kept["sha256"], original_hash)
            self.assertEqual(kept["user_axes"]["y"], 70)
            self.assertFalse(first["ok"])

    def test_unrelated_number_change_with_a_reason_is_allowed(self):
        import trimesh

        from photopart.validate import run_validate

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trimesh.creation.box(extents=(10, 12, 30)).export(root / "part_v1.stl")
            spec = root / "spec.json"
            spec.write_text(json.dumps({"x": 10, "y": 10, "z": 30, "tolerance": 0.4}))
            run_validate(str(root / "part_v1.stl"), spec=str(spec), tolerance=0.4)
            spec.write_text(json.dumps({"x": 10, "y": 12, "z": 30, "tolerance": 0.4}))
            _code, report = run_validate(
                str(root / "part_v1.stl"),
                spec=str(spec),
                spec_reason="user corrected the length",
                tolerance=0.4,
            )
            self.assertTrue(report["ok"], report.get("failures"))
            self.assertEqual(report["user_dimension_changes"], [{"name": "y", "from": 10.0, "to": 12.0}])

    def test_checklist_edit_with_a_reason_still_passes(self):
        import trimesh

        from photopart.validate import run_validate

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trimesh.creation.box(extents=(10, 20, 30)).export(root / "part_v1.stl")
            spec = root / "spec.json"
            body = {"x": 10, "y": 20, "z": 30, "features": ["5 knuckles", "teardrop"]}
            spec.write_text(json.dumps(body))
            run_validate(str(root / "part_v1.stl"), spec=str(spec))
            body["features"] = ["teardrop"]
            spec.write_text(json.dumps(body))
            _code, report = run_validate(
                str(root / "part_v1.stl"),
                spec=str(spec),
                spec_reason="user dropped a knuckle requirement",
            )
            self.assertTrue(report["ok"], report.get("failures"))
            self.assertEqual(report["spec_edits"][-1]["reason"], "user dropped a knuckle requirement")


class GuidanceTests(unittest.TestCase):
    def test_measure_next_step_stops_a_size_only_request(self):
        from photopart.flow import step_measure
        from photopart.tools import tool_specs

        text = step_measure({"part_bbox_mm": [24.26, 12.4]})
        self.assertIn("part_bbox_mm 24.26 x 12.40", text)
        self.assertIn("only a measurement, stop", text)
        self.assertIn("Do not replace a user-stated dimension", text)
        self.assertIn("bottle_cap", text)
        specs = {item["name"]: item for item in tool_specs()}
        self.assertIn("part_bbox_mm", specs["photo_part_measure"]["description"])
        self.assertIn("stop", specs["photo_part_measure"]["description"])
        for name in ("photo_part_template", "photo_part_build"):
            self.assertIn("bottle_cap", specs[name]["description"])
            self.assertIn("features.py", specs[name]["description"])
        for name in ("photo_part_template", "photo_part_build", "photo_part_measure"):
            self.assertLess(len(specs[name]["schema"]["description"]), 900)
            self.assertTrue(specs[name]["schema"]["description"].startswith("photo-to-part:"))

    def test_hook_exception_blocks_protected_reads_and_allows_readme(self):
        from photopart.hooks import on_pre_tool_call, reset_hooks

        reset_hooks()
        try:
            with patch("photopart.hooks._pre", side_effect=RuntimeError("boom")):
                blocked = on_pre_tool_call(tool_name="read_file", args={"path": "evals/runner.py"})
                self.assertEqual(blocked["action"], "block")
                self.assertIsNone(on_pre_tool_call(tool_name="read_file", args={"path": "README.md"}))
                self.assertIsNone(
                    on_pre_tool_call(tool_name="terminal", args={"command": "pytest tests/regression"})
                )
            with patch("photopart.hooks._pre", side_effect=RuntimeError("boom")), \
                 patch("photopart.build_gate.eval_read_block", side_effect=RuntimeError("also")):
                blocked = on_pre_tool_call(tool_name="read_file", args={"path": "evals/tasks.json"})
                self.assertEqual(blocked["action"], "block")
                self.assertIsNone(on_pre_tool_call(tool_name="read_file", args={"path": "README.md"}))
                regression = on_pre_tool_call(
                    tool_name="terminal",
                    args={"command": "cat tests/regression/hinge.stl"},
                )
                self.assertEqual(regression["action"], "block")
        finally:
            reset_hooks()

    def test_yolo_bypass_is_documented_as_hermes_behavior(self):
        security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        skill = (ROOT / "plugin" / "skills" / "photo-to-printable-part" / "SKILL.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for text in (security, skill, readme):
            self.assertIn("--yolo", text)
            self.assertIn("auto-approves", text)
        self.assertIn("does not block", skill)
        self.assertIn("does not block", readme)
        self.assertIn("fails closed", security.lower())
        self.assertNotIn("fails open", security)


if __name__ == "__main__":
    unittest.main()
