#!/usr/bin/env bash
# Usage: bash scripts/get-issue-type.sh <ISSUE_KEY>
# Prints the issuetype name (e.g. "Story", "Bug") to stdout.
# Exits 1 if the type cannot be determined.
set -euo pipefail

KEY="${1:?Usage: get-issue-type.sh <ISSUE_KEY>}"

command -v acli >/dev/null 2>&1 || { echo "Missing required command: acli" >&2; exit 1; }
command -v jq   >/dev/null 2>&1 || { echo "Missing required command: jq"   >&2; exit 1; }

acli jira workitem view "$KEY" --fields 'issuetype' --json \
  | jq -r '.fields.issuetype.name'
