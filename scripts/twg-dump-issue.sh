#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash scripts/twg-dump-issue.sh <ISSUE_KEY> [OUT_DIR]

Writes deterministic Jira JSON dumps via twg for:
  - parent core fields (key/type/summary/status/description)
  - parent comments (with id/author/created/updated/self)
  - subtask list (via JQL parent = KEY)
  - each subtask core fields + comments

Defaults:
  OUT_DIR = tmp/twg-dumps/<ISSUE_KEY>

Requires:
  - twg (authenticated)
  - jq
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || "${1:-}" == "" ]]; then
  usage
  exit 0
fi

ISSUE_KEY="$1"
OUT_DIR="${2:-tmp/twg-dumps/$ISSUE_KEY}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 1; }
}
need_cmd twg
need_cmd jq

# shellcheck source=./twg-utils.sh
source "$SCRIPT_DIR/twg-utils.sh"

mkdir -p "$OUT_DIR"

dump_parent() {
  twg_get_issue_legacy_json \
    "$OUT_DIR/parent.core.json" \
    "$ISSUE_KEY" \
    "key,issuetype,summary,status,description"

  twg_get_issue_legacy_json \
    "$OUT_DIR/parent.comments.json" \
    "$ISSUE_KEY" \
    "key,comment" \
    --comments
}

dump_subtasks_list() {
  twg_query_issues_legacy_json \
    "$OUT_DIR/subtasks.list.json" \
    "parent = $ISSUE_KEY ORDER BY key ASC" \
    "key,issuetype,summary,status"
}

dump_one_subtask() {
  local key="$1"

  twg_get_issue_legacy_json \
    "$OUT_DIR/subtask.${key}.core.json" \
    "$key" \
    "key,issuetype,summary,status,description"

  twg_get_issue_legacy_json \
    "$OUT_DIR/subtask.${key}.comments.json" \
    "$key" \
    "key,comment" \
    --comments
}

warn_if_comments_truncated() {
  local json_path="$1"
  local label="$2"

  local total max
  total="$(jq -r '.fields.comment.total // empty' "$json_path")"
  max="$(jq -r '.fields.comment.maxResults // empty' "$json_path")"

  if [[ -n "${total:-}" && -n "${max:-}" ]]; then
    if [[ "$total" != "null" && "$max" != "null" ]]; then
      if (( total > max )); then
        echo "WARN: $label comments truncated: total=$total maxResults=$max" >&2
      fi
    fi
  fi
}

echo "Dumping parent $ISSUE_KEY -> $OUT_DIR"
dump_parent
warn_if_comments_truncated "$OUT_DIR/parent.comments.json" "$ISSUE_KEY"

echo "Dumping subtasks list..."
dump_subtasks_list

subtask_count="$(jq -r 'length' "$OUT_DIR/subtasks.list.json")"
echo "Found $subtask_count subtasks"

if (( subtask_count > 0 )); then
  while IFS= read -r subkey; do
    [[ -n "$subkey" ]] || continue
    echo "Dumping subtask $subkey"
    dump_one_subtask "$subkey"
    warn_if_comments_truncated "$OUT_DIR/subtask.${subkey}.comments.json" "$subkey"
  done < <(jq -r '.[].key' "$OUT_DIR/subtasks.list.json")
fi

echo "Done. Files written under: $OUT_DIR"
