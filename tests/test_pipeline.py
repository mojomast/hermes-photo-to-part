"""Prove the sample part, the checkers, and the plugin entrypoint."""

from __future__ import annotations

import ast
import json
import runpy
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from photopart.geometry import (  # noqa: E402
    build_mesh,
    expected_extents,
    parse_params,
    write_template,
)
from photopart.io import load_mesh  # noqa: E402
from photopart.heal import heal_mesh
from photopart.render import render_views
from photopart.validate import evaluate, main as validate_main

SKILL = ROOT / "skills" / "photo-to-printable-part"
SCRIPTS = SKILL / "scripts"


class TemplateTests(unittest.TestCase):
    def test_default_plate_is_watertight_and_on_size(self):
        mesh = build_mesh()
        extents = expected_extents(parse_params())
        report = evaluate(mesh, target=extents, tolerance=0.05)
        self.assertTrue(report["ok"], report["failures"])
        self.assertTrue(report["watertight"])
        self.assertTrue(report["winding_consistent"])
        self.assertGreater(report["volume_mm3"], 0)
        self.assertEqual(report["components"], 1)
        self.assertEqual(report["boundary_edges"], 0)
        self.assertEqual(report["nonmanifold_edges"], 0)

    def test_height_changes_the_y_extent(self):
        mesh = build_mesh({"height_mm": 40})
        self.assertAlmostEqual(mesh.extents[1], 40 + 12, places=4)

    def test_straight_plate_still_closes(self):
        mesh = build_mesh({"lower_taper_mm": 0})
        self.assertTrue(mesh.is_watertight)

    def test_slot_outside_the_plate_is_rejected(self):
        with self.assertRaises(ValueError):
            build_mesh({"slot_center_x_mm": 2, "slot_width_mm": 10})

    def test_unknown_parameter_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_params({"not_a_real_parameter": 1})


class ValidateTests(unittest.TestCase):
    def test_stl_roundtrip_keeps_a_real_hole(self):
        box = trimesh.creation.box(extents=(10, 20, 30))
        box.update_faces(np.arange(len(box.faces) - 1))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "open.stl"
            path.write_bytes(box.export(file_type="stl"))
            loaded = load_mesh(path)
        self.assertFalse(loaded.is_watertight)
        report = evaluate(loaded)
        self.assertFalse(report["ok"])

    def test_open_box_fails(self):
        box = trimesh.creation.box(extents=(10, 20, 30))
        box.update_faces(np.arange(len(box.faces) - 1))
        report = evaluate(box, target=(10, 20, 30), tolerance=0.01)
        self.assertFalse(report["ok"])
        self.assertFalse(report["watertight"])

    def test_axis_swap_is_opt_in(self):
        mesh = build_mesh()
        swapped = (6.0, 51.0, 72.6)
        strict = evaluate(mesh, target=swapped, tolerance=0.05)
        loose = evaluate(mesh, target=swapped, tolerance=0.05, allow_axis_swap=True)
        self.assertFalse(strict["ok"])
        self.assertTrue(loose["ok"], loose["failures"])

    def test_cli_exit_codes(self):
        mesh = build_mesh()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "part.stl"
            path.write_bytes(mesh.export(file_type="stl"))
            code = validate_main([str(path), "--size", "51", "72.6", "6", "--tolerance", "0.05"])
            self.assertEqual(code, 0)
            code = validate_main([str(path), "--size", "10", "10", "10", "--tolerance", "0.05"])
            self.assertEqual(code, 2)
            code = validate_main([str(Path(tmp) / "missing.stl")])
            self.assertEqual(code, 1)


class HealTests(unittest.TestCase):
    def test_missing_face_is_filled(self):
        box = trimesh.creation.box(extents=(10, 20, 30))
        box.update_faces(np.arange(len(box.faces) - 1))
        self.assertFalse(box.is_watertight)
        repaired, report = heal_mesh(box)
        self.assertTrue(repaired.is_watertight)
        self.assertTrue(report["after"]["watertight"])
        self.assertEqual(report["after"]["triangles"], 12)
        self.assertFalse(box.is_watertight)

    def test_largest_shell_is_kept(self):
        big = trimesh.creation.box(extents=(10, 10, 10))
        small = trimesh.creation.box(extents=(4, 4, 4))
        small.apply_translation((30, 0, 0))
        both = trimesh.util.concatenate([big, small])
        repaired, report = heal_mesh(both, keep_largest=True)
        self.assertEqual(report["shells_dropped"], 1)
        self.assertEqual(len(repaired.faces), 12)
        self.assertTrue(repaired.is_watertight)


