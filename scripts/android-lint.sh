#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/verification_context.sh
source "$SCRIPT_DIR/lib/verification_context.sh"

KEY="${1:?Usage: android-lint.sh <TASK-KEY>}"
REPO_DIR="$(verification_resolve_repo_dir "$KEY")"

cd "$REPO_DIR"
verification_prepare_android_context "$KEY"

LINT_LOG="$SDD_ANDROID_VERIFICATION_LOGS_PATH/android-lint.log"
LINT_TASKS=()

while IFS= read -r task; do
  [[ -n "$task" ]] || continue
  LINT_TASKS+=("$task")
done < <(verification_strategy_json_lines "$KEY" '.test_selection.gradle_lint_tasks[]? // empty' 2>/dev/null || true)

if [[ "${#LINT_TASKS[@]}" -eq 0 ]]; then
  LINT_TASKS=("lint")
fi

echo "⏳ Running Android lint..."
if GRADLE_USER_HOME="$SDD_ANDROID_GRADLE_USER_HOME" ./gradlew "${LINT_TASKS[@]}" >"$LINT_LOG" 2>&1; then
  echo "✅ ANDROID LINT SUCCEEDED"
  exit 0
fi

echo "❌ ANDROID LINT FAILED"
echo ""
verification_print_failure_matches "$LINT_LOG" "FAILURE:|error:|Exception|What went wrong:|FAILED|BUILD FAILED"
exit 1
