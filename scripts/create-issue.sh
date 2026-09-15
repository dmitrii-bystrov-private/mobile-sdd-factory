#!/usr/bin/env bash
set -euo pipefail

# create-issue.sh — Create a Jira Bug or Story.
#
# Usage:
#   scripts/create-issue.sh --project <IOS|ANDR> --type <Bug|Story> --summary <text>
#                           [--description <text>] [--description-file <path>]
#                           [--priority <Highest|High|Medium|Low|Lowest>]
#                           [--assignee <email>]
#
# Outputs:
#   <KEY>
#   <JIRA_BASE_URL>/<KEY>

JIRA_BASE_URL="${JIRA_BASE_URL:-}"
TEAM_FIELD_ID="${SDD_JIRA_TEAM_FIELD_ID:-}"
TEAM_CUSTOM_FIELD_ID="${SDD_JIRA_TEAM_CUSTOM_FIELD_ID:-customfield_10625}"
DEFAULT_ASSIGNEE="${DEFAULT_JIRA_ASSIGNEE:-}"
DEFAULT_PRIORITY="Medium"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

err() { echo "ERROR: $*" >&2; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || { err "Missing required command: $1"; exit 1; }
}

need_cmd twg
need_cmd jq

[[ -z "$TEAM_FIELD_ID" ]] && { err "SDD_JIRA_TEAM_FIELD_ID is not set"; exit 1; }
[[ -z "$JIRA_BASE_URL" ]] && { err "JIRA_BASE_URL is not set"; exit 1; }
JIRA_BASE_URL="${JIRA_BASE_URL%/}"

# shellcheck source=./twg-utils.sh
source "$SCRIPT_DIR/twg-utils.sh"

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------

PROJECT=""
TYPE=""
SUMMARY=""
DESCRIPTION=""
DESCRIPTION_FILE=""
PRIORITY="$DEFAULT_PRIORITY"
ASSIGNEE="$DEFAULT_ASSIGNEE"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)          PROJECT="${2:-}";          shift 2 ;;
    --type)             TYPE="${2:-}";             shift 2 ;;
    --summary)          SUMMARY="${2:-}";          shift 2 ;;
    --description)      DESCRIPTION="${2:-}";      shift 2 ;;
    --description-file) DESCRIPTION_FILE="${2:-}"; shift 2 ;;
    --priority)         PRIORITY="${2:-}";         shift 2 ;;
    --assignee)         ASSIGNEE="${2:-}";         shift 2 ;;
    *) err "Unknown argument: $1"; exit 1 ;;
  esac
done

[[ -z "$PROJECT" ]]  && { err "Missing required argument: --project"; exit 1; }
[[ -z "$TYPE" ]]     && { err "Missing required argument: --type"; exit 1; }
[[ -z "$SUMMARY" ]]  && { err "Missing required argument: --summary"; exit 1; }

if [[ -n "$DESCRIPTION_FILE" ]] && [[ ! -f "$DESCRIPTION_FILE" ]]; then
  err "Description file not found: $DESCRIPTION_FILE"
  exit 1
fi

# ---------------------------------------------------------------------------
# Build create arguments
# ---------------------------------------------------------------------------

TMPFILE="$(mktemp /tmp/create-issue-XXXXXX.json)"
trap 'rm -f "$TMPFILE"' EXIT

DESCRIPTION_TEXT=""
if [[ -n "$DESCRIPTION_FILE" ]]; then
  DESCRIPTION_TEXT="$(cat "$DESCRIPTION_FILE")"
elif [[ -n "$DESCRIPTION" ]]; then
  DESCRIPTION_TEXT="$DESCRIPTION"
fi

TWG_ARGS=(
  jira workitem create
  --space "$PROJECT"
  --type "$TYPE"
  --summary "$SUMMARY"
  --priority "$PRIORITY"
  --field "$TEAM_CUSTOM_FIELD_ID={\"id\":\"$TEAM_FIELD_ID\"}"
)

if [[ -n "$DESCRIPTION_TEXT" ]]; then
  TWG_ARGS+=(--description "$DESCRIPTION_TEXT" --description-format markdown)
fi

if [[ -n "$ASSIGNEE" ]]; then
  TWG_ARGS+=(--assignee "$ASSIGNEE")
fi

# ---------------------------------------------------------------------------
# Create issue
# ---------------------------------------------------------------------------

run_twg_json "$TMPFILE" "${TWG_ARGS[@]}"
KEY="$(jq -r '.data.key // .key // .data[0].key // empty' "$TMPFILE")"

if [[ -z "$KEY" ]] || [[ "$KEY" == "null" ]]; then
  err "Failed to extract issue key from twg output."
  cat "$TMPFILE" >&2
  exit 1
fi

printf '%s\n' "$KEY"
printf '%s/%s\n' "$JIRA_BASE_URL" "$KEY"
