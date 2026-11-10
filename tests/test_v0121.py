"""v0.1.21: hard gear steering and pane settlement at session end."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from photopart.gear_steer import BLOCK_MESSAGE
from photopart.hooks import (
    HOOKS,
    on_post_tool_call,
    on_pre_llm_call,
    on_pre_tool_call,
    on_session_end,
    reset_hooks,
)
from photopart.progress import note_result


def _state(project: Path) -> dict:
    return json.loads((project / ".photopart" / "pane.json").read_text(encoding="utf-8"))


def _gear_project(root: Path) -> Path:
    project = root / "gear"
    project.mkdir()
    Image.new("RGB", (32, 32), (80, 80, 80)).save(project / "photo.jpg")
    (project / "prompt.txt").write_text(
        "Recreate this steel involute spur gear as a printable STL. "
        "It has 18 teeth. The outside diameter across the tips of the teeth is 30 mm.\n",
        encoding="utf-8",
    )
    return project


def _fitting_project(root: Path) -> Path:
    project = root / "fitting"
    project.mkdir()
    Image.new("RGB", (32, 32), (40, 40, 40)).save(project / "photo.jpg")
    (project / "prompt.txt").write_text(
        "Recreate this pipe fitting as a printable STL. The tube bore is 12 mm.\n",
        encoding="utf-8",
    )
    return project


INVOLUTE = """
import math
import numpy as np
import trimesh

def involute(alpha):
    return math.tan(alpha) - alpha

def gear_profile(teeth=18, module=1.5, pressure_angle=20):
    pts = []
    return np.array(pts)

