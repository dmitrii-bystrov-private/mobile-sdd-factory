#!/usr/bin/env bash
# Usage: bash scripts/complete-subtask.sh <SUBTASK-KEY>
#
# Transitions a Jira subtask to Ready for test without creating a git commit.
#
# Required env: none
# Required CLI: acli, jq
set -euo pipefail

KEY="${1:?Usage: complete-subtask.sh <SUBTASK-KEY>}"

command -v acli >/dev/null 2>&1 || { echo "Missing required command: acli" >&2; exit 1; }
command -v jq   >/dev/null 2>&1 || { echo "Missing required command: jq"   >&2; exit 1; }

json="$(acli jira workitem view "$KEY" --fields 'status' --json)"
current_status="$(printf '%s' "$json" | jq -r '.fields.status.name')"

target_status="Ready for test"

if [[ "$current_status" == "$target_status" ]]; then
  echo "Already done: $KEY is already $target_status"
  exit 0
fi

echo "Transitioning $KEY ($current_status) → $target_status..."
if [[ "$current_status" == "To Do" ]]; then
  acli jira workitem transition --key "$KEY" --status "In Progress"
fi
acli jira workitem transition --key "$KEY" --status "$target_status"
echo "Done: $KEY → $target_status"
