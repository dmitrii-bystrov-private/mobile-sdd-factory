#!/usr/bin/env bash
set -euo pipefail

# create-subtasks-batch.sh — Create Jira subtasks from a decomposition plan.
#
# Usage:
#   scripts/create-subtasks-batch.sh --parent <KEY> [--plan-dir <path-to-plan/>] [--task-file <file.md> ...]
#
# If --plan-dir is omitted, defaults to $SDD_WORKDIR/<KEY>/plan/
# If --task-file is omitted, all task files are read from plan/index.md in order.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CREATE_SUBTASK_SCRIPT="${CREATE_SUBTASK_SCRIPT:-$SCRIPT_DIR/create-subtask.sh}"

err() {
  echo "ERROR: $*" >&2
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || { err "Missing required command: $1"; exit 1; }
}

need_cmd acli
need_cmd jq
need_cmd git

PARENT=""
PLAN_DIR=""
declare -a SELECTED_TASK_FILES=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --parent)
      PARENT="${2:-}"
      shift 2
      ;;
    --plan-dir)
      PLAN_DIR="${2:-}"
      shift 2
      ;;
    --task-file)
      SELECTED_TASK_FILES+=("${2:-}")
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

if [[ -z "$PLAN_DIR" ]]; then
  if [[ -z "${SDD_WORKDIR:-}" ]]; then
    err "Missing --plan-dir and \$SDD_WORKDIR is not set"
    exit 1
  fi
  PLAN_DIR="$SDD_WORKDIR/$PARENT/plan"
fi

INDEX_FILE="$PLAN_DIR/index.md"

if [[ ! -f "$INDEX_FILE" ]]; then
  err "index.md not found at: $INDEX_FILE"
  exit 1
fi

declare -a TASK_FILES=()

if [[ ${#SELECTED_TASK_FILES[@]} -gt 0 ]]; then
  for task_file in "${SELECTED_TASK_FILES[@]}"; do
    if [[ -z "$task_file" ]]; then
      err "Empty value passed to --task-file"
      exit 1
    fi

    if [[ "$task_file" == /* ]]; then
      TASK_FILES+=("$task_file")
    else
      TASK_FILES+=("$PLAN_DIR/${task_file#./}")
    fi
  done
else
  declare -a INDEX_TASK_FILES=()
  mapfile -t INDEX_TASK_FILES < <(grep -oE '\(\./[^)]+\.md\)' "$INDEX_FILE" | tr -d '()') || true
  for task_file in "${INDEX_TASK_FILES[@]}"; do
    TASK_FILES+=("$PLAN_DIR/${task_file#./}")
  done
fi

if [[ ${#TASK_FILES[@]} -eq 0 ]]; then
  err "No task files selected"
  exit 1
fi

if [[ ${#SELECTED_TASK_FILES[@]} -gt 0 ]]; then
  echo "Selected ${#TASK_FILES[@]} task file(s) explicitly"
else
  echo "Found ${#TASK_FILES[@]} task(s) in $INDEX_FILE"
fi

echo "Fetching existing subtasks for $PARENT from Jira..."
EXISTING_TITLES_JSON="$(acli jira workitem search \
  --jql "parent = $PARENT ORDER BY key ASC" \
  --fields key,summary \
  --json --paginate 2>/dev/null)" || EXISTING_TITLES_JSON="[]"

EXISTING_TITLES="$(echo "$EXISTING_TITLES_JSON" | jq -r '.[].fields.summary' 2>/dev/null | tr '[:upper:]' '[:lower:]')" || EXISTING_TITLES=""

declare -a CREATED_KEYS
declare -a CREATED_TITLES
declare -a SKIPPED_TITLES

for i in "${!TASK_FILES[@]}"; do
  TASK_FILE="${TASK_FILES[$i]}"
  TASK_NUM="$(printf '%02d' $((i + 1)))"

  if [[ ! -f "$TASK_FILE" ]]; then
    err "Task file not found: $TASK_FILE (task $TASK_NUM)"
    exit 1
  fi

  TASK_TITLE="$(grep -m1 '^# ' "$TASK_FILE" | sed 's/^# //')"
  if [[ -z "$TASK_TITLE" ]]; then
    BASENAME="$(basename "$TASK_FILE" .md)"
    TASK_TITLE="$(echo "${BASENAME#[0-9][0-9]-}" | tr '-' ' ' | sed 's/\b\(.\)/\u\1/g')"
  fi

  TASK_TITLE_LOWER="$(echo "$TASK_TITLE" | tr '[:upper:]' '[:lower:]')"
  if echo "$EXISTING_TITLES" | grep -qxF "$TASK_TITLE_LOWER"; then
    echo "Skipping subtask $TASK_NUM (already exists): $TASK_TITLE"
    SKIPPED_TITLES+=("$TASK_TITLE")
    continue
  fi

  echo "Creating subtask $TASK_NUM: $TASK_TITLE"

  SUBTASK_KEY="$("$CREATE_SUBTASK_SCRIPT" \
    --parent "$PARENT" \
    --title "$TASK_TITLE" \
    --description "$TASK_FILE")" || {
    err "Failed to create subtask $TASK_NUM ($TASK_TITLE) from $TASK_FILE"
    exit 1
  }

  CREATED_KEYS+=("$SUBTASK_KEY")
  CREATED_TITLES+=("$TASK_TITLE")
  echo "  Created: $SUBTASK_KEY"
done

echo ""
if [[ ${#CREATED_KEYS[@]} -gt 0 ]]; then
  echo "Created subtasks:"
  for i in "${!CREATED_KEYS[@]}"; do
    TASK_NUM="$(printf '%02d' $((i + 1)))"
    printf '%-4s  %-12s  %s\n' "$TASK_NUM" "${CREATED_KEYS[$i]}" "${CREATED_TITLES[$i]}"
  done
else
  echo "No new subtasks created."
fi

if [[ ${#SKIPPED_TITLES[@]} -gt 0 ]]; then
  echo ""
  echo "Skipped (already exist in Jira):"
  for title in "${SKIPPED_TITLES[@]}"; do
    echo "  - $title"
  done
fi
