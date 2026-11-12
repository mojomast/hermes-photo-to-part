"""0.1.23: catalog review fixes (NousResearch/hermes-agent#153757).

1. photo_part_build runs a script with an explicit minimal environment.
2. No environment variable can switch the build approval off.
3. The eval read-block and the steer hooks only act on this plugin's own
   checkout and on sessions that used the plugin.
4. Shared state lives under get_hermes_home()/plugin-data/photo-to-part, and
   per-project .photopart/ files only go into folders named by photo_part_*
   arguments that pass Hermes's write denylist.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hermes_stub import hermes_home_stub  # noqa: E402

from photopart import build_gate, paths  # noqa: E402
from photopart.build_run import CHILD_ENV_NAMES, child_env, run_build  # noqa: E402
from photopart.hooks import on_post_tool_call, on_pre_tool_call, reset_hooks  # noqa: E402
from photopart.progress import index_path  # noqa: E402
from photopart.sessions import hermes_home as sessions_home  # noqa: E402

PLUGIN = Path(__file__).resolve().parents[1] / "plugin"
SENTINEL = "P2P_TEST_PROVIDER_KEY"


class ChildEnvTests(unittest.TestCase):
    def test_allowlist_has_no_secrets_or_prefix_copies(self):
        source = {
            "PATH": "/usr/bin",
            "HOME": "/home/u",
            "LANG": "C.UTF-8",
            "OPENAI_API_KEY": "sk-should-not-pass",
            "ANTHROPIC_API_KEY": "x",
            "NODE_OPTIONS": "--require evil.js",
            "LC_FAKE_SECRET": "x",
            SENTINEL: "x",
        }
        env = child_env(source)
        self.assertEqual(env["PATH"], "/usr/bin")
        self.assertEqual(env["HOME"], "/home/u")
        for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "NODE_OPTIONS", "LC_FAKE_SECRET", SENTINEL):
            self.assertNotIn(name, env)
        self.assertTrue(set(env) <= set(CHILD_ENV_NAMES) | {"PYTHONIOENCODING", "PYTHONDONTWRITEBYTECODE"})
        self.assertIn(str(PLUGIN.resolve()), env["PYTHONPATH"].split(os.pathsep))

    def test_build_script_never_sees_an_unrelated_secret(self):
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            script = project / "probe_env.py"
            script.write_text(
                "import json, os\n"
                "open('env.json', 'w').write(json.dumps(sorted(os.environ)))\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {SENTINEL: "sentinel-value", "OPENAI_API_KEY": "sk-test"}):
                report = run_build(script, cwd=project)
            self.assertTrue(report["ok"], report.get("error"))
            names = json.loads((project / "env.json").read_text(encoding="utf-8"))
            self.assertNotIn(SENTINEL, names)
            self.assertNotIn("OPENAI_API_KEY", names)
            self.assertIn("PATH", names)


class ApprovalSwitchTests(unittest.TestCase):
    def test_no_environment_switch_left_in_the_plugin(self):
        for path in [PLUGIN / "__init__.py", *sorted((PLUGIN / "photopart").glob("*.py"))]:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("PHOTOPART_BUILD_APPROVAL", text, path.name)
            self.assertNotIn("approval_skipped", text, path.name)


class EvalBlockScopeTests(unittest.TestCase):
    def test_installed_plugin_never_blocks_reads(self):
        with patch("photopart.paths.source_checkout_root", return_value=None):
            self.assertIsNone(build_gate.eval_read_block("read_file", {"path": "/work/app/evals/runner.py"}))
            self.assertIsNone(build_gate.eval_read_block("terminal", {"command": "cat evals/tasks.json"}))
            self.assertFalse(build_gate.protected_read_text("cat evals/tasks.json"))

    def test_unrelated_project_evals_are_not_blocked(self):
        with tempfile.TemporaryDirectory() as raw:
            checkout = Path(raw) / "checkout"
            other = Path(raw) / "my-app"
            (checkout / "evals").mkdir(parents=True)
            (other / "evals").mkdir(parents=True)
            (other / "tests" / "regression").mkdir(parents=True)
            with patch("photopart.paths.source_checkout_root", return_value=checkout):
                self.assertIsNone(build_gate.eval_read_block("read_file", {"path": str(other / "evals" / "runner.py")}))
                self.assertIsNone(
                    build_gate.eval_read_block(
                        "terminal",
                        {"command": "cat evals/tasks.json tests/regression/a.stl", "workdir": str(other)},
                    )
                )
                blocked = build_gate.eval_read_block("read_file", {"path": str(checkout / "evals" / "runner.py")})
                self.assertEqual(blocked["action"], "block")
                inside = build_gate.eval_read_block(
                    "terminal", {"command": "cat evals/tasks.json", "workdir": str(checkout)}
                )
                self.assertEqual(inside["action"], "block")
                absolute = build_gate.eval_read_block(
                    "terminal", {"command": f"cat {checkout}/evals/tasks.json", "workdir": str(other)}
                )
                self.assertEqual(absolute["action"], "block")

    def test_pre_tool_hook_leaves_other_projects_alone(self):
        reset_hooks()
        with tempfile.TemporaryDirectory() as raw:
            other = Path(raw) / "service"
            (other / "evals").mkdir(parents=True)
            with patch("photopart.paths.source_checkout_root", return_value=Path(raw) / "checkout"):
                result = on_pre_tool_call(
                    tool_name="read_file",
                    args={"path": str(other / "evals" / "tasks.json")},
                    session_id="unrelated",
                )
            self.assertIsNone(result)


class StateLocationTests(unittest.TestCase):
    def setUp(self):
        reset_hooks()
        self._saved = os.environ.get("HERMES_HOME")

    def tearDown(self):
        reset_hooks()
        if self._saved is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = self._saved

    def test_shared_state_is_under_plugin_data(self):
        with tempfile.TemporaryDirectory() as raw, hermes_home_stub():
            os.environ["HERMES_HOME"] = raw
            expected = Path(raw).resolve() / "plugin-data" / "photo-to-part"
            self.assertEqual(paths.state_dir(), expected)
            self.assertEqual(index_path(), expected / "pane-index.json")
            self.assertEqual(sessions_home(), Path(raw).resolve())

    def test_no_home_guess_outside_hermes(self):
        with patch.dict(sys.modules, {"hermes_constants": None, "plugins.plugin_storage": None}):
            os.environ.pop("HERMES_HOME", None)
            self.assertIsNone(paths.hermes_home())
            self.assertIsNone(paths.state_dir())
            self.assertIsNone(index_path())
            self.assertIsNone(sessions_home())

    def test_other_tool_paths_never_pick_the_project(self):
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw) / "part"
            elsewhere = Path(raw) / "elsewhere"
            project.mkdir()
            elsewhere.mkdir()
            (elsewhere / "notes.txt").write_text("x", encoding="utf-8")
            on_post_tool_call(
                tool_name="skill_view",
                args={"name": "photo-to-part:photo-to-printable-part"},
                session_id="s1",
            )
            on_post_tool_call(
                tool_name="read_file",
                args={"file": str(elsewhere / "notes.txt")},
                session_id="s1",
            )
            self.assertFalse((elsewhere / ".photopart").exists())
            on_post_tool_call(
                tool_name="photo_part_validate",
                args={"help": True, "cwd": str(project)},
                session_id="s1",
            )
            self.assertTrue((project / ".photopart" / "budget.json").is_file())
            on_post_tool_call(
                tool_name="terminal",
                args={"command": "ls", "cwd": str(elsewhere)},
                session_id="s1",
            )
            self.assertFalse((elsewhere / ".photopart").exists())

    def test_write_denylist_is_honoured(self):
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw) / "protected"
            project.mkdir()
            with patch("photopart.paths.write_denied", return_value="Hermes refuses writes here."):
                on_post_tool_call(
                    tool_name="photo_part_validate",
                    args={"help": True, "cwd": str(project)},
                    session_id="s2",
                )
            self.assertFalse((project / ".photopart").exists())


if __name__ == "__main__":
    unittest.main()
