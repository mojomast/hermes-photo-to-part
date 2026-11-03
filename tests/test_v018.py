"""v0.1.8: names, score, checklist, budget, chamfer, and eval hygiene."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from evals.runner import score_transcript, stage_task
from photopart.overlay import _chamfer_of_placed, _select_pose
from photopart.score import compute_score
from photopart.tools import template_tool, validate_tool


def _box(path: Path, extents) -> None:
    import trimesh

    trimesh.creation.box(extents=extents).export(path)


class ScoreAndNameTests(unittest.TestCase):
    def test_clean_part_scores_100_and_concise_drops_versions(self):
        scored = compute_score(
            {
                "ok": True,
                "watertight": True,
                "spec": [{"name": "x", "ok": True, "actual": 10, "value": 10}],
                "checklist": [],
                "printability": {"warnings": []},
            }
        )
        self.assertEqual(scored["score"], 100.0)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mesh = root / "only.stl"
            _box(mesh, (10, 12, 14))
            concise = json.loads(validate_tool({"mesh": str(mesh)}))
            detailed = json.loads(validate_tool({"mesh": str(mesh), "response_format": "detailed"}))
        self.assertNotIn("versions", concise)
        self.assertEqual(concise["best_version"], "only.stl")
        self.assertIn("versions", detailed)
        self.assertIn("budget", concise)

    def test_template_refuses_the_placeholder_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ValueError):
                from photopart.parts import default_stl_name

                default_stl_name("spur_gear", root, "name_v1.stl")
            summary = json.loads(template_tool({"out_dir": str(root), "shape": "plate", "no_3mf": True}))
        self.assertTrue(summary["stl"].endswith("plate_v1.stl"))
        self.assertNotIn("name_v1.stl", summary["stl"])


class ChamferTests(unittest.TestCase):
    def test_noisy_silhouette_stays_near_the_true_pose(self):
        rng = np.random.default_rng(4)
        canvas = np.full((180, 220, 3), 214, np.int16)
        canvas += rng.integers(-12, 13, size=canvas.shape, dtype=np.int16)
        canvas = np.clip(canvas, 0, 255).astype(np.uint8)
        mask = np.zeros((180, 220), dtype=bool)
        mask[50:120, 70:150] = True
        sprite = Image.fromarray(np.where(mask, np.uint8(255), np.uint8(0)), mode="L")
        turned = sprite.rotate(12, resample=Image.Resampling.NEAREST, expand=False, fillcolor=0)
        truth = np.asarray(turned) > 127
        ys, xs = np.nonzero(truth)
        canvas[ys, xs] = (24, 26, 30)
        model = mask
        foreground = truth
        pose = _select_pose(model, foreground, canvas, None)
        distance = abs((float(pose["rotation_deg"]) - 12.0 + 180.0) % 360.0 - 180.0)
        other = abs((float(pose["rotation_deg"]) + 12.0 + 180.0) % 360.0 - 180.0)
        self.assertLess(min(distance, other), 5.0, pose["rotation_deg"])
        metrics = _chamfer_of_placed(pose["placed"], canvas, None)
        self.assertIsNotNone(metrics["chamfer_norm"])
        self.assertLessEqual(metrics["chamfer_norm"], 0.05)
        placed_ys, placed_xs = np.nonzero(pose["placed"])
        shift = max(abs(float(placed_xs.mean()) - float(xs.mean())), abs(float(placed_ys.mean()) - float(ys.mean())))
        self.assertLess(shift, 3.0, shift)


class EvalHygieneTests(unittest.TestCase):
    def test_transcript_leak_and_stage_directory(self):
        scored = score_transcript('open("evals/tasks.json")\nread runner.py\n')
        self.assertTrue(scored["leak"])
        self.assertEqual(scored["wrong_skill_ids"], 0)
        with tempfile.TemporaryDirectory() as tmp:
            staged = stage_task("box_matches_spec", Path(tmp) / "out")
            self.assertTrue((Path(staged["dir"]) / "prompt.txt").is_file())
            self.assertFalse(scored["leak"] and "evals/" in Path(staged["dir"]).as_posix())
        with self.assertRaises(ValueError):
            stage_task("box_matches_spec", Path(__file__).resolve().parents[1] / "evals")


if __name__ == "__main__":
    unittest.main()
