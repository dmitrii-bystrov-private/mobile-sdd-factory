#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/verification_context.sh
source "$SCRIPT_DIR/lib/verification_context.sh"

KEY="${1:?Usage: run-build.sh <TASK-KEY>}"
if [[ "$KEY" == QA-* ]]; then
    echo "QA verification uses identified app artifacts from E2E_BUILD_ROOT or the task's explicit app selection." >&2
    exit 1
fi
REPO_DIR="$(verification_resolve_repo_dir "$KEY")"

cd "$REPO_DIR"

if verification_is_ios_repo "$REPO_DIR"; then
    bash "$SCRIPT_DIR/ios-prepare.sh" "$KEY"
    bash "$SCRIPT_DIR/ios-build.sh" "$KEY"
else
    bash "$SCRIPT_DIR/android-prepare.sh" "$KEY"
    bash "$SCRIPT_DIR/android-build.sh" "$KEY"
fi
