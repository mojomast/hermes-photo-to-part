"""v0.1.10: probe warnings, session budget, CAD guidance, walls, and session scoring."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

import trimesh

from evals.runner import registration_report, score_hermes_session, score_transcript
from photopart.build_run import run_build
from photopart.features import external_thread, tag_faces
from photopart.flow import SKILL_ID
from photopart.holes import check_holes
from photopart.printability import check_printability
from photopart.tools import render_tool, template_tool, tool_specs, validate_tool
from photopart.validate import evaluate

ROOT = Path(__file__).resolve().parents[1]
_WRONG = "plugin:photo-to-part:photo-to-printable-part"


def _call(name: str) -> str:
    return json.dumps([{"function": {"name": name, "arguments": "{}"}}])


class ProbeWarningTests(unittest.TestCase):
    def test_l_bracket_disagreement_warns_and_a_miss_still_fails(self):
        from evals.meshes import thin_l_bracket

        mesh = thin_l_bracket()
        mid, rows = check_holes(mesh, [{"x": 30, "y": 12, "diameter": 5}], tolerance=0.3)
        self.assertEqual(mid, [])
        self.assertTrue(rows[0]["ok"])
        self.assertTrue(rows[0]["warning"])
        self.assertIn("Probe:", rows[0]["warning"])
        self.assertIn("Bore:", rows[0]["warning"])
        self.assertFalse(rows[0]["probe"]["ok"])
        self.assertEqual(rows[0]["bore"]["axis"], "z")
        self.assertIn("does not block delivery", rows[0]["warning"])

        for spec in (
            {"x": 50, "y": 12, "z": 0.75, "diameter": 5},
            {"x": 68, "y": 12, "z": 0.75, "diameter": 5},
        ):
            failures, split = check_holes(mesh, [spec], tolerance=0.3)
            self.assertEqual(failures, [], spec)
            self.assertTrue(split[0]["ok"])
            self.assertTrue(split[0]["probe"]["ambiguous"])
            self.assertIsNotNone(split[0]["bore"])
            self.assertTrue(split[0]["warning"])

        clean, clean_rows = check_holes(
            mesh, [{"x": 30, "y": 12, "z": 0.75, "diameter": 5}], tolerance=0.3
        )
        self.assertEqual(clean, [])
        self.assertTrue(clean_rows[0]["ok"])
        self.assertIsNone(clean_rows[0]["warning"])
        self.assertTrue(clean_rows[0]["probe"]["ok"])

        report = evaluate(mesh, holes=[{"x": 30, "y": 12, "diameter": 5}])
        self.assertTrue(report["ok"], report["failures"])
        self.assertTrue(report["probe_warnings"])
        self.assertTrue(report["holes"][0]["warning"])

        miss = evaluate(mesh, holes=[{"x": 5, "y": 5, "z": 0.75, "diameter": 5}])
        self.assertFalse(miss["ok"])
        self.assertIn("position", " ".join(miss["failures"]))
        self.assertFalse(miss["probe_warnings"])


class SessionBudgetTests(unittest.TestCase):
    def _home(self, root: Path, session_id: str, count: int) -> None:
        db = root / "state.db"
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, tool_calls TEXT, tool_name TEXT)"
        )
        for index in range(count):
            name = "photo_part_validate" if index % 5 == 0 else "terminal"
            conn.execute(
                "INSERT INTO messages (session_id, role, tool_calls, tool_name) VALUES (?, ?, ?, ?)",
                (session_id, "assistant", _call(name), None),
            )
        conn.commit()
        conn.close()

    def test_state_db_beats_a_low_calls_used(self):
        from PIL import Image

        from photopart.tools import measure_tool

        saved_home = os.environ.get("HERMES_HOME")
        saved_session = os.environ.pop("HERMES_SESSION_ID", None)
        saved_cap = os.environ.pop("PHOTO_PART_MAX_CALLS", None)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self._home(root, "round8", 47)
                os.environ["HERMES_HOME"] = str(root)
                image = root / "photo.png"
                Image.new("RGB", (16, 16), (255, 255, 255)).save(image)
                report = json.loads(
                    measure_tool(
                        {"image": str(image), "diameter_mm": 20, "diameter_px": 40, "calls_used": 16},
                        session_id="round8",
                    )
                )
                self.assertEqual(report["budget"]["calls_used"], 47)
                self.assertEqual(report["budget"]["calls_used_source"], "session")
                self.assertEqual(report["budget"]["remaining"], 0)
                self.assertIn("Stop exploring.", report["next_step"])
        finally:
            self._restore(saved_home, saved_session, saved_cap)

    def test_jsonl_counts_when_the_database_has_no_row(self):
        from PIL import Image

        from photopart.tools import measure_tool

        saved_home = os.environ.get("HERMES_HOME")
        saved_session = os.environ.pop("HERMES_SESSION_ID", None)
        saved_cap = os.environ.pop("PHOTO_PART_MAX_CALLS", None)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self._home(root, "other", 3)
                sessions = root / "sessions"
                sessions.mkdir()
                lines = []
                for name in ("terminal", "photo_part_validate", "skill_view"):
                    lines.append(
                        json.dumps(
                            {
                                "role": "assistant",
                                "tool_calls": [{"function": {"name": name, "arguments": "{}"}}],
                            }
                        )
                    )
                    lines.append(json.dumps({"role": "tool", "tool_name": name, "name": name, "content": "ok"}))
                (sessions / "jsonl-only.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
                os.environ["HERMES_HOME"] = str(root)
                image = root / "photo.png"
                Image.new("RGB", (16, 16), (240, 240, 240)).save(image)
                report = json.loads(
                    measure_tool(
                        {"image": str(image), "diameter_mm": 20, "diameter_px": 40, "calls_used": 1},
                        session_id="jsonl-only",
                    )
                )
                self.assertEqual(report["budget"]["calls_used"], 3, report["budget"])
                self.assertEqual(report["budget"]["calls_used_source"], "session")
        finally:
            self._restore(saved_home, saved_session, saved_cap)

    def test_past_eighty_percent_refuses_extra_work(self):
        saved_cap = os.environ.pop("PHOTO_PART_MAX_CALLS", None)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                box = root / "plate_v1.stl"
                trimesh.creation.box(extents=(10, 12, 14)).export(box)
                first = json.loads(validate_tool({"mesh": str(box), "calls_used": 1, "render": False}))
                self.assertTrue(first["ok"], first.get("error") or first.get("failures"))
                repeat = json.loads(validate_tool({"mesh": str(box), "calls_used": 33, "render": False}))
                self.assertTrue(repeat.get("refused"))
                self.assertEqual(repeat.get("budget_refused"), "validate")
                self.assertIn("repeat validate refused", repeat["error"])
                self.assertIn("plate_v1.stl", repeat["error"])
                self.assertTrue(repeat["error"].startswith("Budget: deliver"))

                other = root / "fresh.stl"
                trimesh.creation.box(extents=(8, 9, 10)).export(other)
                opened = json.loads(validate_tool({"mesh": str(other), "calls_used": 33, "render": False}))
                self.assertTrue(opened["ok"], opened.get("error") or opened.get("failures"))
                self.assertNotIn("repeat validate refused", str(opened.get("error")))

                out = root / "renders"
                refused = json.loads(
                    render_tool({"mesh": str(box), "out_dir": str(out), "calls_used": 33})
                )
                self.assertTrue(refused.get("refused"))
                self.assertIn("render refused", refused["error"])
                self.assertTrue(refused["error"].startswith("Budget: deliver plate_v1.stl now"))
                final = json.loads(
                    render_tool({"mesh": str(box), "out_dir": str(root / "final"), "calls_used": 33, "final": True})
                )
                self.assertNotEqual(final.get("budget_refused"), "render")
                self.assertNotIn("render refused", str(final.get("error")))
        finally:
            if saved_cap is None:
                os.environ.pop("PHOTO_PART_MAX_CALLS", None)
            else:
                os.environ["PHOTO_PART_MAX_CALLS"] = saved_cap

    @staticmethod
    def _restore(home, session, cap) -> None:
        if home is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = home
        if session is None:
            os.environ.pop("HERMES_SESSION_ID", None)
        else:
            os.environ["HERMES_SESSION_ID"] = session
        if cap is None:
            os.environ.pop("PHOTO_PART_MAX_CALLS", None)
        else:
            os.environ["PHOTO_PART_MAX_CALLS"] = cap


class BuildGuidanceTests(unittest.TestCase):
    def test_missing_build123d_names_the_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            script = work / "strap.py"
            script.write_text(
                "import build123d\n"
                "# a strap hinge, not a custom kernel\n"
                "print('strap hinge')\n",
                encoding="utf-8",
            )
            report = run_build(script, cwd=work, timeout=30)
            self.assertFalse(report["ok"])
            lines = report["error"].splitlines()
            self.assertTrue(lines[0].startswith("ModuleNotFoundError"), report["error"])
            self.assertIn("build123d", lines[0])
            self.assertIn("Available libraries:", report["error"])
            self.assertIn("trimesh", report["error"])
            self.assertIn("strap_hinge", report["error"])
            self.assertIn("photopart.features", report["error"])
            self.assertIn("Do not install", report["error"])


class ThinWallTests(unittest.TestCase):
    def test_seventy_hundredths_warns_and_tagged_faces_do_not(self):
        plate = trimesh.creation.box(extents=(20, 20, 0.70))
        warned = check_printability(plate)
        self.assertLess(warned["min_wall_p5_mm"], 0.8)
        self.assertTrue(any("wall" in item for item in warned["warnings"]))

        thin = check_printability(trimesh.creation.box(extents=(20, 20, 0.65)))
        self.assertTrue(any("wall" in item for item in thin["warnings"]))
        exact = check_printability(trimesh.creation.box(extents=(20, 20, 0.80)))
        self.assertFalse(exact["warnings"], exact)
        self.assertGreaterEqual(exact["min_wall_p5_mm"], 0.8)
        cube = check_printability(trimesh.creation.box(extents=(10, 10, 10)))
        self.assertFalse(any("wall" in item for item in cube["warnings"]))

        tagged = trimesh.creation.box(extents=(20, 20, 0.70))
        tag_faces(tagged, thread=list(range(len(tagged.faces))))
        skipped = check_printability(tagged)
        self.assertIsNone(skipped["min_wall_p5_mm"])
        self.assertFalse(any("wall" in item for item in skipped["warnings"]))

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "thread.stl"
            mesh = external_thread(designation="M3", length=8.0)
            mesh.export(path)
            sidecar = Path(str(path) + ".faces.json")
            self.assertTrue(sidecar.is_file())
            stored = json.loads(sidecar.read_text(encoding="utf-8"))
            self.assertTrue(stored["thread"])


class SessionScoreTests(unittest.TestCase):
    def test_toolcall_lines_and_session_files(self):
        text = "\n".join(
            [
                '2026-11-03T01:00:00 TOOLCALL terminal {"cmd": "ls"}',
                '2026-11-03T01:01:00 TOOLCALL photo_part_validate {"mesh": "a.stl"}',
                "please call photo_part_build in prose",
            ]
        )
        scored = score_transcript(text)
        self.assertEqual(scored["tool_calls"], 2)
        self.assertEqual(scored["plugin_calls"], 1)

        messages = []
        for name in ("terminal", "photo_part_validate", "skill_view"):
            messages.append(
                json.dumps(
                    {"role": "assistant", "tool_calls": [{"function": {"name": name, "arguments": "{}"}}]}
                )
            )
            messages.append(json.dumps({"role": "tool", "tool_name": name, "name": name, "content": "ok"}))
        paired = score_transcript("\n".join(messages))
        self.assertEqual(paired["tool_calls"], 3)
        self.assertEqual(paired["plugin_calls"], 1)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "state.db"
            conn = sqlite3.connect(db)
            conn.execute(
                "CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, tool_calls TEXT, tool_name TEXT)"
            )
            for name in ("terminal", "photo_part_measure", "photo_part_validate"):
                conn.execute(
                    "INSERT INTO messages (session_id, role, tool_calls, tool_name) VALUES (?, 'assistant', ?, NULL)",
                    ("abc", _call(name)),
                )
                conn.execute(
                    "INSERT INTO messages (session_id, role, tool_calls, tool_name) VALUES (?, 'tool', NULL, ?)",
                    ("abc", name),
                )
            conn.commit()
            conn.close()
            counted = score_hermes_session("abc", home=root)
            self.assertTrue(counted["ok"], counted)
            self.assertEqual(counted["tool_calls"], 3)
            self.assertEqual(counted["plugin_calls"], 2)
            self.assertEqual(counted["calls_source"], "state.db")

            export = root / "export.jsonl"
            export.write_text("\n".join(messages) + "\n", encoding="utf-8")
            from_file = score_hermes_session(str(export))
            self.assertTrue(from_file["ok"])
            self.assertEqual(from_file["tool_calls"], 3)
            self.assertEqual(from_file["calls_source"], "jsonl")

            missing = score_hermes_session("missing-session", home=root)
            self.assertFalse(missing["ok"])
            self.assertEqual(missing["tool_calls"], 0)

        tasks = json.loads((ROOT / "evals" / "tasks.json").read_text(encoding="utf-8"))
        prompt = next(row["prompt"] for row in tasks["tasks"] if row["id"] == "bores_not_genus")
        self.assertTrue(prompt.startswith("Build"))
        self.assertIn("photo_part_validate", prompt)
        self.assertIn("Do not answer from this prompt alone", prompt)


class SkillIdTests(unittest.TestCase):
    def test_help_and_descriptions_lead_with_the_real_id(self):
        raw = template_tool({"help": True, "shape": "strap_hinge"})
        keys = [line.split('"', 2)[1] for line in raw.splitlines() if line.startswith('  "') and '":' in line]
        self.assertEqual(keys[0], "skill_id")
        self.assertEqual(keys[1], "skill_view")
        payload = json.loads(raw)
        self.assertEqual(payload["skill_id"], SKILL_ID)
        self.assertEqual(payload["skill_view"], f'skill_view("{SKILL_ID}")')
        self.assertTrue(payload["note"].startswith(f'skill_view("{SKILL_ID}")'))
        self.assertTrue(payload["example_script"].startswith(f'# skill_view("{SKILL_ID}")'))
        self.assertIn("strap_hinge", payload["example_script"])
        self.assertIn("Do not import build123d", payload["note"])

        for spec in tool_specs():
            self.assertTrue(spec["description"].startswith(SKILL_ID), spec["name"])
            self.assertIn(f'skill_view("{SKILL_ID}")', spec["description"])
            self.assertNotIn(_WRONG, spec["description"])
            self.assertIn("no plugin: prefix", spec["description"])

        report = registration_report()
        self.assertEqual(report["count"], 6)
        self.assertIsNone(report["error"])
        self.assertEqual(
            report["names"],
            [
                "photo_part_validate",
                "photo_part_render",
                "photo_part_heal",
                "photo_part_template",
                "photo_part_measure",
                "photo_part_build",
            ],
        )
