#!/usr/bin/env bash
# Usage: bash scripts/get-issue-status.sh <ISSUE_KEY>
# Prints legacy-shaped JSON containing the issue status.
set -euo pipefail

KEY="${1:?Usage: get-issue-status.sh <ISSUE_KEY>}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

command -v twg >/dev/null 2>&1 || { echo "Missing required command: twg" >&2; exit 1; }
command -v jq >/dev/null 2>&1 || { echo "Missing required command: jq" >&2; exit 1; }

# shellcheck source=scripts/twg-utils.sh
source "$SCRIPT_DIR/twg-utils.sh"

tmp_json="$(mktemp)"
trap 'rm -f "$tmp_json"' EXIT

twg_get_issue_legacy_json "$tmp_json" "$KEY" "status"
cat "$tmp_json"
