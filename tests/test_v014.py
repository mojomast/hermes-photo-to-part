"""v0.1.4: feature solids, overlay pose, spec checks, snapshots, final render."""

from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw

from photopart.build_run import run_build
from photopart.features import (
    external_thread,
    hex_screw,
    hex_standoff,
    internal_thread,
    knurl,
)
from photopart.flow import SKILL_ID
from photopart.overlay import search_alignment
from photopart.parts import build_shape
from photopart.render import run_render
from photopart.tools import build_tool, template_tool
from photopart.validate import run_validate

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "photo-to-printable-part" / "SKILL.md"


def _stl(path: Path, extents=(10, 20, 30)) -> None:
    trimesh.creation.box(extents=extents).export(path)


def _rotated_rect(size: int, width: int, height: int, angle_deg: float) -> Image.Image:
    image = Image.new("RGB", (size, size), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    half_w = width / 2.0
    half_h = height / 2.0
    corners = np.array([[-half_w, -half_h], [half_w, -half_h], [half_w, half_h], [-half_w, half_h]])
    theta = math.radians(angle_deg)
    rotation = np.array([[math.cos(theta), -math.sin(theta)], [math.sin(theta), math.cos(theta)]])
    placed = corners @ rotation.T
    placed[:, 0] += size / 2.0
    placed[:, 1] += size / 2.0
    draw.polygon([tuple(point) for point in placed], fill=(20, 24, 28))
    return image


class FeatureTests(unittest.TestCase):
    def test_threads_knurl_and_fasteners_are_one_shell(self):
        external = external_thread(designation="M3", length=8)
        self.assertTrue(external.is_watertight)
        self.assertEqual(len(external.split(only_watertight=False)), 1)
        self.assertAlmostEqual(float(external.extents[2]), 8.0, delta=0.35)
        self.assertAlmostEqual(float(max(external.extents[0], external.extents[1])), 3.0, delta=0.2)
        internal = internal_thread(designation="M3", length=6)
        solid = math.pi * (3.5 ** 2) * 6.0
        self.assertTrue(internal.is_watertight)
        self.assertEqual(len(internal.split(only_watertight=False)), 1)
        self.assertLess(float(internal.volume), solid * 0.98)
        for style in ("straight", "diamond"):
            body = knurl(style, diameter=8, length=6, count=12)
            self.assertTrue(body.is_watertight, style)
            self.assertEqual(len(body.split(only_watertight=False)), 1, style)
        screw = hex_screw(designation="M3", length=6)
        self.assertEqual(len(screw.split(only_watertight=False)), 1)
        head = screw.vertices[screw.vertices[:, 2] > 6.2]
        radius = np.hypot(head[:, 0], head[:, 1])
        self.assertAlmostEqual(float(radius.max()), 5.5 / math.sqrt(3.0), delta=0.08)
        standoff = hex_standoff(designation="M3", body_length=6, thread_length=3)
        self.assertTrue(standoff.is_watertight)
        self.assertEqual(len(standoff.split(only_watertight=False)), 1)
        cap, doc = build_shape("bottle_cap")
        self.assertEqual(doc["shells"], 1)
        self.assertTrue(cap.is_watertight)
        self.assertEqual(len(cap.split(only_watertight=False)), 1)


class BuildRepairTests(unittest.TestCase):
    def test_overlapping_shells_are_unioned(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            script = work / "overlap.py"
            script.write_text(
                "import trimesh\n"
                "left = trimesh.creation.box((10, 10, 10))\n"
                "right = trimesh.creation.box((10, 10, 10))\n"
                "right.apply_translation((5, 0, 0))\n"
                "trimesh.util.concatenate([left, right]).export('overlap.stl')\n",
                encoding="utf-8",
            )
            report = run_build(script, cwd=work, timeout=60)
            self.assertTrue(report["ok"], report.get("error"))
            row = next(item for item in report["shells"] if item["file"].endswith("overlap.stl"))
            self.assertEqual(row["shells_before"], 2)
            self.assertEqual(row["shells_after"], 1)
            self.assertTrue(row["union_applied"])
            merged = trimesh.load(work / "overlap.stl", force="mesh")
            self.assertEqual(len(merged.split(only_watertight=False)), 1)

    def test_build_error_is_the_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            script = work / "bad.py"
            script.write_text('raise ValueError("boom-thread")\n', encoding="utf-8")
            report = run_build(script, cwd=work, timeout=30)
            self.assertFalse(report["ok"])
            first = report["error"].splitlines()[0]
            self.assertTrue(first.startswith("ValueError"), report["error"])
            self.assertIn("boom-thread", first)
            self.assertFalse(report["error"].startswith("Skill id"))
            self.assertFalse(report["error"].startswith("build exited"))
            payload = json.loads(build_tool({"script": str(script), "cwd": str(work), "timeout": 30}))
            self.assertTrue(payload["error"].startswith("ValueError"), payload["error"])
            self.assertIn(SKILL_ID, payload["next_step"])
            slow = work / "slow.py"
            slow.write_text("import time\ntime.sleep(5)\n", encoding="utf-8")
            timed = run_build(slow, cwd=work, timeout=0.4)
            self.assertTrue(timed["timeout"])
            self.assertTrue(timed["error"].startswith("TimeoutExpired"), timed["error"])


class OverlayPoseTests(unittest.TestCase):
    def test_auto_fit_finds_rotation_mirror_and_view(self):
        foreground = np.zeros((100, 100), dtype=bool)
        foreground[20:70, 20:35] = True
        foreground[20:35, 20:70] = True
        mirrored = np.fliplr(foreground)
        pose = search_alignment(mirrored, foreground)
        self.assertTrue(pose["mirror"])
        self.assertGreater(pose["iou"], 0.75)
        box = trimesh.creation.box(extents=(80, 4, 16))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            photo = root / "photo.png"
            _rotated_rect(400, 48, 240, 45).save(photo)
            manifest = __import__("photopart.render", fromlist=["render_views"]).render_views(
                box,
                root / "views",
                photo=photo,
                photo_scale=3.0,
                overlay_fit="auto",
                pixels=48,
                samples=1,
            )
            self.assertEqual(manifest["overlay_view"], "front")
            self.assertFalse(manifest["overlay_mirror"])
            angle = float(manifest["overlay_rotation_deg"]) % 360.0
            distance = min(abs(angle - 45.0), abs(angle - 225.0))
            self.assertLess(distance, 8.0, manifest["overlay_rotation_deg"])
            self.assertGreater(manifest["overlay_iou"], 0.45)
            straight = root / "straight.png"
            pixels = np.full((400, 400, 3), 255, dtype=np.uint8)
            pixels[40:240, 30:130] = (20, 24, 28)
            Image.fromarray(pixels, mode="RGB").save(straight)
            aligned = trimesh.creation.box(extents=(40, 10, 20))
            report = __import__("photopart.render", fromlist=["render_views"]).render_views(
                aligned,
                root / "aligned",
                photo=straight,
                photo_scale=5.0,
                overlay_fit="auto",
                pixels=48,
                samples=1,
            )
            self.assertGreater(report["overlay_iou"], 0.55)
            self.assertFalse(report["overlay_mirror"])
            wrapped = float(report["overlay_rotation_deg"]) % 360.0
            self.assertLess(min(wrapped, 360.0 - wrapped), 8.0)
            self.assertEqual(report["overlay_view"], "front")


class HistoryTests(unittest.TestCase):
    def test_overwrite_keeps_a_snapshot_and_reports_a_missing_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "part"
            first = json.loads(template_tool({"out_dir": str(out), "shape": "plate", "no_3mf": True}))
            self.assertTrue(first["ok"], first)
            second = json.loads(
                template_tool({"out_dir": str(out), "shape": "plate", "no_3mf": True, "overwrite": True})
            )
            self.assertTrue(second["ok"], second)
            history = out / ".p2p_history"
            self.assertTrue(history.is_dir())
            self.assertTrue(any(path.name.startswith("plate.stl.") for path in history.iterdir()))
            from photopart.heal import run_heal

            src = root / "scan.stl"
            _stl(src, (12, 8, 4))
            code, healed = run_heal([str(src), "--out", str(root / "leaf_v2.stl")])
            self.assertEqual(code, 0, healed)
            self.assertEqual(healed["missing_earlier"], ["leaf_v1.stl"])


class SpecTests(unittest.TestCase):
    def test_spec_and_dim_fail_on_drift(self):
        hinge, _doc = build_shape("hinge")
        plate, _plate = build_shape("plate")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hinge_path = root / "hinge.stl"
            hinge.export(hinge_path)
            code, ok = run_validate(
                str(hinge_path),
                expected_shells=2,
                spec={"knuckles": 4, "knuckle_axis": "x"},
            )
            self.assertEqual(code, 0, ok)
            code, drifted = run_validate(
                str(hinge_path),
                expected_shells=2,
                spec={"knuckles": 5, "knuckle_axis": "x"},
            )
            self.assertEqual(code, 2)
            self.assertFalse(drifted["ok"])
            self.assertTrue(any("knuckles" in item for item in drifted["failures"]))
            plate_path = root / "plate.stl"
            plate.export(plate_path)
            code, holes = run_validate(str(plate_path), spec={"hole_count": 1})
            self.assertEqual(code, 0, holes)
            code, wrong = run_validate(str(plate_path), spec={"hole_count": 3})
            self.assertFalse(wrong["ok"])
            box = root / "box.stl"
            _stl(box, (10, 20, 30))
            spec = root / "spec.json"
            spec.write_text(
                json.dumps({"x": 10, "y": 20, "z": 30, "tolerance": 0.4, "shells": 1}),
                encoding="utf-8",
            )
            code, matched = run_validate(str(box), spec=str(spec))
            self.assertEqual(code, 0, matched)
            code, off = run_validate(str(box), dims=["x=12±0.2", "y=20+/-0.2"])
            self.assertEqual(code, 2)
            self.assertFalse(off["ok"])
            self.assertTrue(any(item.startswith("spec x") for item in off["failures"]))


class FinalAndSidecarTests(unittest.TestCase):
    def test_final_render_requires_a_fresh_sidecar_and_json_out_is_not_a_second_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mesh = root / "part_v2.stl"
            _stl(mesh, (16, 8, 4))
            code, refused = run_render([str(mesh), "--out-dir", str(root / "final"), "--final"])
            self.assertEqual(code, 2)
            self.assertFalse(refused["ok"])
            self.assertTrue(refused["needs_validation"])
            self.assertFalse((root / "final" / "front.png").exists())
            code, preview = run_render([str(mesh), "--out-dir", str(root / "preview")])
            self.assertEqual(code, 2, preview)
            self.assertTrue(preview["unvalidated"])
            self.assertTrue(preview["needs_validation"])
            self.assertFalse((root / "preview" / "front.png").exists())
            other = root / "part_v2.validate.json"
            code, checked = run_validate(str(mesh), json_out=str(other))
            self.assertEqual(code, 0, checked)
            self.assertFalse(other.exists())
            self.assertTrue(Path(str(mesh) + ".validate.json").is_file())
            self.assertIn("part_v2.stl.validate.json", checked["sidecar_note"])
            self.assertIn("not written", checked["sidecar_note"])
            code, again = run_render([str(mesh), "--out-dir", str(root / "preview")])
            self.assertEqual(code, 0, again)
            self.assertFalse(again["unvalidated"])
            self.assertFalse(again["needs_validation"])
            code, final = run_render([str(mesh), "--out-dir", str(root / "shipped"), "--final"])
            self.assertEqual(code, 0, final)
            self.assertFalse(final["needs_validation"])
            self.assertFalse(final["unvalidated"])
            self.assertTrue((root / "shipped" / "front.png").is_file())
            later = root / "part_v3.stl"
            _stl(later, (16, 8, 5))
            code, delivered = run_render([str(mesh), "--out-dir", str(root / "again"), "--final", "--overwrite"])
            self.assertEqual(code, 0, delivered)
            self.assertTrue(str(delivered.get("best_version")).endswith("part_v2.stl"))
            self.assertTrue((root / "again" / "front.png").is_file())
            self.assertTrue((root / "again" / "sheet.png").is_file())


class SkillTextTests(unittest.TestCase):
    def test_skill_forbids_deleting_outputs_and_names_the_helpers(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("spec.json", text)
        self.assertIn("deviations", text)
        self.assertIn("from photopart.features import external_thread, internal_thread, knurl, revolve_profile, sweep_path, hex_screw, hex_standoff", text)
        self.assertIn(".p2p_history", text)
        self.assertIn("rm", text)
        self.assertIn("final", text)
        self.assertIn("skill_view(\"photo-to-part:photo-to-printable-part\")", text)


if __name__ == "__main__":
    unittest.main()
