#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/verification_context.sh
source "$SCRIPT_DIR/lib/verification_context.sh"

KEY="${1:?Usage: run-test.sh <TASK-KEY>}"
REPO_DIR="$(verification_resolve_repo_dir "$KEY")"

cd "$REPO_DIR"

if verification_is_ios_repo "$REPO_DIR"; then
    bash "$SCRIPT_DIR/ios-prepare.sh" "$KEY"
    bash "$SCRIPT_DIR/ios-build-for-testing.sh" "$KEY"
    bash "$SCRIPT_DIR/ios-test-without-building.sh" "$KEY"
else
    bash "$SCRIPT_DIR/android-prepare.sh" "$KEY"
    bash "$SCRIPT_DIR/android-test.sh" "$KEY"
fi
