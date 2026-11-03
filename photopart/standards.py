"""Fastener and bearing sizes used only as warnings.

``check_standard`` never edits the spec. A row is included only when the
number is the nominal value published in the cited standard or catalogue.
ISO 273 clearance holes are omitted: the draft figures were not checked
against the standard text. Catalogue M3 flange diameters are omitted for
the same reason. ISO 4162 has no M3 row.

Sources
-------
* ISO 261 / ISO 262 coarse pitch and nominal major diameter.
  https://en.wikipedia.org/wiki/ISO_metric_screw_thread
* ISO 4017 hexagon head: nominal across-flats ``s`` and maximum head height
  ``k``. The M3–M12 rows match the ISO coarse table already used by
  ``photopart.features``.
  https://www.fasteners.eu/standards/ISO/4017/
* ISO 4762 socket head: maximum head diameter ``dk`` and height ``k``.
  https://www.fasteners.eu/standards/ISO/4762/
* ISO 4032 style-1 nut: nominal across-flats ``s`` and maximum thickness ``m``.
* ISO 4162:2012 flange bolts, maximum flange diameter ``dc``, M5–M8 only
  (the sizes cited from the standard sample). Across-flats is omitted
  because editions disagree (M5 is 7 mm or 8 mm).
  https://cdn.standards.iteh.ai/samples/56451/10d71b8d8c634e9790d4ddcf4c296cc2/ISO-4162-2012.pdf
* ASME B1.1 UNC basic major diameter and pitch.
  https://en.wikipedia.org/wiki/Unified_Thread_Standard
* 608 deep-groove ball bearing, 8 × 22 × 7 mm (ISO 15 dimensions; SKF 608).
"""

from __future__ import annotations

import re
from typing import Any

# major_mm, pitch_mm, and optional heads. Lengths are millimetres.
_METRIC: dict[str, dict[str, Any]] = {
    "M2": {
        "major_mm": 2.0,
        "pitch_mm": 0.4,
        "socket": {"dk_mm": 3.8, "k_mm": 2.0, "source": "ISO 4762"},
    },
    "M2.5": {
        "major_mm": 2.5,
        "pitch_mm": 0.45,
        "socket": {"dk_mm": 4.5, "k_mm": 2.5, "source": "ISO 4762"},
    },
    "M3": {
        "major_mm": 3.0,
        "pitch_mm": 0.5,
        "hex": {"s_mm": 5.5, "k_mm": 2.0, "source": "ISO 4017"},
        "socket": {"dk_mm": 5.5, "k_mm": 3.0, "source": "ISO 4762"},
        "nut": {"s_mm": 5.5, "m_mm": 2.4, "source": "ISO 4032"},
    },
    "M4": {
        "major_mm": 4.0,
        "pitch_mm": 0.7,
        "hex": {"s_mm": 7.0, "k_mm": 2.8, "source": "ISO 4017"},
        "socket": {"dk_mm": 7.0, "k_mm": 4.0, "source": "ISO 4762"},
        "nut": {"s_mm": 7.0, "m_mm": 3.2, "source": "ISO 4032"},
    },
    "M5": {
        "major_mm": 5.0,
        "pitch_mm": 0.8,
        "hex": {"s_mm": 8.0, "k_mm": 3.5, "source": "ISO 4017"},
        "socket": {"dk_mm": 8.5, "k_mm": 5.0, "source": "ISO 4762"},
        "nut": {"s_mm": 8.0, "m_mm": 4.7, "source": "ISO 4032"},
        "flange": {"dc_max_mm": 11.4, "source": "ISO 4162"},
    },
    "M6": {
        "major_mm": 6.0,
        "pitch_mm": 1.0,
        "hex": {"s_mm": 10.0, "k_mm": 4.0, "source": "ISO 4017"},
        "socket": {"dk_mm": 10.0, "k_mm": 6.0, "source": "ISO 4762"},
        "nut": {"s_mm": 10.0, "m_mm": 5.2, "source": "ISO 4032"},
        "flange": {"dc_max_mm": 13.6, "source": "ISO 4162"},
    },
    "M8": {
        "major_mm": 8.0,
        "pitch_mm": 1.25,
        "hex": {"s_mm": 13.0, "k_mm": 5.3, "source": "ISO 4017"},
        "socket": {"dk_mm": 13.0, "k_mm": 8.0, "source": "ISO 4762"},
        "nut": {"s_mm": 13.0, "m_mm": 6.8, "source": "ISO 4032"},
        "flange": {"dc_max_mm": 17.0, "source": "ISO 4162"},
    },
    "M10": {
        "major_mm": 10.0,
        "pitch_mm": 1.5,
        "hex": {"s_mm": 16.0, "k_mm": 6.4, "source": "ISO 4017"},
        "socket": {"dk_mm": 16.0, "k_mm": 10.0, "source": "ISO 4762"},
        "nut": {"s_mm": 16.0, "m_mm": 8.4, "source": "ISO 4032"},
    },
    "M12": {
        "major_mm": 12.0,
        "pitch_mm": 1.75,
        "hex": {"s_mm": 18.0, "k_mm": 7.5, "source": "ISO 4017"},
        "socket": {"dk_mm": 18.0, "k_mm": 12.0, "source": "ISO 4762"},
        "nut": {"s_mm": 18.0, "m_mm": 10.8, "source": "ISO 4032"},
    },
}

