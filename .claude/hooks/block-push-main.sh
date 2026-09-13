#!/usr/bin/env bash
# PreToolUse (Bash): refuse `git push` that targets main. Work reaches main
# through pull requests; a direct push skips CI and the attribution check.
# Tag pushes and pushes to feature branches pass through.
set -uo pipefail

cmd="$(jq -r '.tool_input.command // empty')"
[ -n "$cmd" ] || exit 0
case "$cmd" in *"git push"*) ;; *) exit 0 ;; esac

deny() {
    jq -n --arg reason "$1" '{
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: ("Refused: " + $reason + " Open a pull request instead.")
      }
    }'
    exit 0
}

current="$(git branch --show-current 2>/dev/null || true)"

# Everything after the first `git push`, up to the next shell operator.
rest="${cmd#*git push}"
refspec_given=0
positional=0
for tok in $rest; do
    tok="${tok%;}"
    case "$tok" in
        "" | "&&" | "||" | ";" | "|") [ -z "$tok" ] && continue || break ;;
        -*) continue ;;
    esac
    positional=$((positional + 1))
    # First positional is the remote; later ones are refspecs.
    [ "$positional" -ge 2 ] || continue
    refspec_given=1
    tok="${tok#+}"                  # `+main` is a forced push of main
    dst="${tok##*:}"                # `src:dst` -> dst; bare `ref` -> ref
    src="${tok%%:*}"
    case "$dst" in
        main | refs/heads/main) deny "\`git push\` targets main." ;;
    esac
    # `git push origin HEAD` pushes whatever is checked out.
    if [ "$src" = "HEAD" ] && [ "$tok" = "$src" ] && [ "$current" = "main" ]; then
        deny "\`git push ... HEAD\` while on main would push main."
    fi
done

case " $rest " in
    *" --all "* | *" --mirror "*) deny "\`git push --all/--mirror\` includes main." ;;
    *" --tags "*) [ "$refspec_given" -eq 0 ] && exit 0 ;;   # tags only, no branch
esac

if [ "$refspec_given" -eq 0 ] && [ "$current" = "main" ]; then
    deny "\`git push\` with no refspec while on main would push main."
fi
exit 0
