"""Hermes plugin entrypoint. Registers the skill and the mesh tools."""

import json
import os
from pathlib import Path

_HELP_MODES = {"help", "describe"}
_APPROVAL_OFF = {"allow", "yes", "true", "1", "off", "skip"}


def _approval_args(args) -> dict:
    """Tool arguments as a dict. A JSON object string is accepted."""
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        text = args.strip()
        if text[:1] == "{":
            try:
                loaded = json.loads(text)
            except json.JSONDecodeError:
                return {}
            if isinstance(loaded, dict):
                return loaded
    return {}


def _build_is_help(args: dict) -> bool:
    """True when photo_part_build will not run a script."""
    if args.get("help") or args.get("describe"):
        return True
    return str(args.get("mode") or "").strip().lower() in _HELP_MODES


def _note_gate(decision, project):
    """Record an approval wait for the pane. The decision dict is unchanged."""
    if not isinstance(decision, dict) or decision.get("action") != "approve":
        return decision
    try:
        from photopart.progress import note_approval

        where = project if isinstance(project, str) else None
        note_approval(where, str(decision.get("message") or ""), str(decision.get("rule_key") or "photo_part_build"))
    except Exception:
        return decision
    return decision


def approve_build(tool_name: str = "", args: dict | None = None, **kwargs):
    """pre_tool_call hook: ask before a photo-to-part build runs.

    ``photo_part_build`` is gated unless the call is ``help`` or ``describe``.
    The same ``rule_key`` (``photo_part_build``) covers a terminal or code
    tool that runs ``python build.py``, CadQuery or build123d, or
    ``photopart.build_run`` / ``photopart.stamp``. ``ls``, ``cat``, and
    ``pytest`` are not builds. ``PHOTOPART_BUILD_APPROVAL=allow`` skips the
    prompt for an in-process test or a sealed eval. The default is to ask.
    Hermes fails closed when nobody can approve. Hermes ``--yolo``
    auto-approves the returned action. This plugin does not block that flag.
    """
    if str(tool_name or "") != "photo_part_build":
        from photopart.build_gate import terminal_build_approval

        decision = terminal_build_approval(
            tool_name,
            args,
            session_id=kwargs.get("session_id"),
        )
        parsed = _approval_args(args)
        project = parsed.get("cwd") if isinstance(parsed.get("cwd"), str) else parsed.get("workdir")
        return _note_gate(decision, project)
    parsed = _approval_args(args)
    if _build_is_help(parsed):
        return None
    if os.environ.get("PHOTOPART_BUILD_APPROVAL", "").strip().lower() in _APPROVAL_OFF:
        return None
    raw_args = parsed.get("args") or []
    if not isinstance(raw_args, (list, tuple)):
        raw_args = []
    extra = " ".join(str(item) for item in raw_args)
    script = parsed.get("script", "")
    script = "" if script is None else str(script)
    cwd = parsed.get("cwd") or "."
    message = f"Run {script} {extra}".rstrip() + f" in {cwd}"
    decision = {"action": "approve", "message": message, "rule_key": "photo_part_build"}
    project = parsed.get("cwd") if isinstance(parsed.get("cwd"), str) else None
    if not project and script:
        project = str(Path(script).expanduser().parent)
    return _note_gate(decision, project)


def register(ctx) -> None:
    """Register skills/<name>/SKILL.md and the photo_part_* tools.

    The skill call is the two-argument form, which both current and older
    Hermes builds accept. A skill name cannot contain a colon, so the mistaken
    id ``plugin:photo-to-part:photo-to-printable-part`` cannot be registered
    as an alias. The description in SKILL.md is what ``skills_list`` shows,
    and it starts with the real id ``photo-to-part:photo-to-printable-part``.
    Hermes reads that description from the skill file.
    Tools use the keyword form of register_tool. Hermes v0.21.7 accepts
    name, toolset, schema, handler, description, and emoji, and rejects
    output_schema. That keyword is passed only when the live signature
    accepts it. trimesh is imported when a tool runs, not when the plugin
    is registered. ``pre_tool_call`` still rewrites this skill's id.
    ``post_tool_call`` and ``transform_tool_result`` still count the session
    budget. A second ``pre_tool_call`` callback asks for Hermes approval
    before ``photo_part_build`` runs a script, and before a terminal or
    code tool runs that build directly. ``pre_tool_call`` also blocks reads
    of ``evals/`` scoring files and ``tests/regression``, and blocks a
    handwritten gear or involute script until ``photo_part_template``
    shape ``spur_gear`` has been tried. ``pre_llm_call`` only classifies
    that request and does not inject context. ``on_session_end`` settles
    the Part studio pane to a terminal state when a session ends.
    """
    skills_dir = Path(__file__).resolve().parent / "skills"
    if skills_dir.is_dir():
        for child in sorted(path for path in skills_dir.iterdir() if path.is_dir()):
            skill_md = child / "SKILL.md"
            if skill_md.is_file():
                ctx.register_skill(child.name, skill_md)
    from photopart.tools import register_tools

    register_tools(ctx)
    if hasattr(ctx, "register_hook"):
        try:
            from photopart.hooks import HOOKS

            for hook_name, callback in HOOKS:
                ctx.register_hook(hook_name, callback)
        except Exception:
            # A Hermes build without these hooks still gets the six tools.
            pass
        try:
            ctx.register_hook("pre_tool_call", approve_build)
        except Exception:
            return