# UNC basic major diameter and pitch. No head dimensions: those were not
# checked edition by edition.
_INCH: dict[str, dict[str, float]] = {
    "#4-40": {"major_mm": 2.8448, "pitch_mm": 0.635},
    "#6-32": {"major_mm": 3.5052, "pitch_mm": 0.7938},
    "#8-32": {"major_mm": 4.1656, "pitch_mm": 0.7938},
    "#10-24": {"major_mm": 4.826, "pitch_mm": 1.0583},
    "1/4-20": {"major_mm": 6.35, "pitch_mm": 1.27},
    "5/16-18": {"major_mm": 7.9375, "pitch_mm": 1.4111},
    "3/8-16": {"major_mm": 9.525, "pitch_mm": 1.5875},
    "1/2-13": {"major_mm": 12.7, "pitch_mm": 1.9538},
}

_BEARING_608 = {
    "bore_mm": 8.0,
    "od_mm": 22.0,
    "width_mm": 7.0,
    "source": "ISO 15 / SKF 608",
}

_METRIC_RE = re.compile(r"\bM\s*(\d+(?:\.\d+)?)\b", re.IGNORECASE)
_NUMBER_RE = re.compile(r"#\s*(\d+)\s*[-–]\s*(\d+)\b")
_FRACTION_RE = re.compile(r"\b(1/4|5/16|3/8|1/2)\s*[-–]\s*(\d+)\b")
_BEARING_RE = re.compile(r"\b608\b")


def check_standard(spec, report=None) -> dict:
    """Warn when a named standard disagrees with measured sizes.

    ``spec`` is not modified. Suggestions name the standard value and its
    source. Nothing is written back onto the spec.
    """
    text = _spec_text(spec)
    report = report if isinstance(report, dict) else {}
    warnings: list[dict] = []
    suggestions: list[str] = []
    checked: list[str] = []
    flange_named = "flange" in text.lower()
    for designation in _designations(text):
        if designation in checked:
            continue
        checked.append(designation)
        if designation in _METRIC:
            _check_metric(designation, _METRIC[designation], report, flange_named, warnings, suggestions)
        elif designation in _INCH:
            _check_inch(designation, _INCH[designation], report, warnings, suggestions)
        elif designation == "608":
            _check_bearing(report, warnings, suggestions)
    return {
        "warnings": warnings,
        "suggestions": suggestions,
        "checked": checked,
        "edited_spec": False,
    }


def _check_metric(name: str, row: dict, report: dict, flange_named: bool, warnings: list, suggestions: list) -> None:
    pitch = _number(report.get("pitch_mm"))
    if pitch is not None:
        _compare(
            warnings,
            suggestions,
            name=name,
            label="coarse pitch",
            standard=float(row["pitch_mm"]),
            measured=pitch,
            source="ISO 261",
        )
    span = _cross_section(report)
    if span is None:
        _suggest_row(suggestions, name, row)
        return
    options = [("major diameter", float(row["major_mm"]), "ISO 261")]
    hex_head = row.get("hex") or {}
    if hex_head:
        options.append(("hex across flats", float(hex_head["s_mm"]), str(hex_head["source"])))
    socket = row.get("socket") or {}
    if socket:
        options.append(("socket head diameter", float(socket["dk_mm"]), str(socket["source"])))
    flange = row.get("flange") or {}
    if flange and (flange_named or name != "M3"):
        options.append(("flange diameter", float(flange["dc_max_mm"]), str(flange["source"])))
    closest = min(options, key=lambda item: abs(span - item[1]))
    label, standard, source = closest
    if abs(span - standard) > _tolerance(standard):
        extra = ""
        if flange_named and name == "M3":
            extra = " ISO 4162 flange bolts start at M5; no M3 flange diameter is applied."
        warnings.append(
            {
                "designation": name,
                "message": (
                    f"{name}: measured {span:.1f} mm is {abs(span - standard):.1f} mm from "
                    f"{label} {standard:.1f} mm ({source}).{extra}"
                ),
                "suggest": f"{label} {standard:.4g} mm ({source}); coarse pitch {row['pitch_mm']:.4g} mm (ISO 261)",
                "source": source,
                "standard_mm": standard,
                "measured_mm": span,
            }
        )
        suggestions.append(warnings[-1]["suggest"] + " The spec was not changed.")
    else:
        _suggest_row(suggestions, name, row)


