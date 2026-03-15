#!/usr/bin/env bash
# gen_golden.sh — Bootstrap script to (re)generate golden files from fixtures.
# Run once after changing formatter logic to update expected outputs.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../adf_to_md.sh"
source "$SCRIPT_DIR/../snapshot_formatters.sh"

FIXTURES="$SCRIPT_DIR/fixtures"
GOLDEN="$SCRIPT_DIR/golden"
mkdir -p "$GOLDEN"

# Helper: transform raw acli comments JSON into [{id, created, body_md}] array
_render_comments() {
  local raw_json="$1"
  local encoded_items
  encoded_items="$(printf '%s' "$raw_json" | jq -r '.fields.comment.comments // [] | .[] | @base64')"
  local result="["
  local first=true
  while IFS= read -r encoded; do
    [[ -n "$encoded" ]] || continue
    local comment id created body_adf body_md body_md_json
    comment="$(printf '%s' "$encoded" | base64 -d)"
    id="$(printf '%s' "$comment" | jq -r '.id')"
    created="$(printf '%s' "$comment" | jq -r '.created')"
    body_adf="$(printf '%s' "$comment" | jq '.body')"
    body_md="$(render_adf_to_markdown "$body_adf")"
    body_md_json="$(printf '%s' "$body_md" | jq -Rs .)"
    $first || result+=","
    result+="{\"id\":$(printf '%s' "$id" | jq -Rs .),\"created\":$(printf '%s' "$created" | jq -Rs .),\"body_md\":${body_md_json}}"
    first=false
  done < <(printf '%s\n' "$encoded_items")
  result+="]"
  printf '%s' "$result"
}

_desc_md() {
  local core_json="$1"
  local adf body_md
  adf="$(printf '%s' "$core_json" | jq '.fields.description')"
  body_md="$(render_adf_to_markdown "$adf")"
  printf '%s' "$body_md"
}

_write_desc() {
  local out="$1" core_json="$2"
  local body_md
  body_md="$(_desc_md "$core_json")"
  write_description_md "$out" \
    "$(printf '%s' "$core_json" | jq -r '.key')" \
    "$(printf '%s' "$core_json" | jq -r '.fields.issuetype.name')" \
    "$(printf '%s' "$core_json" | jq -r '.fields.summary')" \
    "$(printf '%s' "$core_json" | jq -r '.fields.status.name')" \
    "$body_md"
}

echo "Generating golden files..."

# --- parent (IOS-100) ---
PARENT_CORE="$(cat "$FIXTURES/parent_core.json")"
_write_desc "$GOLDEN/parent_description.md" "$PARENT_CORE"
echo "  parent_description.md"

PARENT_COMMENTS_JSON="$(_render_comments "$(cat "$FIXTURES/parent_comments.json")")"
write_comments_md "$GOLDEN/parent_comments.md" "$PARENT_COMMENTS_JSON"
echo "  parent_comments.md"

PARENT_STATUS_JSON="$(printf '%s' "$PARENT_CORE" | jq '{key:.key, type:.fields.issuetype.name, title:.fields.summary, status:.fields.status.name}')"
SUBTASKS_STATUS_JSON="$(jq 'map({key:.key, type:(.fields.issuetype.name//""), title:(.fields.summary//""), status:(.fields.status.name//"")})' "$FIXTURES/subtasks_list.json")"
write_statuses_md "$GOLDEN/statuses.md" "$PARENT_STATUS_JSON" "$SUBTASKS_STATUS_JSON"
echo "  statuses.md"

# --- subtask IOS-101 ---
SUB101_CORE="$(cat "$FIXTURES/subtask_IOS-101_core.json")"
_write_desc "$GOLDEN/subtask_IOS-101_description.md" "$SUB101_CORE"
echo "  subtask_IOS-101_description.md"

SUB101_COMMENTS_JSON="$(_render_comments "$(cat "$FIXTURES/subtask_IOS-101_comments.json")")"
write_comments_md "$GOLDEN/subtask_IOS-101_comments.md" "$SUB101_COMMENTS_JSON"
echo "  subtask_IOS-101_comments.md"

# --- subtask IOS-102 ---
SUB102_CORE="$(cat "$FIXTURES/subtask_IOS-102_core.json")"
_write_desc "$GOLDEN/subtask_IOS-102_description.md" "$SUB102_CORE"
echo "  subtask_IOS-102_description.md"

SUB102_COMMENTS_JSON="$(_render_comments "$(cat "$FIXTURES/subtask_IOS-102_comments.json")")"
write_comments_md "$GOLDEN/subtask_IOS-102_comments.md" "$SUB102_COMMENTS_JSON"
echo "  subtask_IOS-102_comments.md"

# --- zero-subtask (IOS-300) ---
PARENT300_CORE="$(cat "$FIXTURES/parent_core_zero_sub.json")"
PARENT300_STATUS_JSON="$(printf '%s' "$PARENT300_CORE" | jq '{key:.key, type:.fields.issuetype.name, title:.fields.summary, status:.fields.status.name}')"
write_statuses_md "$GOLDEN/statuses_zero_sub.md" "$PARENT300_STATUS_JSON" "[]"
echo "  statuses_zero_sub.md"

# --- title edge case (IOS-200) ---
PARENT200_CORE="$(cat "$FIXTURES/parent_core_title_edge.json")"
_write_desc "$GOLDEN/description_title_edge.md" "$PARENT200_CORE"
echo "  description_title_edge.md"

PARENT200_STATUS_JSON="$(printf '%s' "$PARENT200_CORE" | jq '{key:.key, type:.fields.issuetype.name, title:.fields.summary, status:.fields.status.name}')"
write_statuses_md "$GOLDEN/statuses_title_edge.md" "$PARENT200_STATUS_JSON" "[]"
echo "  statuses_title_edge.md"

echo "Done."
