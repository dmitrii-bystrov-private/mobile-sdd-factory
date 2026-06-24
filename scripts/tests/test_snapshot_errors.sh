#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SNAPSHOT="$SCRIPT_DIR/../snapshot.sh"
FIXTURES="$SCRIPT_DIR/fixtures"

PASS=0
FAIL=0

# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

assert_exit_nonzero() {
  local name="$1"; shift
  if "$@" > /dev/null 2>&1; then
    echo "  FAIL  $name (expected non-zero exit, got 0)"
    (( FAIL++ )) || true
  else
    echo "  PASS  $name"
    (( PASS++ )) || true
  fi
}

assert_exit_code() {
  local name="$1" expected="$2"; shift 2
  local actual=0
  "$@" > /dev/null 2>&1 || actual=$?
  if [[ "$actual" -eq "$expected" ]]; then
    echo "  PASS  $name"
    (( PASS++ )) || true
  else
    echo "  FAIL  $name (expected exit $expected, got $actual)"
    (( FAIL++ )) || true
  fi
}

assert_stderr_contains() {
  local name="$1" pattern="$2" stderr_file="$3"
  if grep -q "$pattern" "$stderr_file" 2>/dev/null; then
    echo "  PASS  $name"
    (( PASS++ )) || true
  else
    echo "  FAIL  $name (stderr does not contain '$pattern')"
    echo "        stderr: $(cat "$stderr_file" 2>/dev/null || echo '(empty)')"
    (( FAIL++ )) || true
  fi
}

assert_file_exists() {
  local name="$1" file="$2"
  if [[ -f "$file" ]]; then
    echo "  PASS  $name"
    (( PASS++ )) || true
  else
    echo "  FAIL  $name (expected file: $file)"
    (( FAIL++ )) || true
  fi
}

assert_no_files_under() {
  local name="$1" dir="$2"
  local count
  count="$(find "$dir" -type f 2>/dev/null | wc -l | tr -d ' ')"
  if [[ "$count" -eq 0 ]]; then
    echo "  PASS  $name"
    (( PASS++ )) || true
  else
    echo "  FAIL  $name (expected no files under $dir, found $count)"
    find "$dir" -type f | sed 's/^/        /'
    (( FAIL++ )) || true
  fi
}

assert_no_such_file() {
  local name="$1" file="$2"
  if [[ ! -f "$file" ]]; then
    echo "  PASS  $name"
    (( PASS++ )) || true
  else
    echo "  FAIL  $name (file should not exist: $file)"
    (( FAIL++ )) || true
  fi
}

# ---------------------------------------------------------------------------
# Mock setup helpers
# ---------------------------------------------------------------------------

# Create a temp workspace and populate mock_bin with fake git and acli.
# Sets globals: TMP_ROOT, MOCK_WORKDIR, MOCK_IOS_DIR, MOCK_BIN, MOCK_FIXTURES.
setup_workspace() {
  TMP_ROOT="$(mktemp -d)"
  MOCK_WORKDIR="$TMP_ROOT/workdir"
  MOCK_IOS_DIR="$TMP_ROOT/ios"
  MOCK_BIN="$TMP_ROOT/bin"
  MOCK_FIXTURES="$TMP_ROOT/fixtures"
  mkdir -p "$MOCK_WORKDIR" "$MOCK_IOS_DIR" "$MOCK_BIN" "$MOCK_FIXTURES"
  trap 'rm -rf "$TMP_ROOT"' RETURN

  # Populate mock fixtures (key-named copies for mock acli lookup)
  cp "$FIXTURES/parent_core.json"            "$MOCK_FIXTURES/IOS-100_core.json"
  cp "$FIXTURES/parent_comments.json"        "$MOCK_FIXTURES/IOS-100_comments.json"
  cp "$FIXTURES/subtasks_list.json"          "$MOCK_FIXTURES/subtasks_list.json"
  cp "$FIXTURES/subtask_IOS-101_core.json"   "$MOCK_FIXTURES/IOS-101_core.json"
  cp "$FIXTURES/subtask_IOS-101_comments.json" "$MOCK_FIXTURES/IOS-101_comments.json"
  cp "$FIXTURES/subtask_IOS-102_core.json"   "$MOCK_FIXTURES/IOS-102_core.json"
  cp "$FIXTURES/subtask_IOS-102_comments.json" "$MOCK_FIXTURES/IOS-102_comments.json"
}

