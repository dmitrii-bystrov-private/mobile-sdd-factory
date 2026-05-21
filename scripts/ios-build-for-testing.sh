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
  echo "✅ BUILD-FOR-TESTING SUCCEEDED"
  exit 0
fi

echo "❌ BUILD-FOR-TESTING FAILED"
echo ""
verification_print_failure_matches "$BUILD_LOG" "error:|fatal error:|Testing failed:|encountered an error"
exit 1
