#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/verification_context.sh
source "$SCRIPT_DIR/lib/verification_context.sh"

KEY="${1:?Usage: android-build.sh <TASK-KEY>}"
REPO_DIR="$(verification_resolve_repo_dir "$KEY")"

cd "$REPO_DIR"
verification_prepare_android_context "$KEY"

BUILD_LOG="$SDD_ANDROID_VERIFICATION_LOGS_PATH/android-build.log"
BUILD_TASKS=()

while IFS= read -r task; do
  [[ -n "$task" ]] || continue
  BUILD_TASKS+=("$task")
done < <(verification_strategy_json_lines "$KEY" '.build_selection.gradle_build_tasks[]? // empty' 2>/dev/null || true)

if [[ "${#BUILD_TASKS[@]}" -eq 0 ]]; then
  echo "✅ ANDROID BUILD SKIPPED"
  exit 0
fi

echo "⏳ Building Android verification tasks..."
if GRADLE_USER_HOME="$SDD_ANDROID_GRADLE_USER_HOME" ./gradlew "${BUILD_TASKS[@]}" >"$BUILD_LOG" 2>&1; then
  echo "✅ ANDROID BUILD SUCCEEDED"
  exit 0
fi

echo "❌ ANDROID BUILD FAILED"
echo ""
verification_print_failure_matches "$BUILD_LOG" "FAILURE:|error:|Exception|What went wrong:|BUILD FAILED"
exit 1
