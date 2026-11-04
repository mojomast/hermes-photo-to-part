"""Freeze the requirement in spec.json and record why it later changed.

The hash covers dimensions and checklist items, not the agent's yes/no
answers. The first validate of a spec path writes ``<spec>.freeze.json``.
A later edit fails unless ``--reason`` is set, and that reason is copied
into the validation report.
"""

from __future__ import annotations

import hashlib
import json
import re
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
            # Names and expected values only. Yes/no answers are not part of the freeze.
            kept["features"] = [
                {"expected": _feature(item).get("expected") or "yes", "item": _feature(item)["item"]}
                for item in _items(raw)
            ]
        else:
            kept[key] = raw[key]
    return kept


def fingerprint(raw: dict) -> str:
    blob = json.dumps(requirement(raw), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def checklist(raw: dict) -> list[dict]:
    answers = raw.get("answers") if isinstance(raw.get("answers"), dict) else {}
    rows = []
    for item in _items(raw):
        feature = _feature(item)
        name = feature["item"]
        answer = feature.get("answer")
        if answer is None and name in answers:
            answer = _token(answers[name])
        rows.append(
            {
                "item": name,
                "expected": feature.get("expected") or "yes",
                "answer": answer,
                "answered": answer in {"yes", "no"},
            }
        )
    return rows


_COUNT_ITEM = re.compile(r"(\d+)\s+(knuckles|holes|teeth|shells)\b", re.IGNORECASE)
_COUNT_ALIAS = {"knuckles": "knuckles", "holes": "hole_count", "teeth": "teeth", "shells": "shells"}


def parse_answer(text: str) -> tuple[str, str]:
    """``item=yes`` or ``item=no``. The item text may contain spaces."""
    if "=" not in str(text):
        raise ValueError(f"answer must look like item=yes, got {text!r}")
    item, value = str(text).rsplit("=", 1)
    token = _token(value.strip())
    if not item.strip() or token is None:
        raise ValueError(f"answer must be item=yes or item=no, got {text!r}")
    return item.strip(), token


def apply_answers(rows: list[dict], spec_rows, prior: dict | None, overrides: list | None) -> list[dict]:
    """Fill checklist rows. ``--answer`` wins. Count items are filled from checks.

    ``prior`` is the previous sidecar's answers, so a yes/no survives the next
    validate without editing spec.json.
    """
    forced = []
    for item in overrides or []:
        if isinstance(item, tuple) and len(item) == 2:
            forced.append((str(item[0]), _token(item[1])))
        else:
            forced.append(parse_answer(str(item)))
    forced = [(name, token) for name, token in forced if token in {"yes", "no"}]
    forced_names = {name for name, _token_value in forced}
    by_name = {}
    for row in spec_rows or []:
        if isinstance(row, dict) and row.get("name"):
            by_name[row["name"]] = row
    remembered = prior if isinstance(prior, dict) else {}
    for row in rows:
        if row.get("answered") or row["item"] in forced_names:
            continue
        match = _COUNT_ITEM.search(str(row.get("item") or ""))
        if not match:
            continue
        check = by_name.get(_COUNT_ALIAS[match.group(2).lower()])
        if not isinstance(check, dict) or check.get("actual") is None:
            continue
        expected = int(match.group(1))
        actual = int(round(float(check["actual"])))
        row["answer"] = "yes" if actual == expected else "no"
        row["answered"] = True
        row["auto"] = True
    for row in rows:
        if row.get("answered"):
            continue
        token = _token(remembered.get(row["item"]))
        if token is None:
            continue
        row["answer"] = token
        row["answered"] = True
    for name, token in forced:
        for row in rows:
            if row.get("item") != name:
                continue
            row["answer"] = token
            row["answered"] = True
            row.pop("auto", None)
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


def _items(raw: dict) -> list:
    features = raw.get("features") if isinstance(raw, dict) else None
    if isinstance(features, dict):
        return [{"item": str(key), "answer": value} for key, value in features.items()]
    if isinstance(features, list):
        return features
    return []


def _token(value):
    """yes/no, or None when the value is not an answer."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"yes", "true"}:
        return "yes"
    if text in {"no", "false"}:
        return "no"
    return None


def _feature(item) -> dict:
    if isinstance(item, str):
        return {"item": item, "expected": "yes"}
    if isinstance(item, dict):
        known = {"item", "name", "expected", "answer"}
        extras = [key for key in item if key not in known]
        if not item.get("item") and not item.get("name") and len(extras) == 1:
            key = extras[0]
            row = {"item": str(key), "expected": "yes"}
            token = _token(item.get(key))
            if token:
                row["answer"] = token
            return row
        name = str(item.get("item") or item.get("name") or "")
        expected = str(item.get("expected") or "yes")
        row = {"item": name, "expected": expected}
        token = _token(item.get("answer")) if "answer" in item else None
        if token:
            row["answer"] = token
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
