"""Build approval hook and output path checks."""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from photopart.measure import measure

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugin"


def _plugin():
    spec = importlib.util.spec_from_file_location("photo_to_part_plugin", PLUGIN / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rectify_payload(tmp: Path, out: Path, **extra) -> dict:
    image = tmp / "shot.png"
    Image.fromarray(np.zeros((60, 80, 3), dtype=np.uint8)).save(image)
    return {
        "quad": [[0, 0], [79, 0], [79, 59], [0, 59]],
        "width_mm": 40,
        "height_mm": 30,
        "image": str(image),
        "out": str(out),
        **extra,
    }


class BuildApprovalHookTests(unittest.TestCase):
    def test_build_asks_for_approval_and_other_tools_do_not(self):
        hook = _plugin().approve_build
        result = hook(
            tool_name="photo_part_build",
            args={"script": "/project/make.py", "args": ["--size", "4"], "cwd": "/project"},
            task_id="t",
        )
        self.assertEqual(result["action"], "approve")
        self.assertEqual(result["rule_key"], "photo_part_build")
        self.assertEqual(result["message"], "Run /project/make.py --size 4 in /project")
        self.assertIsNone(hook(tool_name="photo_part_validate", args={"mesh": "a.stl"}))
        described = hook(tool_name="photo_part_build", args={"describe": True, "cwd": "/project"})
        self.assertIsNone(described)
        helped = hook(tool_name="photo_part_build", args={"mode": "help"})
        self.assertIsNone(helped)
        encoded = hook(
            tool_name="photo_part_build",
            args='{"script": "/project/make.py", "args": ["--size", "4"], "cwd": "/project"}',
        )
        self.assertEqual(encoded["message"], "Run /project/make.py --size 4 in /project")
        saved = os.environ.get("PHOTOPART_BUILD_APPROVAL")
        os.environ["PHOTOPART_BUILD_APPROVAL"] = "allow"
        try:
            # 0.1.23: the old environment off-switch is gone and changes nothing.
            still = hook(
                tool_name="photo_part_build",
                args={"script": "/project/make.py", "cwd": "/project"},
            )
            self.assertEqual(still["action"], "approve")
        finally:
            if saved is None:
                os.environ.pop("PHOTOPART_BUILD_APPROVAL", None)
            else:
                os.environ["PHOTOPART_BUILD_APPROVAL"] = saved

    def test_skill_rewrite_hook_does_not_itself_ask_for_build_approval(self):
        from photopart.hooks import on_pre_tool_call, reset_hooks

        reset_hooks()
        try:
            self.assertIsNone(
                on_pre_tool_call(
                    tool_name="photo_part_build",
                    args={"script": "/project/make.py", "cwd": "/tmp/project"},
                    session_id="build-gate",
                )
            )
        finally:
            reset_hooks()


class OutputPathTests(unittest.TestCase):
    def test_measure_out_refuses_an_existing_file_and_a_wrong_suffix(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            out = tmp / "flat.png"
            out.write_bytes(b"keep")
            with self.assertRaises(ValueError):
                measure(_rectify_payload(tmp, out))
            self.assertEqual(out.read_bytes(), b"keep")
            with self.assertRaises(ValueError):
                measure(_rectify_payload(tmp, tmp / "flat.txt"))
            report = measure(_rectify_payload(tmp, out, overwrite=True))
            self.assertNotEqual(out.read_bytes(), b"keep", report)
            out.write_bytes(b"keep2")
            forced = measure(_rectify_payload(tmp, out, force=True))
            self.assertNotEqual(out.read_bytes(), b"keep2", forced)

    def test_paths_hermes_refuses_are_not_written(self):
        from photopart.paths import absolute_path

        fake_agent = types.ModuleType("agent")
        fake_safety = types.ModuleType("agent.file_safety")
        fake_safety.get_write_denied_error = (
            lambda path: f"Write denied: '{path}'" if Path(path).name == "protected.json" else None
        )
        saved = {name: sys.modules.get(name) for name in ("agent", "agent.file_safety")}
        sys.modules["agent"] = fake_agent
        sys.modules["agent.file_safety"] = fake_safety
        try:
            with tempfile.TemporaryDirectory() as raw:
                with self.assertRaises(ValueError):
                    absolute_path(Path(raw) / "protected.json")
                self.assertEqual(absolute_path(Path(raw) / "ok.json").name, "ok.json")
                from photopart.stamp import write_sidecar

                mesh = Path(raw) / "part.stl"
                mesh.write_bytes(b"mesh")
                fake_safety.get_write_denied_error = (
                    lambda path: f"Write denied: '{path}'" if str(path).endswith(".validate.json") else None
                )
                with self.assertRaises(ValueError):
                    write_sidecar(mesh, {"ok": True, "failures": []})
                self.assertFalse(Path(str(mesh) + ".validate.json").exists())
        finally:
            for name, module in saved.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module


if __name__ == "__main__":
    unittest.main()
