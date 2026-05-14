#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BATCH_SCRIPT="$SCRIPT_DIR/../create-subtasks-batch.sh"

PASS=0
FAIL=0

assert_contains() {
  local name="$1" pattern="$2" file="$3"
  if grep -q -- "$pattern" "$file"; then
    echo "  PASS  $name"
    (( PASS++ )) || true
  else
    echo "  FAIL  $name"
    echo "        missing pattern: $pattern"
    echo "        file: $file"
    (( FAIL++ )) || true
  fi
}

assert_not_contains() {
  local name="$1" pattern="$2" file="$3"
  if grep -q -- "$pattern" "$file"; then
    echo "  FAIL  $name"
    echo "        unexpected pattern: $pattern"
    echo "        file: $file"
    (( FAIL++ )) || true
  else
    echo "  PASS  $name"
    (( PASS++ )) || true
  fi
}

setup_workspace() {
  TMP_ROOT="$(mktemp -d)"
  PLAN_DIR="$TMP_ROOT/plan"
  BIN_DIR="$TMP_ROOT/bin"
  mkdir -p "$PLAN_DIR" "$BIN_DIR"

  cat > "$PLAN_DIR/index.md" <<'EOF'
# Plan

| # | Task | Depends on | Status |
|---|------|------------|--------|
| 01 | [Alpha task](./01-alpha-task.md) | — | ☐ |
| 02 | [Beta task](./02-beta-task.md) | 01 | ☐ |
| 03 | [Gamma task](./03-gamma-task.md) | 02 | ☐ |
EOF

  cat > "$PLAN_DIR/01-alpha-task.md" <<'EOF'
# Alpha task
EOF

  cat > "$PLAN_DIR/02-beta-task.md" <<'EOF'
# Beta task
EOF

  cat > "$PLAN_DIR/03-gamma-task.md" <<'EOF'
# Gamma task
EOF

  cat > "$BIN_DIR/acli" <<'EOF'
#!/usr/bin/env bash
if [[ "$*" == *"workitem search"* ]]; then
  cat <<'JSON'
[
  {
    "fields": {
      "summary": "Beta task"
    }
  }
]
JSON
  exit 0
fi
exit 1
EOF

  cat > "$BIN_DIR/git" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF

  cat > "$TMP_ROOT/mock-create-subtask.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
LOG_FILE="${LOG_FILE:?}"
title=""
description=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --title)
      title="${2:-}"
      shift 2
      ;;
    --description)
      description="${2:-}"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done
printf '%s|%s\n' "$title" "$description" >> "$LOG_FILE"
printf 'IOS-9%02d\n' "$(wc -l < "$LOG_FILE" | tr -d ' ')"
EOF

  chmod +x "$BIN_DIR/acli" "$BIN_DIR/git" "$TMP_ROOT/mock-create-subtask.sh"
}

run_batch() {
  local output_file="$1"
  shift
  LOG_FILE="$TMP_ROOT/create.log" \
    PATH="$BIN_DIR:$PATH" \
    CREATE_SUBTASK_SCRIPT="$TMP_ROOT/mock-create-subtask.sh" \
    bash "$BATCH_SCRIPT" --parent IOS-12453 --plan-dir "$PLAN_DIR" "$@" >"$output_file"
}

echo "=== create-subtasks-batch tests ==="

setup_workspace
OUTPUT_ALL="$TMP_ROOT/output-all.txt"
run_batch "$OUTPUT_ALL"
assert_contains "default mode reads index" "Found 3 task(s) in $PLAN_DIR/index.md" "$OUTPUT_ALL"
assert_contains "default mode creates alpha" "Creating subtask 01: Alpha task" "$OUTPUT_ALL"
assert_contains "default mode skips existing beta" "Skipping subtask 02 (already exists): Beta task" "$OUTPUT_ALL"
assert_contains "default mode creates gamma" "Creating subtask 03: Gamma task" "$OUTPUT_ALL"
assert_contains "default mode logs alpha create" "Alpha task|$PLAN_DIR/01-alpha-task.md" "$TMP_ROOT/create.log"
assert_contains "default mode logs gamma create" "Gamma task|$PLAN_DIR/03-gamma-task.md" "$TMP_ROOT/create.log"
assert_not_contains "default mode does not call create for beta" "Beta task|$PLAN_DIR/02-beta-task.md" "$TMP_ROOT/create.log"
rm -rf "$TMP_ROOT"

setup_workspace
OUTPUT_SELECTED="$TMP_ROOT/output-selected.txt"
run_batch "$OUTPUT_SELECTED" --task-file ./03-gamma-task.md --task-file 01-alpha-task.md
assert_contains "selected mode reports explicit selection" "Selected 2 task file(s) explicitly" "$OUTPUT_SELECTED"
assert_contains "selected mode creates gamma first" "Creating subtask 01: Gamma task" "$OUTPUT_SELECTED"
assert_contains "selected mode creates alpha second" "Creating subtask 02: Alpha task" "$OUTPUT_SELECTED"
assert_not_contains "selected mode ignores beta from index" "Beta task" "$OUTPUT_SELECTED"
assert_contains "selected mode logs gamma path" "Gamma task|$PLAN_DIR/03-gamma-task.md" "$TMP_ROOT/create.log"
assert_contains "selected mode logs alpha path" "Alpha task|$PLAN_DIR/01-alpha-task.md" "$TMP_ROOT/create.log"
rm -rf "$TMP_ROOT"

echo ""
echo "Results: $PASS passed, $FAIL failed"
if (( FAIL > 0 )); then
  exit 1
fi
