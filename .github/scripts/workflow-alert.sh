#!/bin/bash
# Report a workflow's outcome from a separate alert job.
#   workflow-alert.sh "<space-separated needs.*.result>"
# Any failure opens (or comments on) "排程失敗：<workflow>"; an all-success run
# closes it; cancelled or skipped runs change nothing.
set -euo pipefail

results="$1"
title="🔴 排程失敗：${GITHUB_WORKFLOW}"
run_url="${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}"
here="$(dirname "$0")"

if [[ " $results " == *" failure "* ]]; then
  failed_steps=$(gh run view "$GITHUB_RUN_ID" --repo "$GITHUB_REPOSITORY" --json jobs \
    --jq '.jobs[] | select(.conclusion == "failure") | .name as $job
          | .steps[] | select(.conclusion == "failure") | "- \($job) / \(.name)"' \
    2>/dev/null || true)
  body="$(mktemp)"
  {
    echo "排程 **${GITHUB_WORKFLOW}** 執行失敗。"
    echo
    echo "- 執行紀錄：${run_url}"
    echo "- 觸發方式：${GITHUB_EVENT_NAME}；commit：${GITHUB_SHA:0:7}"
    echo "- 時間（UTC）：$(date -u '+%Y-%m-%d %H:%M')"
    echo
    echo "失敗步驟："
    echo "${failed_steps:-（無法取得，請開啟執行紀錄查看）}"
    echo
    echo "若失敗步驟是 \`Require manual review for unsafe filing boundaries\`，代表有新申報需要人工確認切分，"
    echo "請處理同批 SEC 通知 issue；其他步驟失敗則代表排程本身壞掉，後續資料不會更新。"
    echo "下一次成功執行時，這個 issue 會自動關閉。"
  } > "$body"
  bash "$here/issue-alert.sh" open "$title" "$body"
elif [[ -n "$results" && " $results " != *" cancelled "* && " $results " != *" skipped "* ]]; then
  bash "$here/issue-alert.sh" close "$title" "✅ 已恢復：${run_url} 執行成功。"
else
  echo "Results '$results': nothing to report."
fi
