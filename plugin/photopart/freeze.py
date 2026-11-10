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


FROZEN_AXIS_TOLERANCE_MM = 0.01


def _source_is_user(source) -> bool:
    """True when a dimension came from the user, or when no source was given."""
    if source is None or source == "":
        return True
    text = str(source).strip().lower()
    if not text:
        return True
    if text.startswith("user"):
        return True
    if text in {"stated", "given"}:
        return True
    return False


def user_axis_values(raw: dict) -> dict:
    """Plain x/y/z numbers. A ``source`` other than user is not locked.

    A top-level ``sources`` map (for example ``{"z": "assumed from the photo"}``)
    is honoured the same way as a nested ``{value, source}`` object. Bare
    numbers with no source stay locked, which matches older specs.
    """
    if not isinstance(raw, dict):
        return {}
    nested = raw.get("dims") if isinstance(raw.get("dims"), dict) else {}
    sources = raw.get("sources") if isinstance(raw.get("sources"), dict) else {}
    found = {}
    for name in ("x", "y", "z"):
        item = raw.get(name, nested.get(name) if isinstance(nested, dict) else None)
        source = sources.get(name)
        if isinstance(item, dict):
            if source is None:
                source = item.get("source")
            value = _number(item.get("value"))
        else:
            value = _number(item)
        if not _source_is_user(source):
            continue
        if value is None:
            continue
        found[name] = value
    return found


def locked_axes_from_spec(spec_source, raw: dict | None = None) -> dict:
    """User axes from a freeze file, else from the spec itself."""
    current = user_axis_values(raw) if isinstance(raw, dict) else {}
    path = freeze_path(spec_source)
    prior = _read(path) if path is not None else None
    stored = prior.get("user_axes") if isinstance(prior, dict) and isinstance(prior.get("user_axes"), dict) else {}
    locked = {}
    # Freeze may predate sources-aware locking. Drop axes the current spec
    # marks as assumed, and keep explicit user axes from the spec.
    for name, value in stored.items():
        if name not in {"x", "y", "z"}:
            continue
        number = _number(value)
        if number is None:
            continue
        if isinstance(raw, dict) and name not in current and name in (raw.get("sources") or {}):
            continue
        locked[name] = number
    locked.update(current)
    return locked


def frozen_axis_failures(mesh, locked: dict, *, tolerance: float = FROZEN_AXIS_TOLERANCE_MM) -> list[str]:
    """Fail when a frozen user axis drifted, even if the general bbox tolerance would allow it."""
    if not locked:
        return []
    extents = _mesh_extents(mesh)
    if extents is None:
        return []
    messages = []
    limit = max(0.0, float(tolerance))
    for name, expected in locked.items():
        if name not in extents:
            continue
        actual = extents[name]
        if abs(actual - expected) <= limit + 1e-9:
            continue
        messages.append(
            f"frozen user {name} {expected:g} mm must stay exact; the mesh is {actual:g} mm. "
            "Do not nudge a user-stated dimension during refine."
        )
    return messages


def snap_mesh_to_locked_axes(mesh, locked: dict, *, tolerance: float = FROZEN_AXIS_TOLERANCE_MM):
    """Scale a mesh so frozen user axes match exactly. Returns ``(mesh, changed)``."""
    if mesh is None or not locked:
        return mesh, False
    extents = _mesh_extents(mesh)
    if extents is None:
        return mesh, False
    scales = [1.0, 1.0, 1.0]
    index = {"x": 0, "y": 1, "z": 2}
    changed = False
    xy_same = (
        "x" in locked
        and "y" in locked
        and abs(locked["x"] - locked["y"]) <= max(tolerance, 1e-9)
    )
    if xy_same:
        current = max(float(extents["x"]), float(extents["y"]), 1e-12)
        factor = float(locked["x"]) / current
        if abs(factor - 1.0) > 1e-12 and (
            abs(extents["x"] - locked["x"]) > tolerance or abs(extents["y"] - locked["y"]) > tolerance
        ):
            scales[0] = factor
            scales[1] = factor
            changed = True
    for name, expected in locked.items():
        if name not in index:
            continue
        if xy_same and name in {"x", "y"}:
            continue
        current = float(extents[name])
        if current <= 1e-12:
            continue
        if abs(current - expected) <= tolerance + 1e-9:
            continue
        scales[index[name]] = float(expected) / current
        changed = True
    if not changed:
        return mesh, False
    mesh.apply_scale(scales)
    return mesh, True


def snap_path_to_spec(mesh_path, spec_source=None) -> dict:
    """Rewrite an STL so frozen user axes stay exact. No-op when nothing is locked."""
    info = {"ok": True, "changed": False, "path": None, "locked": {}}
    if not mesh_path:
        return info
    path = Path(mesh_path).expanduser()
    info["path"] = str(path)
    if not path.is_file() or path.suffix.lower() != ".stl":
        return info
    spec_path = Path(spec_source).expanduser() if spec_source else path.parent / "spec.json"
    if not spec_path.is_file():
        return info
    try:
        raw = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return info
    if not isinstance(raw, dict):
        return info
    locked = locked_axes_from_spec(spec_path, raw)
    info["locked"] = locked
    if not locked:
        return info
    try:
        import trimesh

        loaded = trimesh.load(str(path), force="mesh", process=False)
    except Exception:
        info["ok"] = False
        return info
    mesh = loaded if not isinstance(loaded, list) else (loaded[0] if loaded else None)
    if mesh is None:
        return info
    mesh, changed = snap_mesh_to_locked_axes(mesh, locked)
    if not changed:
        return info
    try:
        mesh.export(str(path))
    except Exception:
        info["ok"] = False
        return info
    info["changed"] = True
    return info


