#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/verification_context.sh
source "$SCRIPT_DIR/lib/verification_context.sh"

KEY="${1:?Usage: run-lint.sh <TASK-KEY>}"
REPO_DIR="$(verification_resolve_repo_dir "$KEY")"

cd "$REPO_DIR"

if verification_is_ios_repo "$REPO_DIR"; then
    verification_prepare_ios_context "$KEY"
    LINT_LOG="$SDD_IOS_VERIFICATION_LOGS_PATH/swiftlint.log"

    echo "⏳ Running SwiftLint..."
    if swiftlint lint --quiet >"$LINT_LOG" 2>&1; then
        echo "✅ SWIFTLINT SUCCEEDED"
        exit 0
    fi

    echo "❌ SWIFTLINT FAILED"
    echo ""
    cat "$LINT_LOG"
    exit 1
else
    bash scripts/android-lint.sh
fi
