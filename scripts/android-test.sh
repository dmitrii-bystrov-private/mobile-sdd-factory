#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/verification_context.sh
source "$SCRIPT_DIR/lib/verification_context.sh"

KEY="${1:?Usage: android-test.sh <TASK-KEY>}"
REPO_DIR="$(verification_resolve_repo_dir "$KEY")"

cd "$REPO_DIR"
verification_prepare_android_context "$KEY"

TEST_LOG="$SDD_ANDROID_VERIFICATION_LOGS_PATH/android-test.log"
TEST_TASKS=()

while IFS= read -r task; do
  [[ -n "$task" ]] || continue
  TEST_TASKS+=("$task")
done < <(verification_strategy_json_lines "$KEY" '.test_selection.gradle_test_tasks[]? // empty' 2>/dev/null || true)

if [[ "${#TEST_TASKS[@]}" -eq 0 ]]; then
  TEST_TASKS=("test")
fi

echo "⏳ Running Android verification tests..."
if GRADLE_USER_HOME="$SDD_ANDROID_GRADLE_USER_HOME" ./gradlew "${TEST_TASKS[@]}" >"$TEST_LOG" 2>&1; then
  echo "✅ ANDROID TEST SUCCEEDED"
  exit 0
fi

echo "❌ ANDROID TEST FAILED"
echo ""
verification_print_failure_matches "$TEST_LOG" "FAILURE:|error:|Exception|What went wrong:|FAILED|BUILD FAILED"
exit 1
