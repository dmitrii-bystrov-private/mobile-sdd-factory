#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/verification_context.sh
source "$SCRIPT_DIR/lib/verification_context.sh"

KEY="${1:?Usage: android-build.sh <TASK-KEY>}"
REPO_DIR="$(verification_resolve_repo_dir "$KEY")"
REPO_BUILD_SCRIPT="$REPO_DIR/scripts/android-build.sh"

cd "$REPO_DIR"
verification_prepare_android_context "$KEY"

BUILD_LOG="$SDD_ANDROID_VERIFICATION_LOGS_PATH/android-build.log"
if [[ ! -x "$REPO_BUILD_SCRIPT" ]]; then
  echo "❌ ANDROID BUILD FAILED"
  echo ""
  echo "Missing repo-local Android build contract: $REPO_BUILD_SCRIPT"
  echo "Android verification expects the repository-owned build script and does not fall back to generic Gradle build tasks."
  exit 1
fi

echo "⏳ Building Android verification tasks..."
if bash "$REPO_BUILD_SCRIPT" >"$BUILD_LOG" 2>&1; then
  cat "$BUILD_LOG"
  exit 0
fi

cat "$BUILD_LOG"
exit 1