mesh = trimesh.creation.extrude_polygon(gear_profile(), 6)
mesh.export("gear.stl")
"""


class GearSteerTests(unittest.TestCase):
    def setUp(self):
        reset_hooks()

    def tearDown(self):
        reset_hooks()

    def test_hooks_include_pre_llm_and_session_end(self):
        self.assertEqual(
            [name for name, _callback in HOOKS],
            [
                "pre_tool_call",
                "post_tool_call",
                "transform_tool_result",
                "pre_llm_call",
                "on_session_end",
            ],
        )

    def test_pre_llm_call_does_not_inject_context(self):
        self.assertIsNone(
            on_pre_llm_call(
                session_id="s-gear",
                user_message="Recreate this involute spur gear as a printable STL.",
                conversation_history=[],
                is_first_turn=True,
            )
        )

    def test_write_file_of_involute_script_is_blocked_until_the_template(self):
        with tempfile.TemporaryDirectory() as raw:
            project = _gear_project(Path(raw))
            on_pre_llm_call(
                session_id="s-gear",
                user_message=(project / "prompt.txt").read_text(encoding="utf-8"),
                conversation_history=[],
                is_first_turn=True,
            )
            with patch("photopart.gear_steer._safe_cwd", return_value=project):
                blocked = on_pre_tool_call(
                    tool_name="write_file",
                    args={"path": str(project / "build_gear.py"), "content": INVOLUTE},
                    session_id="s-gear",
                )
            self.assertEqual(blocked, {"action": "block", "message": BLOCK_MESSAGE})
            self.assertIn("photo_part_template", blocked["message"])
            self.assertIn("spur_gear", blocked["message"])

            allowed = on_pre_tool_call(
                tool_name="photo_part_template",
                args={"shape": "spur_gear", "out_dir": str(project), "params": {"teeth": 18, "module": 1.5}},
                session_id="s-gear",
            )
            self.assertIsNone(allowed)
            on_post_tool_call(
                tool_name="photo_part_template",
                args={"shape": "spur_gear", "out_dir": str(project)},
                session_id="s-gear",
                result={"ok": False, "error": "missing face_width"},
            )
            with patch("photopart.gear_steer._safe_cwd", return_value=project):
                after = on_pre_tool_call(
                    tool_name="write_file",
                    args={"path": str(project / "build_gear.py"), "content": INVOLUTE},
                    session_id="s-gear",
                )
            self.assertIsNone(after)
            self.assertTrue((project / ".photopart" / "gear.json").is_file())

    def test_terminal_and_execute_code_are_blocked_in_a_gear_session(self):
        with tempfile.TemporaryDirectory() as raw:
            project = _gear_project(Path(raw))
            (project / "build_gear.py").write_text(INVOLUTE, encoding="utf-8")
            on_pre_llm_call(
                session_id="s-term",
                user_message="18-tooth involute spur gear, printable STL from this photo.",
                conversation_history=[],
            )
            with patch("photopart.gear_steer._safe_cwd", return_value=project):
                terminal = on_pre_tool_call(
                    tool_name="terminal",
                    args={"command": "python3 build_gear.py"},
                    session_id="s-term",
                )
                code = on_pre_tool_call(
                    tool_name="execute_code",
                    args={"code": INVOLUTE},
                    session_id="s-term",
                )
                measure = on_pre_tool_call(
                    tool_name="terminal",
                    args={
                        "command": "python3 -c \"import cv2, numpy as np; im=cv2.imread('photo.jpg'); print(im.shape)\""
                    },
                    session_id="s-term",
                )
                listing = on_pre_tool_call(
                    tool_name="terminal",
                    args={"command": "ls -l"},
                    session_id="s-term",
                )
                build = on_pre_tool_call(
                    tool_name="photo_part_build",
                    args={"script": str(project / "build_gear.py"), "cwd": str(project)},
                    session_id="s-term",
                )
                help_call = on_pre_tool_call(
                    tool_name="photo_part_build",
                    args={"script": str(project / "build_gear.py"), "cwd": str(project), "help": True},
                    session_id="s-term",
                )
            self.assertEqual(terminal["action"], "block")
            self.assertEqual(code["action"], "block")
            self.assertEqual(build["action"], "block")
            self.assertIsNone(measure)
            self.assertIsNone(listing)
            self.assertIsNone(help_call)

    def test_non_gear_part_scripts_are_not_blocked(self):
        with tempfile.TemporaryDirectory() as raw:
            project = _fitting_project(Path(raw))
            script = (
                "import cadquery as cq\n"
                "import trimesh\n"
                "body = cq.Workplane('XY').circle(12).extrude(20)\n"
                "body.val().exportStl('fitting.stl')\n"
            )
            on_pre_llm_call(
                session_id="s-fit",
                user_message=(project / "prompt.txt").read_text(encoding="utf-8"),
                conversation_history=[],
            )
            with patch("photopart.gear_steer._safe_cwd", return_value=project):
                written = on_pre_tool_call(
                    tool_name="write_file",
                    args={"path": str(project / "build_body.py"), "content": script},
                    session_id="s-fit",
                )
                ran = on_pre_tool_call(
                    tool_name="terminal",
                    args={"command": "python3 build_body.py"},
                    session_id="s-fit",
                )
                template = on_pre_tool_call(
                    tool_name="photo_part_template",
                    args={"shape": "plate", "out_dir": str(project)},
                    session_id="s-fit",
                )
            self.assertIsNone(written)
            self.assertIsNone(ran)
            self.assertIsNone(template)

    def test_unrelated_sessions_are_not_policed(self):
        reset_hooks()
        blocked = on_pre_tool_call(
            tool_name="write_file",
            args={"path": "/tmp/build_gear.py", "content": INVOLUTE},
            session_id="coding-only",
        )
        self.assertIsNone(blocked)

    def test_prompt_file_is_enough_without_pre_llm(self):
        with tempfile.TemporaryDirectory() as raw:
            project = _gear_project(Path(raw))
            with patch("photopart.gear_steer._safe_cwd", return_value=project):
                blocked = on_pre_tool_call(
                    tool_name="write_file",
                    args={"path": str(project / "build_gear.py"), "content": INVOLUTE},
                    session_id="s-prompt",
                )
            self.assertEqual(blocked["action"], "block")


class PaneSessionEndTests(unittest.TestCase):
    def setUp(self):
        reset_hooks()

    def tearDown(self):
        reset_hooks()

    def test_session_end_settles_measure_only_to_measured(self):
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw) / "coin"
            project.mkdir()
            photo = project / "photo.png"
            Image.new("RGB", (16, 16), (20, 20, 20)).save(photo)
            note_result(
                "photo_part_measure",
                {
                    "ok": True,
                    "out_dir": str(project),
                    "image": str(photo),
                    "kind": "coin",
                    "coin": "us_quarter",
                    "px_per_mm": 29.8,
                    "part_bbox_mm": {"x": 24.26, "y": 24.26, "z": 0},
                },
            )
            self.assertEqual(_state(project)["status"], "running")
            from photopart.hooks import _projects

            _projects["sess-coin"] = project
            self.assertIsNone(
                on_session_end(
                    session_id="sess-coin",
                    completed=True,
                    interrupted=False,
                    model="deepseek-v4.1-flash",
                    platform="cli",
                )
            )
            done = _state(project)
            self.assertEqual(done["status"], "measured")
            self.assertIn("Session ended", done["message"])
            self.assertIn("Measurement complete", done["message"])

    def test_session_end_settles_a_validated_part_to_ready(self):
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw) / "fitting"
            project.mkdir()
            stl = project / "body_v1.stl"
            stl.write_bytes(b"solid")
            note_result(
                "photo_part_build",
                {"ok": True, "stl": str(stl), "cwd": str(project), "out_dir": str(project)},
            )
            note_result(
                "photo_part_validate",
                {"ok": True, "file": str(stl), "spec": str(project / "spec.json"), "out_dir": str(project)},
            )
            # Passing validate already marks Ready; force a running file and settle.
            pane = project / ".photopart" / "pane.json"
            body = json.loads(pane.read_text(encoding="utf-8"))
            if body.get("status") == "ready":
                body["status"] = "running"
                pane.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
            from photopart.hooks import _projects

            _projects["sess-fit"] = project
            on_session_end(session_id="sess-fit", completed=True, interrupted=False)
            self.assertEqual(_state(project)["status"], "ready")
            self.assertIn("Ready to deliver", _state(project)["message"])

    def test_session_end_settles_an_empty_run_to_incomplete(self):
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw) / "empty"
            project.mkdir()
            note_result("photo_part_heal", {"ok": True, "cwd": str(project), "out": str(project / "scan.stl")})
            self.assertEqual(_state(project)["status"], "running")
            from photopart.hooks import _projects

            _projects["sess-empty"] = project
            on_session_end(session_id="sess-empty", completed=False, interrupted=True)
            self.assertEqual(_state(project)["status"], "incomplete")

    def test_session_end_ignores_unknown_sessions(self):
        self.assertIsNone(on_session_end(session_id="no-such", completed=True, interrupted=False))


if __name__ == "__main__":
    unittest.main()
