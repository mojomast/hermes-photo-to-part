"""v0.1.6: score, freeze, sheet, printability, GrabCut, provenance, concise tools, evals, meshfix."""

from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np
import trimesh

from evals.runner import load_tasks, run_suite, score_transcript
from photopart.flow import SKILL_ID
from photopart.freeze import fingerprint
from photopart.overlay import _write_overlay
from photopart.printability import check_printability
from photopart.render import run_render
from photopart.score import compute_score
from photopart.tools import register_tools, tool_specs, validate_tool
from photopart.validate import run_validate

ROOT = Path(__file__).resolve().parents[1]


def _box(path: Path, extents=(10, 20, 30)) -> None:
    trimesh.creation.box(extents=extents).export(path)


class ScoreTests(unittest.TestCase):
    def test_passing_score_beats_a_residual(self):
        good = compute_score({"ok": True, "watertight": True, "spec": [{"name": "x", "ok": True, "actual": 10, "value": 10}]})
        bad = compute_score(
            {
                "ok": False,
                "watertight": True,
                "spec": [{"name": "x", "ok": False, "actual": 14, "value": 10}],
                "printability": {"warnings": ["thin"]},
            }
        )
        self.assertGreater(good["score"], bad["score"])
        self.assertEqual(bad["print_warnings"], 1)
        self.assertAlmostEqual(bad["residual_mm"], 4.0)

    def test_final_render_delivers_the_better_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = {"x": 10, "y": 8, "z": 4, "tolerance": 0.3}
            first = root / "part_v1.stl"
            second = root / "part_v2.stl"
            _box(first, (10, 8, 4))
            _box(second, (10, 8, 9))
            code, earlier = run_validate(str(first), spec=spec)
            self.assertEqual(code, 0, earlier)
            self.assertIn("stop", earlier["next_step"])
            self.assertIn("photo_part_render", earlier["next_step"])
            code, later = run_validate(str(second), spec=spec)
            self.assertEqual(code, 2)
            self.assertIn("Revert to part_v1.stl", later["next_step"])
            self.assertLess(later["score"], earlier["score"])
            code, shipped = run_render([str(second), "--out-dir", str(root / "out"), "--final"])
            self.assertEqual(code, 0, shipped)
            self.assertEqual(shipped["best_version"], "part_v1.stl")
            self.assertTrue(shipped["deliverable"].endswith("part_v1.stl"))
            self.assertEqual(shipped["sheet_views"], ["front", "back", "side", "right", "top", "bottom", "iso", "iso2"])
            self.assertTrue((root / "out" / "sheet.png").is_file())


class FreezeTests(unittest.TestCase):
    def test_answers_do_not_change_the_frozen_hash(self):
        raw = {"x": 10, "features": ["5 knuckles", "teardrop"]}
        answered = {"x": 10, "features": ["5 knuckles", "teardrop"], "answers": {"5 knuckles": "yes"}}
        self.assertEqual(fingerprint(raw), fingerprint(answered))


class PrintTests(unittest.TestCase):
    def test_overhang_and_bed_are_measured(self):
        slab = trimesh.creation.box(extents=(30, 20, 2))
        slab.apply_transform(trimesh.transformations.rotation_matrix(math.radians(70), [1, 0, 0]))
        report = check_printability(slab, overhang_deg=45, max_overhang_fraction=0.05, min_bed_mm2=50)
        self.assertGreater(report["overhang_area_mm2"], 0)
        self.assertIsNotNone(report["bed_contact_area_mm2"])
        self.assertTrue(report["warnings"])

    def test_print_strict_fails_a_thin_plate(self):
        with tempfile.TemporaryDirectory() as tmp:
            mesh = Path(tmp) / "thin.stl"
            _box(mesh, (12, 12, 0.4))
            code, report = run_validate(str(mesh), print_strict=True, min_wall_mm=0.8)
            self.assertNotEqual(code, 0)
            self.assertFalse(report["ok"])
            self.assertTrue(any("wall" in item for item in report["failures"]))


