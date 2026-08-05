"""Skills: scaffold, validate, and pack a skill into an upload-ready zip.

Like the MCP example, this one needs **no API key** — it only writes files
locally. It is the programmatic equivalent of `xmagic skills new/validate/pack`.

A skill is a zip containing a SKILL.md with YAML frontmatter (`name` and
`description` are required) plus any supporting files you reference from it.

Run:
    uv run python examples/05_skills.py                  # writes ./expense-policy
    uv run python examples/05_skills.py --into /tmp --name refund-policy
"""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

from xmagic.skills import new_skill, pack_skill, validate_skill

# Supporting files sit next to SKILL.md and get packed with it. Reference them
# from SKILL.md so the agent knows when to reach for them.
FAQ = """\
# Expense FAQ

**What needs a receipt?** Anything over $25.
**How long do reimbursements take?** Two pay cycles.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="expense-policy", help="skill name")
    parser.add_argument("--into", default=".", help="parent directory (default: .)")
    args = parser.parse_args()

    # 1. Scaffold. Creates <name>/SKILL.md with frontmatter already filled in.
    try:
        skill_dir = new_skill(
            args.name,
            args.into,
            description="Answers questions about the company expense policy.",
        )
    except FileExistsError:
        print(f"{Path(args.into) / args.name} already exists — remove it or pass --name.")
        return 1

    print(f"Created {skill_dir}/SKILL.md")

    # 2. Add supporting material. Everything in the directory ends up in the zip.
    (skill_dir / "faq.md").write_text(FAQ, encoding="utf-8")
    print(f"Added {skill_dir / 'faq.md'}")

    # 3. Validate before packing. pack_skill() validates too, so this is really
    #    for surfacing a clear error while you are still editing.
    try:
        manifest = validate_skill(skill_dir)
    except ValueError as e:
        print(f"Invalid skill: {e}")
        return 1

    print(f"\nValid: {manifest.name} — {manifest.description}")

    # 4. Pack.
    archive = pack_skill(skill_dir)
    with zipfile.ZipFile(archive) as zf:
        contents = zf.namelist()

    print(f"\nPacked {archive} ({archive.stat().st_size} bytes)")
    for entry in contents:
        print(f"  {entry}")

    print(
        "\nUpload it in the xMagic dashboard under Skills -> Upload ZIP."
        "\nThere is no public upload API yet (DESIGN.md §10), so this is the"
        "\nlast step the SDK can do for you."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
