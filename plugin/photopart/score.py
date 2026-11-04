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
    """Score out of 100: watertight 30, spec 40, checklist 20, printability 10.

    Printability loses 5 points per warning and does not go below 0. A mesh
    that is not ok loses another 20. Checklist points are the fraction of
    items answered yes. With no checklist, that 20 is kept so a clean part
    reaches 100.
    """
    watertight = 30.0 if report.get("watertight") else 0.0
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
    checklist = [row for row in (report.get("checklist") or []) if isinstance(row, dict)]
    if checklist:
        yes = sum(1 for row in checklist if _yes(row.get("answer")))
        answered = sum(1 for row in checklist if row.get("answered"))
        check_score = 20.0 * yes / len(checklist)
    else:
        yes = 0
        answered = 0
        check_score = 20.0
    print_warnings = list((report.get("printability") or {}).get("warnings") or [])
    print_score = max(0.0, 10.0 - 5.0 * len(print_warnings))
    score = watertight + spec_score + check_score + print_score
    if not report.get("ok"):
        score -= 20.0
    return {
        "score": round(score, 3),
        "residual_mm": round(residual, 4),
        "spec_rows": len(rows),
        "print_warnings": len(print_warnings),
        "watertight": bool(report.get("watertight")),
        "checklist_items": len(checklist),
        "checklist_answered": answered,
        "checklist_yes": yes,
    }


def _yes(answer) -> bool:
    if answer is True:
        return True
    return str(answer).strip().lower() in {"yes", "true"}


def version_report(path: Path, current: dict) -> dict:
    """Best passing version, including this file's in-memory score.

    The sidecar for ``path`` has not been written yet, so the current report
    is added before siblings are read. ``revert_to`` is set only when a
    different version scores higher.
    """
    rows = _version_rows(path, current)
    passing = [row for row in rows if row.get("ok") and isinstance(row.get("score"), (int, float))]
    best = None
    for row in passing:
        if best is None or float(row["score"]) > float(best["score"]) + 1e-9 or (
            abs(float(row["score"]) - float(best["score"])) <= 1e-9 and int(row.get("n") or 0) >= int(best.get("n") or 0)
        ):
            best = row
    current_score = float(current.get("score") or 0.0)
    public = [{"name": row["name"], "ok": bool(row.get("ok")), "score": row.get("score")} for row in rows]
    if best is None:
        return {
            "best_version": None,
            "best_version_reason": "no passing version",
            "revert_to": None,
            "versions": public,
        }
    revert = best["name"] if float(best["score"]) > current_score + 1e-9 else None
    return {
        "best_version": best["name"],
        "best_version_reason": None,
        "revert_to": revert,
        "versions": public,
    }


def _version_rows(path: Path, current: dict) -> list[dict]:
    match = _VERSION.match(path.stem)
    candidates = [path]
    if match:
        prefix = match.group("prefix")
        pattern = re.compile(rf"^{re.escape(prefix)}_v(\d+){re.escape(path.suffix)}$")
        try:
            names = list(path.parent.iterdir())
        except OSError:
            names = []
        for candidate in names:
            if pattern.match(candidate.name) and candidate.is_file():
                candidates.append(candidate)
    seen: set[str] = set()
    rows = []
    for candidate in candidates:
        try:
            key = str(candidate.resolve())
        except OSError:
            key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        number = _number(candidate)
        if candidate.resolve() == path.resolve():
            rows.append(
                {
                    "name": path.name,
                    "ok": bool(current.get("ok")),
                    "score": None if current.get("score") is None else float(current["score"]),
                    "n": number,
                }
            )
            continue
        rows.append(_sidecar_row(candidate, number))
    rows.sort(key=lambda row: int(row.get("n") or 0))
    return rows


def _number(path: Path) -> int:
    match = _VERSION.match(path.stem)
    return int(match.group("n")) if match else 0


def _sidecar_row(path: Path, number: int) -> dict:
    side = sidecar_path(path)
    if not side.is_file():
        return {"name": path.name, "ok": False, "score": None, "n": number}
    try:
        payload = json.loads(side.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {"name": path.name, "ok": False, "score": None, "n": number}
    if not isinstance(payload, dict):
        return {"name": path.name, "ok": False, "score": None, "n": number}
    fresh = payload.get("sha256") == mesh_hash(path)
    score = payload.get("score")
    numeric = float(score) if isinstance(score, (int, float)) else None
    return {
        "name": path.name,
        "ok": bool(payload.get("ok") is True and fresh and numeric is not None),
        "score": numeric,
        "n": number,
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
