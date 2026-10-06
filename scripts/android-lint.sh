#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/verification_context.sh
source "$SCRIPT_DIR/lib/verification_context.sh"

KEY="${1:?Usage: android-lint.sh <TASK-KEY>}"
REPO_DIR="$(verification_resolve_repo_dir "$KEY")"
REPO_LINT_SCRIPT="$REPO_DIR/scripts/android-lint.sh"

cd "$REPO_DIR"
verification_prepare_android_context "$KEY"

LINT_LOG="$SDD_ANDROID_VERIFICATION_LOGS_PATH/android-lint.log"
if [[ ! -x "$REPO_LINT_SCRIPT" ]]; then
  echo "❌ ANDROID LINT FAILED"
  echo ""
  echo "Missing repo-local Android lint contract: $REPO_LINT_SCRIPT"
  echo "Android verification expects the repository-owned ktlint/detekt script and does not fall back to Gradle lint tasks."
  exit 1
fi

echo "⏳ Running Android lint..."
if bash "$REPO_LINT_SCRIPT" >"$LINT_LOG" 2>&1; then
  cat "$LINT_LOG"
  exit 0
fi

cat "$LINT_LOG"
exit 1
