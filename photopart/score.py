"""Per-version score and the best validated sibling.

Higher is better. A passing watertight mesh with every spec row inside
tolerance scores above a mesh that drifted. ``next_step`` says stop on the
best passing version and names the version to revert to when this one is worse.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from photopart.stamp import mesh_hash, sidecar_path

_VERSION = re.compile(r"^(?P<prefix>.+)_v(?P<n>\d+)$")


def compute_score(report: dict) -> dict:
    """Numeric score from watertightness, spec rows, residual, and print warnings."""
    watertight = 40.0 if report.get("watertight") else 0.0
    rows = [row for row in (report.get("spec") or []) if isinstance(row, dict)]
    residual = 0.0
    if rows:
        passed = sum(1 for row in rows if row.get("ok"))
        spec_score = 40.0 * passed / len(rows)
        for row in rows:
            if row.get("name") in {"x", "y", "z"} and row.get("actual") is not None and row.get("value") is not None:
                residual = max(residual, abs(float(row["actual"]) - float(row["value"])))
    else:
        spec_score = 40.0 if report.get("ok") else 0.0
    print_warnings = list((report.get("printability") or {}).get("warnings") or [])
    penalty = min(residual, 30.0) + 5.0 * len(print_warnings)
    if not report.get("ok"):
        penalty += 20.0
    score = round(watertight + spec_score - penalty, 3)
    return {
        "score": score,
        "residual_mm": round(residual, 4),
        "spec_rows": len(rows),
        "print_warnings": len(print_warnings),
        "watertight": bool(report.get("watertight")),
    }


def best_sibling(path: Path) -> dict | None:
    """Highest-scoring fresh passing sibling, excluding ``path`` itself."""
    match = _VERSION.match(path.stem)
    if not match:
        return None
    prefix = match.group("prefix")
    suffix = path.suffix
    best = None
    try:
        names = list(path.parent.iterdir())
    except OSError:
        return None
    pattern = re.compile(rf"^{re.escape(prefix)}_v(\d+){re.escape(suffix)}$")
    for candidate in names:
        found = pattern.match(candidate.name)
        if not found or not candidate.is_file() or candidate.resolve() == path.resolve():
            continue
        row = _fresh_score(candidate)
        if row is None:
            continue
        if best is None or row["score"] > best["score"]:
            best = row
    return best


def best_validated(path: Path) -> dict | None:
    """Highest-scoring fresh passing file in this version family, including ``path``."""
    match = _VERSION.match(path.stem)
    if not match:
        row = _fresh_score(path)
        return row
    prefix = match.group("prefix")
    suffix = path.suffix
    best = None
    pattern = re.compile(rf"^{re.escape(prefix)}_v(\d+){re.escape(suffix)}$")
    try:
        names = list(path.parent.iterdir())
    except OSError:
        return _fresh_score(path)
    for candidate in names:
        if pattern.match(candidate.name) and candidate.is_file():
            row = _fresh_score(candidate)
            if row is None:
                continue
            if best is None or row["score"] > best["score"] or (
                row["score"] == best["score"] and row["n"] > best["n"]
            ):
                best = row
    return best


def _fresh_score(path: Path) -> dict | None:
    side = sidecar_path(path)
    if not side.is_file():
        return None
    try:
        payload = json.loads(side.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        return None
    if payload.get("sha256") != mesh_hash(path):
        return None
    score = payload.get("score")
    if not isinstance(score, (int, float)):
        return None
    match = _VERSION.match(path.stem)
    number = int(match.group("n")) if match else 0
    return {"path": path.resolve(), "name": path.name, "score": float(score), "n": number}
