"""Scale a gear photo from a stated outer diameter when no coin is present.

A spur-gear template already records its tip diameter. When a render has
a photo but no measured px/mm, this estimates scale from the photo's
largest part blob divided by that stated OD. The overlay is labelled
guide-only: it is not a coin- or ruler-backed measurement.
"""

from __future__ import annotations

import json
from pathlib import Path

SCALE_SOURCE = "stated_outer_diameter"
SCALE_LABEL = "scale from stated OD"
SCALE_NOTE = (
    "Scale uses the template's stated outer diameter, not a coin or ruler. "
    "Overlay IoU is a guide only."
)


def stated_outer_diameter_mm(mesh) -> float | None:
    """Tip diameter in millimetres from a spur_gear template sidecar, if any."""
    path = Path(mesh).expanduser() if mesh else None
    if path is None:
        return None
    sidecar = Path(str(path) + ".template.json")
    if not sidecar.is_file():
        return None
    try:
        doc = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(doc, dict) or doc.get("shape") != "spur_gear":
        return None
    raw = doc.get("outer_diameter_mm")
    if isinstance(raw, (int, float)) and float(raw) > 0:
        return float(raw)
    checks = doc.get("spec_checks") if isinstance(doc.get("spec_checks"), dict) else {}
    spans = []
    for key in ("x", "y"):
        value = checks.get(key)
        if isinstance(value, (int, float)) and float(value) > 0:
            spans.append(float(value))
    return max(spans) if spans else None


def scale_from_stated_od(photo, diameter_mm: float) -> dict | None:
    """Return px/mm from the photo silhouette and a stated outer diameter."""
    path = Path(photo).expanduser() if photo else None
    if path is None or not path.is_file():
        return None
    try:
        span_mm = float(diameter_mm)
    except (TypeError, ValueError):
        return None
    if not (span_mm > 0):
        return None
    try:
        import numpy as np
        from PIL import Image
        from photopart.measure import _min_area_size, _part_mask
    except Exception:
        return None
    try:
        image = np.array(Image.open(path).convert("RGB"))
        component = _part_mask(image, None, None, None)
    except Exception:
        return None
    if component is None or int(np.count_nonzero(component)) < 16:
        return None
    try:
        length_px, width_px, _angle = _min_area_size(component)
    except Exception:
        return None
    span_px = max(float(length_px), float(width_px))
    if span_px < 16:
        return None
    return {
        "px_per_mm": span_px / span_mm,
        "span_px": span_px,
        "diameter_mm": span_mm,
        "source": SCALE_SOURCE,
        "label": SCALE_LABEL,
        "note": SCALE_NOTE,
    }


def scale_for_mesh(mesh, photo) -> dict | None:
    """Convenience: stated OD for ``mesh``, then scale from ``photo``."""
    diameter = stated_outer_diameter_mm(mesh)
    if diameter is None:
        return None
    return scale_from_stated_od(photo, diameter)
