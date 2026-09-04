#!/usr/bin/env bash
# Maintain ONE "current state" emoji reaction from the Actions bot on an issue
# or PR, so the Claude workflows visibly signal where a run is:
#
#   seen     👀  gate accepted the trigger, run is queued
#   running  🚀  Claude is actually working it
#   success  🎉  finished cleanly (PR opened / review posted)
#   paused   😕  stopped on the usage limit, auto-resume scheduled
#   failure  👎  real (non-limit) failure, or auto-resume gave up
#
# Each call removes whatever lifecycle reaction the bot left before and adds
# the new one, so exactly one bot reaction is on the item at a time. Human
# reactions (and the bot's own reaction on a specific comment) are untouched.
#
# Usage: react.sh <issue-or-pr-number> <seen|running|success|paused|failure>
# Env:   GH_TOKEN (required), GITHUB_REPOSITORY (auto-set by Actions)
set -euo pipefail

num="${1:?issue/PR number required}"
state="${2:?state required}"
repo="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY not set}"

case "$state" in
  seen)    want=eyes ;;
  running) want=rocket ;;
  success) want=hooray ;;
  paused)  want=confused ;;
  failure) want='-1' ;;
  *) echo "react.sh: unknown state '$state'" >&2; exit 2 ;;
esac

bot='github-actions[bot]'
lifecycle='eyes rocket hooray confused -1'

# Drop stale lifecycle reactions from the bot (keep the one we're about to set
# if it's already there).
while read -r id content; do
  [ -n "${id:-}" ] || continue
  case " $lifecycle " in *" $content "*) : ;; *) continue ;; esac
  [ "$content" = "$want" ] && continue
  gh api --method DELETE "repos/$repo/issues/$num/reactions/$id" >/dev/null 2>&1 || true
done < <(gh api --paginate "repos/$repo/issues/$num/reactions" \
           --jq ".[] | select(.user.login == \"$bot\") | \"\(.id) \(.content)\"" 2>/dev/null || true)

gh api --method POST "repos/$repo/issues/$num/reactions" -f content="$want" >/dev/null
echo "react: #$num -> $state ($want)"
