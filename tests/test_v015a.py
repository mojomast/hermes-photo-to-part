"""v0.1.5 part A: knuckle probe, template spec checks, validation history, render gate."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import trimesh

from photopart.build_run import run_build
from photopart.parts import build_shape, write_shape
from photopart.render import run_render
from photopart.spec import count_knuckles
from photopart.stamp import write_sidecar
from photopart.tools import template_tool
from photopart.validate import run_validate

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugin" / "skills" / "photo-to-printable-part" / "SKILL.md"


def _pinned_knuckles(count: int):
    """A continuous pin with ``count`` overlapping tubes. One shell, N knuckles."""
    import manifold3d

    from photopart.manifold_util import as_mesh

    length = 100.0
    gap = 0.5
    seg = (length - (count - 1) * gap) / count
    pin = manifold3d.Manifold.cylinder(length, 1.5, 1.5, 32, False).rotate((0.0, 90.0, 0.0))
    tubes = [pin]
    start = 0.0
    for _ in range(count):
        outer = manifold3d.Manifold.cylinder(seg, 3.0, 3.0, 32, False)
        inner = manifold3d.Manifold.cylinder(seg + 0.4, 1.2, 1.2, 32, False).translate((0.0, 0.0, -0.2))
        tube = manifold3d.Manifold.batch_boolean([outer, inner], manifold3d.OpType.Subtract)
        tubes.append(tube.rotate((0.0, 90.0, 0.0)).translate((start, 0.0, 0.0)))
        start += seg + gap
    body = manifold3d.Manifold.batch_boolean(tubes, manifold3d.OpType.Add)
    return as_mesh(body)


class KnuckleProbeTests(unittest.TestCase):
    def test_hinge_template_counts_three_five_and_seven(self):
        default, doc = build_shape("hinge")
        self.assertEqual(doc["parameters"]["knuckles"], 4)
        self.assertEqual(doc["shells"], 2)
        self.assertEqual(count_knuckles(default, "x"), 4)
        for count in (3, 5, 7):
            mesh, built = build_shape("hinge", {"knuckles": count})
            self.assertTrue(mesh.is_watertight, count)
            self.assertEqual(len(mesh.split(only_watertight=False)), 2, count)
            self.assertEqual(built["parameters"]["knuckles"], count)
            self.assertEqual(count_knuckles(mesh, "x"), count, count)

    def test_continuous_pin_is_not_reported_as_one_knuckle(self):
        for count in (3, 5, 7):
            mesh = _pinned_knuckles(count)
            self.assertTrue(mesh.is_watertight, count)
            self.assertEqual(count_knuckles(mesh, "x"), count, count)


class TemplateSpecTests(unittest.TestCase):
    def test_dropped_template_check_fails_and_a_full_spec_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            written = write_shape(root, "hinge", {"knuckles": 5}, write_3mf=False)
            sidecar = Path(str(written["stl"]) + ".template.json")
            self.assertTrue(sidecar.is_file())
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
            checks = payload["spec_checks"]
            self.assertEqual(checks["knuckles"], 5)
            self.assertEqual(checks["shells"], 2)
            self.assertEqual(checks["knuckle_axis"], "x")
            params = json.loads((root / "params.json").read_text(encoding="utf-8"))
            self.assertEqual(params["spec_checks"]["knuckles"], 5)
            code, dropped = run_validate(str(written["stl"]), expected_shells=2, spec={"shells": 2, "x": checks["x"]})
            self.assertEqual(code, 2)
            self.assertFalse(dropped["ok"])
            self.assertTrue(any("dropped template check knuckles" in item for item in dropped["failures"]))
            self.assertIn("Do not remove a check the template emitted.", " ".join(dropped["failures"]))
            spec = {
                "x": checks["x"],
                "y": checks["y"],
                "z": checks["z"],
                "shells": checks["shells"],
                "knuckles": checks["knuckles"],
                "knuckle_axis": "x",
                "tolerance": 0.5,
            }
            code, matched = run_validate(str(written["stl"]), expected_shells=2, spec=spec)
            self.assertEqual(code, 0, matched)
            code, again = run_validate(str(written["stl"]), expected_shells=2, spec=spec)
            self.assertEqual(code, 0, again)
            self.assertEqual(len(again["history"]), 2)
            self.assertEqual(again["history"][-1]["sha256"], matched["sha256"])
            self.assertEqual(again["history"][0]["sha256"], dropped["sha256"])
            stored = json.loads(Path(str(written["stl"]) + ".validate.json").read_text(encoding="utf-8"))
            self.assertEqual(stored["sha256"], again["sha256"])
            self.assertEqual(stored["history"][-1]["sha256"], matched["sha256"])
            self.assertNotIn("history", stored["history"][0])

    def test_versioned_copy_still_sees_the_template_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            written = write_shape(root, "hinge", {"knuckles": 3}, write_3mf=False)
            versioned = root / "hinge_v2.stl"
            versioned.write_bytes(written["stl"].read_bytes())
            code, report = run_validate(str(versioned), expected_shells=2)
            self.assertEqual(code, 2)
            self.assertTrue(any("knuckles" in item for item in report["failures"]))


class HistoryAndRenderTests(unittest.TestCase):
    def test_history_is_capped_and_versioned_render_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mesh = root / "cap.stl"
            trimesh.creation.box(extents=(10, 12, 14)).export(mesh)
            for index in range(22):
                write_sidecar(mesh, {"ok": True, "failures": [], "n": index})
            stored = json.loads(Path(str(mesh) + ".validate.json").read_text(encoding="utf-8"))
            self.assertEqual(stored["n"], 21)
            self.assertEqual(len(stored["history"]), 20)
            self.assertNotIn("history", stored["history"][-1])
            versioned = root / "part_v1.stl"
            trimesh.creation.box(extents=(16, 8, 4)).export(versioned)
            code, refused = run_render([str(versioned), "--out-dir", str(root / "views")])
            self.assertEqual(code, 2, refused)
            self.assertTrue(refused["unvalidated"])
            self.assertFalse(refused["ok"])
            self.assertFalse((root / "views" / "front.png").exists())
            plain = root / "box.stl"
            trimesh.creation.box(extents=(16, 8, 4)).export(plain)
            code, preview = run_render([str(plain), "--out-dir", str(root / "plain")])
            self.assertEqual(code, 0, preview)
            self.assertTrue(preview["unvalidated"])
            self.assertTrue((root / "plain" / "front.png").is_file())

    def test_build_and_template_nudge_until_spec_json_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            script = work / "bad.py"
            script.write_text("raise RuntimeError('nope-a')\n", encoding="utf-8")
            report = run_build(script, cwd=work, timeout=30)
            self.assertFalse(report["ok"])
            self.assertIn("photo_part_validate", report["next_step"])
            self.assertTrue(report["next_step"].startswith("No spec.json"))
            self.assertIn("spec_warning", report)
            summary = json.loads(template_tool({"out_dir": str(work / "part"), "shape": "l_bracket", "no_3mf": True}))
            self.assertTrue(summary["ok"], summary)
            self.assertEqual(summary["spec_checks"]["shells"], 1)
            self.assertIn("x", summary["spec_checks"])
            self.assertIn("spec_warning", summary)
            self.assertIn("No spec.json", summary["next_step"])
            self.assertIn("photo_part_validate", summary["next_step"])
            (work / "spec.json").write_text('{"x": 50}\n', encoding="utf-8")
            (work / "part" / "spec.json").write_text('{"x": 50}\n', encoding="utf-8")
            again = run_build(script, cwd=work, timeout=30)
            self.assertNotIn("spec_warning", again)
            self.assertIn("photo_part_validate", again["next_step"])
            second = json.loads(
                template_tool(
                    {"out_dir": str(work / "part"), "shape": "l_bracket", "no_3mf": True, "overwrite": True}
                )
            )
            self.assertTrue(second["ok"], second)
            self.assertNotIn("spec_warning", second)


class SkillOrderTests(unittest.TestCase):
    def test_spec_json_is_the_first_step(self):
        text = SKILL.read_text(encoding="utf-8")
        order = text.split("## Order", 1)[1]
        step1 = order.split("1. ", 1)[1].split("2. ", 1)[0]
        self.assertIn("spec.json", step1)
        self.assertNotIn("photo_part_measure", step1)
        self.assertLess(order.index("spec.json"), order.index("photo_part_measure"))
        self.assertIn("40 tool calls", text)
        self.assertIn("deviations", text)
        self.assertIn("unvalidated", text)
        self.assertIn("history", text)


if __name__ == "__main__":
    unittest.main()
