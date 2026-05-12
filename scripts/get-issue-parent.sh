#!/usr/bin/env bash
# Usage: bash scripts/get-issue-parent.sh <ISSUE_KEY>
#
# Prints the story key for the given issue:
#   - If the issue is a subtask, prints its parent key.
#   - Otherwise, prints the issue key itself.
#
# Exit codes: 0 on success, 1 on error.
set -euo pipefail

KEY="${1:?Usage: get-issue-parent.sh <ISSUE_KEY>}"

command -v acli >/dev/null 2>&1 || { echo "Missing required command: acli" >&2; exit 1; }
command -v jq   >/dev/null 2>&1 || { echo "Missing required command: jq"   >&2; exit 1; }

json="$(acli jira workitem view "$KEY" --fields 'issuetype,parent' --json)"

is_subtask="$(echo "$json" | jq -r '.fields.issuetype.subtask')"

if [[ "$is_subtask" == "true" ]]; then
  echo "$json" | jq -r '.fields.parent.key'
else
  echo "$KEY"
fi