# Write a mock git that always reports the worktree already exists.
write_mock_git() {
  cat > "$MOCK_BIN/git" << 'EOF'
#!/usr/bin/env bash
case "$*" in
  *"rev-parse --is-inside-work-tree"*) echo "true"; exit 0 ;;
  *) exit 0 ;;
esac
EOF
  chmod +x "$MOCK_BIN/git"
}

# Write a mock acli. Modes:
#   fail_parent          — exit 1 immediately (before any output)
#   fail_subtask_IOS-102 — succeed for parent/IOS-101, fail for IOS-102
#   fail_transition      — fail only the optional transition to In Progress
#   succeed              — route all calls to fixture files
write_mock_acli() {
  local mode="${1:-succeed}" fixtures="${MOCK_FIXTURES}"
  cat > "$MOCK_BIN/acli" << EOF
#!/usr/bin/env bash
_MODE="${mode}"
_FIXTURES="${fixtures}"

# Extract the first argument matching a Jira key pattern
_KEY=""
for _arg in "\$@"; do
  [[ "\$_arg" =~ ^[A-Z]+-[0-9]+\$ ]] && _KEY="\$_arg" && break
done

case "\$_MODE" in
  fail_parent)
    echo "mock acli: parent retrieval failed" >&2
    exit 1
    ;;
  fail_transition)
    if echo "\$*" | grep -q "workitem transition"; then
      echo "mock acli: transition failed" >&2
      exit 1
    fi
    ;;
  fail_subtask_IOS-102)
    if [[ "\$_KEY" == "IOS-102" ]]; then
      echo "mock acli: subtask IOS-102 retrieval failed" >&2
      exit 1
    fi
    ;;
esac

# Route to fixture files
if echo "\$*" | grep -q "workitem view"; then
  if echo "\$*" | grep -q "comment"; then
    cat "\$_FIXTURES/\${_KEY}_comments.json"
  else
    cat "\$_FIXTURES/\${_KEY}_core.json"
  fi
elif echo "\$*" | grep -q "workitem search"; then
  cat "\$_FIXTURES/subtasks_list.json"
fi
EOF
  chmod +x "$MOCK_BIN/acli"
}

# Run snapshot.sh with the given extra env vars (key=value pairs after the key arg).
# Captures stderr to TMP_STDERR. Returns snapshot.sh exit code.
run_snapshot() {
  local key="$1"; shift
  TMP_STDERR="$(mktemp)"
  PATH="$MOCK_BIN:$PATH" \
    SDD_WORKDIR="$MOCK_WORKDIR" \
    IOS_DIR="$MOCK_IOS_DIR" \
    "$@" \
    bash "$SNAPSHOT" "$key" 2>"$TMP_STDERR" || true
  # Return the actual exit code
  PATH="$MOCK_BIN:$PATH" \
    SDD_WORKDIR="$MOCK_WORKDIR" \
    IOS_DIR="$MOCK_IOS_DIR" \
    "$@" \
    bash "$SNAPSHOT" "$key" > /dev/null 2>&1; echo $?
}

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

echo "=== Snapshot error-handling tests ==="
echo ""

# ---------------------------------------------------------------------------
# ENV validation: missing SDD_WORKDIR
# ---------------------------------------------------------------------------
echo "--- env validation ---"

STDERR="$(mktemp)"
if SDD_WORKDIR="" IOS_DIR="/tmp" bash "$SNAPSHOT" IOS-100 2>"$STDERR" > /dev/null; then
  echo "  FAIL  missing SDD_WORKDIR: expected non-zero exit"
  (( FAIL++ )) || true
else
  echo "  PASS  missing SDD_WORKDIR: exits non-zero"
  (( PASS++ )) || true
fi
assert_stderr_contains "missing SDD_WORKDIR: stderr mentions SDD_WORKDIR" "SDD_WORKDIR" "$STDERR"
rm -f "$STDERR"

# ENV validation: both IOS_DIR and ANDROID_DIR set is allowed
STDERR="$(mktemp)"
if SDD_WORKDIR="/tmp" IOS_DIR="/tmp/ios" ANDROID_DIR="/tmp/android" bash "$SNAPSHOT" IOS-100 > /dev/null 2>"$STDERR"; then
  echo "  PASS  both IOS_DIR+ANDROID_DIR set: supported"
  (( PASS++ )) || true
