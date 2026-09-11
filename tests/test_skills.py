"""SKILL.md frontmatter is parsed as YAML, not split on colons.

The line-based parser this replaced read `description: >` as the literal
string `>`, and a quoted colon in a name as the end of the key. A real YAML
parse reads both as the author meant them, and a block that is not a mapping,
or a value that is not a string, is refused with the reason rather than
coerced into something that validates.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from xmagic.skills import validate_skill


def _skill(tmp_path: Path, frontmatter: str, body: str = "# Body\n") -> Path:
    skill = tmp_path / "skill"
    skill.mkdir(exist_ok=True)
    (skill / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n\n{body}", encoding="utf-8")
    return skill


def test_a_folded_multi_line_description_reads_as_one_string(tmp_path: Path) -> None:
    skill = _skill(
        tmp_path,
        "name: expense-policy\ndescription: >\n  Answers questions about\n  the expense policy.",
    )

    manifest = validate_skill(skill)

    assert manifest.name == "expense-policy"
    assert manifest.description == "Answers questions about the expense policy."


def test_quoted_values_keep_their_colons_and_comments_are_ignored(tmp_path: Path) -> None:
    skill = _skill(
        tmp_path,
        "# the manifest\nname: \"refunds: policy\"\ndescription: 'Refunds, step by step.'",
    )

    manifest = validate_skill(skill)

    assert manifest.name == "refunds: policy"
    assert manifest.description == "Refunds, step by step."


def test_extra_keys_are_allowed(tmp_path: Path) -> None:
    skill = _skill(tmp_path, "name: a\ndescription: b\nlicense: Apache-2.0\nmetadata:\n  team: ops")

    assert validate_skill(skill).name == "a"


def test_a_missing_key_names_it(tmp_path: Path) -> None:
    skill = _skill(tmp_path, "name: a")

    with pytest.raises(ValueError, match="missing required key: description"):
        validate_skill(skill)


def test_an_empty_value_counts_as_missing(tmp_path: Path) -> None:
    skill = _skill(tmp_path, 'name: a\ndescription: "   "')

    with pytest.raises(ValueError, match="missing required key: description"):
        validate_skill(skill)


def test_a_non_string_value_is_refused_not_coerced(tmp_path: Path) -> None:
    skill = _skill(tmp_path, "name: 2024\ndescription: b")

    with pytest.raises(ValueError, match="'name' must be a string, not int"):
        validate_skill(skill)


def test_a_non_mapping_block_is_refused(tmp_path: Path) -> None:
    skill = _skill(tmp_path, "- name\n- description")

    with pytest.raises(ValueError, match="must be a YAML mapping"):
        validate_skill(skill)


def test_invalid_yaml_reports_the_parser_error(tmp_path: Path) -> None:
    skill = _skill(tmp_path, "name: [unclosed\ndescription: b")

    with pytest.raises(ValueError, match="not valid YAML"):
        validate_skill(skill)


def test_no_frontmatter_at_all_is_refused(tmp_path: Path) -> None:
    skill = tmp_path / "bare"
    skill.mkdir()
    (skill / "SKILL.md").write_text("# Just a heading\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must start with YAML frontmatter"):
        validate_skill(skill)


def test_an_empty_frontmatter_block_reports_the_missing_key(tmp_path: Path) -> None:
    skill = _skill(tmp_path, "# nothing but a comment")

    with pytest.raises(ValueError, match="missing required key: name"):
        validate_skill(skill)
