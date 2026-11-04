"""v0.1.2: venv symlink, silhouette overlay, size policy, blocks, measure."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugin"
import sys

sys.path.insert(0, str(ROOT))

from photopart.heal import heal_mesh, run_heal
from photopart.measure import apply_homography, homography, measure, resolve_coin
from photopart.parts import SHAPES, build_shape
from photopart.render import render_views
from photopart.tools import measure_tool, template_tool, validate_tool
from photopart.validate import evaluate, main as validate_main


class LauncherSymlinkTests(unittest.TestCase):
    def test_venv_python_symlink_is_not_resolved(self):
        from photopart.launcher import candidate_pythons, ensure_plugin_python, pick_reexec

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            base = home / "base" / "python3"
            base.parent.mkdir(parents=True)
            base.write_text("#!/bin/sh\n", encoding="utf-8")
            venv = home / "installs" / "photo-to-part" / "environments" / "3" / "venv"
            link = venv / "bin" / "python"
            link.parent.mkdir(parents=True)
            link.symlink_to(base)
            (venv / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")
            install = home / "installs" / "photo-to-part"
            (install / "facts.json").write_text(
                json.dumps({"packages": {"venv": {"environment": str(venv)}}}),
                encoding="utf-8",
            )
            found = candidate_pythons(home, include_virtualenv=False)
            self.assertEqual(len(found), 1)
            self.assertTrue(found[0].is_symlink())
            self.assertNotEqual(found[0].resolve(), found[0])
            chosen = pick_reexec(
                can_import=False,
                already_reexec=False,
                candidates=found,
                current=base,
            )
            self.assertEqual(chosen, found[0])
            self.assertTrue(chosen.is_symlink())
            recorded = {}

            def fake_exec(program, argv, env):
                recorded["program"] = program

            ensure_plugin_python(
                can_import=False,
                candidates=found,
                exec_fn=fake_exec,
                argv=["export_validate.py", "--help"],
                already=False,
            )
            self.assertEqual(recorded["program"], str(found[0]))
            self.assertNotEqual(Path(recorded["program"]).resolve(), Path(recorded["program"]))


class ClosureAndSizeTests(unittest.TestCase):
    def test_nonmanifold_is_named_instead_of_zero_boundary_edges(self):
        box = trimesh.creation.box(extents=(10, 12, 14))
        dup = trimesh.Trimesh(
            vertices=box.vertices,
            faces=np.vstack([box.faces, box.faces]),
            process=False,
        )
        report = evaluate(dup)
        text = " ".join(report["failures"])
        self.assertFalse(report["ok"])
        self.assertIn("non-manifold", text)
        self.assertNotIn("not watertight (0 boundary edges)", text)
        self.assertIn("photo_part_heal", text)

    def test_units_already_applied_are_not_suggested_again(self):
        box = trimesh.creation.box(extents=(151, 80, 60))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "part.stl"
            path.write_bytes(box.export(file_type="stl"))
            err = StringIO()
            out = StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = validate_main([str(path), "--units", "m"])
            self.assertEqual(code, 2)
            report = json.loads(out.getvalue())
            self.assertFalse(report["ok"])
            warning = report["unit_warning"]
            self.assertIn("after --units m", warning)
            self.assertIn("drop --units", warning)
            self.assertNotIn("pass --units m", warning)
            self.assertIn("after --units m", err.getvalue())
            out = StringIO()
            with redirect_stdout(out), redirect_stderr(StringIO()):
                code = validate_main([str(path), "--units", "m", "--allow-size"])
            self.assertEqual(code, 0)
            self.assertTrue(json.loads(out.getvalue())["ok"])

    def test_expected_shells_accepts_a_hinge(self):
        mesh, doc = build_shape("hinge")
        self.assertEqual(doc["shells"], 2)
        self.assertEqual(len(mesh.split(only_watertight=False)), 2)
        strict = evaluate(mesh)
        self.assertFalse(strict["ok"])
        self.assertTrue(any("shells" in item for item in strict["failures"]))
        exact = evaluate(mesh, expected_shells=2)
        self.assertTrue(exact["ok"], exact["failures"])
        loose = evaluate(mesh, allow_multi_shell=True)
        self.assertTrue(loose["ok"], loose["failures"])

    def test_holes_match_a_plate_and_reject_a_miss(self):
        mesh, doc = build_shape(
            "plate",
            {"width_mm": 40, "height_mm": 30, "thickness_mm": 4, "holes": [{"x": 12, "y": 15, "diameter": 6}]},
        )
        self.assertTrue(mesh.is_watertight)
        hit = evaluate(mesh, holes=[{"x": 12, "y": 15, "diameter": 6}])
        self.assertTrue(hit["ok"], hit["failures"])
        self.assertTrue(hit["holes"][0]["ok"])
        miss = evaluate(mesh, holes=[{"x": 28, "y": 15, "diameter": 6}])
        self.assertFalse(miss["ok"])
        self.assertIn("position", " ".join(miss["failures"]))


class OverlayFitTests(unittest.TestCase):
    def test_auto_fit_reports_iou_and_a_bright_contour(self):
        # Front view of this box is 20 mm wide (z) by 40 mm tall (x).
        box = trimesh.creation.box(extents=(40, 10, 20))
        scale = 5.0
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            photo = root / "photo.png"
            pixels = np.full((400, 400, 3), 255, dtype=np.uint8)
            pixels[40:240, 30:130] = (20, 24, 28)
            Image.fromarray(pixels, mode="RGB").save(photo)
            manifest = render_views(
                box,
                root / "auto",
                photo=photo,
                photo_scale=scale,
                overlay_fit="auto",
                pixels=64,
                samples=1,
            )
            self.assertEqual(manifest["overlay_fit"], "auto")
            self.assertGreater(manifest["overlay_iou"], 0.55)
            self.assertTrue(Path(manifest["overlay_diff"]).is_file())
            overlay = np.asarray(Image.open(root / "auto" / "overlay.png"))
            bright = (overlay[:, :, 0] > 180) & (overlay[:, :, 2] > 120) & (overlay[:, :, 1] < 180)
            self.assertGreater(int(np.count_nonzero(bright)), 30)
            center = render_views(
                box,
                root / "center",
                photo=photo,
                photo_scale=scale,
                overlay_fit="center",
                pixels=64,
                samples=1,
            )
            self.assertEqual(center["overlay_fit"], "center")
            self.assertLess(center["overlay_iou"], manifest["overlay_iou"])


class BlocksAndHealTests(unittest.TestCase):
    def test_every_shape_is_a_solid(self):
        for shape in SHAPES:
            mesh, doc = build_shape(shape)
            self.assertTrue(mesh.is_watertight, shape)
            self.assertGreater(mesh.volume, 0, shape)
            self.assertEqual(len(mesh.split(only_watertight=False)), doc["shells"], shape)

    def test_countersink_deeper_than_the_sheet_is_rejected(self):
        with self.assertRaises(ValueError) as caught:
            build_shape("countersink", {"thickness_mm": 2, "countersink_depth_mm": 8.5, "hole_diameter_mm": 4.5})
        self.assertIn("deeper than the sheet", str(caught.exception))

    def test_template_tool_writes_an_l_bracket(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = json.loads(template_tool({"out_dir": str(Path(tmp) / "part"), "shape": "l_bracket", "no_3mf": True}))
        self.assertTrue(summary["ok"], summary)
        self.assertTrue(summary["stl"].endswith("l_bracket_v1.stl"))
        self.assertEqual(summary["shape"], "l_bracket")

    def test_union_merges_overlapping_boxes(self):
        left = trimesh.creation.box(extents=(10, 10, 10))
        right = trimesh.creation.box(extents=(10, 10, 10))
        right.apply_translation((5, 0, 0))
        both = trimesh.util.concatenate([left, right])
        self.assertEqual(len(both.split(only_watertight=False)), 2)
        merged, report = heal_mesh(both, union=True)
        self.assertTrue(report["union_applied"])
        self.assertEqual(report["after"]["components"], 1)
        self.assertTrue(merged.is_watertight)
        apart = trimesh.creation.box(extents=(4, 4, 4))
        apart.apply_translation((30, 0, 0))
        disjoint = trimesh.util.concatenate([left, apart])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "two.stl"
            src.write_bytes(disjoint.export(file_type="stl"))
            code, healed = run_heal([str(src), "--out", str(root / "out.stl"), "--union", "--keep-all"])
        self.assertEqual(code, 0, healed)
        self.assertTrue(healed["union_applied"])
        self.assertGreaterEqual(healed["after"]["components"], 2)


class MeasureTests(unittest.TestCase):
    def test_euro_coin_scale(self):
        name, diameter = resolve_coin("1euro")
        self.assertEqual(name, "euro_1")
        self.assertAlmostEqual(diameter, 23.25)
        report = measure(
            {
                "coin": "us_quarter",
                "diameter_px": 242.6,
                "measurements": [{"name": "width", "length_px": 121.3}],
            }
        )
        self.assertTrue(report["ok"])
        self.assertAlmostEqual(report["px_per_mm"], 10.0, places=3)
        self.assertAlmostEqual(report["measurements"][0]["mm"], 12.13, places=2)

    def test_homography_and_rectified_image(self):
        src = np.array([[10.0, 12.0], [110.0, 20.0], [100.0, 90.0], [18.0, 80.0]])
        dst = np.array([[0.0, 0.0], [200.0, 0.0], [200.0, 100.0], [0.0, 100.0]])
        mapped = apply_homography(homography(src, dst), src)
        np.testing.assert_allclose(mapped, dst, atol=1e-4)
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "shot.png"
            canvas = np.zeros((120, 160, 3), dtype=np.uint8)
            canvas[:, :] = (20, 40, 60)
            canvas[10:30, 10:40] = (200, 10, 10)
            Image.fromarray(canvas).save(image)
            out = Path(tmp) / "flat.png"
            report = measure(
                {
                    "quad": [[0, 0], [159, 0], [159, 119], [0, 119]],
                    "width_mm": 80,
                    "height_mm": 60,
                    "image": str(image),
                    "out": str(out),
                }
            )
            self.assertTrue(out.is_file(), report)
            self.assertGreater(report["px_per_mm"], 0)
            rectified = np.asarray(Image.open(out))
            self.assertEqual(rectified.ndim, 3)
            self.assertGreater(rectified.shape[0], 10)

    def test_measure_tool_returns_json(self):
        payload = json.loads(measure_tool({"ruler_mm": 50, "points": [[0, 0], [200, 0]]}))
        self.assertTrue(payload["ok"])
        self.assertAlmostEqual(payload["px_per_mm"], 4.0)


class SkillTightnessTests(unittest.TestCase):
    def test_instructions_name_the_id_tools_and_limits(self):
        text = (PLUGIN / "skills" / "photo-to-printable-part" / "SKILL.md").read_text(encoding="utf-8")
        front = text.split("---", 2)[1]
        self.assertIn("photo-to-part:photo-to-printable-part", front)
        self.assertLess(front.index("photo-to-part:photo-to-printable-part"), front.index("STL"))
        for phrase in (
            "trimesh and manifold3d are already installed",
            "sudo apt",
            "Always call the photo_part_* tools",
            "photo_part_measure",
            "expected_shells",
            "contact.png",
            "40 turns",
            "countersink deeper than the sheet",
            "allow_size",
        ):
            self.assertIn(phrase, text)
        plugin = (PLUGIN / "plugin.yaml").read_text(encoding="utf-8")
        self.assertIn("photo-to-part:photo-to-printable-part", plugin)
        self.assertIn("photo_part_measure", plugin)


if __name__ == "__main__":
    unittest.main()
