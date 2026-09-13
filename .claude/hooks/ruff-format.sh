#!/usr/bin/env bash
# PostToolUse (Write|Edit): run ruff format on the file just written, so
# formatting never surfaces as a CI failure or a review comment. Only .py and
# .md (ruff formats fenced Python in Markdown). Never fails the tool call.
set -uo pipefail

f="$(jq -r '.tool_input.file_path // .tool_response.filePath // empty')"
[ -n "$f" ] || exit 0
case "$f" in *.py | *.md) ;; *) exit 0 ;; esac
[ -f "$f" ] || exit 0

root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$root" && uv run ruff format "$f" >/dev/null 2>&1 || true
exit 0
