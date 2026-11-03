"""Prove the sample part, the checkers, and the plugin entrypoint."""

from __future__ import annotations

import ast
import json
import os
import runpy
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
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
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                code = validate_main([str(path), "--size", "51", "72.6", "6", "--tolerance", "0.05"])
            self.assertEqual(code, 0)
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                code = validate_main([str(path), "--size", "10", "10", "10", "--tolerance", "0.05"])
            self.assertEqual(code, 2)
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
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
        self.assertEqual(report["shells_before"], 1)
        self.assertEqual(report["shells_dropped"], 0)
        self.assertEqual(report["repair_fragments_removed"], 0)
        self.assertFalse(report["fan_requested"])
        self.assertFalse(report["fan_used"])
        self.assertFalse(report["fan_fallback"])

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
            manifest = render_views(mesh, root / "renders", grid_mm=2, photo=photo, pixels=240, samples=1)
            for name in ("front.png", "side.png", "top.png", "iso.png", "contact.png", "compare_front.png"):
                path = root / "renders" / name
                self.assertTrue(path.is_file(), name)
                self.assertTrue(path.read_bytes().startswith(b"\x89PNG"))
            self.assertFalse(manifest["decimated_for_preview"])
            self.assertEqual(manifest["decimation"], "none")
            self.assertEqual(manifest["grid_mm"], 2)
            self.assertEqual(manifest["view_axes"]["up"], "y")
            self.assertEqual(manifest["view_axes"]["front_axis"], "z")
            side = np.asarray(Image_open(root / "renders" / "side.png").convert("RGB"))[40:]
            part = np.all(side < 200, axis=2)
            ys, xs = np.nonzero(part)
            thickness_over_height = (xs.max() - xs.min()) / (ys.max() - ys.min())
            self.assertLess(thickness_over_height, 0.2)


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
                with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
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
        tools = []

        class Ctx:
            def register_skill(self, name, path):
                found.append((name, Path(path)))

            def register_tool(self, name, toolset, schema, handler, description="", **kwargs):
                tools.append(
                    {
                        "name": name,
                        "toolset": toolset,
                        "schema": schema,
                        "handler": handler,
                        "description": description,
                    }
                )

        module.register(Ctx())
        self.assertEqual(found, [("photo-to-printable-part", SKILL / "SKILL.md")])
        names = [item["name"] for item in tools]
        self.assertEqual(names, [
            "photo_part_validate",
            "photo_part_render",
            "photo_part_heal",
            "photo_part_template",
            "photo_part_measure",
            "photo_part_build",
        ])
        for item in tools:
            self.assertEqual(item["toolset"], "photo-to-part")
            self.assertEqual(item["schema"]["name"], item["name"])
            self.assertTrue(callable(item["handler"]))
            self.assertTrue(item["description"])

    def test_skill_frontmatter(self):
        import yaml

        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        front = text.split("---", 2)[1]
        meta = yaml.safe_load(front)
        self.assertEqual(meta["name"], "photo-to-printable-part")
        self.assertEqual(meta["version"], "0.1.10")
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
        self.assertEqual(manifest["version"], "0.1.10")
        self.assertEqual(project["project"]["version"], "0.1.10")
        self.assertEqual(manifest["python_dependencies"], project["project"]["dependencies"])
        from photopart.tools import TOOL_NAMES

        self.assertEqual(manifest["provides_tools"], list(TOOL_NAMES))
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
                if path.name == "build_run.py":
                    names = [name for name in names if name != "subprocess"]
                self.assertFalse(banned.intersection(names), f"{path.name} imports {names}")
                if isinstance(node, ast.Call):
                    for keyword in node.keywords:
                        if (
                            keyword.arg == "shell"
                            and isinstance(keyword.value, ast.Constant)
                            and keyword.value.value is True
                        ):
                            self.fail(f"{path} uses shell=True")


