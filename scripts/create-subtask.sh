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

need_cmd acli
need_cmd jq
need_cmd git
need_cmd python3

# Load markdown → ADF converter
# shellcheck source=./md-to-adf.sh
source "$SCRIPT_DIR/md-to-adf.sh"

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

ASSIGNEE_EMAIL="$(acli jira workitem view "$PARENT" --json | jq -r '.fields.assignee.emailAddress')"

if [[ -z "$ASSIGNEE_EMAIL" ]] || [[ "$ASSIGNEE_EMAIL" == "null" ]]; then
  err "Parent issue $PARENT has no assignee or assignee email is missing."
  exit 1
fi

# ---------------------------------------------------------------------------
# Convert description to ADF and build request payload
# ---------------------------------------------------------------------------

DESCRIPTION_ADF="$(render_markdown_to_adf "$DESCRIPTION")"

TMP_JSON="$(mktemp /tmp/create-subtask-XXXXXX.json)"
trap 'rm -f "$TMP_JSON"' EXIT

jq -n \
  --arg project   "$PROJECT" \
  --arg parent    "$PARENT" \
  --arg summary   "$TITLE" \
  --arg assignee  "$ASSIGNEE_EMAIL" \
  --argjson desc  "$DESCRIPTION_ADF" \
  '{
    type: "Sub-task",
    projectKey: $project,
    additionalAttributes: { parent: { key: $parent } },
    summary: $summary,
    description: $desc,
    assignee: $assignee
  }' > "$TMP_JSON"

# ---------------------------------------------------------------------------
# Create the subtask
# ---------------------------------------------------------------------------

CREATE_OUTPUT="$(acli jira workitem create --from-json "$TMP_JSON" --json)"

SUBTASK_KEY="$(printf '%s' "$CREATE_OUTPUT" | jq -r '.key')"

if [[ -z "$SUBTASK_KEY" ]] || [[ "$SUBTASK_KEY" == "null" ]]; then
  err "Failed to extract subtask key from acli output."
  printf '%s\n' "$CREATE_OUTPUT" >&2
  exit 1
fi

printf '%s\n' "$SUBTASK_KEY"