def _mesh_extents(mesh) -> dict | None:
    if mesh is None:
        return None
    extents = getattr(mesh, "extents", None)
    if extents is None:
        return None
    try:
        values = [float(item) for item in extents[:3]]
    except (TypeError, ValueError, IndexError):
        return None
    if len(values) < 3:
        return None
    return {"x": values[0], "y": values[1], "z": values[2]}


def measured_lengths(mesh_path) -> list[float]:
    """Millimetres from ``last_measure.json`` beside the mesh, if that file exists."""
    if not mesh_path:
        return []
    try:
        directory = Path(mesh_path).expanduser().resolve().parent
    except OSError:
        return []
    path = directory / "last_measure.json"
    if not path.is_file():
        return []
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return []
    if not isinstance(loaded, dict):
        return []
    values = []
    bbox = loaded.get("part_bbox_mm")
    if isinstance(bbox, (list, tuple)):
        for item in bbox:
            number = _number(item)
            if number is not None and number > 0:
                values.append(number)
    measurements = loaded.get("measurements")
    if isinstance(measurements, list):
        for item in measurements:
            if not isinstance(item, dict):
                continue
            for key in ("mm", "length_mm", "value"):
                number = _number(item.get(key))
                if number is not None and number > 0:
                    values.append(number)
                    break
    return values


def axis_overrides(stored: dict, current: dict, measured: list) -> list[dict]:
    """User axis values rewritten to a nearby photo measurement."""
    rows = []
    if not isinstance(stored, dict) or not isinstance(current, dict):
        return rows
    for name, old in stored.items():
        if name not in current:
            continue
        old_value = _number(old)
        new_value = _number(current.get(name))
        if old_value is None or new_value is None or abs(old_value - new_value) <= 1e-6:
            continue
        for length in measured or []:
            measured_value = _number(length)
            if measured_value is None or measured_value <= 0:
                continue
            band = max(1.0, 0.02 * abs(measured_value))
            if abs(new_value - measured_value) <= band and abs(old_value - measured_value) > band:
                rows.append(
                    {
                        "name": str(name),
                        "user": old_value,
                        "edited": new_value,
                        "measured": measured_value,
                    }
                )
                break
    return rows


def apply_freeze(spec_source, raw: dict, reason: str | None, measured: list | None = None) -> tuple[list[str], dict]:
    """Return failures and a report fragment. A dict spec is not frozen.

    A frozen user x/y/z that is rewritten to a photo measurement stays at
    the user's number. The freeze hash is not advanced. A reason still
    allows a checklist edit or a number that does not track a measurement.
    """
    info = {
        "frozen_sha256": fingerprint(raw) if isinstance(raw, dict) else None,
        "checklist": checklist(raw) if isinstance(raw, dict) else [],
        "spec_edits": [],
        "user_dimension_conflicts": [],
        "user_dimension_changes": [],
        "locked_axes": {},
    }
    path = freeze_path(spec_source)
    if path is None or not isinstance(raw, dict):
        return [], info
    current = fingerprint(raw)
    info["frozen_sha256"] = current
    prior = _read(path)
    current_axes = user_axis_values(raw)
    if prior is None:
        _write(path, {"sha256": current, "edits": [], "user_axes": current_axes})
        return [], info
    stored = prior.get("user_axes") if isinstance(prior.get("user_axes"), dict) else {}
    overrides = axis_overrides(stored, current_axes, measured or [])
    if overrides:
        info["user_dimension_conflicts"] = overrides
        info["locked_axes"] = {row["name"]: row["user"] for row in overrides}
        info["spec_edits"] = list(prior.get("edits") or [])
        info["frozen_sha256"] = prior.get("sha256")
        messages = [
            (
                f"user {row['name']} {row['user']:g} mm was replaced with measured {row['edited']:g} mm "
                f"(photo measurement {row['measured']:g} mm). Keep {row['user']:g}. "
                "Do not edit spec.json to the measured value."
            )
            for row in overrides
        ]
        return messages, info
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
    kept_axes = dict(stored)
    kept_axes.update(current_axes)
    changes = []
    for name, old in stored.items():
        old_value = _number(old)
        new_value = _number(current_axes.get(name))
        if old_value is None or new_value is None or abs(old_value - new_value) <= 1e-6:
            continue
        changes.append({"name": str(name), "from": old_value, "to": new_value})
    _write(path, {"sha256": current, "edits": edits[-20:], "user_axes": kept_axes})
    info["spec_edits"] = edits[-20:]
    info["user_dimension_changes"] = changes
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


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


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
