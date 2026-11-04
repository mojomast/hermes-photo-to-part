"""v0.1.9: session budget, bore legs, sealed evals, and help output."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

import trimesh
from PIL import Image

from evals.runner import score_transcript, stage_task
from photopart.flow import OVERLAY_LOW_STEP, SKILL_ID
from photopart.paths import plugin_root
from photopart.spec import apply_spec, count_bores, genus_report
from photopart.tools import build_tool, measure_tool, template_tool, validate_tool

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugin"


def _box(path: Path, extents) -> None:
    trimesh.creation.box(extents=extents).export(path)


class BoreTests(unittest.TestCase):
    def test_thin_six_hole_l_and_template_l(self):
        from evals.meshes import six_hole_bracket, thin_l_bracket
        from photopart.parts import build_shape

        thin = count_bores(thin_l_bracket())
        axes = {}
        for bore in thin:
            axes[bore["axis"]] = axes.get(bore["axis"], 0) + 1
        self.assertEqual(len(thin), 6, thin)
        self.assertEqual(axes.get("x"), 3)
        self.assertEqual(axes.get("z"), 3)
        self.assertTrue(all(bore.get("through") is True for bore in thin))

        six = count_bores(six_hole_bracket())
        self.assertEqual(len(six), 6, six)

        mesh, _doc = build_shape("l_bracket", {"thickness_mm": 1.5})
        found = count_bores(mesh)
        self.assertEqual(len(found), 2, found)
        self.assertEqual({bore["axis"] for bore in found}, {"x", "z"})

    def test_square_hole_is_undetected_and_a_solid_still_fails(self):
        from photopart.parts import _as_mesh, _cube, _difference

        square = _as_mesh(_difference(_cube(20.0, 20.0, 4.0), [_cube(4.0, 4.0, 6.0).translate((8.0, 8.0, -1.0))]))
        info = genus_report(square)
        failures, rows = apply_spec(square, spec={"hole_count": 1})
        self.assertEqual(count_bores(square), [])
        self.assertGreater(info.get("genus") or 0, 0)
        self.assertEqual(rows[0]["status"], "undetected")
        self.assertEqual(failures, [])
        self.assertTrue(rows[0]["ok"])

        solid = trimesh.creation.box(extents=(10, 12, 14))
        solid_failures, solid_rows = apply_spec(solid, spec={"hole_count": 1})
        self.assertTrue(solid_failures)
        self.assertNotEqual(solid_rows[0].get("status"), "undetected")
        self.assertFalse(solid_rows[0]["ok"])


class BudgetAndHelpTests(unittest.TestCase):
    def test_calls_used_and_env_cap(self):
        saved = os.environ.pop("PHOTO_PART_MAX_CALLS", None)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                image = Path(tmp) / "photo.png"
                Image.new("RGB", (16, 16), (255, 255, 255)).save(image)
                quiet = json.loads(
                    measure_tool({"image": str(image), "diameter_mm": 20, "diameter_px": 40, "calls_used": 16})
                )
                self.assertEqual(quiet["budget"]["max_calls"], 40)
                self.assertEqual(quiet["budget"]["calls_used_source"], "argument")
                self.assertEqual(quiet["budget"]["remaining"], 24)
                self.assertFalse(str(quiet["next_step"]).startswith("Budget:"))
                hinted = json.loads(
                    measure_tool({"image": str(image), "diameter_mm": 20, "diameter_px": 40, "calls_used": 24})
                )
                self.assertTrue(str(hinted["next_step"]).startswith("Budget: deliver now."))
                self.assertEqual(hinted["budget"]["remaining"], 16)
            os.environ["PHOTO_PART_MAX_CALLS"] = "10"
            with tempfile.TemporaryDirectory() as tmp:
                image = Path(tmp) / "photo.png"
                Image.new("RGB", (16, 16), (240, 240, 240)).save(image)
                small = json.loads(
                    measure_tool({"image": str(image), "diameter_mm": 20, "diameter_px": 40, "calls_used": 6})
                )
                self.assertEqual(small["budget"]["max_calls"], 10)
                self.assertTrue(str(small["next_step"]).startswith("Budget: deliver now."))
                estimated = json.loads(measure_tool({"image": str(image), "diameter_mm": 20, "diameter_px": 40}))
                self.assertEqual(estimated["budget"]["calls_used_source"], "estimate")
                self.assertLessEqual(
                    estimated["budget"]["remaining"],
                    estimated["budget"]["max_calls"] - estimated["budget"]["plugin_calls"],
                )
        finally:
            if saved is None:
                os.environ.pop("PHOTO_PART_MAX_CALLS", None)
            else:
                os.environ["PHOTO_PART_MAX_CALLS"] = saved

    def test_template_and_build_help_do_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            described = json.loads(template_tool({"help": True, "shape": "l_bracket", "out_dir": str(root)}))
            self.assertTrue(described["ok"], described)
            self.assertIn("thickness_mm", described["params"])
            self.assertIn("example_script", described)
            self.assertIn("l_bracket", described["example_script"])
            self.assertFalse(any(root.iterdir()))
            features = json.loads(build_tool({"describe": True}))
            self.assertTrue(features["ok"], features)
            self.assertIn("spur_gear", features["features"])
            self.assertIn("example_script", features)
            self.assertIn("mesh.export", features["example_script"])
            missing = json.loads(build_tool({}))
            self.assertFalse(missing["ok"])
            self.assertIn("script is required", missing["error"])

    def test_skill_id_leads_and_names_the_forty_call_budget(self):
        from photopart.tools import tool_specs

        for spec in tool_specs():
            self.assertTrue(spec["description"].startswith(SKILL_ID), spec["name"])
            self.assertIn('skill_view("photo-to-part:photo-to-printable-part")', spec["description"])
            self.assertIn("calls_used", spec["schema"]["parameters"]["properties"])
        text = (PLUGIN / "skills" / "photo-to-printable-part" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("About 40 tool calls in total.", text)
        self.assertIn("Don't read the plugin's source or evals.", text)
        self.assertIn("Use the tools' help/params outputs.", text)
        self.assertIn("Batch independent calls.", text)
        self.assertIn("Deliver as soon as validate passes.", text)


class ProjectFileTests(unittest.TestCase):
    def test_measure_without_image_stays_out_of_the_plugin_dir(self):
        root = plugin_root()
        self.assertIsNotNone(root)
        target = root / "last_measure.json"
        self.assertFalse(target.exists())
        previous = os.getcwd()
        try:
            os.chdir(root)
            report = json.loads(measure_tool({"diameter_mm": 20, "diameter_px": 80}))
        finally:
            os.chdir(previous)
        self.assertTrue(report["ok"], report)
        self.assertFalse(target.exists())
        self.assertIn("last_measure_warning", report)
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            scoped = json.loads(measure_tool({"diameter_mm": 20, "diameter_px": 80, "out_dir": str(project)}))
            path = project / "last_measure.json"
            self.assertTrue(path.is_file(), scoped)
            body = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(Path(body["project"]).resolve(), project.resolve())
            self.assertEqual(scoped["last_measure"], str(path.resolve()))

    def test_validate_overlay_uses_the_last_measure(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            photo = project / "photo.png"
            Image.new("RGB", (48, 48), (230, 230, 230)).save(photo)
            body = {
                "px_per_mm": 4.0,
                "roi": [4, 4, 32, 32],
                "seed": [20, 20],
                "image": str(photo.resolve()),
                "project": str(project.resolve()),
                "angled": False,
            }
            (project / "last_measure.json").write_text(json.dumps(body) + "\n", encoding="utf-8")
            mesh = project / "part_v1.stl"
            _box(mesh, (10, 20, 30))
            spec = project / "spec.json"
            spec.write_text(json.dumps({"x": 10, "y": 20, "z": 30, "shells": 1}), encoding="utf-8")
            report = json.loads(validate_tool({"mesh": str(mesh), "spec": str(spec)}))
            self.assertTrue(report["ok"], report)
            rendered = report.get("render") or {}
            overlay = Path(str(rendered.get("overlay") or ""))
            self.assertTrue(overlay.is_file(), rendered)
            self.assertTrue(Path(str(rendered.get("sheet") or "")).is_file())
            self.assertEqual(rendered.get("photo_scale"), 4.0)
            self.assertEqual(rendered.get("roi"), "4,4,32,32")
            self.assertEqual(rendered.get("photo"), str(photo.resolve()))
        self.assertIn("seed point", OVERLAY_LOW_STEP)
        self.assertIn("region box", OVERLAY_LOW_STEP)


class EvalSealTests(unittest.TestCase):
    def test_stage_keeps_answers_and_scripted_tasks_are_prompt_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            photo = stage_task("real_photo_overlay", root / "photo")
            staged = Path(photo["dir"])
            self.assertTrue((staged / "washer_photo.jpg").is_file())
            self.assertTrue((staged / "prompt.txt").is_file())
            self.assertFalse((staged / "fixture.json").exists())
            self.assertFalse((staged / "washer_mask.png").exists())
            self.assertIn("fixture.json", photo["answers_withheld"])
            low = stage_task("overlay_low_confidence", root / "low")
            low_dir = Path(low["dir"])
            self.assertTrue(low["scripted"])
            self.assertEqual(list(low_dir.iterdir()), [low_dir / "prompt.txt"])

    def test_leak_is_anchored_and_mentions_are_not_calls(self):
        self.assertFalse(score_transcript("open('hevals/tasks.json')\n")["leak"])
        self.assertTrue(score_transcript('open("evals/tasks.json")\n')["leak"])
        absolute = score_transcript(f"cat {ROOT / 'evals' / 'runner.py'}\n")
        self.assertTrue(absolute["leak"])
        mention = score_transcript(
            "\n".join(
                [
                    "please call photo_part_validate on the part",
                    '{"tool_calls":[{"function":{"name":"photo_part_measure","arguments":"{}"}}]}',
                ]
            )
        )
        self.assertEqual(mention["tool_calls"], 1)
        self.assertEqual(mention["plugin_calls"], 1)
        self.assertFalse(mention["leak"])

    def test_package_excludes_evals_and_tests(self):
        from setuptools import find_packages

        names = find_packages(where=str(PLUGIN), include=["photopart*"], exclude=["evals*", "tests*"])
        self.assertIn("photopart", names)
        self.assertNotIn("evals", names)
        self.assertNotIn("tests", names)
        manifest = (PLUGIN / "MANIFEST.in").read_text(encoding="utf-8")
        self.assertIn("prune evals", manifest)
        self.assertIn("prune tests", manifest)
        project = (PLUGIN / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('exclude = ["evals*", "tests*"]', project)


if __name__ == "__main__":
    unittest.main()
