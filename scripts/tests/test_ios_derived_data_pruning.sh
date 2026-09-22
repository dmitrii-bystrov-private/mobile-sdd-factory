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
REMOVE_KEY="IOS-OLD"
FRESH_KEY="IOS-FRESH"

CURRENT_DD="$SDD_WORKDIR/$CURRENT_KEY/tmp/verification/ios/derived-data"
LOCKED_DD="$SDD_WORKDIR/$LOCKED_KEY/tmp/verification/ios/derived-data"
REMOVE_DD="$SDD_WORKDIR/$REMOVE_KEY/tmp/verification/ios/derived-data"
FRESH_DD="$SDD_WORKDIR/$FRESH_KEY/tmp/verification/ios/derived-data"

mkdir -p "$CURRENT_DD" "$LOCKED_DD" "$REMOVE_DD" "$FRESH_DD"
touch -t 202401010000 "$LOCKED_DD"
touch -t 202402010000 "$REMOVE_DD"
touch -t 202403010000 "$FRESH_DD"
touch -t 202404010000 "$CURRENT_DD"

LOCKED_LOCK_DIR="$(verification_ios_task_lock_dir "$LOCKED_KEY")"
mkdir -p "$LOCKED_LOCK_DIR"
printf '%s\n' "$$" >"$LOCKED_LOCK_DIR/owner.pid"

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
test ! -d "$REMOVE_DD"
test -d "$FRESH_DD"
grep -q "Skipping active iOS task cache: $LOCKED_KEY" "$WORKDIR/prune.stdout"
grep -q "Removed iOS DerivedData cache for $REMOVE_KEY" "$WORKDIR/prune.stdout"
grep -q "Disk space target reached: 60GB free" "$WORKDIR/prune.stdout"

echo "ios derived data pruning test passed"
