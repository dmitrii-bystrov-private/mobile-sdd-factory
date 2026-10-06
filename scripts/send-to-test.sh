#!/usr/bin/env bash
# Usage: bash scripts/send-to-test.sh <TASK-KEY>
#
# Transitions the task to the code-review handoff status without creating a git
# commit. Workflow checkpoint commits should already exist before this step.
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

if [[ "$KEY" == QA-* ]]; then
  if twg_jira_status_is_code_review_or_later "$current_status"; then
    echo "Already done: $KEY is in $current_status"
    exit 0
  fi
  if [[ "$(twg_jira_status_token "$current_status")" == "todoqa" ]]; then
    twg_jira_transition_to_first_available_status "$transition_json" "$KEY" "IN PROGRESS QA" >/dev/null
  fi
  actual_target="$(twg_jira_transition_to_first_available_status "$transition_json" "$KEY" "CODE REVIEW QA")"
  echo "Done: $KEY -> $actual_target"
  exit 0
fi

target_status="Code review"
fallback_status="Resolved"
fallback_resolution="Done"

if twg_jira_status_is_code_review_or_later "$current_status"; then
  echo "Already done: $KEY is already in code-review-or-later status: $current_status"
  exit 0
fi

echo "Transitioning $KEY ($current_status) → $target_status..."
if [[ "$current_status" == "To Do" ]]; then
  twg_jira_transition_to_first_available_status "$transition_json" "$KEY" "In Progress" >/dev/null
fi
if actual_target="$(twg_jira_transition_to_first_available_status "$transition_json" "$KEY" "$target_status" 2>/dev/null)"; then
  echo "Done: $KEY → $actual_target"
  exit 0
fi

transition_fields="$(
  jq -nc --arg resolution "$fallback_resolution" \
    '{resolution: {name: $resolution}}'
)"
actual_target="$(twg_jira_transition_to_first_available_status_with_fields_json "$transition_json" "$KEY" "$transition_fields" "$fallback_status")"
echo "Done: $KEY → $actual_target"
