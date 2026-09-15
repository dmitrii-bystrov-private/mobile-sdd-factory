#!/usr/bin/env bash
set -euo pipefail

# update-issue.sh — Update fields of an existing Jira issue.
#
# Usage:
#   scripts/update-issue.sh --key <KEY>
#                           [--summary <text>]
#                           [--description <text>]
#                           [--description-file <path>]
#                           [--assignee <email>]
#
# Outputs:
#   ✓ Updated: <KEY>
#     <JIRA_BASE_URL>/<KEY>

JIRA_BASE_URL="${JIRA_BASE_URL:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

err() { echo "ERROR: $*" >&2; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || { err "Missing required command: $1"; exit 1; }
}

need_cmd twg
need_cmd jq

[[ -z "$JIRA_BASE_URL" ]] && { err "JIRA_BASE_URL is not set"; exit 1; }
JIRA_BASE_URL="${JIRA_BASE_URL%/}"

# shellcheck source=./twg-utils.sh
source "$SCRIPT_DIR/twg-utils.sh"

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------

KEY=""
SUMMARY=""
DESCRIPTION=""
DESCRIPTION_FILE=""
ASSIGNEE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --key)             KEY="${2:-}";              shift 2 ;;
    --summary)         SUMMARY="${2:-}";          shift 2 ;;
    --description)     DESCRIPTION="${2:-}";      shift 2 ;;
    --description-file) DESCRIPTION_FILE="${2:-}"; shift 2 ;;
    --assignee)        ASSIGNEE="${2:-}";         shift 2 ;;
    *) err "Unknown argument: $1"; exit 1 ;;
  esac
done

[[ -z "$KEY" ]] && { err "Missing required argument: --key"; exit 1; }

if [[ -z "$SUMMARY" && -z "$DESCRIPTION" && -z "$DESCRIPTION_FILE" && -z "$ASSIGNEE" ]]; then
  err "Nothing to update — provide at least one of: --summary, --description, --description-file, --priority, --assignee"
  exit 1
fi

if [[ -n "$DESCRIPTION_FILE" ]] && [[ ! -f "$DESCRIPTION_FILE" ]]; then
  err "Description file not found: $DESCRIPTION_FILE"
  exit 1
fi

# ---------------------------------------------------------------------------
# Build twg arguments
# ---------------------------------------------------------------------------

TMPFILE_JSON="$(mktemp /tmp/update-issue-XXXXXX.json)"
trap 'rm -f "$TMPFILE_JSON"' EXIT

TWG_ARGS=(jira workitem update --id "$KEY")

if [[ -n "$SUMMARY" ]]; then
  TWG_ARGS+=(--summary "$SUMMARY")
fi

if [[ -n "$DESCRIPTION_FILE" ]]; then
  TWG_ARGS+=(--description "$(cat "$DESCRIPTION_FILE")" --description-format markdown)
elif [[ -n "$DESCRIPTION" ]]; then
  TWG_ARGS+=(--description "$DESCRIPTION" --description-format markdown)
fi

if [[ -n "$ASSIGNEE" ]]; then
  TWG_ARGS+=(--assignee "$ASSIGNEE")
fi

# ---------------------------------------------------------------------------
# Update issue
# ---------------------------------------------------------------------------

run_twg_json "$TMPFILE_JSON" "${TWG_ARGS[@]}"

printf '✓ Updated: %s\n' "$KEY"
printf '  %s/%s\n' "$JIRA_BASE_URL" "$KEY"
