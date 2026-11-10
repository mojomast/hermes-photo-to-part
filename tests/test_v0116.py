"""v0.1.16: terminal build approval and eval packaging."""

from __future__ import annotations

import ast
import os
import textwrap
import unittest
from pathlib import Path

import yaml

from photopart.build_gate import eval_read_block, terminal_build_approval
from photopart.hooks import on_pre_tool_call, reset_hooks
from photopart.packaging import installed_files, plugin_dir, repo_root

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugin"


def _gate(command: str, tool: str = "terminal", **kwargs):
    return terminal_build_approval(tool, {"command": command}, **kwargs)


class TerminalBuildApprovalTests(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.pop("PHOTOPART_BUILD_APPROVAL", None)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("PHOTOPART_BUILD_APPROVAL", None)
        else:
            os.environ["PHOTOPART_BUILD_APPROVAL"] = self._saved

    def _approves(self, command: str, tool: str = "terminal", **kwargs) -> None:
        result = _gate(command, tool, **kwargs)
        self.assertIsNotNone(result, command)
        self.assertEqual(result["action"], "approve")
        self.assertEqual(result["rule_key"], "photo_part_build")

    def test_build_commands_ask_for_the_same_rule(self):
        positives = [
            "python build.py",
            "python3 /tmp/project/build.py --fast",
            "uv run python build.py",
            "sudo python build.py",
            "FOO=1 python -m photopart.build_run",
            "python -m photopart.stamp",
            "photo-part-build --out hinge.stl",
            "cadquery",
            "build123d --help",
            'python -c "from photopart.stamp import stamp"',
            'python -c "import photopart.build_run"',
            "python -c 'import cadquery as cq\nresult.export(\"part.step\")'",
            "python make_part.py part.stl",
            "python make_part.py --out hinge.step",
        ]
        for command in positives:
            with self.subTest(command=command):
                self._approves(command)
        coded = terminal_build_approval(
            "execute_code",
            {"code": "import build123d\npart.export_stl('hinge.stl')\n"},
        )
        self.assertEqual(coded["rule_key"], "photo_part_build")
        self.assertIsNone(terminal_build_approval("read_terminal", {"command": "python build.py"}))

    def test_a_readable_script_that_exports_is_a_build(self):
        with self._script("import cadquery as cq\nsolid.exporters.export(part, 'out.step')\n") as path:
            self._approves(f"python {path}")

    def test_a_mesh_written_into_the_session_project_is_a_build(self):
        import photopart.hooks as hooks

        reset_hooks()
        command = "python -c 'from photopart.features import spur_gear' out.stl"
        try:
            self.assertIsNone(_gate(command))
            with __import__("tempfile").TemporaryDirectory() as tmp:
                project = Path(tmp)
                hooks._projects["sess"] = project
                args = {"command": command, "workdir": str(project)}
                hooked = terminal_build_approval("terminal", args, session_id="sess")
                self.assertEqual(hooked["rule_key"], "photo_part_build")
                self.assertIsNone(
                    terminal_build_approval(
                        "terminal",
                        {"command": command, "workdir": "/tmp/elsewhere"},
                        session_id="sess",
                    )
                )
        finally:
            reset_hooks()

    def test_plain_commands_and_tests_are_not_builds(self):
        negatives = [
            "ls",
            "ls evals",
            "cat README.md",
            "cat build.py",
            "head -n 20 plugin/photopart/build_run.py",
            "pytest",
            "pytest tests/test_pipeline.py",
            "python -m pytest",
            "python -m unittest discover -s tests",
            "echo import photopart.build_run",
            "rg photopart.build_run",
            'python -c "print(1)"',
            "python -c 'print(1)' && echo import photopart.build_run",
            'python -c "from photopart.features import spur_gear"',
            'python -c "import cadquery"',
            "git status",
        ]
        for command in negatives:
            with self.subTest(command=command):
                self.assertIsNone(_gate(command), command)

    def test_approval_off_skips_the_prompt(self):
        for value in ("allow", "yes", "true", "1", "off", "skip"):
            os.environ["PHOTOPART_BUILD_APPROVAL"] = value
            self.assertIsNone(_gate("python build.py"), value)
        os.environ["PHOTOPART_BUILD_APPROVAL"] = "ask"
        self._approves("python build.py")

    def test_photo_part_validate_is_not_a_terminal_build(self):
        from importlib.util import module_from_spec, spec_from_file_location

        spec = spec_from_file_location("photo_to_part_plugin", PLUGIN / "__init__.py")
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertIsNone(module.approve_build(tool_name="photo_part_validate", args={"mesh": "a.stl"}))
        gated = module.approve_build(tool_name="terminal", args={"command": "python build.py", "cwd": "/part"})
        self.assertEqual(gated["rule_key"], "photo_part_build")
        self.assertIn("/part", gated["message"])

    def _script(self, source: str):
        import tempfile
        from contextlib import contextmanager

        @contextmanager
        def _open():
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "make_hinge.py"
                path.write_text(source, encoding="utf-8")
                yield path

        return _open()


class EvalReadGuardTests(unittest.TestCase):
    def test_scoring_paths_are_blocked_and_ordinary_reads_are_not(self):
        blocked = [
            ("read_file", {"path": str(ROOT / "evals" / "runner.py")}),
            ("read_file", {"file_path": "evals/tasks.json"}),
            ("search_files", {"path": "evals/meshes.py"}),
            ("search_files", {"path": "tests/regression/hinge.stl"}),
            ("read", {"file": "evals/fixtures/washer_photo.jpg"}),
            ("terminal", {"command": "cat evals/runner.py"}),
            ("terminal", {"command": "sed -n 1,20p evals/README.md"}),
            ("bash", {"command": 'python -c "import evals.runner"'}),
            ("terminal", {"command": "rg p2p-canary-7f3a9c2e evals"}),
        ]
        for tool, args in blocked:
            with self.subTest(tool=tool, args=args):
                result = eval_read_block(tool, args)
                self.assertEqual(result["action"], "block", (tool, args))
                self.assertIn("photo_part_build", result["message"])

        allowed = [
            ("read_file", {"path": str(ROOT / "README.md")}),
            ("read_file", {"path": "SECURITY.md"}),
            ("search_files", {"path": "."}),
            ("search_files", {"path": "plugin/photopart"}),
            ("terminal", {"command": "cat README.md"}),
            ("terminal", {"command": "ls evals"}),
            ("terminal", {"command": "ls"}),
            ("terminal", {"command": "pytest tests/regression"}),
            ("terminal", {"command": "python -m unittest tests/test_regression_rounds.py"}),
            ("photo_part_validate", {"mesh": str(ROOT / "evals" / "runner.py")}),
            ("read_terminal", {"command": "cat evals/runner.py"}),
        ]
        for tool, args in allowed:
            with self.subTest(tool=tool, args=args):
                self.assertIsNone(eval_read_block(tool, args), (tool, args))

    def test_pre_tool_call_blocks_a_read_and_leaves_pytest_alone(self):
        reset_hooks()
        try:
            blocked = on_pre_tool_call(
                tool_name="read_file",
                args={"path": "evals/runner.py"},
                session_id="leak",
            )
            self.assertEqual(blocked["action"], "block")
            self.assertIsNone(
                on_pre_tool_call(
                    tool_name="terminal",
                    args={"command": "pytest -q tests/test_pipeline.py"},
                    session_id="leak",
                )
            )
            self.assertIsNone(
                on_pre_tool_call(
                    tool_name="read_file",
                    args={"path": "README.md"},
                    session_id="leak",
                )
            )
        finally:
            reset_hooks()


class PackagingTests(unittest.TestCase):
    def test_subdirectory_install_omits_evals_and_regression_meshes(self):
        files = installed_files(ROOT)
        self.assertTrue(files)
        self.assertIn("__init__.py", files)
        self.assertIn("photopart/build_gate.py", files)
        self.assertIn("plugin.yaml", files)
        joined = "\n".join(files)
        self.assertNotIn("evals/", joined)
        self.assertNotIn("tests/", joined)
        for name in ("runner.py", "meshes.py", "tasks.json"):
            self.assertFalse(any(path.endswith(name) for path in files), name)
        self.assertFalse(any(path.endswith(".stl") and "regression" in path for path in files))
        self.assertTrue((ROOT / "evals" / "runner.py").is_file())
        self.assertTrue((ROOT / "tests" / "regression").is_dir())
        self.assertEqual(plugin_dir(ROOT), PLUGIN)
        self.assertEqual(repo_root(), ROOT)

    def test_plugin_code_does_not_import_evals(self):
        roots = [PLUGIN / "photopart", PLUGIN / "__init__.py"]
        for root in roots:
            paths = [root] if root.is_file() else list(root.rglob("*.py"))
            for path in paths:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        names = [alias.name.split(".")[0] for alias in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        names = [node.module.split(".")[0]]
                    else:
                        continue
                    self.assertNotIn("evals", names, path)

    def test_root_manifest_refuses_a_root_install(self):
        stub = yaml.safe_load((ROOT / "plugin.yaml").read_text(encoding="utf-8"))
        self.assertEqual(stub["name"], "photo-to-part-repo-root")
        self.assertEqual(stub["version"], "0.1.22")
        self.assertEqual(stub["manifest_version"], 99)
        self.assertEqual(stub["requires_hermes"], ">=999.0.0")
        plugin = yaml.safe_load((PLUGIN / "plugin.yaml").read_text(encoding="utf-8"))
        self.assertEqual(plugin["name"], "photo-to-part")
        self.assertEqual(plugin["version"], "0.1.22")
        self.assertEqual(plugin["manifest_version"], 2)

    def test_skill_frontmatter_stays_within_the_length_cap(self):
        text = (PLUGIN / "skills" / "photo-to-printable-part" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Do not run that script with the terminal tool.", text)
        meta = yaml.safe_load(text.split("---", 2)[1])
        self.assertLessEqual(len(meta["description"].strip()), 1024)
        self.assertFalse(textwrap.dedent(meta["description"]).strip().startswith("plugin:"))


if __name__ == "__main__":
    unittest.main()
