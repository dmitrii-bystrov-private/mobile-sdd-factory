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
#   https://pnlfintech.atlassian.net/browse/<KEY>

JIRA_BASE_URL="https://pnlfintech.atlassian.net/browse"
TEAM_FIELD_ID="11914"   # common-mobile (customfield_10625)
DEFAULT_ASSIGNEE="${DEFAULT_JIRA_ASSIGNEE:-}"
DEFAULT_PRIORITY="Medium"
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
# Build JSON payload
# ---------------------------------------------------------------------------

TMPFILE="$(mktemp /tmp/create-issue-XXXXXX.json)"
TMPFILE_DESC="$(mktemp /tmp/create-issue-desc-XXXXXX.md)"
trap 'rm -f "$TMPFILE" "$TMPFILE_DESC"' EXIT

# Build description ADF
if [[ -n "$DESCRIPTION_FILE" ]]; then
  DESC_JSON="$(render_markdown_to_adf "$DESCRIPTION_FILE")"
elif [[ -n "$DESCRIPTION" ]]; then
  printf '%s' "$DESCRIPTION" > "$TMPFILE_DESC"
  DESC_JSON="$(render_markdown_to_adf "$TMPFILE_DESC")"
else
  DESC_JSON="null"
fi

jq -n \
  --arg summary  "$SUMMARY" \
  --arg project  "$PROJECT" \
  --arg type     "$TYPE" \
  --arg assignee "$ASSIGNEE" \
  --arg priority "$PRIORITY" \
  --arg teamId   "$TEAM_FIELD_ID" \
  --argjson desc "$DESC_JSON" \
  '{
    additionalAttributes: {
      priority: {name: $priority},
      customfield_10625: {id: $teamId}
    },
    assignee:    (if $assignee != "" then $assignee else null end),
    summary:     $summary,
    description: $desc,
    projectKey:  $project,
    type:        $type
  }' > "$TMPFILE"

# ---------------------------------------------------------------------------
# Create issue
# ---------------------------------------------------------------------------

OUTPUT="$(acli jira workitem create --from-json "$TMPFILE" --json)"
KEY="$(printf '%s' "$OUTPUT" | jq -r '.key')"

if [[ -z "$KEY" ]] || [[ "$KEY" == "null" ]]; then
  err "Failed to extract issue key from acli output."
  printf '%s\n' "$OUTPUT" >&2
  exit 1
fi

printf '%s\n' "$KEY"
printf '%s/%s\n' "$JIRA_BASE_URL" "$KEY"
