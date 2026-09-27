#!/bin/bash
# Keep exactly one open tracking issue per alert title.
#   issue-alert.sh open  "<title>" <body-file>   create it, or comment on the open one
#   issue-alert.sh close "<title>" "<comment>"   comment and close it if open
# Needs GH_TOKEN and GITHUB_REPOSITORY (set by GitHub Actions).
set -euo pipefail

action="$1"
export ALERT_TITLE="$2"

existing=$(gh issue list --repo "$GITHUB_REPOSITORY" --state open --limit 100 \
  --search "\"$ALERT_TITLE\" in:title" --json number,title \
  --jq '[.[] | select(.title == env.ALERT_TITLE)][0].number // empty')

case "$action" in
  open)
    if [ -n "$existing" ]; then
      gh issue comment "$existing" --repo "$GITHUB_REPOSITORY" --body-file "$3"
      echo "Updated open issue #$existing"
    else
      gh issue create --repo "$GITHUB_REPOSITORY" --title "$ALERT_TITLE" \
        --body-file "$3" --assignee "$GITHUB_REPOSITORY_OWNER"
    fi
    ;;
  close)
    if [ -n "$existing" ]; then
      gh issue close "$existing" --repo "$GITHUB_REPOSITORY" --comment "$3"
      echo "Closed recovered issue #$existing"
    else
      echo "No open issue titled: $ALERT_TITLE"
    fi
    ;;
  *)
    echo "usage: issue-alert.sh open|close <title> <body-file|comment>" >&2
    exit 2
    ;;
esac
