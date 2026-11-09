"""Shared skill id and the one-line next step every tool returns."""

from __future__ import annotations

from pathlib import Path

SKILL_ID = "photo-to-part:photo-to-printable-part"
OVERLAY_LOW_STEP = (
    "overlay unreliable: pass a seed point (seed=x,y on the part) "
    "or a region box (roi=x,y,w,h). Do not iterate geometry on it."
)

_ERROR_STEP = (
    "Read the error, then continue the flow: photo_part_measure, "
    "photo_part_template or photo_part_build, photo_part_validate, "
    "photo_part_render, deliver. Do not overwrite a validated file."
)


def attach_flow(report: dict, step: str) -> dict:
    """Add the skill id and the next action. Tools and CLIs share this."""
    report["skill_id"] = SKILL_ID
    text = step.rstrip()
    if SKILL_ID not in text:
        text = f"{text} Skill id: {SKILL_ID}."
    report["next_step"] = text
    return report


def failed(message: str, step: str | None = None) -> dict:
    """Error JSON that names the skill id in both error and next_step."""
    text = message.rstrip()
    if SKILL_ID not in text:
        text = f"{text} Skill id: {SKILL_ID}."
    return attach_flow({"ok": False, "error": text}, step or _ERROR_STEP)


def step_measure(report: dict | None = None) -> str:
    """Next action after a measurement. A size-only request stops here."""
    box = None if not isinstance(report, dict) else report.get("part_bbox_mm")
    measured = ""
    if isinstance(box, (list, tuple)) and box:
        shown = " x ".join(f"{float(item):.2f}" for item in box if _is_number(item))
        if shown:
            measured = (
                f"Report part_bbox_mm {shown} mm. "
                "If the request was only a measurement, stop. "
                "Do not invent a quad for a tilted coin. "
                "Do not replace a user-stated dimension with this box. "
            )
    return (
        f"{measured}"
        "Do not open the plugin source, features.py, or evals. "
        "If a printable part was requested: write spec.json from the user's numbers "
        "(a measured box does not overwrite those numbers), then one photo_part_template "
        "(bottle_cap, strap_hinge, spur_gear, hinge, and the other shapes; "
        "pass help true instead of reading source) or one photo_part_build, "
        "then photo_part_validate. "
        "Write <shape>_v1.stl in an absolute project directory. "
        "Do not write into HERMES_HOME/cache. Do not delete an STL or 3MF."
    )


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def step_model(path: str) -> str:
    return (
        f"Next: photo_part_validate {path}. Do not overwrite it. "
        "A later edit is a new name_vN.stl. Then photo_part_render the same file and deliver."
    )


def step_validate(
    path: str,
    *,
    ok: bool,
    was_stale: bool | None,
    score: float | None = None,
    best: dict | None = None,
    failures: list | None = None,
    open_items: int | None = None,
) -> str:
    name = Path(path).name
    if best and score is not None and float(best["score"]) > float(score) + 1e-9:
        return (
            f"Revert to {best['name']}. {name} scored {score:g} and {best['name']} scored {best['score']:g}. "
            "Do not deliver this file. photo_part_render the better version."
        )
    if ok:
        pending = int(open_items or 0)
        if pending:
            return (
                f"answer {pending} open items: --answer 'item=yes', judged against render sheet.png. "
                f"Do not overwrite {path}."
            )
        extra = ""
        if was_stale:
            extra = (
                " This file had changed after an earlier validation; "
                "this report is the new check."
            )
        return (
            f"stop. Every check passed. Next: photo_part_render this same file ({path}), then deliver it.{extra} "
            "Do not overwrite it."
        )
    listed = "; ".join(str(item) for item in (failures or []) if item)
    failed_bit = f" Failed: {listed}." if listed else ""
    return (
        f"Fix the mesh as a new name_vN.stl. Do not overwrite {path}.{failed_bit} "
        "Then photo_part_validate and photo_part_render the new file."
    )


def step_render(path: str, *, stale: bool | None, validation_ok) -> str:
    if stale is True:
        return (
            f"stale_validation is true: {path} changed after photo_part_validate. "
            "Re-validate this same file before delivering."
        )
    if stale is None:
        return (
            f"No validation sidecar for {path}. photo_part_validate this same file "
            "before delivering."
        )
    if validation_ok:
        return f"Validation matches {path}. Deliver this file. Do not overwrite it."
    return (
        f"The sidecar for {path} is not ok. Fix the mesh as a new name_vN.stl, "
        "then photo_part_validate and photo_part_render that new file."
    )


def step_heal(path: str) -> str:
    return (
        f"Next: photo_part_validate {path}, then rebuild the CAD as a new name_vN.stl "
        "if the shape is still wrong. Do not overwrite a validated mesh."
    )


def step_build(outputs: list[str], *, ok: bool) -> str:
    stl = next((path for path in outputs if str(path).lower().endswith(".stl")), None)
    if ok and stl:
        return (
            f"Next: photo_part_validate {stl} with spec.json. Do not overwrite it and do not "
            "delete an older STL or 3MF. A later edit is a new name_vN.stl. "
            "Then photo_part_render the same file and deliver."
        )
    if ok:
        return (
            "Next: if the script wrote an STL, photo_part_validate that absolute path with spec.json. "
            "Do not overwrite it. A later edit is a new name_vN.stl."
        )
    return (
        "Next: photo_part_validate the STL once the script succeeds. "
        "The error field is the exception. Fix the script and run photo_part_build again. "
        "Do not delete or overwrite an STL or 3MF."
    )
