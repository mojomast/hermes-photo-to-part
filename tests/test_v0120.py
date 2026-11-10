"""v0.1.20: pane terminals, tool steering, budget reserve, failed overlays, frozen axes."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from photopart.pane import view_state
from photopart.progress import note_result, settle_project
from photopart.tools import tool_specs

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugin"
SKILL = PLUGIN / "skills" / "photo-to-printable-part" / "SKILL.md"


def _state(project: Path) -> dict:
    return json.loads((project / ".photopart" / "pane.json").read_text(encoding="utf-8"))


class PaneTerminalTests(unittest.TestCase):
    def test_passing_validate_is_ready_without_a_photo_compare(self):
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw) / "fitting"
            project.mkdir()
            stl = project / "body_v4.stl"
            stl.write_bytes(b"solid")
            note_result(
                "photo_part_validate",
                {"ok": True, "file": str(stl), "spec": str(project / "spec.json"), "out_dir": str(project)},
            )
            state = _state(project)
            self.assertEqual(state["status"], "ready")
            self.assertIn("Ready to deliver", state["message"])

    def test_measure_only_settles_to_measured_when_the_session_ends(self):
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
            mid = _state(project)
            self.assertEqual(mid["status"], "running")
            self.assertTrue(mid.get("measure_complete"))
            settle_project(project, ended=True)
            done = _state(project)
            self.assertEqual(done["status"], "measured")
            self.assertIn("Measurement complete", done["message"])

    def test_interrupted_runs_go_stale_then_ready_or_incomplete(self):
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw) / "bracket"
            project.mkdir()
            stl = project / "bracket_v1.stl"
            stl.write_bytes(b"solid")
            note_result(
                "photo_part_build",
                {"ok": True, "stl": str(stl), "cwd": str(project), "out_dir": str(project)},
            )
            note_result(
                "photo_part_validate",
                {"ok": True, "file": str(stl), "spec": str(project / "spec.json"), "out_dir": str(project)},
            )
            # Already ready from validate. Make a running mid-refine run for stale.
            running = Path(raw) / "open"
            running.mkdir()
            note_result(
                "photo_part_measure",
                {"ok": True, "out_dir": str(running), "px_per_mm": 4, "kind": "ruler"},
            )
            first = settle_project(running, ended=False, stale_after=0, now="2099-01-01T00:00:00Z")
            self.assertEqual(first["status"], "stale")
            settle_project(running, ended=True)
            self.assertEqual(_state(running)["status"], "measured")

            empty = Path(raw) / "empty"
            empty.mkdir()
            note_result("photo_part_heal", {"ok": True, "cwd": str(empty), "out": str(empty / "scan.stl")})
            settle_project(empty, force=True, ended=True)
            self.assertEqual(_state(empty)["status"], "incomplete")

            settle_project(project, ended=True)
            self.assertEqual(_state(project)["status"], "ready")

    def test_iteration_strip_follows_the_headline_not_a_failed_later_build(self):
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw) / "hinge"
            project.mkdir()
            Image.new("RGB", (12, 12), (200, 180, 160)).save(project / "photo.png")
            Image.new("RGB", (12, 12), (40, 90, 140)).save(project / "overlay.png")
            Image.new("RGB", (12, 12), (180, 180, 180)).save(project / "front.png")
            (project / "strap_v1.stl").write_bytes(b"solid")
            note_result(
                "photo_part_render",
                {
                    "ok": True,
                    "mesh": str(project / "strap_v1.stl"),
                    "out_dir": str(project),
                    "overlay": str(project / "overlay.png"),
                    "overlay_iou": 0.4212,
                    "overlay_iou_label": "untrusted",
                    "views": [str(project / "front.png")],
                    "final": True,
                    "spec": str(project / "spec.json"),
                },
            )
            # A passing validate first so the run can be ready, then failed later builds.
            note_result(
                "photo_part_validate",
                {
                    "ok": True,
                    "file": str(project / "strap_v1.stl"),
                    "spec": str(project / "spec.json"),
                    "out_dir": str(project),
                    "overlay_iou": 0.4212,
                },
            )
            for n in (2, 3, 4):
                note_result(
                    "photo_part_build",
                    {
                        "ok": False,
                        "error": "not a volume",
                        "cwd": str(project),
                        "script": str(project / f"build_v{n}.py"),
                        "overlay": str(project / "overlay.png"),
                    },
                )
            state = _state(project)
            self.assertEqual(state["iteration"], 1)
            ious = {item["n"]: item.get("iou") for item in state["iterations"]}
            self.assertAlmostEqual(ious[1], 0.4212)
            for n in (2, 3, 4):
                self.assertIsNone(ious.get(n), ious)
            view = view_state(state)
            active = [item["n"] for item in view["iterations"] if item["active"]]
            self.assertEqual(active, [1])
            self.assertAlmostEqual(view["metrics"]["iou"], 0.4212)

    def test_validate_render_payload_includes_a_front_view(self):
        from photopart.tools import _maybe_render

        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            mesh = project / "fork_v1.stl"
            mesh.write_bytes(b"solid")
            front = project / "renders" / "front.png"
            overlay = project / "renders" / "overlay.png"
            front.parent.mkdir()
            Image.new("RGB", (8, 8), (10, 10, 10)).save(front)
            Image.new("RGB", (8, 8), (11, 11, 11)).save(overlay)
            report = {"ok": True, "file": str(mesh)}
            manifest = {
                "ok": True,
                "overlay": str(overlay),
                "views": [str(front)],
                "compare_front": str(front),
                "sheet": str(front),
            }
            with patch("photopart.render.run_render", return_value=(0, manifest)), \
                 patch("photopart.measure.load_last_measure", return_value={"px_per_mm": 10, "image": str(project / "p.png")}):
                (project / "p.png").write_bytes(front.read_bytes())
                _maybe_render({"spec": str(project / "spec.json"), "photo": str(project / "p.png")}, report)
            self.assertEqual(report["render"]["front"], str(front))
            self.assertEqual(report["render"]["views"], [str(front)])
            note_result("photo_part_validate", report)
            state = _state(project)
            self.assertTrue(state["images"].get("render", "").endswith("front.png"), state["images"])

    def test_hole_and_knuckle_probe_notes_are_quiet_on_the_pane(self):
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw) / "part"
            project.mkdir()
            stl = project / "part_v1.stl"
            stl.write_bytes(b"solid")
            note_result(
                "photo_part_validate",
                {
                    "ok": True,
                    "file": str(stl),
                    "spec": str(project / "spec.json"),
                    "out_dir": str(project),
                    "warnings": [
                        "min wall 0.9 mm is close to 0.8 mm.",
                        "per-hole probe disagrees with the bore detector or the probe is ambiguous. "
                        "Warning only. This does not fail validation and does not block delivery.",
                        "knuckles=3 by rings, 0 cylinders. knuckle probe is unreliable here; "
                        "the check is reported as a warning",
                    ],
                },
            )
            view = view_state(_state(project))
            joined = " ".join(view["warnings"])
            self.assertNotIn("per-hole probe disagrees", joined)
            self.assertNotIn("knuckle probe is unreliable", joined)
            self.assertIn("2 hole or knuckle probe notes hidden", joined)
            self.assertTrue(any("min wall" in item for item in view["warnings"]))


class SteeringAndBudgetTests(unittest.TestCase):
    def test_skill_and_tool_text_point_at_the_spur_gear_template(self):
        skill = SKILL.read_text(encoding="utf-8")
        self.assertIn("shape `spur_gear`", skill)
        self.assertIn("involute", skill.lower())
        specs = {item["name"]: item for item in tool_specs()}
        for name in ("photo_part_template", "photo_part_build"):
            blob = specs[name]["description"] + specs[name]["schema"]["description"]
            self.assertIn("spur_gear", blob)
            self.assertIn("involute", blob.lower())
            self.assertLess(len(specs[name]["schema"]["description"]), 900)
        from photopart.catalog import describe_shapes

        help_text = describe_shapes("spur_gear")
        self.assertIn("spur_gear", help_text["note"])
        self.assertIn("involute", help_text["summary"].lower())

    def test_reserve_wall_refuses_a_new_template_when_a_validated_file_exists(self):
        import trimesh

        from photopart.tools import template_tool
        from photopart.validate import run_validate

        saved = os.environ.get("PHOTO_PART_MAX_CALLS")
        os.environ["PHOTO_PART_MAX_CALLS"] = "20"
        try:
            with tempfile.TemporaryDirectory() as raw:
                project = Path(raw)
                trimesh.creation.box(extents=(10, 8, 4)).export(project / "plate_v1.stl")
                spec = project / "spec.json"
                spec.write_text(json.dumps({"x": 10, "y": 8, "z": 4}), encoding="utf-8")
                code, report = run_validate(str(project / "plate_v1.stl"), spec=str(spec), tolerance=0.2)
                self.assertTrue(report["ok"], report.get("failures"))
                self.assertEqual(code, 0)
                refused = json.loads(
                    template_tool({"shape": "plate", "out_dir": str(project), "calls_used": 19})
                )
                self.assertFalse(refused["ok"], refused)
                self.assertTrue(refused.get("refused"))
                self.assertIn("deliver", refused["error"].lower())
                self.assertIn("plate_v1.stl", refused["error"])
                empty = Path(raw) / "fresh"
                empty.mkdir()
                allowed = json.loads(
                    template_tool(
                        {"shape": "plate", "out_dir": str(empty), "calls_used": 19, "no_3mf": True}
                    )
                )
                self.assertTrue(allowed["ok"], allowed)
        finally:
            if saved is None:
                os.environ.pop("PHOTO_PART_MAX_CALLS", None)
            else:
                os.environ["PHOTO_PART_MAX_CALLS"] = saved

    def test_hook_note_at_95_percent_says_to_deliver(self):
        from photopart.hooks import _NOTE, _transform, reset_hooks
        import photopart.hooks as hooks

        reset_hooks()
        try:
            hooks._active.add("s")
            hooks._counts["s"] = 38
            hooks._notes["s"] = {"60", "80"}
            text = _transform(tool_name="terminal", args={"command": "ls"}, session_id="s", result="ok")
            self.assertIn("38 of 40", text)
            self.assertIn("deliver the best validated version", text)
            self.assertIn("{advice}", _NOTE)
        finally:
            reset_hooks()


class OverlayAndDimensionTests(unittest.TestCase):
    def test_low_iou_on_an_angled_photo_is_untrusted_not_a_success(self):
        import numpy as np

        from photopart.overlay import _overlay_warnings, _write_overlay

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            image = np.full((40, 40, 3), 255, dtype=np.uint8)
            placed = np.zeros((40, 40), dtype=bool)
            placed[2:8, 2:8] = True
            foreground = np.zeros((40, 40), dtype=bool)
            foreground[10:36, 10:36] = True
            blob = {"x": 10, "y": 10, "w": 26, "h": 26, "source": "largest"}
            warnings = _overlay_warnings(0.06, blob, angled=True, missed=False, fit={"iou": 0.06, "fit_confidence": "low"})
            report = _write_overlay(
                image,
                placed,
                foreground,
                blob,
                root / "overlay.png",
                root / "diff.png",
                fit="auto",
                note="",
                iou=0.06,
                warnings=warnings,
                rotation=0,
                mirror=False,
                view="front",
                angled=True,
                alignment={"iou": 0.06, "iou_trusted": False},
            )
            self.assertEqual(report["overlay_iou_label"], "untrusted")
            joined = " ".join(report["overlay_warnings"])
            self.assertIn("untrusted", joined)
            self.assertIn("do not treat this as a successful photo match", joined.lower())
            self.assertNotIn("overlay_iou_label is guide_only", joined)

    def test_usable_angled_fit_stays_guide_only(self):
        import numpy as np

        from photopart.overlay import _write_overlay

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            image = np.full((24, 24, 3), 255, dtype=np.uint8)
            mask = np.zeros((24, 24), dtype=bool)
            mask[4:20, 4:20] = True
            report = _write_overlay(
                image,
                mask,
                mask,
                {"x": 4, "y": 4, "w": 16, "h": 16, "source": "roi"},
                root / "overlay.png",
                root / "diff.png",
                fit="auto",
                note="",
                iou=0.79,
                warnings=[],
                rotation=0,
                mirror=False,
                view="front",
                angled=True,
            )
            self.assertEqual(report["overlay_iou_label"], "guide_only")

    def test_assumed_axes_are_not_frozen_and_user_axes_stay_exact(self):
        import trimesh

        from photopart.freeze import locked_axes_from_spec, snap_mesh_to_locked_axes, user_axis_values
        from photopart.validate import run_validate

        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            spec = {
                "x": 30.5,
                "y": 30.5,
                "z": 13.0,
                "sources": {
                    "x": "user stated outside diameter 30.5 mm",
                    "y": "user stated outside diameter 30.5 mm",
                    "z": "assumed: photo-derived height",
                },
            }
            self.assertEqual(set(user_axis_values(spec)), {"x", "y"})
            mesh = trimesh.creation.cylinder(radius=15.2315, height=13)
            # extents x/y are the diameter ~30.463
            self.assertAlmostEqual(float(mesh.extents[0]), 30.463, places=2)
            locked = locked_axes_from_spec(None, spec)
            self.assertEqual(set(locked), {"x", "y"})
            snapped, changed = snap_mesh_to_locked_axes(mesh, locked)
            self.assertTrue(changed)
            self.assertAlmostEqual(float(snapped.extents[0]), 30.5, places=2)
            self.assertAlmostEqual(float(snapped.extents[1]), 30.5, places=2)
            drifted = project / "cap_v2.stl"
            trimesh.creation.cylinder(radius=15.2315, height=13).export(drifted)
            spec_path = project / "spec.json"
            spec_path.write_text(json.dumps(spec), encoding="utf-8")
            _code, first = run_validate(str(drifted), spec=str(spec_path), tolerance=0.3)
            self.assertFalse(first["ok"], first)
            self.assertTrue(any("must stay exact" in item for item in first["failures"]), first["failures"])
            snapped_path = project / "cap_v3.stl"
            mesh2 = trimesh.creation.cylinder(radius=15.2315, height=13)
            mesh2, _changed = snap_mesh_to_locked_axes(mesh2, locked)
            mesh2.export(snapped_path)
            _code, second = run_validate(
                str(snapped_path),
                spec=str(spec_path),
                tolerance=0.3,
                spec_reason=None,
            )
            # The freeze already exists from the first validate; extents now match.
            self.assertTrue(second["ok"], second.get("failures"))


if __name__ == "__main__":
    unittest.main()
