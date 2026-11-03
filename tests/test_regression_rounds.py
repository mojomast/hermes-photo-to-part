"""Live meshes from Hermes rounds r10–r12.

``unittest discover -s tests`` collects this module, so a regression fails CI.
Each case is checked with no sidecar and, when a ``.faces.json`` is present,
again with whatever ``load_face_tags`` accepts.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from photopart.features import load_face_tags
from photopart.io import load_mesh
from photopart.printability import check_printability
from photopart.spec import apply_spec, detect_knuckles, openings

ROOT = Path(__file__).resolve().parent / "regression"
MANIFEST = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))


def _wall_warning(report: dict) -> bool:
    return any("wall" in item or "thin area" in item for item in report.get("warnings") or [])


class LiveRoundTests(unittest.TestCase):
    def test_every_archived_case(self):
        self.assertGreaterEqual(len(MANIFEST["cases"]), 24)
        for row in MANIFEST["cases"]:
            with self.subTest(row["id"]):
                self._check(row)

    def _check(self, row: dict) -> None:
        expect = row["expect"]
        mesh_path = ROOT / row["mesh"]
        spec = json.loads((ROOT / row["spec"]).read_text(encoding="utf-8"))
        mesh = load_mesh(mesh_path)
        axis = str(spec.get("knuckle_axis") or "x")
        detected = None
        if "knuckles" in expect or "cylinders_max" in expect or expect.get("no_knuckle_failure"):
            detected = detect_knuckles(mesh, axis)
        if "knuckles" in expect:
            self.assertEqual(detected["knuckles"], expect["knuckles"], row.get("note"))
        if "cylinders_max" in expect:
            self.assertLessEqual(detected["cylinders"], expect["cylinders_max"])
        if "bores" in expect or expect.get("dish_not_bore"):
            found = openings(mesh)
            if "bores" in expect:
                self.assertEqual(len(found["bores"]), expect["bores"], found["bores"])
            if expect.get("dish_not_bore"):
                wide = [bore for bore in found["bores"] if float(bore.get("diameter") or 0) >= 12.0]
                self.assertEqual(wide, [], "a decorative dish is a recess, not a bore")
        if "wall_warning" in expect:
            bare = check_printability(mesh)
            self.assertEqual(_wall_warning(bare), expect["wall_warning"], bare.get("warnings"))
            sidecar = row.get("sidecar")
            if sidecar:
                tags = load_face_tags(mesh_path)
                if tags is not None:
                    tagged = check_printability(mesh, face_tags=tags)
                    self.assertEqual(
                        _wall_warning(tagged),
                        expect["wall_warning"],
                        tagged.get("warnings"),
                    )
        if "spec_pass" in expect or expect.get("no_knuckle_failure"):
            failures, _rows = apply_spec(mesh, spec=spec)
            if expect.get("spec_pass") is True:
                self.assertEqual(failures, [])
            elif expect.get("spec_pass") is False:
                self.assertTrue(failures, "this archived spec does not match the mesh")
            if expect.get("no_knuckle_failure"):
                knuckle_failures = [item for item in failures if item.startswith("spec knuckles")]
                self.assertEqual(knuckle_failures, [])
