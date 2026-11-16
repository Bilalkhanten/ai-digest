#!/usr/bin/env bash
# Open (or comment on) / close a single GitHub issue identified by its exact title.
# Usage: alert_issue.sh open|close "<title>" "<body>"
# Needs: gh CLI, jq, GH_TOKEN (the workflow's GITHUB_TOKEN with issues: write), GH_REPO.
set -euo pipefail

action="${1:?usage: alert_issue.sh open|close <title> <body>}"
title="${2:?missing title}"
body="${3:-}"

existing="$(
  gh issue list --state open --search "\"$title\" in:title" --json number,title |
    jq -r --arg t "$title" '[.[] | select(.title == $t)][0].number // empty'
)"

case "$action" in
  open)
    if [ -n "$existing" ]; then
      gh issue comment "$existing" --body "$body"
    else
      gh issue create --title "$title" --body "$body"
    fi
    ;;
  close)
    if [ -n "$existing" ]; then
      gh issue comment "$existing" --body "$body"
      gh issue close "$existing" --reason completed
    fi
    ;;
  *)
    echo "unknown action: $action" >&2
    exit 2
    ;;
esac
