"""v0.1.13: template params, shallow recesses, skill-id paths, staged coins."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from evals.meshes import blind_tap, pip_hinge_fine_tessellation
from evals.runner import score_transcript, stage_task
from photopart.flow import SKILL_ID
from photopart.hooks import on_pre_tool_call
from photopart.parts import _as_mesh, _cube, _cylinder_z, _difference
from photopart.spec import apply_spec, count_bores, detect_knuckles, openings
from photopart.tools import template_tool


def _loads(payload: str) -> dict:
    return json.loads(payload)


class TemplateArgumentTests(unittest.TestCase):
    def test_top_level_knuckles_builds_five(self):
        """The hinge_five_knuckles eval passed knuckles beside shape. That must count."""
        with tempfile.TemporaryDirectory() as tmp:
            payload = _loads(
                template_tool(
                    {
                        "shape": "hinge",
                        "knuckles": 5,
                        "out_dir": tmp,
                        "no_3mf": True,
                    }
                )
            )
            self.assertTrue(payload["ok"], payload.get("error"))
            self.assertEqual(payload["spec_checks"]["knuckles"], 5)
            import trimesh

            mesh = trimesh.load(payload["stl"], force="mesh")
            self.assertEqual(detect_knuckles(mesh, "x")["knuckles"], 5)

    def test_other_shapes_merge_and_conflicts_are_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            plate = _loads(
                template_tool(
                    {
                        "shape": "plate",
                        "thickness_mm": 7,
                        "params": '{"width_mm": 22}',
                        "out_dir": tmp,
                        "no_3mf": True,
                    }
                )
            )
            self.assertTrue(plate["ok"], plate.get("error"))
            extents = plate["expected_extents_mm"]
            self.assertAlmostEqual(extents["x"], 22, delta=0.2)
            self.assertAlmostEqual(extents["z"], 7, delta=0.2)
            gear = _loads(
                template_tool(
                    {
                        "shape": "spur_gear",
                        "teeth": 12,
                        "out_dir": str(Path(tmp) / "gear"),
                        "no_3mf": True,
                    }
                )
            )
            self.assertTrue(gear["ok"], gear.get("error"))
            self.assertLess(max(gear["expected_extents_mm"].values()), 18)
            unknown = _loads(template_tool({"shape": "hinge", "fingers": 5, "out_dir": tmp, "no_3mf": True}))
            self.assertFalse(unknown["ok"])
            self.assertIn("params", unknown["error"])
            self.assertIn("fingers", unknown["error"])
            conflict = _loads(
                template_tool(
                    {
                        "shape": "hinge",
                        "knuckles": 5,
                        "params": {"knuckles": 4},
                        "out_dir": tmp,
                        "no_3mf": True,
                    }
                )
            )
            self.assertFalse(conflict["ok"])
            self.assertIn("params", conflict["error"])
            self.assertIn("knuckles", conflict["error"])


class RecessTests(unittest.TestCase):
    def test_shallow_dish_is_a_recess_and_known_bores_stay(self):
        plate = _cube(45, 45, 8)
        dish = _cylinder_z(11.75, 3.0, 22.5, 22.5, 6.5, segments=64)
        hole = _cylinder_z(2.5, 12.0, 8.0, 8.0, -2.0, segments=32)
        mesh = _as_mesh(_difference(plate, [dish, hole]))
        found = openings(mesh)
        self.assertEqual(len(found["bores"]), 1)
        self.assertTrue(found["bores"][0]["through"])
        self.assertAlmostEqual(found["bores"][0]["diameter"], 5.0, delta=0.15)
        self.assertEqual(len(found["recesses"]), 1)
        recess = found["recesses"][0]
        self.assertEqual(recess["kind"], "recess")
        self.assertAlmostEqual(recess["diameter"], 23.5, delta=0.4)
        self.assertLess(recess["depth_mm"], 3.0)
        _failures, rows = apply_spec(mesh, spec={"hole_count": 1})
        self.assertTrue(rows[0]["ok"])
        self.assertEqual(rows[0]["actual"], 1)
        self.assertIn("not bores", rows[0]["recess_note"])

        pin = count_bores(pip_hinge_fine_tessellation())
        self.assertEqual(len(pin), 2)
        for bore in pin:
            self.assertEqual(bore["kind"], "pin_clearance")
            self.assertGreater(bore["depth_mm"], 1.0)
        tap = count_bores(blind_tap())
        self.assertEqual(len(tap), 1)
        self.assertFalse(tap[0]["through"])
        self.assertGreater(tap[0]["depth_mm"], 4.0)


class SkillPathTests(unittest.TestCase):
    def test_wrapper_and_skills_list_are_rewritten_and_scored(self):
        wrapper = {
            "calls": [
                {
                    "name": "skill_view",
                    "arguments": {"name": "plugin:photo-to-part:photo-to-printable-part"},
                },
                {
                    "name": "skills_list",
                    "arguments": json.dumps({"query": "photo-to-part/photo-to-printable-part"}),
                },
                {"name": "skill_view", "arguments": {"name": "superpowers:x"}},
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            result = on_pre_tool_call(
                tool_name="tool_call",
                args=json.dumps(wrapper),
                session_id="wrap",
            )
            # The JSON string has no project path, so pass one on a dict call too.
            logged = on_pre_tool_call(
                tool_name="tool_call",
                args={"cwd": tmp, **wrapper},
                session_id="wrap-dir",
            )
            self.assertEqual(result["action"], "modify")
            updated = json.loads(result["args"])
            self.assertEqual(updated["calls"][0]["arguments"]["name"], SKILL_ID)
            self.assertEqual(
                json.loads(updated["calls"][1]["arguments"])["query"],
                SKILL_ID,
            )
            self.assertEqual(updated["calls"][2]["arguments"]["name"], "superpowers:x")
            self.assertEqual(logged["args"]["calls"][0]["arguments"]["name"], SKILL_ID)
            # 0.1.23: the rewrite row waits for a photo_part_* call to name the folder.
            self.assertFalse((Path(tmp) / ".photopart" / "calls.jsonl").exists())
            on_pre_tool_call(
                tool_name="photo_part_validate",
                args={"help": True, "cwd": tmp},
                session_id="wrap-dir",
            )
            text = (Path(tmp) / ".photopart" / "calls.jsonl").read_text(encoding="utf-8")
            self.assertIn("rewrite_from", text)
            self.assertIn("plugin:photo-to-part:photo-to-printable-part", text)
            self.assertNotIn("superpowers:x", text)

        transcript = json.dumps({"calls": wrapper["calls"][:1]})
        bare = score_transcript(transcript)
        self.assertEqual(bare["wrong_skill_ids"], 1)
        self.assertEqual(bare["skill_id_rewritten"], 0)
        paired = score_transcript(
            transcript,
            calls=[{"tool": "skill_view", "rewrite_from": "plugin:photo-to-part:photo-to-printable-part"}],
        )
        self.assertEqual(paired["wrong_skill_ids"], 0)
        self.assertEqual(paired["skill_id_rewritten"], 1)
        toolcall = score_transcript(
            '2026-11-03T12:00:00 TOOLCALL tool_call '
            '{"calls":[{"name":"skill_view","arguments":{"name":"plugin:photo-to-part:photo-to-printable-part"}}]}'
        )
        self.assertEqual(toolcall["wrong_skill_ids"], 1)
        keyword = score_transcript('skills_list(query="photo-to-printable-part")')
        self.assertEqual(keyword["wrong_skill_ids"], 1)
        prose = score_transcript("`plugin:photo-to-part:photo-to-printable-part` is not a skill name")
        self.assertEqual(prose["wrong_skill_ids"], 0)
        exact = score_transcript(f'skill_view("{SKILL_ID}")')
        self.assertEqual(exact["wrong_skill_ids"], 0)
        mixed = score_transcript(
            "\n".join(
                [
                    'skill_view("plugin:photo-to-part:photo-to-printable-part")',
                    'skill_view(name="photo-to-part/photo-to-printable-part")',
                ]
            ),
            calls=[{"rewrite_from": "plugin:photo-to-part:photo-to-printable-part"}],
        )
        self.assertEqual(mixed["skill_id_rewritten"], 1)
        self.assertEqual(mixed["wrong_skill_ids"], 1)


class CoinStageTests(unittest.TestCase):
    def test_coin_scale_sealed_stages_photos_measure_can_read(self):
        from photopart.measure import measure

        with tempfile.TemporaryDirectory() as tmp:
            staged = stage_task("coin_scale_sealed", Path(tmp) / "task")
            directory = Path(staged["dir"])
            self.assertEqual(
                staged["fixtures"],
                ["us_quarter.png", "cad_loonie.png", "euro_1.png"],
            )
            for name in staged["fixtures"]:
                self.assertTrue((directory / name).is_file())
            self.assertTrue((directory / "prompt.txt").is_file())
            report = measure(
                {
                    "coin": "us_quarter",
                    "image": str(directory / "us_quarter.png"),
                    "auto": True,
                    "part_seed": [480, 280],
                    "out_dir": str(directory / "out"),
                }
            )
            self.assertGreater(float(report["px_per_mm"]), 1.0)
            box = sorted(float(value) for value in report["part_bbox_mm"])
            self.assertAlmostEqual(box[0], 10.0, delta=1.0)
            self.assertAlmostEqual(box[1], 18.0, delta=1.5)


if __name__ == "__main__":
    unittest.main()
