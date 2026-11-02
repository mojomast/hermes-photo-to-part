"""Hermes plugin entrypoint. Registers the skill and the mesh tools."""

from pathlib import Path


def register(ctx) -> None:
    """Register skills/<name>/SKILL.md and the photo_part_* tools.

    The skill call is the two-argument form, which both current and older
    Hermes builds accept. A skill name cannot contain a colon, so the mistaken
    id ``plugin:photo-to-part:photo-to-printable-part`` cannot be registered
    as an alias. The description in SKILL.md is what ``skills_list`` shows,
    and it starts with the real id ``photo-to-part:photo-to-printable-part``.
    Hermes reads that description from the skill file.
    Tools are registered with the keyword form of register_tool from Hermes
    v0.21.7 (name, toolset, schema, handler). trimesh is imported when a tool
    runs, not when the plugin is registered.
    """
    skills_dir = Path(__file__).resolve().parent / "skills"
    if skills_dir.is_dir():
        for child in sorted(path for path in skills_dir.iterdir() if path.is_dir()):
            skill_md = child / "SKILL.md"
            if skill_md.is_file():
                ctx.register_skill(child.name, skill_md)
    from photopart.tools import register_tools

    register_tools(ctx)