class ExampleTests(unittest.TestCase):
    def test_checked_in_sample_still_validates(self):
        stl = ROOT / "examples" / "plate-clip" / "plate_clip.stl"
        report_path = ROOT / "examples" / "plate-clip" / "report.json"
        sidecar = Path(str(stl) + ".validate.json")
        self.assertTrue(stl.is_file(), "run python -m photopart.showcase to build the sample")
        try:
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                code = validate_main([str(stl), "--size", "51", "72.6", "6", "--tolerance", "0.05"])
            self.assertEqual(code, 0)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertTrue(report["ok"])
        finally:
            if sidecar.is_file():
                sidecar.unlink()


class StdoutContractTests(unittest.TestCase):
    def _json_stdout(self, func, argv):
        out = StringIO()
        err = StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = func(argv)
        text = out.getvalue().strip()
        self.assertTrue(text, "stdout was empty")
        self.assertNotEqual(text.splitlines()[-1], "ok")
        self.assertNotIn("FAILED", text)
        return code, json.loads(text), err.getvalue()

    def test_validate_status_is_on_stderr(self):
        mesh = build_mesh()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "part.stl"
            path.write_bytes(mesh.export(file_type="stl"))
            code, report, err = self._json_stdout(
                validate_main, [str(path), "--size", "51", "72.6", "6", "--tolerance", "0.05"]
            )
            self.assertEqual(code, 0)
            self.assertTrue(report["ok"])
            self.assertIn("ok", err)
            code, report, err = self._json_stdout(
                validate_main, [str(path), "--size", "10", "10", "10", "--tolerance", "0.05"]
            )
            self.assertEqual(code, 2)
            self.assertFalse(report["ok"])
            self.assertIn("FAILED", err)
            self.assertNotIn("ok", err)

    def test_heal_and_render_stdout_are_json(self):
        from photopart.heal import main as heal_main
        from photopart.render import main as render_main

        mesh = build_mesh()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "part.stl"
            src.write_bytes(mesh.export(file_type="stl"))
            code, report, err = self._json_stdout(
                heal_main, [str(src), "--out", str(root / "healed.stl")]
            )
            self.assertEqual(code, 0)
            self.assertTrue(report["ok"])
            self.assertIn("ok", err)
            code, report, err = self._json_stdout(
                render_main,
                [str(src), "--out-dir", str(root / "renders"), "--grid-mm", "2"],
            )
            self.assertEqual(code, 0)
            self.assertTrue(report["ok"])
            self.assertIn("ok", err)
            self.assertTrue(str(report["views"][0]).endswith("front.png"))


class UnitAndFrameTests(unittest.TestCase):
    def test_metre_scale_warns_until_units_are_declared(self):
        box = trimesh.creation.box(extents=(0.10, 0.12, 0.156))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scan.stl"
            path.write_bytes(box.export(file_type="stl"))
            out = StringIO()
            with redirect_stdout(out), redirect_stderr(StringIO()):
                code = validate_main([str(path)])
            self.assertEqual(code, 2)
            report = json.loads(out.getvalue())
            self.assertFalse(report["ok"])
            self.assertIsNotNone(report["unit_warning"])
            self.assertLess(report["extents_mm"]["z"], 1.0)
            self.assertAlmostEqual(report["input_extents_file"]["z"], report["extents_mm"]["z"], places=3)
            out = StringIO()
            with redirect_stdout(out), redirect_stderr(StringIO()):
                code = validate_main([str(path), "--allow-size"])
            self.assertEqual(code, 0)
            allowed = json.loads(out.getvalue())
            self.assertTrue(allowed["ok"])
            self.assertIsNotNone(allowed["unit_warning"])
            out = StringIO()
            with redirect_stdout(out), redirect_stderr(StringIO()):
                code = validate_main([str(path), "--units", "m", "--size", "100", "120", "156", "--tolerance", "0.5"])
            self.assertEqual(code, 0)
            scaled = json.loads(out.getvalue())
            self.assertIsNone(scaled["unit_warning"])
            self.assertAlmostEqual(scaled["extents_mm"]["z"], 156.0, delta=0.5)
            self.assertAlmostEqual(scaled["scale_to_mm"], 1000.0)
            self.assertEqual(scaled["length_unit"], "millimetres")

    def test_centimetre_box_is_ten_times_larger(self):
        box = trimesh.creation.box(extents=(1.0, 2.0, 3.0))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cm.stl"
            path.write_bytes(box.export(file_type="stl"))
            out = StringIO()
            with redirect_stdout(out):
                code = validate_main(
                    [str(path), "--units", "cm", "--size", "10", "20", "30", "--tolerance", "0.05"]
                )
            self.assertEqual(code, 0, out.getvalue())
            report = json.loads(out.getvalue())
            self.assertTrue(report["ok"], report["failures"])

    def test_tiny_mesh_fills_the_render_frame(self):
        from photopart.render import run_render

        box = trimesh.creation.box(extents=(0.10, 0.10, 0.156))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "tiny.stl"
            path.write_bytes(box.export(file_type="stl"))
            _code, manifest = run_render([str(path), "--out-dir", str(root / "cli")])
            self.assertEqual(manifest["length_unit"], "file units")
            self.assertIsNotNone(manifest["unit_warning"])
            manifest = render_views(box, root / "direct", pixels=180, samples=1)
            image = np.asarray(Image_open(root / "direct" / "front.png"))
            mask = np.any(image < 250, axis=2)
            ys, xs = np.nonzero(mask)
            self.assertGreater((xs.max() - xs.min()) / image.shape[1], 0.4)
            self.assertGreater((ys.max() - ys.min()) / image.shape[0], 0.4)

    def test_upright_part_uses_z_as_up(self):
        peg = trimesh.creation.box(extents=(10, 10, 100))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = render_views(peg, root / "auto", pixels=80, samples=1)
            self.assertEqual(manifest["view_axes"]["up"], "z")
            self.assertEqual(manifest["view_axes"]["front_axis"], "x")
            forced = render_views(peg, root / "forced", up="y", pixels=80, samples=1)
            self.assertEqual(forced["view_axes"]["up"], "y")
            self.assertNotEqual(forced["view_axes"]["front_axis"], forced["view_axes"]["up"])


