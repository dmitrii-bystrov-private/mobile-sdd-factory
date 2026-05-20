#!/usr/bin/env bash
# Usage: bash scripts/send-to-test.sh <TASK-KEY>
#
# Transitions the task to the appropriate testing-ready status without creating
# a git commit. MR handoff is responsible for committing and pushing changes.
#
# Required env: none
# Required CLI: acli, jq
set -euo pipefail

KEY="${1:?Usage: send-to-test.sh <TASK-KEY>}"

command -v acli >/dev/null 2>&1 || { echo "Missing required command: acli" >&2; exit 1; }
command -v jq   >/dev/null 2>&1 || { echo "Missing required command: jq"   >&2; exit 1; }

json="$(acli jira workitem view "$KEY" --fields 'status' --json)"
current_status="$(printf '%s' "$json" | jq -r '.fields.status.name')"

target_status="Ready for test"

echo "Transitioning $KEY ($current_status) → $target_status..."
if [[ "$current_status" == "To Do" ]]; then
  acli jira workitem transition --key "$KEY" --status "In Progress"
fi
acli jira workitem transition --key "$KEY" --status "$target_status"
echo "Done: $KEY → $target_status"
