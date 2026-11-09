"""v0.1.12: bores, standards, knuckles, threads, overlay IoU, skill rewrites."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from evals.meshes import pip_hinge_fine_tessellation, staircase_square_hole
from evals.runner import score_transcript
from photopart.features import external_thread, load_face_tags, write_face_tags
from photopart.parts import _as_mesh, _cube, _cylinder_x, build_shape
from photopart.spec import count_bores, count_knuckles, detect_knuckles
from photopart.standards import check_standard


class BoreTests(unittest.TestCase):
    def test_fine_tessellation_pin_clearance_and_square_staircase(self):
        mesh = pip_hinge_fine_tessellation()
        bores = count_bores(mesh)
        self.assertEqual(len(bores), 2)
        for bore in bores:
            self.assertAlmostEqual(bore["diameter"], 3.8, delta=0.08)
            self.assertEqual(bore["kind"], "pin_clearance")
            self.assertAlmostEqual(bore["clearance_mm"], 0.4, delta=0.05)
        self.assertEqual(count_bores(staircase_square_hole()), [])
        found = detect_knuckles(mesh, "x")
        self.assertEqual(found["knuckles"], 5)
        self.assertGreaterEqual(found["cylinders"], 2)

    def test_template_hinge_counts_stay_on_the_cylinder_detector(self):
        for count in (3, 4, 5, 7):
            params = {} if count == 4 else {"knuckles": count}
            mesh, _resolved = build_shape("hinge", params)
            found = detect_knuckles(mesh, "x")
            self.assertEqual(found["knuckles"], count, count)
            self.assertEqual(count_knuckles(mesh, "x"), count, count)


class KnuckleShapeTests(unittest.TestCase):
    def test_rod_is_one_segment_and_a_plate_is_not_a_knuckle(self):
        rod = _as_mesh(_cylinder_x(2.0, 40.0, 0.0, 0.0, 0.0, segments=48))
        found = detect_knuckles(rod, "x")
        self.assertIn(found["knuckles"], (0, 1))
        self.assertLessEqual(found["cylinders"], 1)
        plate = _as_mesh(_cube(40.0, 14.0, 3.0))
        self.assertEqual(detect_knuckles(plate, "x")["cylinders"], 0)

    def test_strap_hinge_does_not_emit_knuckles_without_a_pivot(self):
        from photopart.parts import write_shape

        with tempfile.TemporaryDirectory() as tmp:
            written = write_shape(Path(tmp), "strap_hinge", write_3mf=False)
        self.assertNotIn("knuckles", written["spec_checks"])


class StandardsRoleTests(unittest.TestCase):
    def test_rosette_uses_the_clearance_hole_not_the_envelope(self):
        spec = {
            "part": "rosette",
            "notes": "45 mm rosette, M5 mounting screw",
            "decorative": True,
        }
        result = check_standard(spec, {"extents_mm": [45, 45, 8], "holes": [{"diameter": 5.5}]})
        self.assertEqual(result["warnings"], [])
        self.assertFalse(result["edited_spec"])
        row = next(item for item in result["checked"] if item["designation"] == "M5")
        self.assertEqual(row["role"], "clearance")
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["source"], "ISO 273")
        self.assertAlmostEqual(row["standard_mm"], 5.5)

    def test_implausible_envelope_is_skipped(self):
        spec = {"part": "glass pull", "notes": "mounts with an M5 screw"}
        result = check_standard(spec, {"extents_mm": {"x": 45, "y": 45, "z": 8}})
        self.assertEqual(result["warnings"], [])
        row = next(item for item in result["checked"] if item["designation"] == "M5")
        self.assertEqual(row["status"], "skipped")
        self.assertIn("not plausible", row["message"])

    def test_m5_flange_that_is_too_small_warns(self):
        result = check_standard(
            {"designation": "M5 flange bolt"},
            {"extents_mm": {"x": 8.1, "y": 8.1, "z": 20}, "pitch_mm": 0.8},
        )
        text = " ".join(row["message"] for row in result["warnings"])
        self.assertIn("ISO 4162", text)
        self.assertIn("flange", text.lower())


class RewriteScoreTests(unittest.TestCase):
    def test_hook_rewrites_are_not_wrong_ids(self):
        text = (
            'skill_view("plugin:photo-to-part:photo-to-printable-part")\n'
            'skill_view("plugin:photo-to-part:photo-to-printable-part")\n'
        )
        bare = score_transcript(text)
        self.assertEqual(bare["wrong_skill_ids"], 2)
        self.assertEqual(bare["skill_id_rewritten"], 0)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "calls.jsonl"
            rows = [
                {"tool": "skill_view", "rewrite_from": "plugin:photo-to-part:photo-to-printable-part"},
                {"tool": "skill_view", "rewrite_from": "plugin:photo-to-part:photo-to-printable-part"},
            ]
            path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            scored = score_transcript(text, path)
        self.assertEqual(scored["wrong_skill_ids"], 0)
        self.assertEqual(scored["skill_id_rewritten"], 2)


class ThreadCacheTests(unittest.TestCase):
    def test_copied_screw_without_a_sidecar_is_detected(self):
        import trimesh

        from photopart.printability import check_printability

        thread = external_thread(designation="M3", length=8)
        naked = trimesh.Trimesh(vertices=np.asarray(thread.vertices), faces=np.asarray(thread.faces), process=True)
        report = check_printability(naked)
        self.assertEqual(report["tags_source"], "detected")
        self.assertTrue(report.get("auto_feature"))
        self.assertNotIn("wall", " ".join(report["warnings"]))
        pitch = None
        for region in report["regions"]:
            if region.get("kind") == "thread":
                pitch = float(region["pitch"])
        self.assertIsNotNone(pitch)
        self.assertAlmostEqual(pitch, 0.5, delta=0.05)

    def test_sidecar_hash_mismatch_is_ignored(self):
        import trimesh

        thread = external_thread(designation="M3", length=8)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "screw.stl"
            path.write_bytes(thread.export(file_type="stl"))
            write_face_tags(thread, path)
            sidecar = Path(str(path) + ".faces.json")
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
            self.assertIn("mesh_sha256", payload)
            payload["mesh_sha256"] = "0" * 64
            sidecar.write_text(json.dumps(payload), encoding="utf-8")
            self.assertIsNone(load_face_tags(path))
            # A legacy sidecar with no hash is still accepted.
            payload.pop("mesh_sha256")
            sidecar.write_text(json.dumps(payload), encoding="utf-8")
            loaded = load_face_tags(path)
            self.assertEqual(loaded["tags_source"], "sidecar")

    def test_3mf_metadata_round_trip(self):
        import trimesh

        from photopart.geometry import export_3mf

        thread = external_thread(designation="M3", length=8)
        self.assertTrue(thread.metadata.get("face_tags", {}).get("thread"))
        self.assertTrue(thread.metadata.get("feature_regions"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "screw.3mf"
            export_3mf(thread, path)
            loaded = load_face_tags(path)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["tags_source"], "3mf")
            self.assertTrue(loaded["thread"])
            self.assertTrue(loaded["regions"])
            self.assertEqual(loaded["regions"][0].get("kind"), "thread")
            # trimesh reloads the mesh; the photopart hints stay in the zip.
            trimesh.load(path)
            again = load_face_tags(path)
            self.assertEqual(again["tags_source"], "3mf")
            self.assertEqual(again["thread"], loaded["thread"])


class AssumedDimensionTests(unittest.TestCase):
    def test_hub_boss_warns_without_failing(self):
        from photopart.features import spur_gear
        from photopart.spec import apply_spec

        gear = spur_gear(module=1.0, teeth=20, face_width=8, hub_diameter=12, hub_length=11)
        extra = float(gear.extents[2]) - 8.0
        self.assertGreater(extra, 2.0)
        spec = {
            "z": {"value": 8, "tol": 0.5, "source": "user"},
            "assumed_features": [{"name": "hub boss", "axis": "z", "adds_mm": extra}],
        }
        failures, rows = apply_spec(gear, spec=spec)
        z_row = next(item for item in rows if item["name"] == "z")
        self.assertIn("assumed hub boss", z_row.get("warning") or "")
        self.assertIn("Put the hub within the face width", z_row["warning"])
        self.assertTrue(z_row["ok"])
        self.assertEqual(failures, [])
        # The same mesh with no assumed feature is a real drift.
        drifted, drift_rows = apply_spec(gear, spec={"z": {"value": 8, "tol": 0.5}})
        self.assertTrue(drifted)
        self.assertFalse(next(item for item in drift_rows if item["name"] == "z")["ok"])

    def test_all_given_dimensions_do_not_warn(self):
        from photopart.spec import apply_spec

        mesh, _resolved = build_shape("hinge", {"knuckles": 5})
        extents = [float(value) for value in mesh.extents]
        spec = {"x": extents[0], "y": extents[1], "z": extents[2], "knuckles": 5, "tolerance": 0.5}
        _failures, rows = apply_spec(mesh, spec=spec)
        for row in rows:
            self.assertNotIn("assumed", row.get("warning") or "")
            self.assertTrue(row["ok"], row)


class OverlayRefineTests(unittest.TestCase):
    def test_tilted_rectangle_iou_recovers(self):
        import cv2

        from photopart.overlay import refine_silhouette

        canvas = np.zeros((220, 220), dtype=np.uint8)
        cv2.rectangle(canvas, (20, 96), (200, 124), 255, thickness=-1)
        source = canvas > 0
        # A 10° tilt is a rotation. Euclidean ECC can recover it without rescaling.
        matrix = cv2.getRotationMatrix2D((110, 110), 10, 1.0)
        homography = np.vstack([matrix, [0.0, 0.0, 1.0]])
        warped = cv2.warpPerspective(canvas, homography, (220, 220))
        target = warped > 0
        before = _iou(source, target)
        refined = refine_silhouette(source, target)
        self.assertIsNotNone(refined)
        after = _iou(refined, target)
        self.assertLess(before, 0.7)
        self.assertGreaterEqual(after, 0.9)


def _iou(left: np.ndarray, right: np.ndarray) -> float:
    union = np.logical_or(left, right).sum()
    if union == 0:
        return 0.0
    return float(np.logical_and(left, right).sum()) / float(union)


if __name__ == "__main__":
    unittest.main()
