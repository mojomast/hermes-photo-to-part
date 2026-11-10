"""v0.1.22: pane Ready on budget refusal, deliver-after-template, stated-OD scale."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from photopart.hooks import on_post_tool_call, on_pre_tool_call, on_session_end, reset_hooks
from photopart.progress import note_result, settle_project


def _state(project: Path) -> dict:
    return json.loads((project / ".photopart" / "pane.json").read_text(encoding="utf-8"))


def _project(root: Path, name: str = "part") -> Path:
    project = root / name
    project.mkdir()
    return project


class PaneBudgetRefusalTests(unittest.TestCase):
    def test_budget_refused_render_stays_ready_with_a_note(self):
        with tempfile.TemporaryDirectory() as raw:
            project = _project(Path(raw), "gear")
            stl = project / "gear_18t_m1.5_v3.stl"
            stl.write_bytes(b"solid")
            note_result(
                "photo_part_template",
                {"ok": True, "stl": str(stl), "cwd": str(project), "out_dir": str(project)},
            )
            note_result(
                "photo_part_validate",
                {"ok": True, "file": str(stl), "out_dir": str(project)},
            )
            self.assertEqual(_state(project)["status"], "ready")
            note_result(
                "photo_part_render",
                {
                    "ok": False,
                    "refused": True,
                    "budget_refused": "render",
                    "error": "Budget: deliver gear_18t_m1.5_v3.stl now; render refused.",
                    "next_step": "Budget: deliver gear_18t_m1.5_v3.stl now; render refused.",
                    "out_dir": str(project),
                    "cwd": str(project),
                },
            )
            pane = _state(project)
            self.assertEqual(pane["status"], "ready")
            self.assertFalse(pane.get("errors"))
            self.assertTrue(any("Budget:" in item for item in pane.get("warnings") or []))
            self.assertIn("Ready to deliver", pane["message"])
            self.assertIn("gear_18t_m1.5_v3.stl", pane["message"])
            self.assertIn("Budget:", pane["message"])

    def test_genuine_validate_failure_still_errors(self):
        with tempfile.TemporaryDirectory() as raw:
            project = _project(Path(raw), "open")
            stl = project / "body_v1.stl"
            stl.write_bytes(b"solid")
            note_result(
                "photo_part_validate",
                {
                    "ok": False,
                    "file": str(stl),
                    "error": "mesh is open",
                    "failures": ["mesh is open"],
                    "out_dir": str(project),
                    "cwd": str(project),
                },
            )
            pane = _state(project)
            self.assertEqual(pane["status"], "error")
            self.assertTrue(any("open" in item.lower() for item in pane.get("errors") or []))

    def test_session_end_promotes_error_to_ready_when_a_validated_stl_exists(self):
        with tempfile.TemporaryDirectory() as raw:
            project = _project(Path(raw), "gear")
            v1 = project / "gear_v1.stl"
            v3 = project / "gear_v3.stl"
            v1.write_bytes(b"solid")
            v3.write_bytes(b"solid")
            note_result(
                "photo_part_template",
                {"ok": True, "stl": str(v1), "cwd": str(project), "out_dir": str(project)},
            )
            note_result(
                "photo_part_validate",
                {"ok": True, "file": str(v1), "out_dir": str(project)},
            )
            note_result(
                "photo_part_build",
                {"ok": True, "stl": str(v3), "cwd": str(project), "out_dir": str(project)},
            )
            note_result(
                "photo_part_validate",
                {"ok": True, "file": str(v3), "out_dir": str(project)},
            )
            pane_path = project / ".photopart" / "pane.json"
            body = json.loads(pane_path.read_text(encoding="utf-8"))
            body["status"] = "error"
            body["errors"] = ["Budget: deliver gear_v3.stl now; render refused."]
            body["message"] = "Budget: deliver gear_v3.stl now; render refused."
            body["iteration"] = 2
            pane_path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
            from photopart.hooks import _projects

            reset_hooks()
            _projects["sess-gear"] = project
            on_session_end(session_id="sess-gear", completed=True, interrupted=False)
            done = _state(project)
            self.assertEqual(done["status"], "ready")
            self.assertFalse(done.get("errors"))
            self.assertTrue(any("Budget:" in item for item in done.get("warnings") or []))
            self.assertIn("Ready to deliver", done["message"])
            self.assertIn("gear_v3.stl", done["message"])
            self.assertEqual(done["iteration"], 3)

    def test_settle_project_also_promotes_error_with_a_deliverable(self):
        with tempfile.TemporaryDirectory() as raw:
            project = _project(Path(raw), "fitting")
            stl = project / "body_v1.stl"
            stl.write_bytes(b"solid")
            note_result(
                "photo_part_build",
                {"ok": True, "stl": str(stl), "cwd": str(project), "out_dir": str(project)},
            )
            note_result(
                "photo_part_validate",
                {"ok": True, "file": str(stl), "out_dir": str(project)},
            )
            pane_path = project / ".photopart" / "pane.json"
            body = json.loads(pane_path.read_text(encoding="utf-8"))
            body["status"] = "error"
            body["errors"] = ["Budget: deliver body_v1.stl now; render refused."]
            pane_path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
            settle_project(project, ended=True)
            done = _state(project)
            self.assertEqual(done["status"], "ready")
            self.assertIn("body_v1.stl", done["message"])


class DeliverSteerTests(unittest.TestCase):
    def setUp(self):
        reset_hooks()
        self._cwd = Path.cwd()

    def tearDown(self):
        os.chdir(self._cwd)
        reset_hooks()

    def test_after_template_validates_vision_is_blocked_and_one_refine_is_allowed(self):
        from photopart.deliver_steer import REFINE_BLOCK, VISION_BLOCK, note_validated

        with tempfile.TemporaryDirectory() as raw:
            project = _project(Path(raw), "gear")
            stl = project / "gear_18t_m1.5_v1.stl"
            stl.write_bytes(b"solid")
            (project / f"{stl.name}.template.json").write_text(
                json.dumps({"file": str(stl), "shape": "spur_gear", "spec_checks": {"x": 30, "y": 30, "z": 6}}),
                encoding="utf-8",
            )
            os.chdir(project)
            on_post_tool_call(
                "photo_part_template",
                {"shape": "spur_gear", "file": str(stl), "stl": str(stl), "cwd": str(project), "out_dir": str(project)},
                "task",
                "sess-del",
            )
            note_validated(stl, project)
            vision = on_pre_tool_call(
                "vision_analyze",
                {"image": str(project / "photo.jpg")},
                "task",
                "sess-del",
            )
            self.assertIsInstance(vision, dict)
            self.assertEqual(vision.get("action"), "block")
            self.assertIn("Vision loops are blocked", vision["message"])
            self.assertIn("gear_18t_m1.5_v1.stl", vision["message"])
            self.assertIn("photo_part_render", vision["message"])
            self.assertIsNone(
                on_pre_tool_call(
                    "photo_part_measure",
                    {"image": str(project / "photo.jpg"), "cwd": str(project)},
                    "task",
                    "sess-del",
                )
            )
            self.assertIsNone(
                on_pre_tool_call(
                    "photo_part_render",
                    {"file": str(stl), "final": True, "out_dir": str(project)},
                    "task",
                    "sess-del",
                )
            )
            self.assertIsNone(
                on_pre_tool_call(
                    "photo_part_build",
                    {"script": str(project / "build_gear_v2.py"), "cwd": str(project)},
                    "task",
                    "sess-del",
                )
            )
            on_post_tool_call(
                "photo_part_build",
                {"script": str(project / "build_gear_v2.py"), "file": str(project / "gear_18t_m1.5_v2.stl"), "cwd": str(project)},
                "task",
                "sess-del",
            )
            second = on_pre_tool_call(
                "photo_part_build",
                {"script": str(project / "build_gear_v3.py"), "cwd": str(project)},
                "task",
                "sess-del",
            )
            self.assertIsInstance(second, dict)
            self.assertEqual(second.get("action"), "block")
            self.assertIn("one allowed measured refine", second["message"])
            cad = on_pre_tool_call(
                "write_file",
                {"path": str(project / "build_gear_v3.py"), "content": "import trimesh\nmesh.export('gear.stl')\n"},
                "task",
                "sess-del",
            )
            self.assertIsInstance(cad, dict)
            self.assertEqual(cad.get("action"), "block")
            self.assertTrue(VISION_BLOCK)
            self.assertTrue(REFINE_BLOCK)

    def test_validate_of_a_template_sets_a_deliver_hint(self):
        from photopart.deliver_steer import deliver_hint, is_template_mesh

        with tempfile.TemporaryDirectory() as raw:
            project = _project(Path(raw), "gear")
            stl = project / "gear_v1.stl"
            stl.write_bytes(b"solid")
            sidecar = project / "gear_v1.stl.template.json"
            sidecar.write_text(json.dumps({"file": str(stl), "shape": "spur_gear"}), encoding="utf-8")
            self.assertTrue(is_template_mesh(stl))
            hint = deliver_hint(stl)
            self.assertIn("Deliver it now", hint)
            self.assertIn("photo_part_render final=true", hint)
            self.assertIn("one measured refine", hint)
            self.assertIn("vision loop", hint.lower())

    def test_non_template_paths_are_not_steered(self):
        with tempfile.TemporaryDirectory() as raw:
            project = _project(Path(raw), "fitting")
            stl = project / "body_v1.stl"
            stl.write_bytes(b"solid")
            os.chdir(project)
            self.assertIsNone(
                on_pre_tool_call(
                    "vision_analyze",
                    {"image": str(project / "photo.jpg"), "cwd": str(project)},
                    "task",
                    "sess-fit",
                )
            )


class StatedOdScaleTests(unittest.TestCase):
    def test_scale_from_stated_outer_diameter(self):
        from photopart.stated_scale import SCALE_SOURCE, scale_for_mesh, stated_outer_diameter_mm

        with tempfile.TemporaryDirectory() as raw:
            project = _project(Path(raw), "gear")
            stl = project / "gear_v1.stl"
            stl.write_bytes(b"solid")
            (project / "gear_v1.stl.template.json").write_text(
                json.dumps(
                    {
                        "file": str(stl),
                        "shape": "spur_gear",
                        "outer_diameter_mm": 30.0,
                        "spec_checks": {"x": 30.0, "y": 29.7, "z": 6.0},
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(stated_outer_diameter_mm(stl), 30.0)
            photo = project / "photo.png"
            size = 400
            diameter_px = 300
            image = np.full((size, size, 3), 255, dtype=np.uint8)
            yy, xx = np.ogrid[:size, :size]
            circle = (xx - 200) ** 2 + (yy - 200) ** 2 <= (diameter_px / 2) ** 2
            image[circle] = (10, 10, 10)
            Image.fromarray(image).save(photo)
            report = scale_for_mesh(stl, photo)
            self.assertIsNotNone(report, "expected a stated-OD scale from the high-contrast circle")
            self.assertEqual(report["source"], SCALE_SOURCE)
            self.assertEqual(report["label"], "scale from stated OD")
            self.assertIn("guide only", report["note"].lower())
            self.assertAlmostEqual(report["px_per_mm"], 10.0, delta=0.6)

    def test_non_gear_templates_are_not_scaled(self):
        from photopart.stated_scale import stated_outer_diameter_mm

        with tempfile.TemporaryDirectory() as raw:
            project = _project(Path(raw), "hinge")
            stl = project / "hinge_v1.stl"
            stl.write_bytes(b"solid")
            (project / "hinge_v1.stl.template.json").write_text(
                json.dumps({"file": str(stl), "shape": "strap_hinge", "spec_checks": {"x": 80, "y": 40, "z": 4}}),
                encoding="utf-8",
            )
            self.assertIsNone(stated_outer_diameter_mm(stl))


if __name__ == "__main__":
    unittest.main()
