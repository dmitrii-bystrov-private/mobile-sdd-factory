#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

export SDD_WORKDIR="$WORKDIR/workdir"
export IOS_MIN_FREE_DISK_GB=50
mkdir -p "$SDD_WORKDIR"

# shellcheck source=scripts/lib/verification_context.sh
source "$REPO_ROOT/scripts/lib/verification_context.sh"

CURRENT_KEY="IOS-CURRENT"
LOCKED_KEY="IOS-LOCKED"
PROTECTED_DEV_KEY="IOS-INPROGRESS"
PROTECTED_TEST_KEY="IOS-INTESTING"
REMOVE_KEY="IOS-CODEREVIEW"
FRESH_KEY="IOS-FRESH"

CURRENT_DD="$SDD_WORKDIR/$CURRENT_KEY/tmp/verification/ios/derived-data"
LOCKED_DD="$SDD_WORKDIR/$LOCKED_KEY/tmp/verification/ios/derived-data"
PROTECTED_DEV_DD="$SDD_WORKDIR/$PROTECTED_DEV_KEY/tmp/verification/ios/derived-data"
PROTECTED_TEST_DD="$SDD_WORKDIR/$PROTECTED_TEST_KEY/tmp/verification/ios/derived-data"
REMOVE_DD="$SDD_WORKDIR/$REMOVE_KEY/tmp/verification/ios/derived-data"
FRESH_DD="$SDD_WORKDIR/$FRESH_KEY/tmp/verification/ios/derived-data"

mkdir -p "$CURRENT_DD" "$LOCKED_DD" "$PROTECTED_DEV_DD" "$PROTECTED_TEST_DD" "$REMOVE_DD" "$FRESH_DD"
touch -t 202401010000 "$LOCKED_DD"
touch -t 202402010000 "$PROTECTED_DEV_DD"
touch -t 202403010000 "$PROTECTED_TEST_DD"
touch -t 202404010000 "$REMOVE_DD"
touch -t 202405010000 "$FRESH_DD"
touch -t 202406010000 "$CURRENT_DD"

LOCKED_LOCK_DIR="$(verification_ios_task_lock_dir "$LOCKED_KEY")"
mkdir -p "$LOCKED_LOCK_DIR"
printf '%s\n' "$$" >"$LOCKED_LOCK_DIR/owner.pid"

cat >"$WORKDIR/twg" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
key=""
previous=""
for arg in "$@"; do
  if [[ "$previous" == "get" ]]; then
    key="$arg"
    break
  fi
  previous="$arg"
done
status="To Do"
if [[ "$key" == "IOS-INPROGRESS" ]]; then
  status="In Progress"
elif [[ "$key" == "IOS-INTESTING" ]]; then
  status="In testing"
elif [[ "$key" == "IOS-CODEREVIEW" ]]; then
  status="Code review"
fi
cat <<JSON
{"data":[{"key":"$key","status":{"name":"$status"}}]}
JSON
EOF
chmod +x "$WORKDIR/twg"

export REMOVE_DD
cat >"$WORKDIR/df" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ -d "${REMOVE_DD:?}" ]]; then
  available_kb=$((10 * 1024 * 1024))
else
  available_kb=$((60 * 1024 * 1024))
fi
cat <<DF
Filesystem 1024-blocks Used Available Capacity Mounted on
/dev/disk-test 100000000 1 $available_kb 1% /tmp
DF
EOF
chmod +x "$WORKDIR/df"
PATH="$WORKDIR:$PATH"

verification_prune_ios_derived_data_if_needed "$CURRENT_KEY" >"$WORKDIR/prune.stdout"

test -d "$CURRENT_DD"
test -d "$LOCKED_DD"
test -d "$PROTECTED_DEV_DD"
test -d "$PROTECTED_TEST_DD"
test ! -d "$REMOVE_DD"
test ! -d "$(verification_ios_task_lock_dir "$REMOVE_KEY")"
test -d "$FRESH_DD"
grep -q "Skipping active iOS task cache: $LOCKED_KEY" "$WORKDIR/prune.stdout"
grep -q "Skipping active-work iOS task cache: $PROTECTED_DEV_KEY (In Progress)" "$WORKDIR/prune.stdout"
grep -q "Skipping active-work iOS task cache: $PROTECTED_TEST_KEY (In testing)" "$WORKDIR/prune.stdout"
grep -q "Removed iOS DerivedData cache for $REMOVE_KEY" "$WORKDIR/prune.stdout"
grep -q "Disk space target reached: 60GB free" "$WORKDIR/prune.stdout"

echo "ios derived data pruning test passed"

# Backend/client checks use only local status evidence and protect unfinished factory sessions.
mkdir -p "$REMOVE_DD"
printf '| Task | Title | Type | Status |\n| %s | task | Story | Code review |\n' "$REMOVE_KEY" > "$SDD_WORKDIR/$REMOVE_KEY/statuses.md"
printf '| Task | Title | Type | Status |\n| %s | task | Story | Code review |\n' "$FRESH_KEY" > "$SDD_WORKDIR/$FRESH_KEY/statuses.md"
cat >"$WORKDIR/twg" <<'EOF'
#!/usr/bin/env bash
echo 'local cleanup must not call Jira' >&2
exit 99
EOF
verification_prune_ios_derived_data_if_needed "$CURRENT_KEY" local "$FRESH_KEY" >"$WORKDIR/local-prune.stdout"
test ! -d "$REMOVE_DD"
test -d "$FRESH_DD"
test -d "$PROTECTED_DEV_DD"
test -d "$CURRENT_DD"
grep -q "Skipping active factory task cache: $FRESH_KEY" "$WORKDIR/local-prune.stdout"
grep -q "Skipping iOS cache with unknown task status: $PROTECTED_DEV_KEY" "$WORKDIR/local-prune.stdout"
echo "local disk pressure pruning test passed"
