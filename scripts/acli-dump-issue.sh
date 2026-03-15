#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash scripts/acli-dump-issue.sh <ISSUE_KEY> [OUT_DIR]

Writes deterministic Jira JSON dumps via acli for:
  - parent core fields (key/type/summary/status/description)
  - parent comments (with id/author/created/updated/self)
  - subtask list (via JQL parent = KEY)
  - each subtask core fields + comments

Defaults:
  OUT_DIR = tmp/acli-dumps/<ISSUE_KEY>

Requires:
  - acli (authenticated)
  - jq
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || "${1:-}" == "" ]]; then
  usage
  exit 0
fi

ISSUE_KEY="$1"
OUT_DIR="${2:-tmp/acli-dumps/$ISSUE_KEY}"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 1; }
}
need_cmd acli
need_cmd jq

mkdir -p "$OUT_DIR"

dump_parent() {
  acli jira workitem view "$ISSUE_KEY" \
    --fields key,issuetype,summary,status,description \
    --json > "$OUT_DIR/parent.core.json"

  acli jira workitem view "$ISSUE_KEY" \
    --fields key,comment \
    --json > "$OUT_DIR/parent.comments.json"
}

dump_subtasks_list() {
  acli jira workitem search \
    --jql "parent = $ISSUE_KEY ORDER BY key ASC" \
    --fields key,issuetype,summary,status \
    --json --paginate > "$OUT_DIR/subtasks.list.json"
}

dump_one_subtask() {
  local key="$1"

  acli jira workitem view "$key" \
    --fields key,issuetype,summary,status,description \
    --json > "$OUT_DIR/subtask.${key}.core.json"

  acli jira workitem view "$key" \
    --fields key,comment \
    --json > "$OUT_DIR/subtask.${key}.comments.json"
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
        echo "WARN: $label comments truncated: total=$total maxResults=$max (acli workitem view does not paginate comments)" >&2
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
