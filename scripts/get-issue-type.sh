#!/usr/bin/env bash
# Usage: bash scripts/get-issue-type.sh <ISSUE_KEY>
# Prints the issuetype name (e.g. "Story", "Bug") to stdout.
# Exits 1 if the type cannot be determined.
set -euo pipefail

KEY="${1:?Usage: get-issue-type.sh <ISSUE_KEY>}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

command -v twg >/dev/null 2>&1 || { echo "Missing required command: twg" >&2; exit 1; }
command -v jq   >/dev/null 2>&1 || { echo "Missing required command: jq"   >&2; exit 1; }

source "$SCRIPT_DIR/twg-utils.sh"

tmp_json="$(mktemp)"
trap 'rm -f "$tmp_json"' EXIT

twg_get_issue_legacy_json "$tmp_json" "$KEY" "issuetype"
cat "$tmp_json" \
  | jq -r '.fields.issuetype.name'
