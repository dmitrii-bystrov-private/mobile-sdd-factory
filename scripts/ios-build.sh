#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/verification_context.sh
source "$SCRIPT_DIR/lib/verification_context.sh"

KEY="${1:?Usage: ios-build.sh <TASK-KEY>}"
REPO_DIR="$(verification_resolve_repo_dir "$KEY")"
SCHEME="$(verification_ios_scheme "$KEY")"

cd "$REPO_DIR"
verification_prepare_ios_context "$KEY"
verification_source_ios_env "$REPO_DIR"

if [[ -z "${TESTING_DEVICE_ID:-}" ]]; then
  echo "⚠️  TESTING_DEVICE_ID is not set"
  echo ""
  echo "  Run the following to find your simulator ID:"
  echo "  xcrun simctl list devices available | grep iPhone"
  echo ""
  echo "  Then add to your ~/.zshrc or ~/.bashrc:"
  echo "  export TESTING_DEVICE_ID=\"your-device-uuid\""
  exit 1
fi

BUILD_LOG="$SDD_IOS_VERIFICATION_LOGS_PATH/build.log"
RESULT_BUNDLE="$SDD_IOS_XCRESULT_ROOT/build.xcresult"

rm -rf "$RESULT_BUNDLE"
echo "⏳ Building with task-local Xcode context..."
if xcodebuild \
  -workspace Finom-Tuist.xcworkspace \
  -scheme "$SCHEME" \
  -configuration Debug \
  -destination "platform=iOS Simulator,id=$TESTING_DEVICE_ID" \
  -derivedDataPath "$SDD_IOS_DERIVED_DATA_PATH" \
  -clonedSourcePackagesDirPath "$SDD_IOS_CLONED_SOURCE_PACKAGES_PATH" \
  -resultBundlePath "$RESULT_BUNDLE" \
  build \
  CODE_SIGN_IDENTITY="" \
  CODE_SIGNING_REQUIRED=NO >"$BUILD_LOG" 2>&1; then
  echo "✅ BUILD SUCCEEDED"
  exit 0
fi

echo "❌ BUILD FAILED"
echo ""
verification_print_failure_matches "$BUILD_LOG" "error:|fatal error:|Testing failed:|encountered an error"
exit 1
