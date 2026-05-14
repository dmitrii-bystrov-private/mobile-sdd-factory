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
#     https://pnlfintech.atlassian.net/browse/<KEY>

JIRA_BASE_URL="https://pnlfintech.atlassian.net/browse"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

err() { echo "ERROR: $*" >&2; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || { err "Missing required command: $1"; exit 1; }
}

need_cmd acli
need_cmd jq
need_cmd python3

# shellcheck source=./md-to-adf.sh
source "$SCRIPT_DIR/md-to-adf.sh"

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
# Build acli arguments
# ---------------------------------------------------------------------------

TMPFILE_DESC="$(mktemp /tmp/update-issue-desc-XXXXXX.md)"
trap 'rm -f "$TMPFILE_DESC"' EXIT

ACLI_ARGS=(jira workitem edit --key "$KEY" --yes)

if [[ -n "$SUMMARY" ]]; then
  ACLI_ARGS+=(--summary "$SUMMARY")
fi

if [[ -n "$DESCRIPTION_FILE" ]]; then
  ADF_JSON="$(render_markdown_to_adf "$DESCRIPTION_FILE")"
  printf '%s' "$ADF_JSON" > "$TMPFILE_DESC"
  ACLI_ARGS+=(--description-file "$TMPFILE_DESC")
elif [[ -n "$DESCRIPTION" ]]; then
  printf '%s' "$DESCRIPTION" > "$TMPFILE_DESC"
  ADF_JSON="$(render_markdown_to_adf "$TMPFILE_DESC")"
  printf '%s' "$ADF_JSON" > "$TMPFILE_DESC"
  ACLI_ARGS+=(--description-file "$TMPFILE_DESC")
fi

if [[ -n "$ASSIGNEE" ]]; then
  ACLI_ARGS+=(--assignee "$ASSIGNEE")
fi

# ---------------------------------------------------------------------------
# Update issue
# ---------------------------------------------------------------------------

acli "${ACLI_ARGS[@]}"

printf '✓ Updated: %s\n' "$KEY"
printf '  %s/%s\n' "$JIRA_BASE_URL" "$KEY"
