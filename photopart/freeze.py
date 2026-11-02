"""Freeze the requirement in spec.json and record why it later changed.

The hash covers dimensions and checklist items, not the agent's yes/no
answers. The first validate of a spec path writes ``<spec>.freeze.json``.
A later edit fails unless ``--reason`` is set, and that reason is copied
into the validation report.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

_SKIP = {"answers", "freeze_reason", "frozen_sha256"}


def freeze_path(spec_source) -> Path | None:
    if not isinstance(spec_source, (str, Path)):
        return None
    path = Path(spec_source).expanduser()
    if not path.is_file():
        return None
    return Path(str(path.resolve()) + ".freeze.json")


def requirement(raw: dict) -> dict:
    kept = {}
    for key in sorted(raw):
        if key in _SKIP:
            continue
        if key == "features":
            kept["features"] = [_feature(item) for item in raw.get("features") or []]
        else:
            kept[key] = raw[key]
    return kept


def fingerprint(raw: dict) -> str:
    blob = json.dumps(requirement(raw), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def checklist(raw: dict) -> list[dict]:
    answers = raw.get("answers") if isinstance(raw.get("answers"), dict) else {}
    rows = []
    for item in raw.get("features") or []:
        feature = _feature(item)
        name = feature["item"]
        answer = feature.get("answer")
        if answer is None and name in answers:
            answer = answers[name]
        rows.append(
            {
                "item": name,
                "expected": feature.get("expected") or "yes",
                "answer": answer,
                "answered": answer in {"yes", "no"},
            }
        )
    return rows


def apply_freeze(spec_source, raw: dict, reason: str | None) -> tuple[list[str], dict]:
    """Return failures and a report fragment. A dict spec is not frozen."""
    info = {
        "frozen_sha256": fingerprint(raw) if isinstance(raw, dict) else None,
        "checklist": checklist(raw) if isinstance(raw, dict) else [],
        "spec_edits": [],
    }
    path = freeze_path(spec_source)
    if path is None or not isinstance(raw, dict):
        return [], info
    current = fingerprint(raw)
    info["frozen_sha256"] = current
    prior = _read(path)
    if prior is None:
        _write(path, {"sha256": current, "edits": []})
        return [], info
    if prior.get("sha256") == current:
        info["spec_edits"] = list(prior.get("edits") or [])
        return [], info
    text = (reason or "").strip()
    if not text:
        return [
            "frozen spec changed. Pass --reason with why the checklist or a number changed. "
            "Do not drop a requirement to make the mesh pass."
        ], info
    edit = {
        "from": prior.get("sha256"),
        "to": current,
        "reason": text,
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    edits = [item for item in (prior.get("edits") or []) if isinstance(item, dict)]
    edits.append(edit)
    _write(path, {"sha256": current, "edits": edits[-20:]})
    info["spec_edits"] = edits[-20:]
    return [], info


def _feature(item) -> dict:
    if isinstance(item, str):
        return {"item": item, "expected": "yes"}
    if isinstance(item, dict):
        name = str(item.get("item") or item.get("name") or "")
        expected = str(item.get("expected") or "yes")
        row = {"item": name, "expected": expected}
        if item.get("answer") in {"yes", "no"}:
            row["answer"] = item["answer"]
        return row
    return {"item": str(item), "expected": "yes"}


def _read(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    if not isinstance(loaded, dict):
        return None
    return loaded


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
