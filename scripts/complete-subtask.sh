#!/usr/bin/env bash
# Usage: bash scripts/complete-subtask.sh <SUBTASK-KEY>
#
# Transitions a Jira subtask to Ready for test without creating a git commit.
#
# Required env: none
# Required CLI: twg, jq
set -euo pipefail

KEY="${1:?Usage: complete-subtask.sh <SUBTASK-KEY>}"
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

if twg_jira_status_is_testing_or_later "$current_status"; then
  echo "Already done: $KEY is already in testing-or-later status: $current_status"
  exit 0
fi

echo "Transitioning $KEY ($current_status) → $target_status..."
if [[ "$current_status" == "To Do" ]]; then
  twg_jira_transition_to_first_available_status "$transition_json" "$KEY" "In Progress" >/dev/null
fi
actual_target="$(twg_jira_transition_to_first_available_status "$transition_json" "$KEY" "$target_status" "In Testing")"
echo "Done: $KEY → $actual_target"
