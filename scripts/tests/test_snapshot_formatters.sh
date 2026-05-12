#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../adf-to-md.sh"
source "$SCRIPT_DIR/../snapshot-formatters.sh"

FIXTURES="$SCRIPT_DIR/fixtures"
GOLDEN="$SCRIPT_DIR/golden"

# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

PASS=0
FAIL=0

assert_file_eq() {
  local name="$1" expected_file="$2" actual_file="$3"
  if diff -q "$expected_file" "$actual_file" > /dev/null 2>&1; then
    echo "  PASS  $name"
    (( PASS++ )) || true
  else
    echo "  FAIL  $name"
    diff "$expected_file" "$actual_file" | head -20 | sed 's/^/        /'
    (( FAIL++ )) || true
  fi
}

assert_eq() {
  local name="$1" expected="$2" actual="$3"
  if [[ "$expected" == "$actual" ]]; then
    echo "  PASS  $name"
    (( PASS++ )) || true
  else
    echo "  FAIL  $name"
    echo "        expected: $(printf '%s' "$expected" | head -3)"
    echo "        actual:   $(printf '%s' "$actual"   | head -3)"
    (( FAIL++ )) || true
  fi
}

# Helper: transform raw acli comments JSON into [{id, created, body_md}] array
_render_comments() {
  local raw_json="$1"
  local encoded_items
  encoded_items="$(printf '%s' "$raw_json" | jq -r '.fields.comment.comments // [] | .[] | @base64')"
  local result="["
  local first=true
  while IFS= read -r encoded || [[ -n "$encoded" ]]; do
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
  local adf
  adf="$(printf '%s' "$core_json" | jq '.fields.description')"
  render_adf_to_markdown "$adf"
}

_write_desc_to_tmp() {
  local core_json="$1"
  local out
  out="$(mktemp)"
  write_description_md "$out" \
    "$(printf '%s' "$core_json" | jq -r '.key')" \
    "$(printf '%s' "$core_json" | jq -r '.fields.issuetype.name')" \
    "$(printf '%s' "$core_json" | jq -r '.fields.summary')" \
    "$(printf '%s' "$core_json" | jq -r '.fields.status.name')" \
    "$(_desc_md "$core_json")"
  printf '%s' "$out"
}

# ---------------------------------------------------------------------------
# Load fixtures
# ---------------------------------------------------------------------------

PARENT_CORE="$(cat "$FIXTURES/parent_core.json")"
PARENT_COMMENTS_RAW="$(cat "$FIXTURES/parent_comments.json")"
SUBTASKS_LIST="$(cat "$FIXTURES/subtasks_list.json")"
SUB101_CORE="$(cat "$FIXTURES/subtask_IOS-101_core.json")"
SUB101_COMMENTS_RAW="$(cat "$FIXTURES/subtask_IOS-101_comments.json")"
SUB102_CORE="$(cat "$FIXTURES/subtask_IOS-102_core.json")"
SUB102_COMMENTS_RAW="$(cat "$FIXTURES/subtask_IOS-102_comments.json")"
PARENT300_CORE="$(cat "$FIXTURES/parent_core_zero_sub.json")"
PARENT200_CORE="$(cat "$FIXTURES/parent_core_title_edge.json")"

echo "=== Snapshot formatter golden-file tests ==="
echo ""

# ---------------------------------------------------------------------------
# description.md tests
# ---------------------------------------------------------------------------

echo "--- description.md ---"

tmp="$(_write_desc_to_tmp "$PARENT_CORE")"
assert_file_eq "parent description.md" "$GOLDEN/parent_description.md" "$tmp"
rm -f "$tmp"

tmp="$(_write_desc_to_tmp "$SUB101_CORE")"
assert_file_eq "subtask IOS-101 description.md" "$GOLDEN/subtask_IOS-101_description.md" "$tmp"
rm -f "$tmp"

tmp="$(_write_desc_to_tmp "$SUB102_CORE")"
assert_file_eq "subtask IOS-102 description.md (null description)" "$GOLDEN/subtask_IOS-102_description.md" "$tmp"
rm -f "$tmp"

# Title normalization: line breaks, extra spaces, pipe
tmp="$(_write_desc_to_tmp "$PARENT200_CORE")"
assert_file_eq "description.md: title with newline / spaces / pipe" "$GOLDEN/description_title_edge.md" "$tmp"
rm -f "$tmp"

# ---------------------------------------------------------------------------
# comments.md tests
# ---------------------------------------------------------------------------

echo ""
echo "--- comments.md ---"

