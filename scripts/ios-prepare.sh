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
MISE_CMD="$(verification_resolve_mise_cmd "$REPO_DIR")"

TUIST_INSTALL_LOG="$SDD_IOS_VERIFICATION_LOGS_PATH/tuist-install.log"
TUIST_LOG="$SDD_IOS_VERIFICATION_LOGS_PATH/tuist-generate.log"
PREPARE_MARKER="$SDD_IOS_VERIFICATION_CONTEXT_ROOT/prepare.marker.json"
PREPARE_POLICY="required"

if policy_value="$(verification_strategy_json_value "$KEY" '.prepare.policy // "required"' 2>/dev/null)"; then
  PREPARE_POLICY="$policy_value"
fi

if [[ "$PREPARE_POLICY" == "reuse_if_available" && -f "$PREPARE_MARKER" ]]; then
  echo "✅ IOS PREPARE REUSED"
  exit 0
fi

echo "⏳ Installing Tuist SPM dependencies..."
if ! GIT_TERMINAL_PROMPT=0 "$MISE_CMD" exec -- tuist install >"$TUIST_INSTALL_LOG" 2>&1; then
  echo "❌ TUIST INSTALL FAILED"
  verification_print_failure_matches "$TUIST_INSTALL_LOG" "error:|fatal:|failed|exception"
  exit 1
fi

echo "⏳ Generating Tuist project..."
if ! "$MISE_CMD" exec -- tuist generate --no-open >"$TUIST_LOG" 2>&1; then
  echo "❌ TUIST GENERATE FAILED"
  verification_print_failure_matches "$TUIST_LOG" "error:|fatal:|failed|exception"
  exit 1
fi

cat >"$PREPARE_MARKER" <<EOF
{"policy":"$PREPARE_POLICY","head":"$(git rev-parse HEAD 2>/dev/null || echo unknown)"}
EOF

echo "✅ IOS PREPARE SUCCEEDED"