else
  echo "  FAIL  both dirs set: expected success"
  echo "        stderr: $(cat "$STDERR" 2>/dev/null || echo '(empty)')"
  (( FAIL++ )) || true
fi
rm -f "$STDERR"

# ENV validation: neither IOS_DIR nor ANDROID_DIR set
STDERR="$(mktemp)"
if SDD_WORKDIR="/tmp" IOS_DIR="" ANDROID_DIR="" bash "$SNAPSHOT" IOS-100 2>"$STDERR" > /dev/null; then
  echo "  FAIL  neither dir set: expected non-zero exit"
  (( FAIL++ )) || true
else
  echo "  PASS  neither IOS_DIR nor ANDROID_DIR: exits non-zero"
  (( PASS++ )) || true
fi
assert_stderr_contains "neither dir set: stderr mentions IOS_DIR"     "IOS_DIR"     "$STDERR"
rm -f "$STDERR"

# ---------------------------------------------------------------------------
# Parent retrieval failure: no artifacts written
# ---------------------------------------------------------------------------
echo ""
echo "--- parent retrieval failure ---"

TMP_ROOT="$(mktemp -d)"
MOCK_WORKDIR="$TMP_ROOT/workdir"
MOCK_IOS_DIR="$TMP_ROOT/ios"
MOCK_BIN="$TMP_ROOT/bin"
MOCK_FIXTURES="$TMP_ROOT/fixtures"
mkdir -p "$MOCK_WORKDIR" "$MOCK_IOS_DIR" "$MOCK_BIN" "$MOCK_FIXTURES"

cp "$FIXTURES/subtasks_list.json" "$MOCK_FIXTURES/"
write_mock_git
write_mock_acli "fail_parent"

STDERR="$(mktemp)"
if PATH="$MOCK_BIN:$PATH" SDD_WORKDIR="$MOCK_WORKDIR" IOS_DIR="$MOCK_IOS_DIR" \
    bash "$SNAPSHOT" IOS-100 > /dev/null 2>"$STDERR"; then
  echo "  FAIL  parent failure: expected non-zero exit"
  (( FAIL++ )) || true
else
  echo "  PASS  parent failure: exits non-zero"
  (( PASS++ )) || true
fi
assert_stderr_contains "parent failure: stderr mentions error" "ERROR" "$STDERR"
assert_no_files_under "parent failure: no snapshot artifacts written" "$MOCK_WORKDIR"
rm -f "$STDERR"
rm -rf "$TMP_ROOT"

# ---------------------------------------------------------------------------
# Transition failure: snapshot still renders artifacts
# ---------------------------------------------------------------------------
echo ""
echo "--- transition failure ---"

TMP_ROOT="$(mktemp -d)"
MOCK_WORKDIR="$TMP_ROOT/workdir"
MOCK_IOS_DIR="$TMP_ROOT/ios"
MOCK_BIN="$TMP_ROOT/bin"
MOCK_FIXTURES="$TMP_ROOT/fixtures"
mkdir -p "$MOCK_WORKDIR" "$MOCK_IOS_DIR" "$MOCK_BIN" "$MOCK_FIXTURES"

jq '.fields.status.name = "To Do" | .fields.issuetype.name = "Bug"' "$FIXTURES/parent_core.json" > "$MOCK_FIXTURES/IOS-100_core.json"
cp "$FIXTURES/parent_comments.json"        "$MOCK_FIXTURES/IOS-100_comments.json"
cp "$FIXTURES/subtasks_list.json"          "$MOCK_FIXTURES/subtasks_list.json"
cp "$FIXTURES/subtask_IOS-101_core.json"   "$MOCK_FIXTURES/IOS-101_core.json"
cp "$FIXTURES/subtask_IOS-101_comments.json" "$MOCK_FIXTURES/IOS-101_comments.json"
cp "$FIXTURES/subtask_IOS-102_core.json"   "$MOCK_FIXTURES/IOS-102_core.json"
cp "$FIXTURES/subtask_IOS-102_comments.json" "$MOCK_FIXTURES/IOS-102_comments.json"

write_mock_git
write_mock_acli "fail_transition"

