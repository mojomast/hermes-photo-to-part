"""Part studio progress events and the pane backend.

The desktop file is optional. These tests never import FastAPI and never change
tool schemas, the build approval decision, or the eval read block.
"""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from photopart.build_gate import eval_read_block
from photopart.hooks import HOOKS
from photopart.pane import get_run, list_runs, read_media, safe_image
from photopart.paths import plugin_root
from photopart.progress import note_approval, note_result, note_start
from photopart.tools import TOOL_NAMES, tool_specs

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugin"
DESKTOP = PLUGIN / "desktop"


def _plugin_module():
    spec = importlib.util.spec_from_file_location("photo_to_part_plugin_pane", PLUGIN / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _builder():
    spec = importlib.util.spec_from_file_location("photo_to_part_pane_build", DESKTOP / "build_plugin.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self._saved_home = os.environ.get("HERMES_HOME")
        self._saved_approval = os.environ.get("PHOTOPART_BUILD_APPROVAL")
        os.environ.pop("PHOTOPART_BUILD_APPROVAL", None)

    def tearDown(self):
        if self._saved_home is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = self._saved_home
        if self._saved_approval is None:
            os.environ.pop("PHOTOPART_BUILD_APPROVAL", None)
        else:
            os.environ["PHOTOPART_BUILD_APPROVAL"] = self._saved_approval

    def test_measure_render_and_approval_update_one_run(self):
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw) / "hermes"
            project = Path(raw) / "plate"
            renders = project / "renders"
            renders.mkdir(parents=True)
            os.environ["HERMES_HOME"] = str(home)
            photo = project / "photo.png"
            overlay = renders / "overlay.png"
            front = renders / "front.png"
            Image.new("RGB", (24, 24), (210, 200, 180)).save(photo)
            Image.new("RGB", (24, 24), (40, 90, 140)).save(overlay)
            Image.new("RGB", (24, 24), (180, 180, 180)).save(front)
            stl = project / "plate_v2.stl"
            scad = project / "plate_v2.scad"
            stl.write_bytes(b"solid")
            scad.write_text("cube(1);", encoding="utf-8")

            note_result(
                "photo_part_measure",
                {
                    "ok": True,
                    "out_dir": str(project),
                    "image": str(photo),
                    "part": "plate clip",
                    "kind": "coin",
                    "coin": "us_quarter",
                    "px_per_mm": 4.5,
                    "scale_uncertainty_pct": 2.1,
                    "part_bbox_mm": {"x": 51, "y": 72.6, "z": 6},
                    "extents_mm": {"x": 51, "y": 72.6, "z": 6},
                },
            )
            note_approval(str(project), "Run make.py in the project", "photo_part_build")
            waiting = _state(project)
            self.assertEqual(waiting["status"], "waiting")
            self.assertEqual(waiting["stage"], "approval")
            self.assertEqual(waiting["approval"]["rule_key"], "photo_part_build")
            self.assertIn("scale", waiting["done_stages"])
            self.assertEqual(waiting["metrics"]["scale_source"], "us quarter")
            self.assertEqual(waiting["metrics"]["scale_confidence"], "±2.1%")
            self.assertEqual(waiting["metrics"]["dimensions"], "51 × 72.6 × 6 mm")

            note_start("photo_part_build", {"cwd": str(project), "script": str(project / "make.py")})
            self.assertEqual(_state(project)["approval"]["status"], "approved")
            note_result(
                "photo_part_validate",
                {"ok": True, "file": str(stl), "spec": str(project / "spec.json"), "out_dir": str(project)},
            )
            note_result(
                "photo_part_render",
                {
                    "ok": True,
                    "mesh": str(project / "plate_v1.stl"),
                    "out_dir": str(project),
                    "overlay": str(overlay),
                    "overlay_iou": 0.42,
                    "overlay_iou_label": "untrusted",
                    "alignment": {"iou": 0.42, "iou_trusted": False, "iou_trust_reason": "overlay fit is low"},
                    "views": [str(front)],
                },
            )
            note_start("photo_part_render", {"mesh": str(stl), "out_dir": str(renders)})
            mid = _state(project)
            self.assertEqual(mid["status"], "running")
            self.assertIn("Refinement 2", mid["message"])
            self.assertEqual(len(mid["iterations"]), 1)

            note_result(
                "photo_part_render",
                {
                    "ok": True,
                    "mesh": str(stl),
                    "stl": str(stl),
                    "scad": str(scad),
                    "out_dir": str(project),
                    "overlay": str(overlay),
                    "compare_front": str(front),
                    "overlay_iou": 0.86,
                    "overlay_iou_label": "measured",
                    "alignment": {"iou": 0.86, "iou_trusted": True},
                    "views": [str(front)],
                    "final": True,
                },
            )
            done = _state(project)
            self.assertEqual(done["status"], "ready")
            self.assertEqual(done["metrics"]["iou"], 0.86)
            self.assertEqual(done["metrics"]["trust"], "trusted")
            self.assertNotIn("overlay fit is low", done["warnings"])
            self.assertEqual([item["n"] for item in done["iterations"]], [1, 2])
            self.assertEqual(done["iterations"][-1]["iou"], 0.86)
            kinds = {item["kind"] for item in done["outputs"]}
            self.assertIn("STL", kinds)
            self.assertIn("SCAD", kinds)

            listed = list_runs()
            self.assertTrue(listed["ok"])
            self.assertEqual(listed["runs"][0]["id"], done["id"])
            view = get_run(done["id"])
            self.assertTrue(view["ok"], view)
            self.assertEqual(view["run"]["metrics"]["trust"], "trusted")
            self.assertTrue(any(item["path"] == "plate_v2.stl" for item in view["run"]["outputs"]))
            self.assertTrue(view["run"]["images"]["overlay"].startswith("data:image/jpeg;base64,"))
            self.assertEqual(view["run"]["stages"][-1]["id"], "refine")
            self.assertEqual(len(view["run"]["iterations"]), 2)
            media = read_media(done["id"], "renders/overlay.png")
            self.assertTrue(media["ok"], media)
            self.assertTrue(media["data_url"].startswith("data:image/jpeg;base64,"))

    def test_help_plugin_dir_and_eval_trees_are_not_written(self):
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw) / "job"
            project.mkdir()
            from photopart.tools import template_tool

            described = json.loads(template_tool({"help": True, "shape": "l_bracket", "out_dir": str(project)}))
            self.assertTrue(described["ok"], described)
            self.assertFalse((project / ".photopart").exists())
            self.assertEqual(list(project.iterdir()), [])

            root = plugin_root()
            self.assertIsNotNone(root)
            note_result("photo_part_measure", {"ok": True, "out_dir": str(root), "px_per_mm": 2, "kind": "ruler"})
            self.assertFalse((root / ".photopart" / "pane.json").exists())

            blocked = Path(raw) / "evals" / "case"
            blocked.mkdir(parents=True)
            note_result("photo_part_measure", {"ok": True, "out_dir": str(blocked), "px_per_mm": 2})
            self.assertFalse((blocked / ".photopart").exists())
            regression = Path(raw) / "tests" / "regression" / "mesh"
            regression.mkdir(parents=True)
            note_result("photo_part_render", {"ok": True, "out_dir": str(regression), "overlay_iou": 0.5})
            self.assertFalse((regression / ".photopart").exists())

    def test_media_stays_inside_the_project_and_rejects_the_canary(self):
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw) / "hermes"
            project = Path(raw) / "part"
            project.mkdir()
            os.environ["HERMES_HOME"] = str(home)
            photo = project / "photo.png"
            Image.new("RGB", (8, 8), (20, 20, 20)).save(photo)
            leaked = project / "note.png"
            leaked.write_bytes(photo.read_bytes() + b"\np2p-canary-test\n")
            note_result(
                "photo_part_measure",
                {"ok": True, "out_dir": str(project), "image": str(photo), "px_per_mm": 3, "kind": "ruler"},
            )
            run = _state(project)["id"]
            self.assertIsNone(safe_image(project, "../photo.png"))
            self.assertIsNone(safe_image(project, "/etc/passwd"))
            self.assertIsNone(safe_image(project, "note.png"))
            outside = read_media(run, "../photo.png")
            self.assertFalse(outside["ok"])
            self.assertNotIn("data_url", outside)
            self.assertFalse(read_media(run, "note.png")["ok"])
            self.assertTrue(read_media(run, "photo.png")["ok"])
            missing = get_run("no-such-run")
            self.assertFalse(missing["ok"])

    def test_a_failing_progress_write_does_not_change_approval_or_the_eval_block(self):
        module = _plugin_module()
        with patch("photopart.progress.note_approval", side_effect=RuntimeError("pane down")):
            decision = module.approve_build(
                tool_name="photo_part_build",
                args={"script": "/project/make.py", "args": ["--size", "4"], "cwd": "/project"},
            )
        self.assertEqual(decision["action"], "approve")
        self.assertEqual(decision["rule_key"], "photo_part_build")
        self.assertEqual(decision["message"], "Run /project/make.py --size 4 in /project")
        self.assertIsNone(module.approve_build(tool_name="photo_part_build", args={"describe": True}))
        blocked = eval_read_block("terminal", {"command": "cat evals/runner.py"})
        self.assertEqual(blocked["action"], "block")

    def test_errors_are_recorded_and_broadcast_is_optional(self):
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw) / "part"
            project.mkdir()
            note_start("photo_part_validate", {"mesh": str(project / "part_v1.stl"), "cwd": str(project)})
            note_result("photo_part_validate", {"ok": False, "error": "mesh is open", "cwd": str(project)})
            state = _state(project)
            self.assertEqual(state["status"], "error")
            self.assertIn("mesh is open", state["errors"][0])
            self.assertTrue(state["events"])