def _check_inch(name: str, row: dict, report: dict, warnings: list, suggestions: list) -> None:
    pitch = _number(report.get("pitch_mm"))
    if pitch is not None:
        _compare(
            warnings,
            suggestions,
            name=name,
            label="pitch",
            standard=float(row["pitch_mm"]),
            measured=pitch,
            source="ASME B1.1",
        )
    span = _cross_section(report)
    if span is None:
        return
    _compare(
        warnings,
        suggestions,
        name=name,
        label="basic major diameter",
        standard=float(row["major_mm"]),
        measured=span,
        source="ASME B1.1",
    )


def _check_bearing(report: dict, warnings: list, suggestions: list) -> None:
    extents = _extents(report)
    if len(extents) < 3:
        return
    expected = (
        ("bore", _BEARING_608["bore_mm"]),
        ("outside diameter", _BEARING_608["od_mm"]),
        ("width", _BEARING_608["width_mm"]),
    )
    missing = []
    for label, standard in expected:
        if not any(abs(value - standard) <= _tolerance(standard) for value in extents):
            missing.append(f"{label} {standard:.4g} mm")
    if missing:
        message = (
            "608 bearing is 8 × 22 × 7 mm (ISO 15 / SKF 608); measured extents "
            + " × ".join(f"{value:.1f}" for value in extents)
            + " mm, missing "
            + ", ".join(missing)
            + "."
        )
        warnings.append(
            {
                "designation": "608",
                "message": message,
                "suggest": "bore 8 mm, outside diameter 22 mm, width 7 mm (ISO 15 / SKF 608)",
                "source": _BEARING_608["source"],
                "standard_mm": 22.0,
                "measured_mm": max(extents),
            }
        )
        suggestions.append(warnings[-1]["suggest"] + " The spec was not changed.")


def _compare(warnings, suggestions, *, name, label, standard, measured, source) -> None:
    if abs(measured - standard) <= _tolerance(standard):
        return
    warnings.append(
        {
            "designation": name,
            "message": (
                f"{name}: measured {label} {measured:.4g} mm is outside "
                f"{standard:.4g} mm ({source})."
            ),
            "suggest": f"{label} {standard:.4g} mm ({source})",
            "source": source,
            "standard_mm": standard,
            "measured_mm": measured,
        }
    )
    suggestions.append(warnings[-1]["suggest"] + " The spec was not changed.")


def _suggest_row(suggestions: list, name: str, row: dict) -> None:
    hex_head = row.get("hex") or {}
    if hex_head:
        suggestions.append(
            f"{name}: hex across flats {hex_head['s_mm']:.4g} mm ({hex_head['source']}); "
            f"coarse pitch {row['pitch_mm']:.4g} mm (ISO 261). The spec was not changed."
        )


def _tolerance(standard: float) -> float:
    return max(0.3, 0.08 * abs(float(standard)))


def _cross_section(report: dict) -> float | None:
    explicit = _number(report.get("across_mm") or report.get("width_mm") or report.get("flange_mm"))
    if explicit is not None:
        return explicit
    part = report.get("part_bbox_mm")
    if isinstance(part, (list, tuple)) and len(part) >= 2:
        try:
            return float(min(float(part[0]), float(part[1])))
        except (TypeError, ValueError):
            return None
    extents = _extents(report)
    if len(extents) < 2:
        return None
    ordered = sorted(extents)
    # The two closest extents are the head or the shank. The long axis is length.
    pairs = ((ordered[0], ordered[1]), (ordered[1], ordered[2]) if len(ordered) > 2 else (ordered[0], ordered[1]))
    best = min(pairs, key=lambda item: abs(item[0] - item[1]))
    return float(sum(best) / 2.0)


def _extents(report: dict) -> list[float]:
    raw = report.get("extents_mm")
    if isinstance(raw, dict):
        values = [raw.get("x"), raw.get("y"), raw.get("z")]
    elif isinstance(raw, (list, tuple)):
        values = list(raw)
    else:
        values = []
    found = []
    for value in values:
        number = _number(value)
        if number is not None and number > 0:
            found.append(number)
    return found


def _number(value) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _spec_text(spec) -> str:
    if spec is None:
        return ""
    if isinstance(spec, str):
        return spec
    if isinstance(spec, dict):
        parts: list[str] = []
        for key in ("part", "name", "designation", "notes", "note", "title", "description"):
            value = spec.get(key)
            if isinstance(value, str):
                parts.append(value)
        features = spec.get("features")
        if isinstance(features, str):
            parts.append(features)
        elif isinstance(features, list):
            parts.extend(str(item) for item in features)
        return " ".join(parts)
    return str(spec)


def _designations(text: str) -> list[str]:
    found: list[str] = []
    for match in _METRIC_RE.finditer(text):
        key = "M" + match.group(1)
        if key in _METRIC and key not in found:
            found.append(key)
    for match in _NUMBER_RE.finditer(text):
        key = f"#{match.group(1)}-{match.group(2)}"
        if key in _INCH and key not in found:
            found.append(key)
    for match in _FRACTION_RE.finditer(text):
        key = f"{match.group(1)}-{match.group(2)}"
        if key in _INCH and key not in found:
            found.append(key)
    if _BEARING_RE.search(text):
        found.append("608")
    return found
