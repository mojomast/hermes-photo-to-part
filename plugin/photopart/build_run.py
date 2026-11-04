"""Run one local build script with the plugin interpreter.

``cwd`` is the project directory. stdout and stderr are captured. The argument
list is passed without a shell. Timeout defaults to 60 seconds and cannot
exceed 300. This module does not open a socket and does not add credentials.
"""

from __future__ import annotations

import json
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
        from photopart.spec import note_missing_spec

        return note_missing_spec(attach_flow(report, step_build([], ok=False)), work)
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
        report["error"] = _failure_text(completed.stderr, completed.returncode, script_path)
    from photopart.spec import note_missing_spec

    return note_missing_spec(attach_flow(report, step_build(outputs, ok=ok)), work)


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
        note = None
        try:
            from photopart.repair_fallback import try_meshfix
            from photopart.report import measure as measure_mesh

            current = trimesh.load(path, force="mesh", process=True)
            if isinstance(current, trimesh.Trimesh) and (measure_mesh(current).get("nonmanifold_edges") or 0) > 0:
                fixed, info = try_meshfix(current)
                note = info.get("meshfix_note")
                if info.get("meshfix_applied"):
                    payload = fixed.export(file_type="stl" if path.suffix.lower() == ".stl" else "3mf")
                    if isinstance(payload, str):
                        payload = payload.encode("utf-8")
                    path.write_bytes(payload)
        except Exception:
            note = None
        _ensure_feature_sidecar(path)
        rows.append(
            {
                "file": str(path),
                "shells_before": before,
                "shells_after": after if applied or before == 1 else before,
                "union_applied": applied,
                "meshfix_note": note,
            }
        )
    return rows


def _ensure_feature_sidecar(path: Path) -> None:
    """Write geometric thread or knurl regions when a script export left none.

    Face indices die in a boolean. Detection runs only when the mesh is already
    thin and nothing was tagged, and a failure here does not fail the build.
    """
    try:
        import trimesh

        from photopart.features import load_face_tags
        from photopart.printability import _min_wall, detect_periodic_regions

        existing = load_face_tags(path)
        if existing and (
            existing.get("regions") or any(existing.get(key) for key in ("thread", "knurl", "teeth"))
        ):
            return
        loaded = trimesh.load(path, force="mesh", process=True)
        if not isinstance(loaded, trimesh.Trimesh) or len(loaded.faces) < 16:
            return
        raw = _min_wall(loaded, 24)
        if raw is None or raw >= 0.8:
            return
        regions = detect_periodic_regions(loaded)
        if not regions:
            return
        payload = {"knurl": [], "regions": regions, "teeth": [], "thread": []}
        Path(str(path) + ".faces.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except Exception:
        return


def _failure_text(stderr, returncode: int, script: Path | None = None) -> str:
    """Exception line first, then a short traceback. No skill-id filler.

    A missing build123d or cadquery import names the libraries that are
    installed and the template to use instead of installing one.
    """
    text = _clip(stderr).strip()
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        body = f"build exited {returncode} with no stderr"
    else:
        exception = lines[-1]
        context = lines[max(0, len(lines) - 13) : -1]
        body = exception if not context else exception + "\n" + "\n".join(context)
    guidance = _cad_guidance(body, script)
    if guidance:
        return body + "\n" + guidance
    return body


_CAD_MODULES = ("build123d", "cadquery", "OCP")
_TEMPLATE_RULES = (
    ("strap_hinge", ("strap_hinge", "strap hinge", "strap", "scroll")),
    ("spur_gear", ("spur_gear", "involute", "gear")),
    ("bottle_cap", ("bottle_cap", "bottle cap", "bottle")),
    ("hex_screw", ("hex_screw", "screw")),
    ("hex_standoff", ("hex_standoff", "standoff")),
    ("l_bracket", ("l_bracket", "bracket")),
    ("hinge", ("knuckle", "print-in-place", "print_in_place")),
    ("thread", ("thread",)),
    ("knurl", ("knurl",)),
    ("sweep", ("sweep",)),
)
_FEATURE_IMPORT = {
    "strap_hinge": "strap_hinge",
    "spur_gear": "spur_gear",
    "bottle_cap": "bottle_cap",
    "hex_screw": "hex_screw",
    "hex_standoff": "hex_standoff",
    "thread": "external_thread",
    "knurl": "knurl",
    "sweep": "sweep_path",
    "scroll": "spiral_scroll",
}


def _cad_guidance(error: str, script: Path | None) -> str | None:
    module = _missing_cad_module(error)
    if module is None:
        return None
    script_text = _script_text(script)
    shape = _matching_template(script_text)
    available = _available_libraries()
    if shape:
        point = f"Use photo_part_template shape {shape}."
    else:
        point = "Use photo_part_template. For a strap hinge the shape is strap_hinge."
    feature = _FEATURE_IMPORT.get(shape or "")
    if feature:
        path = f"A trimesh/manifold script can `from photopart.features import {feature}`."
    else:
        path = "A trimesh/manifold script can import photopart.features, or call photo_part_template."
    return (
        f"{module} is not available. Available libraries: {available}. "
        f"{point} {path} "
        "Do not install the missing CAD library and do not patch around it."
    )


def _missing_cad_module(error: str) -> str | None:
    import re

    match = re.search(r"No module named ['\"]([^'\"]+)['\"]", error)
    if match:
        root = match.group(1).split(".", 1)[0]
        if root in _CAD_MODULES or root.lower() in {name.lower() for name in _CAD_MODULES}:
            return root
        return None
    if "ModuleNotFoundError" not in error and "ImportError" not in error:
        return None
    lowered = error.lower()
    for name in _CAD_MODULES:
        if name.lower() in lowered:
            return name
    return None


def _matching_template(script_text: str) -> str | None:
    lowered = script_text.lower()
    if not lowered:
        return None
    for shape, keys in _TEMPLATE_RULES:
        if any(key in lowered for key in keys):
            return shape
    return None


def _script_text(script: Path | None) -> str:
    if script is None:
        return ""
    try:
        return Path(script).read_text(encoding="utf-8", errors="replace")[:20000]
    except OSError:
        return ""


def _available_libraries() -> str:
    import importlib.util

    found = []
    for name in ("trimesh", "manifold3d", "shapely", "numpy", "photopart.features"):
        try:
            spec = importlib.util.find_spec(name)
        except (ImportError, ValueError):
            spec = None
        if spec is not None:
            found.append(name)
    return ", ".join(found) if found else "none"


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