class PaneContractTests(unittest.TestCase):
    def test_tools_hooks_and_schemas_stay_the_same_shape(self):
        self.assertEqual(
            list(TOOL_NAMES),
            [
                "photo_part_validate",
                "photo_part_render",
                "photo_part_heal",
                "photo_part_template",
                "photo_part_measure",
                "photo_part_build",
            ],
        )
        self.assertEqual([name for name, _callback in HOOKS], ["pre_tool_call", "post_tool_call", "transform_tool_result", "pre_llm_call", "on_session_end"])
        for spec in tool_specs():
            properties = spec["schema"]["parameters"]["properties"]
            for key in properties:
                self.assertNotIn("pane", key)
                self.assertNotIn("progress", key)
            self.assertIn("calls_used", properties)

    def test_desktop_bundle_matches_sources_and_imports_only_the_sdk(self):
        import re

        bundled = (DESKTOP / "plugin.js").read_text(encoding="utf-8")
        self.assertEqual(bundled, _builder().render_plugin())
        self.assertIn('id: "photo-to-part"', bundled)
        self.assertIn('area: "panes"', bundled)
        self.assertIn("function mountPane", bundled)
        self.assertIn("plugin.photo-to-part.run.updated", bundled)
        self.assertIn("Part studio", bundled)
        imports = re.findall(r"""from\s+["']([^"']+)["']""", bundled)
        self.assertEqual(sorted(set(imports)), ["@hermes/plugin-sdk", "react", "react/jsx-runtime"])
        manifest = json.loads((PLUGIN / "dashboard" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "photo-to-part")
        self.assertEqual(manifest["api"], "plugin_api.py")
        source = (PLUGIN / "dashboard" / "plugin_api.py").read_text(encoding="utf-8")
        for route in ("/health", "/runs", "/runs/{run_id}", "/media"):
            self.assertIn(route, source)


def _state(project: Path) -> dict:
    return json.loads((project / ".photopart" / "pane.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
