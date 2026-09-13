"""Refuse AI-attribution lines in commit messages and pull request text.

Earlier tooling appended ``Claude-Session:`` trailers, ``Co-Authored-By:
Claude ...`` lines, ``Generated with [Claude Code]`` footers, and bare
claude.ai session links to commits and pull requests. None of that belongs
in this repository's history, so this script rejects it in three places:

    check_attribution.py FILE            commit-msg hook: FILE is the message
    check_attribution.py --range A..B    every commit message in the range
    check_attribution.py --stdin         arbitrary text, e.g. a PR body

Exit status is 1 with the offending lines on stderr, else 0. Product names
in prose (a ``litellm:anthropic/...`` model ref, say) are not matched; only
the attribution forms are.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PATTERNS = (
    re.compile(r"^\s*claude-session:", re.I),
    re.compile(r"^\s*co-authored-by:.*\b(claude|anthropic)\b", re.I),
    re.compile(r"generated with \[?claude code", re.I),
    re.compile(r"https?://claude\.ai/code/", re.I),
    re.compile(r"https?://claude\.com/claude-code", re.I),
)


def offending_lines(text: str, *, skip_comments: bool = False) -> list[str]:
    """Return the lines of ``text`` that carry attribution."""
    found = []
    for line in text.splitlines():
        if skip_comments and line.startswith("#"):
            continue
        if any(p.search(line) for p in PATTERNS):
            found.append(line.rstrip())
    return found


def check_commit_range(rev_range: str) -> int:
    revs = subprocess.run(
        ["git", "rev-list", "--no-merges", rev_range],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    status = 0
    for rev in revs:
        body = subprocess.run(
            ["git", "log", "-1", "--format=%B", rev],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        if bad := offending_lines(body):
            status = 1
            _report(f"commit {rev[:12]}", bad)
    return status


def _report(where: str, lines: list[str]) -> None:
    print(f"attribution check: {where} carries AI attribution:", file=sys.stderr)
    for line in lines:
        print(f"    {line}", file=sys.stderr)
    print(
        "  Remove it. This repository does not record AI tooling in commits,\n"
        "  pull requests, or issues (see CONTRIBUTING.md).",
        file=sys.stderr,
    )


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[1] == "--stdin":
        if bad := offending_lines(sys.stdin.read()):
            _report("the text", bad)
            return 1
        return 0
    if len(argv) == 3 and argv[1] == "--range":
        return check_commit_range(argv[2])
    if len(argv) == 2:
        text = Path(argv[1]).read_text(encoding="utf-8")
        if bad := offending_lines(text, skip_comments=True):
            _report("this commit message", bad)
            return 1
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
