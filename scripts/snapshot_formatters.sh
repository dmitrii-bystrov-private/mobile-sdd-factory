#!/usr/bin/env bash
# snapshot_formatters.sh — Pure formatting functions for Jira snapshot artifacts.
#
# Source this file to get:
#   write_description_md  <out_file> <key> <type> <title> <status> <body_md>
#   write_comments_md     <out_file> <comments_json>
#   write_statuses_md     <out_file> <parent_json> <subtasks_json> [existing_statuses_file]

# ---------------------------------------------------------------------------
# Sentinel / delimiter constants (single source of truth)
# ---------------------------------------------------------------------------

readonly SENTINEL_DESC_START="<!-- jira-description:start -->"
readonly SENTINEL_DESC_END="<!-- jira-description:end -->"
readonly SENTINEL_COMMENT_START="<!-- jira-comment:start -->"
readonly SENTINEL_COMMENT_END="<!-- jira-comment:end -->"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# normalize_title <text>
# Replace line breaks with spaces, collapse whitespace, escape |
normalize_title() {
  local text="$1"
  # Replace \r\n, \r, \n with space; collapse runs of whitespace; escape |
  printf '%s' "$text" \
    | tr '\r\n' '  ' \
    | sed 's/[[:space:]]\{2,\}/ /g' \
    | sed 's/|/\\|/g' \
    | sed 's/^[[:space:]]//; s/[[:space:]]$//'
}

# ---------------------------------------------------------------------------
# write_description_md
#
# Args:
#   $1  out_file   — path to write
#   $2  key        — Jira issue key (e.g. IOS-123)
#   $3  type       — Jira issue type name (e.g. Story, Bug)
#   $4  title      — Jira summary (will be normalized)
#   $5  status     — Jira status name (verbatim)
#   $6  body_md    — already-rendered Markdown description body (may be empty)
# ---------------------------------------------------------------------------

write_description_md() {
  local out_file="$1"
  local key="$2"
  local issue_type="$3"
  local title="$4"
  local issue_status="$5"
  local body_md="$6"

  local norm_title
  norm_title="$(normalize_title "$title")"

  {
    printf '# Description\n'
    printf 'ID: %s\n' "$key"
    printf 'Type: %s\n' "$issue_type"
    printf 'Title: %s\n' "$norm_title"
    printf 'Status: %s\n' "$issue_status"
    printf '\n'
    printf '## Raw Description\n'
    printf '\n'
    printf '%s\n' "$SENTINEL_DESC_START"
    if [[ -n "$body_md" ]]; then
      printf '%s\n' "$body_md"
    fi
    printf '%s\n' "$SENTINEL_DESC_END"
  } > "$out_file"
}

# ---------------------------------------------------------------------------
# write_comments_md
#
# Args:
#   $1  out_file       — path to write
#   $2  comments_json  — JSON array of comment objects, each with:
#                         .id, .created, .body_md (already-rendered Markdown)
#
# comments_json format (shell-produced JSON array):
#   [{"id":"1","created":"2024-01-01T00:00:00.000+0000","body_md":"..."},...]
#
# Comments are written in chronological order (sorted by .created asc,
# tie-break by .id asc).
# ---------------------------------------------------------------------------

write_comments_md() {
  local out_file="$1"
  local comments_json="$2"

  {
    printf '## Comments\n'

    # Sort by created asc, then id asc; iterate and emit each block
    printf '%s' "$comments_json" | jq -r '
      sort_by(.created, .id) |
      .[] |
      @base64
    ' | while IFS= read -r encoded; do
      comment="$(printf '%s' "$encoded" | base64 -d)"
      id="$(printf '%s' "$comment" | jq -r '.id')"
      body_md="$(printf '%s' "$comment" | jq -r '.body_md')"

      printf '\n'
      printf '%s\n' "$SENTINEL_COMMENT_START"
      printf 'ID: %s\n' "$id"
      printf '\n'
      if [[ -n "$body_md" && "$body_md" != "null" ]]; then
        printf '%s\n' "$body_md"
      fi
      printf '%s\n' "$SENTINEL_COMMENT_END"
    done
  } > "$out_file"
}

# ---------------------------------------------------------------------------
# write_statuses_md
#
# Args:
#   $1  out_file              — path to write
#   $2  parent_json           — single-object JSON: {key, type, title, status}
#   $3  subtasks_json         — JSON array: [{key, type, title, status}, ...]
#                               sorted by key asc; may be "[]"
#   $4  existing_file         — (optional) path to existing statuses.md for
#                               carrying forward last-known values on failure;
#                               pass "" or omit if not available
#
# For subtasks with empty title/type/status (retrieval failed), values are
# carried forward from existing_file if provided.
# ---------------------------------------------------------------------------

write_statuses_md() {
  local out_file="$1"
  local parent_json="$2"
  local subtasks_json="$3"
  local existing_file="${4:-}"

  # Build a lookup map of last-known values from existing statuses.md
  # Format in existing file: | KEY | TYPE | TITLE | STATUS |
  declare -A last_type last_title last_status
  if [[ -n "$existing_file" && -f "$existing_file" ]]; then
    while IFS='|' read -r _ k t ti s _rest; do
      k="$(printf '%s' "$k" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
      t="$(printf '%s' "$t" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
      ti="$(printf '%s' "$ti" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
      s="$(printf '%s' "$s" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
      if [[ -n "$k" && "$k" != "Key" ]]; then
        last_type["$k"]="$t"
        last_title["$k"]="$ti"
        last_status["$k"]="$s"
      fi
    done < <(grep '^|' "$existing_file" || true)
  fi

  _fmt_row() {
    local row_key="$1" row_type="$2" row_title="$3" row_status="$4"
    local norm
    norm="$(normalize_title "$row_title")"
    printf '| %s | %s | %s | %s |\n' "$row_key" "$row_type" "$norm" "$row_status"
  }

  {
    printf '# Statuses\n'
    printf '\n'
    printf '| Key | Type | Title | Status |\n'
    printf '|-----|------|-------|--------|\n'

    # Parent row
    local p_key p_type p_title p_status
    p_key="$(printf '%s' "$parent_json"    | jq -r '.key')"
    p_type="$(printf '%s' "$parent_json"   | jq -r '.type')"
    p_title="$(printf '%s' "$parent_json"  | jq -r '.title')"
    p_status="$(printf '%s' "$parent_json" | jq -r '.status')"
    _fmt_row "$p_key" "$p_type" "$p_title" "$p_status"

    # Subtask rows
    printf '%s' "$subtasks_json" | jq -r '.[] | @base64' | while IFS= read -r encoded; do
      sub="$(printf '%s' "$encoded" | base64 -d)"
      s_key="$(printf '%s' "$sub"    | jq -r '.key')"
      s_type="$(printf '%s' "$sub"   | jq -r '.type')"
      s_title="$(printf '%s' "$sub"  | jq -r '.title')"
      s_status="$(printf '%s' "$sub" | jq -r '.status')"

      # Carry forward last-known values for failed subtasks (empty fields)
      if [[ -z "$s_type"   || "$s_type"   == "null" ]]; then s_type="${last_type["$s_key"]:-}";   fi
      if [[ -z "$s_title"  || "$s_title"  == "null" ]]; then s_title="${last_title["$s_key"]:-}";  fi
      if [[ -z "$s_status" || "$s_status" == "null" ]]; then s_status="${last_status["$s_key"]:-}"; fi

      _fmt_row "$s_key" "$s_type" "$s_title" "$s_status"
    done
  } > "$out_file"
}
