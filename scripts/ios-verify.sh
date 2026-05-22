#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/verification_context.sh
source "$SCRIPT_DIR/lib/verification_context.sh"

KEY="${1:?Usage: ios-verify.sh <TASK-KEY>}"
REPO_DIR="$(verification_resolve_repo_dir "$KEY")"

cd "$REPO_DIR"
verification_prepare_ios_context "$KEY"

STRATEGY_PATH="$(verification_strategy_path "$KEY")"
if [[ ! -f "$STRATEGY_PATH" ]]; then
  echo "Missing verification strategy: $STRATEGY_PATH" >&2
  exit 1
fi

mapfile -t PHASES < <(jq -r '.phases[]? // empty' "$STRATEGY_PATH")
if [[ "${#PHASES[@]}" -eq 0 ]]; then
  MODE="$(jq -r '.mode // ""' "$STRATEGY_PATH")"
  if [[ "$MODE" == "ios_docs_only_skip" ]]; then
    echo "✅ IOS VERIFICATION SKIPPED (docs-only)"
    exit 0
  fi
  echo "Verification strategy has no phases: $STRATEGY_PATH" >&2
  exit 1
fi

for phase in "${PHASES[@]}"; do
  case "$phase" in
    prepare)
      bash "$SCRIPT_DIR/ios-prepare.sh" "$KEY"
      ;;
    build)
      bash "$SCRIPT_DIR/ios-build.sh" "$KEY"
      ;;
    build_for_testing)
      bash "$SCRIPT_DIR/ios-build-for-testing.sh" "$KEY"
      ;;
    test_without_building)
      bash "$SCRIPT_DIR/ios-test-without-building.sh" "$KEY"
      ;;
    lint)
      bash "$SCRIPT_DIR/run-lint.sh" "$KEY"
      ;;
    *)
      echo "Unsupported iOS verification phase: $phase" >&2
      exit 1
      ;;
  esac
done
