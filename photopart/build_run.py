"""Run one local build script with the plugin interpreter.

``cwd`` is the project directory. stdout and stderr are captured. The argument
list is passed without a shell. Timeout defaults to 60 seconds and cannot
exceed 300. This module does not open a socket and does not add credentials.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from photopart.flow import attach_flow, failed, step_build
from photopart.launcher import plugin_python
from photopart.paths import absolute_path, under_cache

_OUTPUT_CAP = 20_000
_MAX_OUTPUTS = 200


def run_build(
    script: str | Path,
    *,
    cwd: str | Path | None = None,
    timeout: float = 60,
    args: list | None = None,
) -> dict:
    """Execute ``script`` and return JSON-ready fields, including new files."""
    script_path = Path(script).expanduser()
    if not script_path.is_file():
        raise ValueError(f"build script not found: {script_path}")
    if script_path.suffix.lower() != ".py":
        raise ValueError("build script must be a .py file")
    script_path = script_path.resolve()
    work = _workdir(cwd)
    limit = _timeout(timeout)
    extra = [str(item) for item in (args or [])]
    interpreter = plugin_python()
    before = _snapshot(work)
    argv = [interpreter, str(script_path), *extra]
    try:
        completed = subprocess.run(
            argv,
            cwd=str(work),
            timeout=limit,
            capture_output=True,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        report = {
            "ok": False,
            "timeout": True,
            "error": f"build exceeded {limit:g}s",
            "interpreter": interpreter,
            "cwd": str(work),
            "script": str(script_path),
            "returncode": None,
            "stdout": _clip(exc.stdout),
            "stderr": _clip(exc.stderr),
            "outputs": [],
        }
        return attach_flow(report, step_build([], ok=False))
    outputs = _changed(work, before)
    ok = completed.returncode == 0
    report = {
        "ok": ok,
        "timeout": False,
        "interpreter": interpreter,
        "cwd": str(work),
        "script": str(script_path),
        "returncode": completed.returncode,
        "stdout": _clip(completed.stdout),
        "stderr": _clip(completed.stderr),
        "outputs": outputs,
    }
    if not ok:
        report["error"] = f"build exited {completed.returncode}"
    return attach_flow(report, step_build(outputs, ok=ok))


def _workdir(cwd: str | Path | None) -> Path:
    if cwd is None or cwd == "":
        work = Path.cwd().resolve()
        if under_cache(work):
            raise ValueError(
                "the working directory is inside HERMES_HOME/cache. "
                "Pass cwd as an absolute path in the user project."
            )
        return work
    work = absolute_path(cwd)
    if not work.is_dir():
        raise ValueError(f"cwd is not a directory: {work}")
    return work


def _timeout(timeout: float) -> float:
    try:
        limit = float(timeout)
    except (TypeError, ValueError) as exc:
        raise ValueError("timeout must be a number of seconds") from exc
    if limit != limit or limit <= 0:  # NaN or non-positive
        raise ValueError("timeout must be positive and at most 300 seconds")
    if limit > 300:
        raise ValueError("timeout must be at most 300 seconds")
    return limit


def _snapshot(root: Path) -> dict[str, tuple[int, int]]:
    found: dict[str, tuple[int, int]] = {}
    if not root.is_dir():
        return found
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        found[str(path.resolve())] = (stat.st_size, stat.st_mtime_ns)
    return found


def _changed(root: Path, before: dict[str, tuple[int, int]]) -> list[str]:
    found = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        resolved = path.resolve()
        key = str(resolved)
        try:
            stat = path.stat()
        except OSError:
            continue
        current = (stat.st_size, stat.st_mtime_ns)
        if before.get(key) == current:
            continue
        found.append(key)
        if len(found) >= _MAX_OUTPUTS:
            break
    return found


def _clip(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        text = value.decode("utf-8", "replace")
    else:
        text = str(value)
    if len(text) > _OUTPUT_CAP:
        return text[:_OUTPUT_CAP] + "\n...truncated..."
    return text


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Run a build script with the plugin interpreter.")
    parser.add_argument("script")
    parser.add_argument("--cwd", help="Project directory. Default: the working directory.")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("script_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    extra = list(args.script_args)
    if extra[:1] == ["--"]:
        extra = extra[1:]
    try:
        report = run_build(args.script, cwd=args.cwd, timeout=args.timeout, args=extra)
    except (OSError, ValueError) as exc:
        print(json.dumps(failed(str(exc)), indent=2, sort_keys=True))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("ok") else 1
