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
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

command -v twg >/dev/null 2>&1 || { echo "Missing required command: twg" >&2; exit 1; }
command -v jq   >/dev/null 2>&1 || { echo "Missing required command: jq"   >&2; exit 1; }

source "$SCRIPT_DIR/twg-utils.sh"

tmp_json="$(mktemp)"
trap 'rm -f "$tmp_json"' EXIT

twg_get_issue_legacy_json "$tmp_json" "$KEY" "issuetype,parent"
json="$(cat "$tmp_json")"

is_subtask="$(echo "$json" | jq -r '.fields.issuetype.subtask')"

if [[ "$is_subtask" == "true" ]]; then
  echo "$json" | jq -r '.fields.parent.key'
else
  echo "$KEY"
fi
