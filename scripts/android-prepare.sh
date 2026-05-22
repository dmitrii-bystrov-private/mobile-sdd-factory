#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/verification_context.sh
source "$SCRIPT_DIR/lib/verification_context.sh"

KEY="${1:?Usage: android-prepare.sh <TASK-KEY>}"
REPO_DIR="$(verification_resolve_repo_dir "$KEY")"

cd "$REPO_DIR"
verification_prepare_android_context "$KEY"

PREPARE_LOG="$SDD_ANDROID_VERIFICATION_LOGS_PATH/gradle-prepare.log"
PREPARE_MARKER="$SDD_ANDROID_VERIFICATION_CONTEXT_ROOT/prepare.marker.json"
PREPARE_POLICY="required"

if policy_value="$(verification_strategy_json_value "$KEY" '.prepare.policy // "required"' 2>/dev/null)"; then
  PREPARE_POLICY="$policy_value"
fi

if [[ "$PREPARE_POLICY" == "reuse_if_available" && -f "$PREPARE_MARKER" ]]; then
  echo "✅ ANDROID PREPARE REUSED"
  exit 0
fi

if [[ ! -x ./gradlew ]]; then
  echo "❌ ANDROID PREPARE FAILED"
  echo "./gradlew is missing or not executable" >&2
  exit 1
fi

echo "⏳ Priming task-local Gradle context..."
if ! GRADLE_USER_HOME="$SDD_ANDROID_GRADLE_USER_HOME" ./gradlew --version >"$PREPARE_LOG" 2>&1; then
  echo "❌ ANDROID PREPARE FAILED"
  verification_print_failure_matches "$PREPARE_LOG" "FAILURE:|error:|Exception|What went wrong:"
  exit 1
fi

cat >"$PREPARE_MARKER" <<EOF
{"policy":"$PREPARE_POLICY","head":"$(git rev-parse HEAD 2>/dev/null || echo unknown)"}
EOF

echo "✅ ANDROID PREPARE SUCCEEDED"
