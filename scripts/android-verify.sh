#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/verification_context.sh
source "$SCRIPT_DIR/lib/verification_context.sh"

KEY="${1:?Usage: android-verify.sh <TASK-KEY>}"
REPO_DIR="$(verification_resolve_repo_dir "$KEY")"

cd "$REPO_DIR"
verification_prepare_android_context "$KEY"

STRATEGY_PATH="$(verification_strategy_path "$KEY")"
if [[ ! -f "$STRATEGY_PATH" ]]; then
  echo "Missing verification strategy: $STRATEGY_PATH" >&2
  exit 1
fi

PHASES=()
while IFS= read -r phase; do
  [[ -n "$phase" ]] || continue
  PHASES+=("$phase")
done < <(verification_strategy_json_lines "$KEY" '.phases[]? // empty' 2>/dev/null || true)

if [[ "${#PHASES[@]}" -eq 0 ]]; then
  MODE="$(verification_strategy_json_value "$KEY" '.mode // ""' 2>/dev/null || echo "")"
  if [[ "$MODE" == "android_docs_only_skip" ]]; then
    echo "✅ ANDROID VERIFICATION SKIPPED (docs-only)"
    exit 0
  fi
  echo "Verification strategy has no phases: $STRATEGY_PATH" >&2
  exit 1
fi

for phase in "${PHASES[@]}"; do
  case "$phase" in
    prepare)
      bash "$SCRIPT_DIR/android-prepare.sh" "$KEY"
      ;;
    build)
      bash "$SCRIPT_DIR/android-build.sh" "$KEY"
      ;;
    test)
      bash "$SCRIPT_DIR/android-test.sh" "$KEY"
      ;;
    lint)
      bash "$SCRIPT_DIR/android-lint.sh" "$KEY"
      ;;
    *)
      echo "Unsupported Android verification phase: $phase" >&2
      exit 1
      ;;
  esac
done
