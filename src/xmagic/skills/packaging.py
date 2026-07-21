"""Create, validate, and pack xMagic Skills.

A Skill is a ``.zip`` archive containing a ``SKILL.md`` with YAML frontmatter
(required keys: ``name``, ``description``) plus optional supporting files
(reference docs, FAQs, templates). Skills are uploaded via the xMagic
dashboard (Sidebar -> Skills -> Upload ZIP); no public upload API is
documented yet (see DESIGN.md §10).
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)

SKILL_TEMPLATE = """\
---
name: {name}
description: {description}
---

# {name}

Describe when the agent should use this skill and how to perform it.

## Instructions

1. ...
2. ...

## References

Add supporting files (FAQs, templates, docs) alongside this SKILL.md and
mention them here.
"""


@dataclass
class SkillManifest:
    """Parsed SKILL.md frontmatter."""

    name: str
    description: str


def _parse_frontmatter(text: str) -> dict[str, str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError("SKILL.md must start with YAML frontmatter delimited by '---'")
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip().strip("\"'")
    return fields


def validate_skill(path: str | Path) -> SkillManifest:
    """Validate a skill directory (or SKILL.md); return its manifest.

    Raises ValueError with an actionable message on failure.
    """
    p = Path(path)
    skill_md = p / "SKILL.md" if p.is_dir() else p
    if not skill_md.is_file():
        raise ValueError(f"SKILL.md not found at {skill_md}")
    fields = _parse_frontmatter(skill_md.read_text(encoding="utf-8"))
    missing = [k for k in ("name", "description") if not fields.get(k)]
    if missing:
        raise ValueError(f"SKILL.md frontmatter missing required keys: {', '.join(missing)}")
    return SkillManifest(name=fields["name"], description=fields["description"])


def new_skill(name: str, directory: str | Path, description: str = "TODO") -> Path:
    """Scaffold a new skill directory containing a SKILL.md."""
    target = Path(directory) / name
    target.mkdir(parents=True, exist_ok=False)
    (target / "SKILL.md").write_text(
        SKILL_TEMPLATE.format(name=name, description=description), encoding="utf-8"
    )
    return target


def pack_skill(path: str | Path, output: str | Path | None = None) -> Path:
    """Validate then zip a skill directory into an upload-ready archive."""
    src = Path(path)
    manifest = validate_skill(src)
    out = Path(output) if output else src.parent / f"{manifest.name}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(src.rglob("*")):
            if file.is_file() and "__pycache__" not in file.parts:
                zf.write(file, file.relative_to(src))
    return out
