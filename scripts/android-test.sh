#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/verification_context.sh
source "$SCRIPT_DIR/lib/verification_context.sh"

KEY="${1:?Usage: android-test.sh <TASK-KEY>}"
REPO_DIR="$(verification_resolve_repo_dir "$KEY")"
REPO_TEST_SCRIPT="$REPO_DIR/scripts/android-test.sh"

cd "$REPO_DIR"
verification_prepare_android_context "$KEY"

TEST_LOG="$SDD_ANDROID_VERIFICATION_LOGS_PATH/android-test.log"
if [[ ! -x "$REPO_TEST_SCRIPT" ]]; then
  echo "❌ ANDROID TEST FAILED"
  echo ""
  echo "Missing repo-local Android test contract: $REPO_TEST_SCRIPT"
  echo "Android verification expects the repository-owned test script and does not fall back to generic Gradle test tasks."
  exit 1
fi

echo "⏳ Running Android verification tests..."
if bash "$REPO_TEST_SCRIPT" >"$TEST_LOG" 2>&1; then
  cat "$TEST_LOG"
  exit 0
fi

cat "$TEST_LOG"
exit 1