def _interior_coverage(path: Path) -> float:
    """Fraction of the part's own bounding box that is painted, not background."""
    image = np.asarray(Image_open(path).convert("RGB"))
    # The title sits in a 40px header. Measuring past it keeps the title out of the part box.
    if image.shape[0] > 40:
        image = image[40:]
    mask = np.any(image < 250, axis=2)
    ys, xs = np.nonzero(mask)
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    # Inset so the silhouette edge and the title band are not the sample.
    pad_y = max(1, (y1 - y0) // 10)
    pad_x = max(1, (x1 - x0) // 10)
    interior = mask[y0 + pad_y : y1 - pad_y, x0 + pad_x : x1 - pad_x]
    self_empty = interior.size == 0
    if self_empty:
        return 0.0
    return float(np.mean(interior))


def Image_open(path):
    from PIL import Image

    return Image.open(path)


class PreviewAndOverlayTests(unittest.TestCase):
    def test_quadric_preview_keeps_one_body(self):
        from photopart.render import PREVIEW_FACE_CAP, _preview_mesh

        sphere = trimesh.creation.icosphere(subdivisions=5, radius=20)
        self.assertGreater(len(sphere.faces), PREVIEW_FACE_CAP)
        preview, info = _preview_mesh(sphere)
        self.assertEqual(info["decimation"], "quadric")
        self.assertTrue(info["decimated_for_preview"])
        self.assertLess(info["preview_faces"], len(sphere.faces))
        self.assertLessEqual(info["preview_faces"], PREVIEW_FACE_CAP * 1.5)
        parts = preview.split(only_watertight=False)
        largest = max(len(part.faces) for part in parts)
        self.assertGreater(largest / len(preview.faces), 0.9)
        source = (ROOT / "photopart" / "render.py").read_text(encoding="utf-8")
        self.assertNotIn("np.linspace", source)
        with tempfile.TemporaryDirectory() as tmp:
            render_views(preview, Path(tmp), pixels=72, samples=1)
            filled = _interior_coverage(Path(tmp) / "front.png")
        self.assertGreater(filled, 0.9)

    def test_flat_part_interior_is_solid(self):
        plate = trimesh.creation.box(extents=(40, 30, 8))
        plate = plate.subdivide().subdivide()
        with tempfile.TemporaryDirectory() as tmp:
            render_views(plate, Path(tmp), pixels=120, samples=1)
            self.assertGreater(_interior_coverage(Path(tmp) / "front.png"), 0.95)

    def test_vertex_cluster_fallback_does_not_stride_faces(self):
        from photopart.render import _cluster_preview

        sphere = trimesh.creation.icosphere(subdivisions=4, radius=15)
        clustered = _cluster_preview(sphere, 600)
        self.assertLessEqual(len(clustered.faces), 600)
        self.assertGreater(len(clustered.faces), 0)
        parts = clustered.split(only_watertight=False)
        largest = max(len(part.faces) for part in parts)
        self.assertGreater(largest / max(len(clustered.faces), 1), 0.5)

    def test_full_raster_when_quadric_is_unavailable(self):
        from photopart.render import _preview_mesh

        sphere = trimesh.creation.icosphere(subdivisions=5, radius=10)

        def boom(*_args, **_kwargs):
            raise RuntimeError("no decimator")

        sphere.simplify_quadric_decimation = boom
        preview, info = _preview_mesh(sphere)
        self.assertEqual(info["decimation"], "full")
        self.assertEqual(len(preview.faces), len(sphere.faces))
        self.assertFalse(info["decimated_for_preview"])

    def test_overlay_changes_the_photo(self):
        from PIL import Image

        box = trimesh.creation.box(extents=(10, 20, 30))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            photo = root / "photo.png"
            Image.new("RGB", (240, 240), "white").save(photo)
            manifest = render_views(
                box,
                root / "renders",
                photo=photo,
                photo_scale=4,
                pixels=80,
                samples=1,
            )
            overlay = root / "renders" / "overlay.png"
            self.assertEqual(manifest["overlay"], str(overlay))
            self.assertTrue(overlay.is_file())
            self.assertTrue((root / "renders" / "compare_front.png").is_file())
            before = np.asarray(Image.open(photo))
            after = np.asarray(Image.open(overlay))
            self.assertEqual(before.shape, after.shape)
            self.assertTrue(np.any(before != after))
            self.assertGreater(int(np.count_nonzero(np.any(after < 250, axis=2))), 40)


class HealReportTests(unittest.TestCase):
    def test_shell_accounting_keeps_fragments_out_of_shells_dropped(self):
        from photopart.heal import account_shells

        self.assertEqual(account_shells(1, 2), (0, 1))
        self.assertEqual(account_shells(2, 2), (1, 0))
        self.assertEqual(account_shells(1, 1), (0, 0))
        self.assertEqual(account_shells(2, 4), (1, 2))

    def test_fan_fallback_is_labeled_on_a_large_hole(self):
        cyl = trimesh.creation.cylinder(radius=5, height=10, sections=24)
        top = (cyl.triangles_center[:, 2] > 4.0) & (cyl.face_normals[:, 2] > 0.7)
        self.assertTrue(np.any(top))
        cyl.update_faces(~top)
        self.assertFalse(cyl.is_watertight)
        repaired, report = heal_mesh(cyl)
        self.assertTrue(report["fan_fallback"])
        self.assertTrue(report["fan_used"])
        self.assertFalse(report["fan_requested"])
        self.assertEqual(report["shells_before"], 1)
        self.assertEqual(report["shells_dropped"], 0)
        self.assertIn("fan_fallback", report["note"])
        _mesh, forced = heal_mesh(cyl.copy(), use_fan=True)
        self.assertTrue(forced["fan_requested"])
        self.assertTrue(forced["fan_used"])
        self.assertFalse(forced["fan_fallback"])

    def test_repair_fragment_is_not_an_input_shell(self):
        mesh = _boxes_joined_by_degenerate_bridge()
        before = mesh.split(only_watertight=False)
        self.assertEqual(len(before), 1, "bridge should make one shell before the repair")
        _repaired, report = heal_mesh(mesh)
        self.assertEqual(report["shells_before"], 1)
        self.assertEqual(report["shells_dropped"], 0)
        self.assertGreaterEqual(report["repair_fragments_removed"], 1)
        self.assertEqual(report["after"]["components"], 1)


def _open_box(extents: tuple[float, float, float]) -> tuple[trimesh.Trimesh, tuple[int, int]]:
    """A box missing one face, plus one boundary edge of that hole."""
    box = trimesh.creation.box(extents=extents)
    box.update_faces(np.arange(len(box.faces) - 1))
    counts = np.bincount(np.asarray(box.edges_unique_inverse))
    boundary = np.flatnonzero(counts == 1)
    edge = np.asarray(box.edges_unique)[int(boundary[0])]
    return box, (int(edge[0]), int(edge[1]))


def _boxes_joined_by_degenerate_bridge() -> trimesh.Trimesh:
    """Two open boxes linked only by zero-area faces, so repair splits them.

    The link uses boundary edges, which trimesh counts as adjacent. A third
    face on an edge that already has two neighbors would not join the graph.
    """
    box_a, (i0, i1) = _open_box((10, 10, 10))
    box_b, (j0, j1) = _open_box((6, 6, 6))
    vertices_a = np.asarray(box_a.vertices, dtype=float)
    vertices_b = np.asarray(box_b.vertices, dtype=float)
    direction = vertices_a[i1] - vertices_a[i0]
    direction = direction / np.linalg.norm(direction)
    vertices_b = vertices_b + (vertices_a[i1] + direction * 4.0 - vertices_b[j0])
    vertices_b[j0] = vertices_a[i1] + direction * 4.0
    vertices_b[j1] = vertices_a[i1] + direction * 8.0
    offset = len(vertices_a)
    faces = np.vstack(
        [
            np.asarray(box_a.faces),
            np.asarray(box_b.faces) + offset,
            [[i0, i1, offset + j0], [offset + j0, offset + j1, i0]],
        ]
    )
    return trimesh.Trimesh(vertices=np.vstack([vertices_a, vertices_b]), faces=faces, process=False)


class ToolAndLauncherTests(unittest.TestCase):
    def test_tools_return_json_and_do_not_print_ok(self):
        from photopart.tools import heal_tool, render_tool, template_tool, validate_tool

        mesh = build_mesh()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "part.stl"
            path.write_bytes(mesh.export(file_type="stl"))
            out = StringIO()
            with redirect_stdout(out):
                raw = validate_tool({"mesh": str(path), "size": [51, 72.6, 6], "tolerance": 0.05})
            self.assertEqual(out.getvalue(), "")
            report = json.loads(raw)
            self.assertTrue(report["ok"], report.get("failures"))
            with redirect_stdout(out):
                rendered = render_tool(
                    {"mesh": str(path), "out_dir": str(root / "views"), "grid_mm": 2}
                )
            self.assertEqual(out.getvalue(), "")
            manifest = json.loads(rendered)
            self.assertTrue(manifest["ok"])
            self.assertTrue((root / "views" / "front.png").is_file())
            with redirect_stdout(out):
                healed = heal_tool({"mesh": str(path), "out": str(root / "healed.stl")})
            self.assertEqual(out.getvalue(), "")
            self.assertTrue(json.loads(healed)["ok"])
            with redirect_stdout(out):
                made = template_tool({"out_dir": str(root / "sample"), "no_3mf": True, "ascii": True})
            self.assertEqual(out.getvalue(), "")
            summary = json.loads(made)
            self.assertTrue(summary["ok"])
            self.assertTrue((root / "sample" / "plate_clip.stl").is_file())

    def test_register_module_does_not_import_trimesh_at_load(self):
        for path in (ROOT / "__init__.py", ROOT / "photopart" / "tools.py", ROOT / "photopart" / "launcher.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in tree.body:
                if isinstance(node, ast.Import):
                    names = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module.split(".")[0]]
                else:
                    continue
                self.assertNotIn("trimesh", names, path.name)

    def test_scripts_reexec_before_importing_trimesh_modules(self):
        expected = {
            "export_validate.py": "photopart.validate",
            "render_views.py": "photopart.render",
            "heal_scan.py": "photopart.heal",
            "make_template.py": "photopart.geometry",
        }
        for name, imported in expected.items():
            source = (SCRIPTS / name).read_text(encoding="utf-8")
            self.assertLess(source.index("ensure_plugin_python()"), source.index(imported))

    def test_launcher_stays_when_trimesh_imports(self):
        from photopart.launcher import candidate_pythons, ensure_plugin_python, pick_reexec

        with tempfile.TemporaryDirectory() as tmp:
            old = os.environ.get("HERMES_HOME")
            os.environ["HERMES_HOME"] = tmp
            try:
                self.assertEqual(candidate_pythons(Path(tmp), include_virtualenv=False), [])
                ensure_plugin_python()
            finally:
                if old is None:
                    os.environ.pop("HERMES_HOME", None)
                else:
                    os.environ["HERMES_HOME"] = old
        self.assertIsNone(
            pick_reexec(
                can_import=True,
                already_reexec=False,
                candidates=[Path("/usr/bin/python3")],
                current=Path("/usr/bin/false"),
            )
        )
        chosen = pick_reexec(
            can_import=False,
            already_reexec=False,
            candidates=[Path("/usr/bin/python3")],
            current=Path("/usr/bin/false"),
        )
        self.assertEqual(chosen, Path("/usr/bin/python3"))

    def test_facts_json_points_at_the_plugin_python(self):
        from photopart.launcher import candidate_pythons, ensure_plugin_python

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            install = home / "installs" / "photo-to-part"
            venv = install / "environments" / "3" / "venv"
            binary = venv / "bin" / "python"
            binary.parent.mkdir(parents=True)
            binary.write_text("", encoding="utf-8")
            (install / "facts.json").write_text(
                json.dumps({"packages": {"venv": {"environment": str(venv)}}}),
                encoding="utf-8",
            )
            found = candidate_pythons(home, include_virtualenv=False)
            self.assertEqual(found, [binary.resolve()])
            recorded = {}

            def fake_exec(program, argv, env):
                recorded["program"] = program
                recorded["argv"] = argv
                recorded["flag"] = env.get("PHOTO_PART_PYTHON_REEXEC")

            choice = ensure_plugin_python(
                can_import=False,
                candidates=found,
                exec_fn=fake_exec,
                argv=["heal_scan.py", "scan.stl"],
                already=False,
            )
            self.assertEqual(choice, binary.resolve())
            self.assertEqual(recorded["program"], str(binary.resolve()))
            self.assertEqual(recorded["flag"], "1")
            self.assertEqual(recorded["argv"][0], str(binary.resolve()))

    def test_missing_plugin_env_tells_the_agent_to_use_tools(self):
        from photopart.launcher import ensure_plugin_python

        err = StringIO()
        with redirect_stderr(err):
            with self.assertRaises(SystemExit) as caught:
                ensure_plugin_python(
                    can_import=False,
                    candidates=[],
                    exec_fn=lambda *_args: self.fail("exec should not run"),
                    already=False,
                )
        self.assertEqual(caught.exception.code, 1)
        text = err.getvalue()
        self.assertIn("photo_part_validate", text)
        self.assertIn("Do not pip install", text)


class GuidanceTests(unittest.TestCase):
    def test_skill_states_the_real_id_budget_and_limits(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("photo-to-part:photo-to-printable-part", text)
        self.assertIn("`plugin:photo-to-part:photo-to-printable-part` is not a skill name", text)
        self.assertIn("Use one photo_part_validate and one photo_part_render per version.", text)
        self.assertIn("Do not write an overlay script.", text)
        self.assertIn("Do not delete a file the user told you to skip.", text)
        self.assertIn("Do not claim the part passed a fit test", text)
        self.assertIn("--photo-scale", text)
        self.assertIn("photo_part_heal", text)
        self.assertNotIn("No network", text)
        backends = (SKILL / "references" / "cad-backends.md").read_text(encoding="utf-8")
        self.assertIn('cadquery>=2.6,<2.9', backends)
        self.assertIn('build123d>=0.10,<0.14', backends)
        self.assertIn("several minutes", backends)
        self.assertNotIn("No network", backends)
        for relative in ("README.md", "SECURITY.md", "plugin.yaml"):
            self.assertNotIn("No network", (ROOT / relative).read_text(encoding="utf-8"), relative)


if __name__ == "__main__":
    unittest.main()
