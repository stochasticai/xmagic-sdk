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
from typing import Any

import yaml

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


def _parse_frontmatter(text: str) -> dict[str, Any]:
    """The frontmatter block as YAML parsed it.

    A real YAML parse rather than a line split, so a folded multi-line
    description, a quoted colon, or a comment all read as the author meant
    them. A block that is not a mapping is refused: ``name`` and
    ``description`` have nowhere to live in a list or a bare scalar.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError("SKILL.md must start with YAML frontmatter delimited by '---'")
    try:
        fields = yaml.safe_load(match.group(1))
    except yaml.YAMLError as e:
        raise ValueError(f"SKILL.md frontmatter is not valid YAML: {e}") from e
    if fields is None:
        return {}
    if not isinstance(fields, dict):
        raise ValueError(
            "SKILL.md frontmatter must be a YAML mapping of keys to values, "
            f"not a {type(fields).__name__}"
        )
    return fields


def _required_string(fields: dict[str, Any], key: str) -> str:
    """A non-empty string under ``key``, or a message naming what was there."""
    value = fields.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"SKILL.md frontmatter missing required key: {key}")
    if not isinstance(value, str):
        raise ValueError(
            f"SKILL.md frontmatter key {key!r} must be a string, "
            f"not {type(value).__name__} ({value!r}); quote it if it looks like a number"
        )
    return value.strip()


def validate_skill(path: str | Path) -> SkillManifest:
    """Validate a skill directory (or SKILL.md); return its manifest.

    Raises ValueError with an actionable message on failure.
    """
    p = Path(path)
    skill_md = p / "SKILL.md" if p.is_dir() else p
    if not skill_md.is_file():
        raise ValueError(f"SKILL.md not found at {skill_md}")
    fields = _parse_frontmatter(skill_md.read_text(encoding="utf-8"))
    return SkillManifest(
        name=_required_string(fields, "name"),
        description=_required_string(fields, "description"),
    )


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
