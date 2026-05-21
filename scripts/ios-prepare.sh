#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/verification_context.sh
source "$SCRIPT_DIR/lib/verification_context.sh"

KEY="${1:?Usage: ios-prepare.sh <TASK-KEY>}"
REPO_DIR="$(verification_resolve_repo_dir "$KEY")"

cd "$REPO_DIR"
verification_prepare_ios_context "$KEY"
verification_source_ios_env "$REPO_DIR"

TUIST_LOG="$SDD_IOS_VERIFICATION_LOGS_PATH/tuist-generate.log"
POD_LOG="$SDD_IOS_VERIFICATION_LOGS_PATH/pod-install.log"

echo "⏳ Generating Tuist project..."
if ! mise exec -- tuist generate --no-open >"$TUIST_LOG" 2>&1; then
  echo "❌ TUIST GENERATE FAILED"
  verification_print_failure_matches "$TUIST_LOG" "error:|fatal:|failed|exception"
  exit 1
fi

echo "⏳ Installing pods..."
if ! pod install >"$POD_LOG" 2>&1; then
  echo "❌ POD INSTALL FAILED"
  verification_print_failure_matches "$POD_LOG" "error:|fatal:|failed|exception"
  exit 1
fi

echo "✅ IOS PREPARE SUCCEEDED"