STDERR="$(mktemp)"
ACTUAL_EXIT=0
PATH="$MOCK_BIN:$PATH" SDD_WORKDIR="$MOCK_WORKDIR" IOS_DIR="$MOCK_IOS_DIR" \
  bash "$SNAPSHOT" IOS-100 > /dev/null 2>"$STDERR" || ACTUAL_EXIT=$?
if [[ "$ACTUAL_EXIT" -eq 0 ]]; then
  echo "  PASS  transition failure: snapshot continues"
  (( PASS++ )) || true
else
  echo "  FAIL  transition failure: expected exit 0, got $ACTUAL_EXIT"
  echo "        stderr: $(cat "$STDERR" 2>/dev/null || echo '(empty)')"
  (( FAIL++ )) || true
fi
assert_stderr_contains "transition failure: warning logged" "could not transition IOS-100" "$STDERR"
assert_stderr_contains "transition failure: acli output logged" "mock acli: transition failed" "$STDERR"

WDIR="$MOCK_WORKDIR/IOS-100"
assert_file_exists "transition failure: parent description.md written" "$WDIR/description.md"
assert_file_exists "transition failure: parent comments.md written" "$WDIR/comments.md"
assert_file_exists "transition failure: IOS-101 description.md written" "$WDIR/IOS-101/description.md"
assert_file_exists "transition failure: IOS-102 description.md written" "$WDIR/IOS-102/description.md"

rm -f "$STDERR"
rm -rf "$TMP_ROOT"

# ---------------------------------------------------------------------------
# Subtask retrieval failure: partial success
# ---------------------------------------------------------------------------
echo ""
echo "--- subtask retrieval failure (IOS-102) ---"

TMP_ROOT="$(mktemp -d)"
MOCK_WORKDIR="$TMP_ROOT/workdir"
MOCK_IOS_DIR="$TMP_ROOT/ios"
MOCK_BIN="$TMP_ROOT/bin"
MOCK_FIXTURES="$TMP_ROOT/fixtures"
mkdir -p "$MOCK_WORKDIR" "$MOCK_IOS_DIR" "$MOCK_BIN" "$MOCK_FIXTURES"

cp "$FIXTURES/parent_core.json"            "$MOCK_FIXTURES/IOS-100_core.json"
cp "$FIXTURES/parent_comments.json"        "$MOCK_FIXTURES/IOS-100_comments.json"
cp "$FIXTURES/subtasks_list.json"          "$MOCK_FIXTURES/subtasks_list.json"
cp "$FIXTURES/subtask_IOS-101_core.json"   "$MOCK_FIXTURES/IOS-101_core.json"
cp "$FIXTURES/subtask_IOS-101_comments.json" "$MOCK_FIXTURES/IOS-101_comments.json"

write_mock_git
write_mock_acli "fail_subtask_IOS-102"

STDERR="$(mktemp)"
ACTUAL_EXIT=0
PATH="$MOCK_BIN:$PATH" SDD_WORKDIR="$MOCK_WORKDIR" IOS_DIR="$MOCK_IOS_DIR" \
  bash "$SNAPSHOT" IOS-100 > /dev/null 2>"$STDERR" || ACTUAL_EXIT=$?
if [[ "$ACTUAL_EXIT" -eq 2 ]]; then
  echo "  PASS  subtask failure: exits with code 2"
  (( PASS++ )) || true
else
  echo "  FAIL  subtask failure: expected exit 2, got $ACTUAL_EXIT"
  (( FAIL++ )) || true
fi
assert_stderr_contains "subtask failure: failed key reported" "IOS-102" "$STDERR"

WDIR="$MOCK_WORKDIR/IOS-100"
assert_file_exists  "subtask failure: parent description.md written"     "$WDIR/description.md"
assert_file_exists  "subtask failure: parent comments.md written"        "$WDIR/comments.md"
assert_file_exists  "subtask failure: IOS-101 description.md written"    "$WDIR/IOS-101/description.md"
assert_file_exists  "subtask failure: IOS-101 comments.md written"       "$WDIR/IOS-101/comments.md"
assert_no_such_file "subtask failure: IOS-102 description.md not written" "$WDIR/IOS-102/description.md"

rm -f "$STDERR"
rm -rf "$TMP_ROOT"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "Results: $PASS passed, $FAIL failed"
if (( FAIL > 0 )); then
  exit 1
fi