class ToolContractTests(unittest.TestCase):
    def test_concise_drops_history_and_errors_lead_with_a_fix(self):
        with tempfile.TemporaryDirectory() as tmp:
            mesh = Path(tmp) / "part.stl"
            _box(mesh)
            validate_tool({"mesh": str(mesh)})
            concise = json.loads(validate_tool({"mesh": str(mesh), "response_format": "concise"}))
            detailed = json.loads(validate_tool({"mesh": str(mesh), "response_format": "detailed"}))
            self.assertNotIn("history", concise)
            self.assertEqual(concise["response_format"], "concise")
            self.assertIn("history", detailed)
            self.assertGreaterEqual(len(detailed["history"]), 1)
            broken = json.loads(validate_tool({"mesh": str(mesh), "response_format": "verbose"}))
            self.assertIn("cause", broken)
            self.assertIn("fix", broken)
            self.assertIn("concise or detailed", broken["cause"])

    def test_every_tool_declares_response_format_and_an_output_schema(self):
        specs = tool_specs()
        names = [spec["name"] for spec in specs]
        self.assertEqual(
            names,
            [
                "photo_part_validate",
                "photo_part_render",
                "photo_part_heal",
                "photo_part_template",
                "photo_part_measure",
                "photo_part_build",
            ],
        )
        for spec in specs:
            props = spec["schema"]["parameters"]["properties"]
            self.assertEqual(props["response_format"]["enum"], ["concise", "detailed"])
            self.assertIn(SKILL_ID, spec["description"])

        class Ctx:
            def __init__(self):
                self.tools = []

            def register_tool(self, **kwargs):
                self.tools.append(kwargs)

        ctx = Ctx()
        register_tools(ctx)
        self.assertEqual([item["name"] for item in ctx.tools], names)
        for item in ctx.tools:
            schema = item["output_schema"]
            self.assertIn("cause", schema["properties"])
            self.assertIn("fix", schema["properties"])
            self.assertIn("ok", schema["required"])

    def test_top_poses_are_three(self):
        poses = [{"view": f"v{index}"} for index in range(5)]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = np.full((8, 8, 3), 255, np.uint8)
            report = _write_overlay(
                image,
                np.zeros((8, 8), dtype=bool),
                None,
                None,
                root / "overlay.png",
                root / "diff.png",
                fit="auto",
                note=None,
                iou=0.8,
                warnings=[],
                rotation=0,
                mirror=False,
                view="front",
                poses=poses,
            )
        self.assertEqual(len(report["overlay_poses"]), 5)
        self.assertEqual(len(report["overlay_top_poses"]), 3)


class EvalTests(unittest.TestCase):
    def test_suite_passes_and_transcript_counts_mistakes(self):
        tasks = load_tasks()
        self.assertGreaterEqual(len(tasks), 15)
        self.assertTrue((ROOT / "evals" / "photos.json").is_file())
        photos = json.loads((ROOT / "evals" / "photos.json").read_text(encoding="utf-8"))
        for photo in photos["photos"]:
            self.assertTrue(photo["url"].startswith("https://"))
            self.assertTrue(photo["licence"])
        report = run_suite()
        failed = [row["id"] for row in report["results"] if not row.get("passed")]
        self.assertEqual(failed, [], json.dumps(report["results"], indent=2, default=str))
        self.assertGreaterEqual(report["passed"], 15)
        self.assertTrue(report["ok"], report.get("holdouts"))
        self.assertGreaterEqual(report["holdout_tasks"], 3)
        self.assertEqual(report["holdout_passed"], report["holdout_tasks"])
        self.assertEqual(report["tools_registered"], 6)
        self.assertIsNone(report.get("registration_error"))
        self.assertEqual(report["wrong_skill_ids"], 0)
        self.assertEqual(report["deleted_files"], [])
        scored = score_transcript(
            "\n".join(
                [
                    "2026-11-02T22:00:00 skill_view(\"plugin:photo-to-part:photo-to-printable-part\")",
                    "2026-11-02T22:04:00 photo_part_validate part_v1.stl",
                    "mention photo_part_validate in prose does not count",
                    "rm part_v1.stl",
                    "`plugin:photo-to-part:photo-to-printable-part` is not a skill name",
                ]
            )
        )
        self.assertEqual(scored["wrong_skill_ids"], 1)
        self.assertFalse(scored["leak"])
        self.assertEqual(scored["tool_calls"], 2)
        self.assertEqual(scored["plugin_calls"], 1)
        self.assertEqual(len(scored["deleted_files"]), 1)
        self.assertAlmostEqual(scored["minutes"], 4.0)


if __name__ == "__main__":
    unittest.main()
