"""Convert a mesh's file units into millimetres, without guessing."""

from __future__ import annotations

import argparse

import numpy as np

UNIT_TO_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}
# A printable part smaller than this, or larger than this, is usually a unit mistake.
IMPLAUSIBLE_MIN_MM = 1.0
IMPLAUSIBLE_MAX_MM = 2000.0


def add_unit_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--units",
        choices=tuple(UNIT_TO_MM),
        help="Units stored in the file. Converted to millimetres. Default: treat the numbers as millimetres.",
    )
    parser.add_argument(
        "--scale",
        type=float,
        help="Extra multiplier applied after --units. Use this when the file unit is not one of mm, cm, m, or in.",
    )


def conversion_factor(units: str | None, scale: float | None) -> float:
    """Millimetres per file unit. 1 means the numbers are already millimetres."""
    if units is None:
        factor = 1.0
    elif units not in UNIT_TO_MM:
        known = ", ".join(UNIT_TO_MM)
        raise ValueError(f"unknown units {units!r}. Use one of: {known}")
    else:
        factor = UNIT_TO_MM[units]
    if scale is None:
        return factor
    try:
        extra = float(scale)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"scale must be a positive number, got {scale!r}") from exc
    if not np.isfinite(extra) or extra <= 0:
        raise ValueError(f"scale must be a positive finite number, got {scale!r}")
    return factor * extra


def _size_warning(longest: float, factor: float, units: str | None, scale: float | None) -> str | None:
    """Name a unit mistake without repeating a flag the caller already passed."""
    if IMPLAUSIBLE_MIN_MM <= longest <= IMPLAUSIBLE_MAX_MM:
        return None
    applied: list[str] = []
    if units not in (None, "mm"):
        applied.append(f"--units {units}")
    if scale is not None and float(scale) != 1.0:
        applied.append(f"--scale {float(scale):g}")
    if applied:
        flags = " and ".join(applied)
        return (
            f"after {flags} the part is {longest:.6g} mm long (scale {factor:.6g}). "
            "That is under 1 mm or over 2 m, which is implausible for a printable part. "
            f"The conversion was already applied. If the file was already millimetres, drop {flags}."
        )
    warning = (
        f"longest side is {longest:.6g} mm after scale {factor:.6g}. "
        "That is under 1 mm or over 2 m, which is implausible for a printable part. "
        "If the file is metres, centimetres, or inches, pass --units m, cm, or in, or pass --scale. "
        "Nothing was rescaled automatically."
    )
    if factor == 1.0:
        warning += " File numbers are still being treated as millimetres."
    return warning


def file_extents(mesh) -> dict[str, float]:
    extents = np.asarray(mesh.extents, dtype=float)
    return {"x": float(extents[0]), "y": float(extents[1]), "z": float(extents[2])}


def prepare_mesh(mesh, units: str | None, scale: float | None):
    """Return a mesh in millimetres and a report of what was (and was not) scaled.

    The copy is scaled only when ``units`` or ``scale`` says so. An implausible
    size produces a warning. It does not pick a new scale.
    """
    factor = conversion_factor(units, scale)
    original = file_extents(mesh)
    if factor == 1.0:
        scaled = mesh
    else:
        scaled = mesh.copy()
        scaled.apply_scale(factor)
    longest = float(np.max(np.asarray(scaled.extents, dtype=float)))
    warning = _size_warning(longest, factor, units, scale)
    # Call the axes millimetres only after a real conversion, or when the numbers already look like millimetres.
    if factor == 1.0 and warning:
        length_unit = "file units"
    else:
        length_unit = "millimetres"
    meta = {
        "file_units": units or "unspecified",
        "scale_to_mm": factor,
        "unit_warning": warning,
        "length_unit": length_unit,
        "input_extents_file": original,
    }
    return scaled, meta


def attach_units(report: dict, meta: dict) -> dict:
    report["file_units"] = meta["file_units"]
    report["scale_to_mm"] = meta["scale_to_mm"]
    report["unit_warning"] = meta["unit_warning"]
    report["length_unit"] = meta["length_unit"]
    report["input_extents_file"] = meta["input_extents_file"]
    return report