class RenderTests(unittest.TestCase):
    def test_views_and_side_by_side(self):
        mesh = build_mesh()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            photo = root / "photo.png"
            from photopart.showcase import synthetic_reference

            synthetic_reference(photo)
            manifest = render_views(mesh, root / "renders", grid_mm=2, photo=photo)
            for name in ("front.png", "side.png", "top.png", "iso.png", "contact.png", "compare_front.png"):
                path = root / "renders" / name
                self.assertTrue(path.is_file(), name)
                self.assertTrue(path.read_bytes().startswith(b"\x89PNG"))
            self.assertFalse(manifest["decimated_for_preview"])
            self.assertEqual(manifest["grid_mm"], 2)


class ExportTests(unittest.TestCase):
    def test_ascii_stl_and_optional_3mf(self):
        with tempfile.TemporaryDirectory() as tmp:
            written = write_template(Path(tmp), ascii_stl=True, write_3mf=True)
            text = written["stl"].read_text(encoding="utf-8")
            self.assertIn("facet normal", text)
            scad = written["scad"].read_text(encoding="utf-8")
            self.assertIn("linear_extrude", scad)
            self.assertIn("polygon", scad)
            if written["threemf"] is None:
                self.skipTest(written["threemf_error"])
            with zipfile.ZipFile(written["threemf"]) as archive:
                model = next(name for name in archive.namelist() if name.endswith("3dmodel.model"))
                xml = archive.read(model)
            self.assertIn(b"millimeter", xml)


class ScriptTests(unittest.TestCase):
    def test_validate_script_bootstraps(self):
        mesh = build_mesh()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "part.stl"
            path.write_bytes(mesh.export(file_type="stl"))
            argv = sys.argv
            sys.argv = [
                "export_validate.py",
                str(path),
                "--size",
                "51",
                "72.6",
                "6",
                "--tolerance",
                "0.05",
            ]
            try:
                with self.assertRaises(SystemExit) as caught:
                    runpy.run_path(str(SCRIPTS / "export_validate.py"), run_name="__main__")
            finally:
                sys.argv = argv
            self.assertEqual(caught.exception.code, 0)


class PluginTests(unittest.TestCase):
    def test_register_discovers_the_skill(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("photo_to_part_plugin", ROOT / "__init__.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        found = []

        class Ctx:
            def register_skill(self, name, path):
                found.append((name, Path(path)))

        module.register(Ctx())
        self.assertEqual(found, [("photo-to-printable-part", SKILL / "SKILL.md")])

    def test_skill_frontmatter(self):
        import yaml

        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        front = text.split("---", 2)[1]
        meta = yaml.safe_load(front)
        self.assertEqual(meta["name"], "photo-to-printable-part")
        self.assertEqual(meta["version"], "0.1.0")
        description = meta["description"].strip()
        self.assertLessEqual(len(description), 1024)
        self.assertIn("STL", description)
        self.assertIn("grid", description)
        for name in (
            "references/cad-backends.md",
            "references/print-tolerances.md",
            "references/feedback-and-scale.md",
            "references/scan-cleanup.md",
        ):
            self.assertIn(name, text)
            self.assertTrue((SKILL / name).is_file())

    def test_manifest_matches_project(self):
        import tomllib
        import yaml

        manifest = yaml.safe_load((ROOT / "plugin.yaml").read_text(encoding="utf-8"))
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "photo-to-part")
        self.assertEqual(manifest["version"], "0.1.0")
        self.assertEqual(project["project"]["version"], "0.1.0")
        self.assertEqual(manifest["python_dependencies"], project["project"]["dependencies"])
        self.assertEqual(manifest["provides_tools"], [])
        self.assertEqual(manifest["provides_hooks"], [])
        self.assertEqual(manifest["requires_env"], [])
        self.assertEqual(manifest["license"], "MIT")

    def test_helpers_do_not_shell_out_or_open_the_network(self):
        banned = {"subprocess", "socket", "urllib", "requests", "httpx", "pickle", "eval", "exec"}
        roots = [ROOT / "photopart", SCRIPTS, ROOT / "__init__.py"]
        files = []
        for root in roots:
            if root.is_file():
                files.append(root)
            else:
                files.extend(root.rglob("*.py"))
        for path in files:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module.split(".")[0]]
                else:
                    names = []
                self.assertFalse(banned.intersection(names), f"{path.name} imports {names}")


class ExampleTests(unittest.TestCase):
    def test_checked_in_sample_still_validates(self):
        stl = ROOT / "examples" / "plate-clip" / "plate_clip.stl"
        report_path = ROOT / "examples" / "plate-clip" / "report.json"
        self.assertTrue(stl.is_file(), "run python -m photopart.showcase to build the sample")
        code = validate_main([str(stl), "--size", "51", "72.6", "6", "--tolerance", "0.05"])
        self.assertEqual(code, 0)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertTrue(report["ok"])


if __name__ == "__main__":
    unittest.main()
