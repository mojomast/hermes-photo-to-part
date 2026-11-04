"""Fastener and bearing sizes used only as warnings.

``check_standard`` never edits the spec. A row is included only when the
number is the nominal value published in the cited standard or catalogue.
Catalogue M3 flange diameters are omitted: they were not checked against
a standard. ISO 4162 has no M3 row. Clearance holes use only the ISO 273
rows cited above.

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
* ISO 273:1979 clearance holes, fine / medium / coarse, for the rows that
  are readable in the official preview (M2.5, M3, M4, M5, M6, M8). Other
  sizes are omitted rather than copied from a secondary chart.
  https://cdn.standards.iteh.ai/samples/4183/1a8db2e6de054d2e9bed7d40be64d6e1/ISO-273-1979.pdf
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

# ISO 273:1979 fine / medium / coarse, millimetres. Only rows read from the
# preview PDF are listed. See the module docstring for the citation.
_CLEARANCE: dict[str, tuple[float, float, float]] = {
    "M2.5": (2.7, 2.9, 3.1),
    "M3": (3.2, 3.4, 3.6),
    "M4": (4.3, 4.5, 4.8),
    "M5": (5.3, 5.5, 5.8),
    "M6": (6.4, 6.6, 7.0),
    "M8": (8.4, 9.0, 10.0),
}

_FASTENER_NOUN = re.compile(r"\b(screws?|bolts?|nuts?|washers?|standoffs?)\b", re.IGNORECASE)
_DECORATIVE = re.compile(r"\b(handles?|pulls?|knobs?|rosettes?)\b", re.IGNORECASE)
_CLEARANCE_BEFORE = re.compile(
    r"(?:mounts?\s+with|mounting|takes|accepts|fits|used\s+with|for)\s+(?:an?\s+|a\s+)?$",
    re.IGNORECASE,
)
_ROLE_WORDS = {
    "screw": "fastener",
    "bolt": "fastener",
    "nut": "fastener",
    "washer": "fastener",
    "standoff": "fastener",
    "thread": "thread",
    "clearance_hole": "clearance",
    "clearance": "clearance",
    "tapped_hole": "clearance",
    "hole": "clearance",
}

_METRIC_RE = re.compile(r"\bM\s*(\d+(?:\.\d+)?)\b", re.IGNORECASE)
_NUMBER_RE = re.compile(r"#\s*(\d+)\s*[-–]\s*(\d+)\b")
_FRACTION_RE = re.compile(r"\b(1/4|5/16|3/8|1/2)\s*[-–]\s*(\d+)\b")
_BEARING_RE = re.compile(r"\b608\b")


def check_standard(spec, report=None) -> dict:
    """Warn when a named standard disagrees with a measured feature.

    A designation is checked only when it is tied to a fastener role: a
    ``fasteners`` entry, a tagged thread, or a name that is itself a screw,
    bolt, nut, washer, or standoff. "Mounts with an M5 screw" is a clearance
    hole and is compared with ISO 273, never with the part envelope. A size
    outside 0.5× nominal to 2× the largest cited dimension is skipped, not
    warned. ``spec`` is not modified.
    """
    text = _spec_text(spec)
    report = report if isinstance(report, dict) else {}
    warnings: list[dict] = []
    suggestions: list[str] = []
    checked: list[dict] = []
    seen: set[str] = set()
    flange_named = "flange" in text.lower() or _number(report.get("flange_mm")) is not None
    for designation, role in _bindings(spec, text, report):
        if designation in seen:
            continue
        seen.add(designation)
        if designation in _METRIC:
            _check_metric(
                designation,
                _METRIC[designation],
                report,
                flange_named,
                role,
                warnings,
                suggestions,
                checked,
            )
        elif designation in _INCH and role == "fastener":
            _check_inch(designation, _INCH[designation], report, warnings, suggestions, checked)
        elif designation == "608":
            before = len(warnings)
            _check_bearing(report, warnings, suggestions)
            checked.append(
                {
                    "designation": "608",
                    "role": "bearing",
                    "status": "warn" if len(warnings) > before else "ok",
                }
            )
    return {
        "warnings": warnings,
        "suggestions": suggestions,
        "checked": checked,
        "edited_spec": False,
    }


def _check_metric(
    name: str,
    row: dict,
    report: dict,
    flange_named: bool,
    role: str,
    warnings: list,
    suggestions: list,
    checked: list,
) -> None:
    if role == "clearance":
        _check_clearance(name, row, report, warnings, suggestions, checked)
        return
    if role in {"fastener", "thread"}:
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
    if role != "fastener":
        checked.append({"designation": name, "role": role, "status": "ok" if not warnings else "warn"})
        return
    span = _cross_section(report)
    if span is None:
        _suggest_row(suggestions, name, row)
        checked.append({"designation": name, "role": role, "status": "ok"})
        return
    largest, largest_label = _largest_dim(name, row)
    nominal = float(row["major_mm"])
    if span < 0.5 * nominal - 1e-9 or span > 2.0 * largest + 1e-9:
        message = f"size {span:.1f} mm is not plausible for {name} ({largest_label} max {largest:.1f})"
        checked.append({"designation": name, "role": role, "status": "skipped", "message": message})
        return
    if flange_named and row.get("flange"):
        _check_flange(name, row, span, warnings, suggestions, checked)
        return
    options = [("major diameter", float(row["major_mm"]), "ISO 261")]
    hex_head = row.get("hex") or {}
    if hex_head:
        options.append(("hex across flats", float(hex_head["s_mm"]), str(hex_head["source"])))
    socket = row.get("socket") or {}
    if socket:
        options.append(("socket head diameter", float(socket["dk_mm"]), str(socket["source"])))
    label, standard, source = min(options, key=lambda item: abs(span - item[1]))
    if not _within_band(label, standard, span):
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
        checked.append({"designation": name, "role": role, "status": "warn", "message": warnings[-1]["message"]})
    else:
        _suggest_row(suggestions, name, row)
        checked.append({"designation": name, "role": role, "status": "ok"})


def _check_flange(name: str, row: dict, span: float, warnings: list, suggestions: list, checked: list) -> None:
    """A named flange is compared with dc max, not with the nearest hex size."""
    flange = row["flange"]
    dc = float(flange["dc_max_mm"])
    source = str(flange["source"])
    lower = dc - max(0.3, 0.08 * dc)
    upper = dc + 0.3
    if lower - 1e-9 <= span <= upper + 1e-9:
        _suggest_row(suggestions, name, row)
        checked.append({"designation": name, "role": "fastener", "status": "ok", "feature": "flange"})
        return
    message = (
        f"{name}: measured flange {span:.1f} mm is outside {lower:.1f}–{upper:.1f} mm "
        f"(dc max {dc:.1f} mm, {source})."
    )
    warnings.append(
        {
            "designation": name,
            "message": message,
            "suggest": f"flange diameter {dc:.4g} mm ({source})",
            "source": source,
            "standard_mm": dc,
            "measured_mm": span,
        }
    )
    suggestions.append(warnings[-1]["suggest"] + " The spec was not changed.")
    checked.append({"designation": name, "role": "fastener", "status": "warn", "message": message})


def _check_clearance(name: str, row: dict, report: dict, warnings: list, suggestions: list, checked: list) -> None:
    """Compare bore diameters with ISO 273. The part envelope is not a fastener."""
    classes = _CLEARANCE.get(name)
    largest, largest_label = _largest_dim(name, row)
    nominal = float(row["major_mm"])
    bores = _bore_diameters(report)
    plausible = [item for item in bores if 0.5 * nominal - 1e-9 <= item <= 2.0 * largest + 1e-9]
    if classes is None:
        checked.append(
            {
                "designation": name,
                "role": "clearance",
                "status": "skipped",
                "message": f"no ISO 273 row verified for {name}",
            }
        )
        return
    if not plausible:
        span = _cross_section(report)
        shown = span if span is not None else nominal
        message = (
            f"size {shown:.1f} mm is not plausible for {name} ({largest_label} max {largest:.1f})"
            if span is not None and (span < 0.5 * nominal or span > 2.0 * largest)
            else f"no bore diameter to compare with ISO 273 for {name}"
        )
        checked.append({"designation": name, "role": "clearance", "status": "skipped", "message": message})
        return
    fine, medium, coarse = classes
    matched = [
        item
        for item in plausible
        if any(abs(item - standard) <= 0.15 for standard in classes)
    ]
    if matched:
        suggestions.append(
            f"{name}: clearance hole {medium:.4g} mm medium (ISO 273 fine {fine:.4g} / coarse {coarse:.4g}). "
            "The spec was not changed."
        )
        checked.append(
            {
                "designation": name,
                "role": "clearance",
                "status": "ok",
                "standard_mm": medium,
                "measured_mm": matched[0],
                "source": "ISO 273",
            }
        )
        return
    measured = plausible[0]
    message = (
        f"{name}: bore {measured:.2f} mm is outside ISO 273 "
        f"fine {fine:.1f} / medium {medium:.1f} / coarse {coarse:.1f} mm."
    )
    warnings.append(
        {
            "designation": name,
            "message": message,
            "suggest": f"clearance hole {medium:.4g} mm medium (ISO 273)",
            "source": "ISO 273",
            "standard_mm": medium,
            "measured_mm": measured,
        }
    )
    suggestions.append(warnings[-1]["suggest"] + " The spec was not changed.")
    checked.append({"designation": name, "role": "clearance", "status": "warn", "message": message})


def _check_inch(name: str, row: dict, report: dict, warnings: list, suggestions: list, checked: list) -> None:
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
        checked.append({"designation": name, "role": "fastener", "status": "ok"})
        return
    nominal = float(row["major_mm"])
    if span < 0.5 * nominal or span > 2.0 * nominal:
        checked.append(
            {
                "designation": name,
                "role": "fastener",
                "status": "skipped",
                "message": f"size {span:.1f} mm is not plausible for {name} (major max {nominal:.1f})",
            }
        )
        return
    before = len(warnings)
    _compare(
        warnings,
        suggestions,
        name=name,
        label="basic major diameter",
        standard=nominal,
        measured=span,
        source="ASME B1.1",
    )
    checked.append(
        {"designation": name, "role": "fastener", "status": "warn" if len(warnings) > before else "ok"}
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


def _within_band(label: str, standard: float, measured: float) -> bool:
    """Major diameter uses an ISO 965 6g-style band. Other dims use the fallback."""
    if label == "major diameter":
        delta = measured - standard
        return -0.25 - 1e-9 <= delta <= 0.05 + 1e-9
    return abs(measured - standard) <= _tolerance(standard)


def _largest_dim(name: str, row: dict) -> tuple[float, str]:
    options = [("major", float(row["major_mm"]))]
    for key, label, field in (
        ("hex", "hex", "s_mm"),
        ("socket", "socket", "dk_mm"),
        ("nut", "nut", "s_mm"),
        ("flange", "flange", "dc_max_mm"),
    ):
        block = row.get(key) or {}
        if block.get(field) is not None:
            options.append((label, float(block[field])))
    classes = _CLEARANCE.get(name)
    if classes:
        options.append(("clearance", float(max(classes))))
    label, value = max(options, key=lambda item: item[1])
    return value, label


def _bore_diameters(report: dict) -> list[float]:
    found: list[float] = []
    for key in ("holes", "bores"):
        raw = report.get(key)
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    number = _number(item.get("diameter") or item.get("diameter_mm"))
                else:
                    number = _number(item)
                if number is not None and number > 0:
                    found.append(number)
    for row in report.get("spec") or []:
        if not isinstance(row, dict):
            continue
        bores = row.get("bores")
        if isinstance(bores, list):
            for item in bores:
                if isinstance(item, dict):
                    number = _number(item.get("diameter"))
                    if number is not None and number > 0:
                        found.append(number)
    return found


def _bindings(spec, text: str, report: dict) -> list[tuple[str, str]]:
    declared = _declared_fasteners(spec)
    if declared:
        found = list(declared)
    else:
        found = []
        decorative = _is_decorative(spec, text)
        for match in _METRIC_RE.finditer(text):
            key = "M" + match.group(1)
            if key not in _METRIC:
                continue
            role = _role_at(spec, text, match, key, decorative, report)
            if role and (key, role) not in found:
                found.append((key, role))
        for match in _NUMBER_RE.finditer(text):
            key = f"#{match.group(1)}-{match.group(2)}"
            if key in _INCH and _part_is_fastener(spec):
                found.append((key, "fastener"))
        for match in _FRACTION_RE.finditer(text):
            key = f"{match.group(1)}-{match.group(2)}"
            if key in _INCH and _part_is_fastener(spec):
                found.append((key, "fastener"))
    if _BEARING_RE.search(text) and not any(item[0] == "608" for item in found):
        found.append(("608", "bearing"))
    return found


def _declared_fasteners(spec) -> list[tuple[str, str]]:
    if not isinstance(spec, dict):
        return []
    raw = spec.get("fasteners")
    if not isinstance(raw, list):
        return []
    found = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = _canonical(str(item.get("designation") or ""))
        if not key:
            continue
        role = _ROLE_WORDS.get(str(item.get("role") or "screw").lower().replace("-", "_"), "fastener")
        found.append((key, role))
    return found


def _canonical(text: str) -> str | None:
    match = _METRIC_RE.search(text)
    if match:
        key = "M" + match.group(1)
        if key in _METRIC:
            return key
    match = _NUMBER_RE.search(text)
    if match:
        key = f"#{match.group(1)}-{match.group(2)}"
        if key in _INCH:
            return key
    return None


def _role_at(spec, text: str, match: re.Match, key: str, decorative: bool, report: dict) -> str | None:
    before = text[max(0, match.start() - 48) : match.start()]
    after = text[match.end() : match.end() + 24]
    if _CLEARANCE_BEFORE.search(before) or re.match(r"\s+mounting\b", after, re.IGNORECASE):
        return "clearance"
    if decorative and re.search(r"\b(screw|bolt)\b", before + after, re.IGNORECASE):
        return "clearance"
    if decorative:
        return None
    if _part_is_fastener(spec) or _named_designation(spec, key):
        return "fastener"
    if _has_thread(spec, report):
        return "thread"
    return None


def _named_designation(spec, key: str) -> bool:
    if not isinstance(spec, dict):
        return False
    value = spec.get("designation")
    if not isinstance(value, str):
        return False
    compact = re.sub(r"\s+", "", value)
    if re.fullmatch(key, compact, re.IGNORECASE):
        return True
    return key.lower() in compact.lower() and bool(_FASTENER_NOUN.search(value)) and not _DECORATIVE.search(value)


def _part_is_fastener(spec) -> bool:
    if isinstance(spec, str):
        return bool(_FASTENER_NOUN.search(spec)) and not _DECORATIVE.search(spec)
    if not isinstance(spec, dict):
        return False
    for key in ("part", "name", "designation"):
        value = spec.get(key)
        if isinstance(value, str) and _FASTENER_NOUN.search(value) and not _DECORATIVE.search(value):
            return True
    return False


def _is_decorative(spec, text: str) -> bool:
    if isinstance(spec, dict) and spec.get("decorative") is True:
        return True
    blob = text
    if isinstance(spec, dict):
        parts = []
        for key in ("part", "name", "role", "title"):
            value = spec.get(key)
            if isinstance(value, str):
                parts.append(value)
        if parts:
            blob = " ".join(parts)
    return bool(_DECORATIVE.search(blob))


def _has_thread(spec, report: dict) -> bool:
    if isinstance(spec, dict):
        regions = spec.get("regions") or spec.get("features")
        if isinstance(regions, list):
            for item in regions:
                if isinstance(item, dict) and str(item.get("kind") or "").lower() == "thread":
                    return True
                if isinstance(item, str) and "thread" in item.lower():
                    return True
    regions = report.get("regions")
    if isinstance(regions, list) and any(isinstance(item, dict) and item.get("kind") == "thread" for item in regions):
        return True
    printable = report.get("printability")
    if isinstance(printable, dict):
        if printable.get("auto_feature"):
            return True
        regions = printable.get("regions")
        if isinstance(regions, list) and regions:
            return True
    return False


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