tmp="$(mktemp)"
PARENT_COMMENTS_JSON="$(_render_comments "$PARENT_COMMENTS_RAW")"
write_comments_md "$tmp" "$PARENT_COMMENTS_JSON"
assert_file_eq "parent comments.md (2 comments incl. QA_HANDOFF)" "$GOLDEN/parent_comments.md" "$tmp"
rm -f "$tmp"

tmp="$(mktemp)"
SUB101_COMMENTS_JSON="$(_render_comments "$SUB101_COMMENTS_RAW")"
write_comments_md "$tmp" "$SUB101_COMMENTS_JSON"
assert_file_eq "subtask IOS-101 comments.md (empty)" "$GOLDEN/subtask_IOS-101_comments.md" "$tmp"
rm -f "$tmp"

tmp="$(mktemp)"
SUB102_COMMENTS_JSON="$(_render_comments "$SUB102_COMMENTS_RAW")"
write_comments_md "$tmp" "$SUB102_COMMENTS_JSON"
assert_file_eq "subtask IOS-102 comments.md (1 comment)" "$GOLDEN/subtask_IOS-102_comments.md" "$tmp"
rm -f "$tmp"

# ---------------------------------------------------------------------------
# statuses.md tests
# ---------------------------------------------------------------------------

echo ""
echo "--- statuses.md ---"

PARENT_STATUS_JSON="$(printf '%s' "$PARENT_CORE" | jq '{key:.key, type:.fields.issuetype.name, title:.fields.summary, status:.fields.status.name}')"
SUBTASKS_STATUS_JSON="$(printf '%s' "$SUBTASKS_LIST" | jq 'map({key:.key, type:(.fields.issuetype.name//""), title:(.fields.summary//""), status:(.fields.status.name//"")})')"

tmp="$(mktemp)"
write_statuses_md "$tmp" "$PARENT_STATUS_JSON" "$SUBTASKS_STATUS_JSON"
assert_file_eq "statuses.md (parent + 2 subtasks)" "$GOLDEN/statuses.md" "$tmp"
rm -f "$tmp"

# Zero subtasks: statuses.md must have exactly one data row
PARENT300_STATUS_JSON="$(printf '%s' "$PARENT300_CORE" | jq '{key:.key, type:.fields.issuetype.name, title:.fields.summary, status:.fields.status.name}')"
tmp="$(mktemp)"
write_statuses_md "$tmp" "$PARENT300_STATUS_JSON" "[]"
assert_file_eq "statuses.md (zero subtasks — single data row)" "$GOLDEN/statuses_zero_sub.md" "$tmp"
DATA_ROWS="$(grep -c '^| IOS-' "$tmp" || true)"
assert_eq "statuses.md zero-subtask: exactly one data row" "1" "$DATA_ROWS"
rm -f "$tmp"

# Title normalization in statuses.md
PARENT200_STATUS_JSON="$(printf '%s' "$PARENT200_CORE" | jq '{key:.key, type:.fields.issuetype.name, title:.fields.summary, status:.fields.status.name}')"
tmp="$(mktemp)"
write_statuses_md "$tmp" "$PARENT200_STATUS_JSON" "[]"
assert_file_eq "statuses.md: title with newline / spaces / pipe" "$GOLDEN/statuses_title_edge.md" "$tmp"
rm -f "$tmp"

# ---------------------------------------------------------------------------
# Determinism: running formatters twice on same fixture produces identical output
# ---------------------------------------------------------------------------

echo ""
echo "--- determinism ---"

tmp1="$(_write_desc_to_tmp "$PARENT_CORE")"
tmp2="$(_write_desc_to_tmp "$PARENT_CORE")"
assert_file_eq "description.md determinism (two runs identical)" "$tmp1" "$tmp2"
rm -f "$tmp1" "$tmp2"

tmp1="$(mktemp)"
tmp2="$(mktemp)"
write_comments_md "$tmp1" "$PARENT_COMMENTS_JSON"
write_comments_md "$tmp2" "$PARENT_COMMENTS_JSON"
assert_file_eq "comments.md determinism (two runs identical)" "$tmp1" "$tmp2"
rm -f "$tmp1" "$tmp2"

tmp1="$(mktemp)"
tmp2="$(mktemp)"
write_statuses_md "$tmp1" "$PARENT_STATUS_JSON" "$SUBTASKS_STATUS_JSON"
write_statuses_md "$tmp2" "$PARENT_STATUS_JSON" "$SUBTASKS_STATUS_JSON"
assert_file_eq "statuses.md determinism (two runs identical)" "$tmp1" "$tmp2"
rm -f "$tmp1" "$tmp2"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "Results: $PASS passed, $FAIL failed"
if (( FAIL > 0 )); then
  exit 1
fi
