#!/usr/bin/env bash
set -euo pipefail

# create-subtask.sh — Create a single Jira subtask under a parent story.
#
# Usage:
#   scripts/create-subtask.sh --parent <KEY> --title <title> --description <file.md>

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

err() {
  echo "ERROR: $*" >&2
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || { err "Missing required command: $1"; exit 1; }
}

# ---------------------------------------------------------------------------
# Validate required tools
# ---------------------------------------------------------------------------

need_cmd twg
need_cmd jq
need_cmd git

# shellcheck source=./twg-utils.sh
source "$SCRIPT_DIR/twg-utils.sh"

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------

PARENT=""
TITLE=""
DESCRIPTION=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --parent)
      PARENT="${2:-}"
      shift 2
      ;;
    --title)
      TITLE="${2:-}"
      shift 2
      ;;
    --description)
      DESCRIPTION="${2:-}"
      shift 2
      ;;
    *)
      err "Unknown argument: $1"
      exit 1
      ;;
  esac
done

if [[ -z "$PARENT" ]]; then
  err "Missing required argument: --parent"
  exit 1
fi

if [[ -z "$TITLE" ]]; then
  err "Missing required argument: --title"
  exit 1
fi

if [[ -z "$DESCRIPTION" ]]; then
  err "Missing required argument: --description"
  exit 1
fi

# ---------------------------------------------------------------------------
# Validate description file
# ---------------------------------------------------------------------------

if [[ ! -f "$DESCRIPTION" ]] || [[ ! -r "$DESCRIPTION" ]]; then
  err "Description file not found or not readable: $DESCRIPTION"
  exit 1
fi

# ---------------------------------------------------------------------------
# Derive project key from parent (e.g. IOS-12042 → IOS)
# ---------------------------------------------------------------------------

PROJECT="${PARENT%%-*}"

# ---------------------------------------------------------------------------
# Fetch parent assignee
# ---------------------------------------------------------------------------

PARENT_JSON="$(mktemp)"
CREATE_JSON="$(mktemp)"
trap 'rm -f "$PARENT_JSON" "$CREATE_JSON"' EXIT

twg_get_issue_legacy_json "$PARENT_JSON" "$PARENT" "assignee"
ASSIGNEE_ACCOUNT_ID="$(jq -r '.fields.assignee.accountId // empty' "$PARENT_JSON")"

if [[ -z "$ASSIGNEE_ACCOUNT_ID" ]] || [[ "$ASSIGNEE_ACCOUNT_ID" == "null" ]]; then
  err "Parent issue $PARENT has no assignee or assignee account id is missing."
  exit 1
fi

# ---------------------------------------------------------------------------
# Create the subtask
# ---------------------------------------------------------------------------

run_twg_json "$CREATE_JSON" \
  jira workitem create \
  --space "$PROJECT" \
  --type "Sub-task" \
  --parent "$PARENT" \
  --summary "$TITLE" \
  --description "$(cat "$DESCRIPTION")" \
  --description-format markdown \
  --assignee "$ASSIGNEE_ACCOUNT_ID"

SUBTASK_KEY="$(jq -r '.data.key // .key // .data[0].key // empty' "$CREATE_JSON")"

if [[ -z "$SUBTASK_KEY" ]] || [[ "$SUBTASK_KEY" == "null" ]]; then
  err "Failed to extract subtask key from twg output."
  cat "$CREATE_JSON" >&2
  exit 1
fi

printf '%s\n' "$SUBTASK_KEY"
