#!/usr/bin/env bash
# PreToolUse (Bash): refuse a command that would write AI attribution into
# git or GitHub. Scans the command text of `git commit`, `gh pr`, `gh issue`,
# and `gh release` invocations with scripts/check_attribution.py, the same
# checker the commit-msg hook and CI run. Anything else exits 0 untouched.
#
# A message passed through `-F file` is not visible here; the git commit-msg
# hook (git config core.hooksPath .githooks) and CI still catch that.
set -uo pipefail

cmd="$(jq -r '.tool_input.command // empty')"
[ -n "$cmd" ] || exit 0

case "$cmd" in
    *"git commit"* | *"gh pr"* | *"gh issue"* | *"gh release"*) ;;
    *) exit 0 ;;
esac

root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
if err="$(printf '%s\n' "$cmd" | python3 "$root/scripts/check_attribution.py" --stdin 2>&1)"; then
    exit 0
fi

jq -n --arg reason "$err" '{
  hookSpecificOutput: {
    hookEventName: "PreToolUse",
    permissionDecision: "deny",
    permissionDecisionReason: ("Refused: the command carries AI attribution. Strip Claude-Session trailers, Co-Authored-By: Claude lines, and claude.ai links, then retry.\n" + $reason)
  }
}'
