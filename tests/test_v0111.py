"""v0.1.11: hooks, coin scale, thread regions, scorer, overlay fit, standards."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from evals.runner import (
    HermesV0217Context,
    _coin_scene,
    _thread_from_script,
    load_plugin_register,
    score_hermes_session,
    score_transcript,
)
from photopart.budget import _resolve_used
from photopart.canary import EVAL_CANARY
from photopart.flow import SKILL_ID
from photopart.hooks import (
    hook_call_count,
    on_post_tool_call,
    on_pre_tool_call,
    on_transform_tool_result,
    reset_hooks,
)
from photopart.measure import measure
from photopart.overlay import fit_metrics
from photopart.sessions import names_from_json
from photopart.standards import check_standard

ROOT = Path(__file__).resolve().parents[1]


class HookTests(unittest.TestCase):
    def setUp(self):
        reset_hooks()
        self._cap = os.environ.pop("PHOTO_PART_MAX_CALLS", None)
        self._block = os.environ.pop("PHOTOPART_BLOCK_PROBES", None)

    def tearDown(self):
        reset_hooks()
        if self._cap is None:
            os.environ.pop("PHOTO_PART_MAX_CALLS", None)
        else:
            os.environ["PHOTO_PART_MAX_CALLS"] = self._cap
        if self._block is None:
            os.environ.pop("PHOTOPART_BLOCK_PROBES", None)
        else:
            os.environ["PHOTOPART_BLOCK_PROBES"] = self._block

    def test_budget_note_counts_terminal_calls_without_plugin_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = {"command": "echo hi", "cwd": tmp}
            rewritten = on_pre_tool_call(
                tool_name="skill_view",
                args={"name": "photo-to-printable-part", "cwd": tmp},
                session_id="budget",
            )
            self.assertEqual(rewritten["action"], "modify")
            self.assertEqual(rewritten["args"]["name"], SKILL_ID)
            for _ in range(23):
                on_post_tool_call(tool_name="terminal", args=args, session_id="budget")
            quiet = on_transform_tool_result(
                tool_name="terminal", args=args, result="ok", session_id="budget"
            )
            self.assertIsNone(quiet)
            on_post_tool_call(tool_name="terminal", args=args, session_id="budget")
            noted = on_transform_tool_result(
                tool_name="terminal", args=args, result="done", session_id="budget"
            )
            self.assertIn("24 of 40 tool calls used", noted)
            self.assertIn("photo_part_measure / photo_part_build", noted)
            self.assertTrue(noted.startswith("done"))
            on_post_tool_call(tool_name="terminal", args=args, session_id="budget")
            again = on_transform_tool_result(
                tool_name="terminal", args=args, result="later", session_id="budget"
            )
            self.assertIsNone(again)
            used, source = _resolve_used(0, None, 40, "budget", Path(tmp))
            self.assertEqual((used, source), (25, "hook"))

    def test_inactive_session_is_a_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = {"command": "echo hi", "cwd": tmp}
            for _ in range(25):
                self.assertIsNone(
                    on_post_tool_call(tool_name="terminal", args=args, session_id="stranger")
                )
            self.assertIsNone(
                on_transform_tool_result(
                    tool_name="terminal", args=args, result="ok", session_id="stranger"
                )
            )
            self.assertIsNone(hook_call_count("stranger", Path(tmp)))

    def test_hook_failure_does_not_raise(self):
        import photopart.hooks as hooks

        original = hooks._post
        hooks._post = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            self.assertIsNone(on_post_tool_call(tool_name="terminal", session_id="x"))
        finally:
            hooks._post = original

    def test_skill_misspellings_rewrite_and_other_skills_do_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            misses = (
                "plugin:photo-to-part:photo-to-printable-part",
                "plugins:photo-to-part:photo-to-printable-part",
                "photo-to-part/photo-to-printable-part",
                "photo-to-printable-part",
            )
            for index, skill in enumerate(misses):
                result = on_pre_tool_call(
                    tool_name="skill_view",
                    args={"name": skill, "cwd": tmp},
                    session_id=f"skill-{index}",
                )
                self.assertEqual(result["args"]["name"], SKILL_ID)
            untouched = on_pre_tool_call(
                tool_name="skill_view",
                args={"name": "superpowers:x", "cwd": tmp},
                session_id="other-skill",
            )
            self.assertIsNone(untouched)
            log = Path(tmp) / ".photopart" / "calls.jsonl"
            text = log.read_text(encoding="utf-8")
            for skill in misses:
                self.assertIn(skill, text)
            self.assertIn("rewrite_from", text)
            self.assertNotIn("superpowers:x", text)

    def test_photo_probe_is_a_note_unless_blocking_is_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "peg-unique-photo.png"
            image.write_bytes(b"not-really-an-image")
            command = f"python -c \"import cv2; from PIL import Image; Image.open('{image}'); cv2.imread('{image}')\""
            args = {"command": command, "cwd": tmp}
            on_pre_tool_call(
                tool_name="photo_part_measure",
                args={"image": str(image), "cwd": tmp},
                session_id="probe",
            )
            self.assertIsNone(on_pre_tool_call(tool_name="terminal", args=args, session_id="probe"))
            on_post_tool_call(tool_name="terminal", args=args, session_id="probe")
            noted = on_transform_tool_result(
                tool_name="terminal", args=args, result="pixels", session_id="probe"
            )
            self.assertIn("photo_part_measure already measures this photo", noted)
            self.assertIn("seed=", noted)
            os.environ["PHOTOPART_BLOCK_PROBES"] = "1"
            blocked = None
            for _ in range(3):
                blocked = on_pre_tool_call(tool_name="terminal", args=args, session_id="probe")
            self.assertEqual(blocked["action"], "block")

    def test_register_lists_the_three_hooks(self):
        ctx = HermesV0217Context()
        load_plugin_register()(ctx)
        self.assertEqual(
            [name for name, _callback in ctx.hooks],
            ["pre_tool_call", "post_tool_call", "transform_tool_result"],
        )
        self.assertEqual(len(ctx.tools), 6)


class ScorerTests(unittest.TestCase):
    def test_tool_call_wrapper_counts_as_a_plugin_call(self):
        message = {
            "name": "tool_call",
            "arguments": json.dumps({"calls": [{"name": "photo_part_validate"}]}),
        }
        self.assertEqual(names_from_json(message), ["photo_part_validate"])
        scored = score_transcript(json.dumps({"role": "assistant", "tool_calls": [message]}))
        self.assertEqual(scored["plugin_calls"], 1)
        ordinary = {
            "name": "read_file",
            "arguments": json.dumps({"calls": [{"name": "photo_part_validate"}]}),
        }
        self.assertEqual(names_from_json(ordinary), ["read_file"])

    def test_minutes_and_argument_leak_come_from_state_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            database = home / "state.db"
            connection = sqlite3.connect(database)
            connection.execute(
                "CREATE TABLE messages (session_id TEXT, role TEXT, tool_calls TEXT, timestamp TEXT)"
            )
            wrapper = json.dumps(
                [{"name": "tool_call", "arguments": json.dumps({"calls": [{"name": "photo_part_validate"}]})}]
            )
            leaked = json.dumps(
                [{"name": "read_file", "arguments": {"path": str(ROOT / "evals" / "runner.py")}}]
            )
            connection.execute(
                "INSERT INTO messages VALUES (?, ?, ?, ?)",
                ("sess", "assistant", wrapper, "2026-11-03T00:00:00"),
            )
            connection.execute(
                "INSERT INTO messages VALUES (?, ?, ?, ?)",
                ("sess", "assistant", leaked, "2026-11-03T00:01:30"),
            )
            connection.commit()
            connection.close()
            scored = score_hermes_session("sess", home=home)
        self.assertTrue(scored["ok"])
        self.assertEqual(scored["plugin_calls"], 1)
        self.assertEqual(scored["minutes"], 1.5)
        self.assertTrue(scored["leak"])
        self.assertTrue(score_transcript(f"see {EVAL_CANARY} in the tool result")["leak"])


class MeasureAndFitTests(unittest.TestCase):
    def test_synthetic_coin_and_part_are_within_tolerance(self):
        image, seed = _coin_scene(24.26, 18.0, 10.0, 0.0)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "quarter.png"
            Image.fromarray(image, mode="RGB").save(path)
            report = measure(
                {
                    "coin": "us_quarter",
                    "image": str(path),
                    "auto": True,
                    "part_seed": [seed[0], seed[1]],
                    "out_dir": tmp,
                }
            )
        coin_px = 24.26 * 4.0
        self.assertLessEqual(abs(report["coin_px"] - coin_px) / coin_px, 0.015)
        self.assertIn(report["coin_detect"], {"hough", "contour"})
        self.assertIsInstance(report["scale_uncertainty_pct"], float)
        truth = [18.0, 10.0]
        for got, expected in zip(report["part_bbox_mm"], truth):
            self.assertLessEqual(abs(got - expected) / expected, 0.03)

    def test_shifted_rectangle_drops_iou_and_reports_the_shift(self):
        placed = np.zeros((80, 80), dtype=bool)
        placed[20:50, 20:50] = True
        same = fit_metrics(placed, placed, px_per_mm=4.0)
        shifted_mask = np.zeros_like(placed)
        shifted_mask[20:50, 28:58] = True
        shifted = fit_metrics(placed, shifted_mask, px_per_mm=4.0)
        self.assertLess(shifted["iou"], same["iou"])
        # Nearest-point chamfer averages edges that still touch. HD95 is the shift.
        self.assertGreater(shifted["chamfer_px"], 2.0)
        self.assertAlmostEqual(shifted["hd95_px"], 8.0, delta=1.5)
        self.assertAlmostEqual(shifted["chamfer_mm"], shifted["chamfer_px"] / 4.0, delta=0.05)
        self.assertEqual(same["fit_confidence"], "high")
        self.assertIn("boundary_iou", shifted)
        self.assertIn("hd95_mm", shifted)

    def test_thread_union_is_quiet_and_a_flange_still_warns(self):
        outcome = _thread_from_script()
        self.assertTrue(outcome["passed"], outcome["detail"])


class StandardsTests(unittest.TestCase):
    def test_m3_flange_warns_from_hex_and_m5_flange_does_not(self):
        spec = {"designation": "M3 flange screw", "notes": "keep this"}
        before = json.dumps(spec)
        result = check_standard(spec, {"extents_mm": {"x": 8.1, "y": 8.1, "z": 9.2}})
        self.assertEqual(json.dumps(spec), before)
        self.assertFalse(result["edited_spec"])
        text = " ".join(row["message"] for row in result["warnings"])
        self.assertIn("5.5", text)
        self.assertIn("ISO 4017", text)
        self.assertIn("ISO 4162", text)
        self.assertNotIn("6-7", text)
        self.assertNotIn("6–7", text)
        quiet = check_standard(
            {"designation": "M5 flange bolt"},
            {"extents_mm": {"x": 11.4, "y": 11.4, "z": 20.0}, "pitch_mm": 0.8},
        )
        self.assertEqual(quiet["warnings"], [])
        pitch = check_standard(
            {"designation": "M3"},
            {"pitch_mm": 0.5, "extents_mm": {"x": 5.5, "y": 5.5, "z": 12.0}},
        )
        self.assertEqual(pitch["warnings"], [])
        self.assertIn("The spec was not changed.", " ".join(result["suggestions"]))


if __name__ == "__main__":
    unittest.main()
