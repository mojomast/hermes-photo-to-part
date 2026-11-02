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
    history = _snapshot_existing(work)
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
            "error": _timeout_error(limit, exc.stderr),
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
    shells = []
    if ok:
        shells = _union_outputs(outputs)
        outputs = _changed(work, before)
    missing = []
    for path in outputs:
        if Path(path).suffix.lower() in {".stl", ".3mf"}:
            from photopart.history import missing_versions

            for name in missing_versions(path):
                if name not in missing:
                    missing.append(name)
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
        "shells": shells,
        "missing_earlier": missing,
        "history": history,
    }
    if not ok:
        report["error"] = _failure_text(completed.stderr, completed.returncode)
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
        if ".p2p_history" in path.parts:
            continue
        found.append(key)
        if len(found) >= _MAX_OUTPUTS:
            break
    return found


def _snapshot_existing(root: Path) -> list[str]:
    """Keep the previous bytes of top-level STL and 3MF files before the script runs."""
    from photopart.history import snapshot

    saved = []
    if not root.is_dir():
        return saved
    for path in root.iterdir():
        if path.is_file() and path.suffix.lower() in {".stl", ".3mf"}:
            copied = snapshot(path)
            if copied:
                saved.append(copied)
    return saved


def _union_outputs(paths: list[str]) -> list[dict]:
    """Boolean-union overlapping shells and report the count before and after."""
    import trimesh

    from photopart.history import snapshot
    from photopart.manifold_util import union_components

    rows = []
    for raw in paths:
        path = Path(raw)
        if path.suffix.lower() not in {".stl", ".3mf"} or ".p2p_history" in path.parts:
            continue
        try:
            loaded = trimesh.load(path, force="mesh", process=True)
        except Exception as exc:
            rows.append(
                {
                    "file": str(path),
                    "shells_before": None,
                    "shells_after": None,
                    "union_applied": False,
                    "error": str(exc),
                }
            )
            continue
        if not isinstance(loaded, trimesh.Trimesh) or len(loaded.faces) == 0:
            continue
        before = len(loaded.split(only_watertight=False))
        applied = False
        after = before
        if before > 1:
            merged, did = union_components(loaded)
            if did:
                after = len(merged.split(only_watertight=False))
                if after < before:
                    try:
                        snapshot(path)
                        kind = "stl" if path.suffix.lower() == ".stl" else "3mf"
                        payload = merged.export(file_type=kind)
                        if isinstance(payload, str):
                            payload = payload.encode("utf-8")
                        path.write_bytes(payload)
                        applied = True
                    except Exception:
                        after = before
                        applied = False
                else:
                    after = before
        rows.append(
            {
                "file": str(path),
                "shells_before": before,
                "shells_after": after if applied or before == 1 else before,
                "union_applied": applied,
            }
        )
    return rows


def _failure_text(stderr, returncode: int) -> str:
    """Exception line first, then a short traceback. No skill-id filler."""
    text = _clip(stderr).strip()
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return f"build exited {returncode} with no stderr"
    exception = lines[-1]
    context = lines[max(0, len(lines) - 13) : -1]
    if not context:
        return exception
    return exception + "\n" + "\n".join(context)


def _timeout_error(limit: float, stderr) -> str:
    text = _clip(stderr).strip()
    lines = [line for line in text.splitlines() if line.strip()]
    message = f"TimeoutExpired: build exceeded {limit:g}s"
    if lines:
        return message + "\n" + lines[-1]
    return message


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
