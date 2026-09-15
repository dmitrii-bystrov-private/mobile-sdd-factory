#!/usr/bin/env bash
# Usage: bash scripts/send-to-test.sh <TASK-KEY>
#
# Transitions the task to the appropriate testing-ready status without creating
# a git commit. Workflow checkpoint commits should already exist before this step.
#
# Required env: none
# Required CLI: twg, jq
set -euo pipefail

KEY="${1:?Usage: send-to-test.sh <TASK-KEY>}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

command -v twg >/dev/null 2>&1 || { echo "Missing required command: twg" >&2; exit 1; }
command -v jq   >/dev/null 2>&1 || { echo "Missing required command: jq"   >&2; exit 1; }

source "$SCRIPT_DIR/twg-utils.sh"

tmp_json="$(mktemp)"
transition_json="$(mktemp)"
trap 'rm -f "$tmp_json" "$transition_json"' EXIT

twg_get_issue_legacy_json "$tmp_json" "$KEY" "status"
json="$(cat "$tmp_json")"
current_status="$(printf '%s' "$json" | jq -r '.fields.status.name')"

target_status="Ready for test"

echo "Transitioning $KEY ($current_status) → $target_status..."
if [[ "$current_status" == "To Do" ]]; then
  run_twg_json "$transition_json" jira workitem update --id "$KEY" --status "In Progress"
fi
run_twg_json "$transition_json" jira workitem update --id "$KEY" --status "$target_status"
echo "Done: $KEY → $target_status"
