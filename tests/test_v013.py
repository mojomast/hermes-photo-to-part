"""v0.1.3: part region, validation sidecar, build tool, absolute outputs."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))

from photopart.build_run import run_build
from photopart.flow import SKILL_ID
from photopart.heal import run_heal
from photopart.measure import load_measure_hints, measure
from photopart.render import render_views, run_render
from photopart.tools import build_tool, measure_tool, template_tool, tool_specs, validate_tool
from photopart.validate import run_validate


def _box_stl(path: Path, extents=(40, 10, 20)) -> None:
    mesh = trimesh.creation.box(extents=extents)
    path.write_bytes(mesh.export(file_type="stl"))


def _coin_photo(path: Path) -> None:
    """A large coin on the left and a small part rectangle on the right."""
    pixels = np.full((480, 480, 3), 255, dtype=np.uint8)
    pixels[30:190, 30:190] = (190, 150, 40)
    pixels[240:320, 260:300] = (20, 24, 28)
    Image.fromarray(pixels, mode="RGB").save(path)


class OverlayRegionTests(unittest.TestCase):
    def test_seed_and_exclude_beat_the_largest_blob(self):
        box = trimesh.creation.box(extents=(40, 10, 20))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            photo = root / "photo.png"
            _coin_photo(photo)
            auto = render_views(
                box,
                root / "auto",
                photo=photo,
                photo_scale=2,
                overlay_fit="auto",
                pixels=48,
                samples=1,
            )
            self.assertEqual(auto["overlay_blob"]["source"], "largest")
            self.assertLess(auto["overlay_blob"]["x"], 150)
            seeded = render_views(
                box,
                root / "seed",
                photo=photo,
                photo_scale=2,
                overlay_fit="auto",
                overlay_seed=(280, 280),
                pixels=48,
                samples=1,
            )
            self.assertEqual(seeded["overlay_blob"]["source"], "seed")
            self.assertGreater(seeded["overlay_blob"]["x"], 200)
            self.assertGreater(seeded["overlay_iou"], 0.5)
            excluded = render_views(
                box,
                root / "exclude",
                photo=photo,
                photo_scale=2,
                overlay_fit="auto",
                overlay_exclude=[(30, 30, 160, 160)],
                pixels=48,
                samples=1,
            )
            self.assertGreater(excluded["overlay_blob"]["x"], 200)
            self.assertGreater(excluded["overlay_iou"], 0.5)
            angled = render_views(
                box,
                root / "angled",
                photo=photo,
                photo_scale=2,
                overlay_fit="auto",
                overlay_seed=(280, 280),
                overlay_angled=True,
                pixels=48,
                samples=1,
            )
            self.assertTrue(any("angled" in item.lower() for item in angled["overlay_warnings"]))

    def test_low_iou_and_measure_json_are_reported(self):
        box = trimesh.creation.box(extents=(40, 10, 20))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            photo = root / "corner.png"
            pixels = np.full((400, 400, 3), 255, dtype=np.uint8)
            pixels[12:70, 12:90] = (20, 24, 28)
            Image.fromarray(pixels, mode="RGB").save(photo)
            centered = render_views(
                box,
                root / "center",
                photo=photo,
                photo_scale=2,
                overlay_fit="center",
                pixels=48,
                samples=1,
            )
            self.assertLess(centered["overlay_iou"], 0.5)
            self.assertTrue(any("0.5" in item for item in centered["overlay_warnings"]))
            _box_stl(root / "part_v1.stl")
            code, checked = run_validate(str(root / "part_v1.stl"))
            self.assertEqual(code, 0, checked)
            hints = {
                "reference_bbox": {"x": 30, "y": 30, "w": 160, "h": 160},
                "angled": True,
            }
            rects, flagged = load_measure_hints(hints)
            self.assertEqual(len(rects), 1)
            self.assertTrue(flagged)
            (root / "measure.json").write_text(json.dumps(hints), encoding="utf-8")
            wide = root / "wide.png"
            _coin_photo(wide)
            code, manifest = run_render(
                [
                    str(root / "part_v1.stl"),
                    "--out-dir",
                    str(root / "views"),
                    "--photo",
                    str(wide),
                    "--photo-scale",
                    "2",
                    "--overlay-fit",
                    "auto",
                    "--measure-json",
                    str(root / "measure.json"),
                ]
            )
            self.assertEqual(code, 0, manifest)
            self.assertGreater(manifest["overlay_iou"], 0.5)
            self.assertTrue(any("angled" in item.lower() for item in manifest["overlay_warnings"]))
            self.assertTrue(Path(manifest["views"][0]).is_absolute())


class SidecarTests(unittest.TestCase):
    def test_validate_stamps_the_file_and_render_notices_a_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mesh = root / "peg_v1.stl"
            _box_stl(mesh)
            code, report = run_validate(str(mesh))
            self.assertEqual(code, 0, report)
            self.assertIsNone(report["stale_validation"])
            self.assertIn("next_step", report)
            self.assertIn(SKILL_ID, report["next_step"])
            side = Path(str(mesh) + ".validate.json")
            stored = json.loads(side.read_text(encoding="utf-8"))
            self.assertEqual(stored["sha256"], report["sha256"])
            original = report["sha256"]
            _box_stl(mesh, (30, 12, 18))
            code, rendered = run_render([str(mesh), "--out-dir", str(root / "renders")])
            self.assertEqual(code, 2, rendered)
            self.assertTrue(rendered["unvalidated"])
            self.assertTrue(rendered["stale_validation"])
            self.assertIn("stale_validation", rendered["next_step"])
            self.assertFalse((root / "renders" / "front.png").exists())
            self.assertEqual(json.loads(side.read_text(encoding="utf-8"))["sha256"], original)
            code, again = run_validate(str(mesh))
            self.assertEqual(code, 0, again)
            self.assertTrue(again["stale_validation"])
            self.assertNotEqual(again["sha256"], original)
            self.assertEqual(json.loads(side.read_text(encoding="utf-8"))["sha256"], again["sha256"])


class OverwriteAndPathTests(unittest.TestCase):
    def test_template_and_heal_refuse_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "part"
            first = json.loads(template_tool({"out_dir": str(out), "shape": "plate", "no_3mf": True}))
            self.assertTrue(first["ok"], first)
            self.assertTrue(Path(first["stl"]).is_absolute())
            self.assertTrue(first["interpreter"])
            second = json.loads(template_tool({"out_dir": str(out), "shape": "plate", "no_3mf": True}))
            self.assertFalse(second["ok"])
            self.assertIn("--overwrite", second["error"])
            self.assertIn(SKILL_ID, second["error"])
            forced = json.loads(
                template_tool({"out_dir": str(out), "shape": "plate", "no_3mf": True, "force": True})
            )
            self.assertTrue(forced["ok"], forced)
            replaced = json.loads(
                template_tool({"out_dir": str(out), "shape": "plate", "no_3mf": True, "overwrite": True})
            )
            self.assertTrue(replaced["ok"], replaced)
            src = root / "scan.stl"
            healed = root / "healed_v1.stl"
            _box_stl(src, (20, 20, 20))
            code, report = run_heal([str(src), "--out", str(healed)])
            self.assertEqual(code, 0, report)
            code, blocked = run_heal([str(src), "--out", str(healed)])
            self.assertEqual(code, 1)
            self.assertIn("--overwrite", blocked["error"])
            code, again = run_heal([str(src), "--out", str(healed), "--overwrite"])
            self.assertEqual(code, 0, again)

    def test_defaults_stay_out_of_the_hermes_cache(self):
        old_home = os.environ.get("HERMES_HOME")
        old_cwd = Path.cwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                home = root / "hermes"
                scratch = home / "cache" / "scratch"
                scratch.mkdir(parents=True)
                work = root / "project"
                work.mkdir()
                os.environ["HERMES_HOME"] = str(home)
                os.chdir(work)
                image = scratch / "photo.png"
                pixels = np.full((80, 120, 3), 255, dtype=np.uint8)
                pixels[10:70, 10:110] = (30, 30, 30)
                Image.fromarray(pixels, mode="RGB").save(image)
                report = measure(
                    {
                        "quad": [[0, 0], [119, 0], [119, 79], [0, 79]],
                        "width_mm": 40,
                        "height_mm": 30,
                        "image": str(image),
                    }
                )
                rectified = Path(report["rectified"])
                self.assertTrue(rectified.is_absolute())
                self.assertEqual(rectified.parent, work.resolve())
                self.assertFalse(str(rectified).startswith(str(scratch.resolve())))
                refused = json.loads(
                    template_tool({"out_dir": str(scratch), "shape": "l_bracket", "no_3mf": True})
                )
                self.assertFalse(refused["ok"])
                self.assertIn("HERMES_HOME/cache", refused["error"])
                self.assertIn("next_step", refused)
        finally:
            os.chdir(old_cwd)
            if old_home is None:
                os.environ.pop("HERMES_HOME", None)
            else:
                os.environ["HERMES_HOME"] = old_home

    def test_template_without_out_dir_uses_the_working_directory(self):
        old_cwd = Path.cwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(tmp)
                summary = json.loads(template_tool({"shape": "l_bracket", "no_3mf": True}))
                self.assertTrue(summary["ok"], summary)
                self.assertEqual(Path(summary["stl"]).parent, Path(tmp).resolve())
                self.assertIn("next_step", summary)
        finally:
            os.chdir(old_cwd)


class BuildToolTests(unittest.TestCase):
    def test_build_runs_in_the_plugin_interpreter_and_times_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            script = work / "build_part.py"
            script.write_text(
                "from pathlib import Path\nPath('made.txt').write_text('hi\\n', encoding='utf-8')\nprint('built')\n",
                encoding="utf-8",
            )
            report = run_build(script, cwd=work, timeout=30)
            self.assertTrue(report["ok"], report)
            self.assertIn("built", report["stdout"])
            self.assertTrue(any(path.endswith("made.txt") for path in report["outputs"]))
            self.assertTrue(all(Path(path).is_absolute() for path in report["outputs"]))
            self.assertTrue(report["interpreter"])
            self.assertIn(SKILL_ID, report["next_step"])
            slow = work / "slow.py"
            slow.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
            timed = run_build(slow, cwd=work, timeout=1)
            self.assertFalse(timed["ok"])
            self.assertTrue(timed["timeout"])
            payload = json.loads(build_tool({"script": str(script), "cwd": str(work), "timeout": 30}))
            self.assertTrue(payload["ok"], payload)
            self.assertEqual(payload["skill_id"], SKILL_ID)


class FlowTextTests(unittest.TestCase):
    def test_every_tool_leads_with_the_skill_id(self):
        for spec in tool_specs():
            self.assertTrue(spec["description"].startswith(SKILL_ID), spec["name"])
            self.assertTrue(spec["schema"]["description"].startswith(SKILL_ID), spec["name"])
        text = (ROOT / "skills" / "photo-to-printable-part" / "SKILL.md").read_text(encoding="utf-8")
        for phrase in (
            "name_vN.stl",
            "photo_part_build",
            "thickness or depth",
            "25 tool calls",
            "l_bracket",
            "stale_validation",
            "--roi",
            "--seed",
        ):
            self.assertIn(phrase, text)
        measured = json.loads(measure_tool({"coin": "euro_1", "points": [[10, 40], [110, 40]]}))
        self.assertTrue(measured["ok"], measured)
        box = measured["reference_bbox"]
        self.assertAlmostEqual(box["x"] + box["w"] / 2.0, 60.0, delta=1.0)
        self.assertAlmostEqual(box["y"] + box["h"] / 2.0, 40.0, delta=1.0)
        self.assertIn("next_step", measured)
        self.assertIn(SKILL_ID, measured["skill_id"])
        with tempfile.TemporaryDirectory() as tmp:
            mesh = Path(tmp) / "part_v1.stl"
            _box_stl(mesh)
            checked = json.loads(validate_tool({"mesh": str(mesh)}))
            self.assertTrue(checked["ok"], checked)
            self.assertIn("photo_part_render", checked["next_step"])


if __name__ == "__main__":
    unittest.main()
