#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/verification_context.sh
source "$SCRIPT_DIR/lib/verification_context.sh"

KEY="${1:?Usage: ios-build-for-testing.sh <TASK-KEY>}"
REPO_DIR="$(verification_resolve_repo_dir "$KEY")"

cd "$REPO_DIR"
verification_prepare_ios_context "$KEY"
verification_source_ios_env "$REPO_DIR"

BUILD_LOG="$SDD_IOS_VERIFICATION_LOGS_PATH/build-for-testing.log"
RESULT_BUNDLE="$SDD_IOS_XCRESULT_ROOT/build-for-testing.xcresult"
BUILD_MARKER="$SDD_IOS_VERIFICATION_CONTEXT_ROOT/build-for-testing.marker.json"
CURRENT_HEAD="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
BUILD_PRODUCTS_POLICY="rebuild"

if policy_value="$(verification_strategy_json_value "$KEY" '.build_products_policy // "rebuild"' 2>/dev/null)"; then
  BUILD_PRODUCTS_POLICY="$policy_value"
fi

if [[ "$BUILD_PRODUCTS_POLICY" == "reuse_if_same_head" && -f "$BUILD_MARKER" ]]; then
  MARKER_HEAD="$(jq -r '.head // ""' "$BUILD_MARKER" 2>/dev/null || echo "")"
  if [[ "$MARKER_HEAD" == "$CURRENT_HEAD" && -d "$SDD_IOS_DERIVED_DATA_PATH/Build" ]]; then
    echo "✅ BUILD-FOR-TESTING REUSED"
    exit 0
  fi
fi

rm -rf "$RESULT_BUNDLE"
echo "⏳ Building for testing with task-local Xcode context..."
if xcodebuild \
  -workspace Finom-Tuist.xcworkspace \
  -scheme Finom \
  -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath "$SDD_IOS_DERIVED_DATA_PATH" \
  -clonedSourcePackagesDirPath "$SDD_IOS_CLONED_SOURCE_PACKAGES_PATH" \
  -resultBundlePath "$RESULT_BUNDLE" \
  build-for-testing \
  CODE_SIGN_IDENTITY="" \
  CODE_SIGNING_REQUIRED=NO >"$BUILD_LOG" 2>&1; then
  cat >"$BUILD_MARKER" <<EOF
{"head":"$CURRENT_HEAD","policy":"$BUILD_PRODUCTS_POLICY"}
EOF
  echo "✅ BUILD-FOR-TESTING SUCCEEDED"
  exit 0
fi

echo "❌ BUILD-FOR-TESTING FAILED"
echo ""
verification_print_failure_matches "$BUILD_LOG" "error:|fatal error:|Testing failed:|encountered an error"
exit 1
