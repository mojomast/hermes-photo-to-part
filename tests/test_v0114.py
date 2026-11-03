"""v0.1.14: case-scoped scorer and the loonie measure mask."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from evals.runner import score_hermes_session
from photopart.measure import measure

LOONIE = Path(__file__).resolve().parent / "regression" / "photos" / "cad_loonie.png"
WRONG = "plugin:photo-to-part:photo-to-printable-part"


class ScorerLogTests(unittest.TestCase):
    def test_shared_log_does_not_count_other_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "sessions").mkdir()
            (home / ".photopart").mkdir()
            rows = [
                {
                    "session_id": f"other-{index}",
                    "tool": "skill_view",
                    "rewrite_from": WRONG,
                }
                for index in range(9)
            ]
            (home / ".photopart" / "calls.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in rows),
                encoding="utf-8",
            )
            session = {
                "messages": [
                    {
                        "role": "assistant",
                        "tool_calls": [
                            {"name": "photo_part_validate", "arguments": {"mesh": "box.stl"}},
                        ],
                    }
                ]
            }
            (home / "sessions" / "box.json").write_text(json.dumps(session), encoding="utf-8")
            scored = score_hermes_session("box", home=home)
        self.assertTrue(scored["ok"], scored)
        self.assertEqual(scored["wrong_skill_ids"], 0)
        self.assertEqual(scored["skill_id_rewritten"], 0)

    def test_case_log_counts_only_that_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            case = root / "case"
            (home / "sessions").mkdir(parents=True)
            (home / ".photopart").mkdir()
            (case / ".photopart").mkdir(parents=True)
            others = [
                {"session_id": f"other-{index}", "rewrite_from": WRONG}
                for index in range(9)
            ]
            (home / ".photopart" / "calls.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in others),
                encoding="utf-8",
            )
            (case / ".photopart" / "calls.jsonl").write_text(
                json.dumps(
                    {
                        "session_id": "box",
                        "tool": "skill_view",
                        "rewrite_from": WRONG,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            mesh = case / "box.stl"
            mesh.write_text("solid box\n", encoding="utf-8")
            session = {
                "messages": [
                    {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "name": "skill_view",
                                "arguments": {"name": WRONG},
                            },
                            {
                                "name": "photo_part_validate",
                                "arguments": {"mesh": str(mesh)},
                            },
                        ],
                    }
                ]
            }
            (home / "sessions" / "box.json").write_text(json.dumps(session), encoding="utf-8")
            scored = score_hermes_session("box", home=home)
        self.assertEqual(scored["skill_id_rewritten"], 1, scored)
        self.assertEqual(scored["wrong_skill_ids"], 0)


class LoonieMaskTests(unittest.TestCase):
    def test_seed_just_above_the_part_stays_within_five_percent(self):
        self.assertTrue(LOONIE.is_file(), LOONIE)
        with tempfile.TemporaryDirectory() as tmp:
            report = measure(
                {
                    "coin": "cad_loonie",
                    "image": str(LOONIE),
                    "auto": True,
                    "part_seed": [479, 252],
                    "out_dir": tmp,
                }
            )
        longer, shorter = report["part_bbox_mm"]
        self.assertLessEqual(abs(longer - 22.0) / 22.0, 0.05, report["part_bbox_mm"])
        self.assertLessEqual(abs(shorter - 12.0) / 12.0, 0.05, report["part_bbox_mm"])
