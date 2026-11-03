"""v0.1.7: register_tool omits output_schema unless Hermes accepts it."""

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

import trimesh

from evals.runner import HermesV0217Context, load_plugin_register, registration_report
from photopart.tools import TOOL_NAMES, _call_register_tool, register_tools, tool_specs, validate_tool

ROOT = Path(__file__).resolve().parents[1]


def _plugin_register():
    return load_plugin_register()


class _Recording:
    def __init__(self, register_tool):
        self.tools = []
        self.skills = []
        self._register_tool = register_tool

    def register_skill(self, name, path):
        self.skills.append((name, path))

    def register_tool(self, *args, **kwargs):
        self._register_tool(self, *args, **kwargs)


def _accepting_output_schema(ctx, name, toolset, schema, handler, description="", output_schema=None, **kwargs):
    ctx.tools.append(
        {
            "name": name,
            "toolset": toolset,
            "schema": schema,
            "handler": handler,
            "description": description,
            "output_schema": output_schema,
            "extra": kwargs,
        }
    )


def _kwargs_accepting(ctx, name, toolset, schema, handler, description="", **kwargs):
    ctx.tools.append(
        {
            "name": name,
            "toolset": toolset,
            "schema": schema,
            "handler": handler,
            "description": description,
            "kwargs": kwargs,
        }
    )


class RegisterCompatTests(unittest.TestCase):
    def test_version_is_0_1_7(self):
        from photopart import __version__

        self.assertEqual(__version__, "0.1.15")

    def test_six_tools_register_against_hermes_v0217(self):
        ctx = HermesV0217Context()
        _plugin_register()(ctx)
        self.assertEqual(len(ctx.tools), 6)
        self.assertEqual([item["name"] for item in ctx.tools], list(TOOL_NAMES))
        for item in ctx.tools:
            self.assertNotIn("output_schema", item)
            self.assertIn("output_schema=", item["description"])
            self.assertIn("output_schema=", item["schema"]["description"])
            self.assertIn('"ok"', item["description"])
            self.assertTrue(callable(item["handler"]))

    def test_six_tools_register_when_output_schema_is_a_parameter(self):
        specs = tool_specs()
        original = specs[0]["schema"]["description"]
        ctx = _Recording(_accepting_output_schema)
        register_tools(ctx)
        self.assertEqual(len(ctx.tools), 6)
        self.assertEqual([item["name"] for item in ctx.tools], list(TOOL_NAMES))
        self.assertEqual(specs[0]["schema"]["description"], original)
        for spec, item in zip(specs, ctx.tools):
            self.assertEqual(item["output_schema"]["description"], spec["name"])
            self.assertIn("cause", item["output_schema"]["properties"])
            self.assertIn("fix", item["output_schema"]["properties"])
            self.assertNotIn("output_schema=", item["description"])
            self.assertNotIn("output_schema=", item["schema"]["description"])

    def test_six_tools_register_when_register_tool_takes_var_keyword(self):
        ctx = _Recording(_kwargs_accepting)
        _plugin_register()(ctx)
        self.assertEqual([item["name"] for item in ctx.tools], list(TOOL_NAMES))
        for item in ctx.tools:
            self.assertIn("output_schema", item["kwargs"])
            self.assertNotIn("output_schema=", item["description"])

    def test_typeerror_fallback_retries_without_output_schema(self):
        seen = []

        def register_tool(name, toolset, schema, handler, description="", output_schema=None, **kwargs):
            if output_schema is not None:
                raise TypeError("register_tool() got an unexpected keyword argument 'output_schema'")
            seen.append(
                {
                    "name": name,
                    "description": description,
                    "schema_description": schema["description"],
                    "kwargs": kwargs,
                }
            )

        register_tools(type("Ctx", (), {"register_tool": staticmethod(register_tool)})())
        self.assertEqual(len(seen), 6)
        self.assertEqual([item["name"] for item in seen], list(TOOL_NAMES))
        for item in seen:
            self.assertIn("output_schema=", item["description"])
            self.assertNotIn("output_schema", item["kwargs"])

    def test_other_optional_keywords_are_omitted_when_unsupported(self):
        seen = {}

        def register_tool(name, toolset, schema, handler, description=""):
            seen["description"] = description
            seen["schema_description"] = schema["description"]
            seen["names"] = (name, toolset)

        _call_register_tool(
            register_tool,
            name="photo_part_validate",
            toolset="photo-to-part",
            schema={"name": "photo_part_validate", "description": "check the mesh"},
            handler=validate_tool,
            description="check the mesh",
            output_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
            emoji="cube",
        )
        self.assertEqual(seen["names"], ("photo_part_validate", "photo-to-part"))
        self.assertIn("output_schema=", seen["description"])
        self.assertIn("unsupported_register_kwargs=", seen["description"])
        self.assertIn("cube", seen["description"])
        self.assertIn("output_schema=", seen["schema_description"])

    def test_detailed_result_keeps_the_output_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            mesh = Path(tmp) / "part.stl"
            trimesh.creation.box(extents=(10, 20, 30)).export(mesh)
            concise = json.loads(validate_tool({"mesh": str(mesh), "response_format": "concise"}))
            detailed = json.loads(validate_tool({"mesh": str(mesh), "response_format": "detailed"}))
        self.assertNotIn("output_schema", concise)
        schema = detailed["output_schema"]
        self.assertEqual(schema["description"], "photo_part_validate")
        self.assertIn("ok", schema["required"])
        self.assertIn("cause", schema["properties"])
        self.assertIn("fix", schema["properties"])

    def test_entrypoint_registration_report_names_six_tools(self):
        report = registration_report()
        self.assertIsNone(report["error"], report["error"])
        self.assertEqual(report["count"], 6)
        self.assertEqual(report["names"], list(TOOL_NAMES))

    def test_runner_fails_when_register_yields_fewer_than_six_tools(self):
        import evals.runner as runner

        def register(ctx):
            ctx.register_tool(
                "photo_part_validate",
                "photo-to-part",
                {},
                lambda params: "{}",
                description="only one",
            )

        original = runner.load_plugin_register
        runner.load_plugin_register = lambda: register
        try:
            report = runner.run_suite()
            stderr = StringIO()
            with redirect_stderr(stderr), redirect_stdout(StringIO()):
                code = runner.main([])
        finally:
            runner.load_plugin_register = original
        self.assertFalse(report["ok"])
        self.assertEqual(report["tools_registered"], 1)
        self.assertEqual(report["results"], [])
        self.assertIn("plugin registration failed", report["registration_error"])
        self.assertIn("yielded 1 tools, expected 6", report["registration_error"])
        self.assertEqual(code, 1)
        self.assertIn("plugin registration failed", stderr.getvalue())
        self.assertIn("expected 6", stderr.getvalue())


class HermesCliTests(unittest.TestCase):
    def test_hermes_plugins_validate_and_doctor(self):
        import os
        import shutil
        import subprocess

        hermes = shutil.which("hermes")
        if hermes is None:
            self.skipTest(
                "hermes-agent is not installed. Hermes v0.21.7 dependencies require "
                "Python 3.14, so the 3.11/3.12 unit jobs skip `hermes plugins validate` "
                "and `hermes plugins doctor`. The signature tests above cover registration."
            )
        home = tempfile.mkdtemp(prefix="hermes-home-")
        env = dict(os.environ)
        env["HERMES_HOME"] = home
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        validate = subprocess.run(
            [hermes, "plugins", "validate", str(ROOT)],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        doctor = subprocess.run(
            [hermes, "plugins", "doctor", str(ROOT), "--ci"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(validate.returncode, 0, validate.stdout + validate.stderr)
        self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
        self.assertIn("6 tool", doctor.stdout + doctor.stderr)


if __name__ == "__main__":
    unittest.main()
