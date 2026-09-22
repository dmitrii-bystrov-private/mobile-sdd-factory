#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/verification_context.sh
source "$SCRIPT_DIR/lib/verification_context.sh"

KEY="${1:?Usage: ios-test-without-building.sh <TASK-KEY>}"
REPO_DIR="$(verification_resolve_repo_dir "$KEY")"
SCHEME="$(verification_ios_scheme "$KEY")"
WORKSPACE="$(verification_ios_workspace "$REPO_DIR")"

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

TEST_LOG="$SDD_IOS_VERIFICATION_LOGS_PATH/test-without-building.log"
RESULT_BUNDLE="$SDD_IOS_XCRESULT_ROOT/test-without-building.xcresult"

rm -rf "$RESULT_BUNDLE"
echo "⏳ Running tests without rebuilding on device: $TESTING_DEVICE_ID..."
XCODEBUILD_CMD=(
  xcodebuild
  -workspace "$WORKSPACE"
  -scheme "$SCHEME"
  -destination "platform=iOS Simulator,id=$TESTING_DEVICE_ID"
  -derivedDataPath "$SDD_IOS_DERIVED_DATA_PATH"
  -clonedSourcePackagesDirPath "$SDD_IOS_CLONED_SOURCE_PACKAGES_PATH"
  -resultBundlePath "$RESULT_BUNDLE"
)
XCODEBUILD_CMD+=(
  test-without-building
  CODE_SIGN_IDENTITY=
  CODE_SIGNING_REQUIRED=NO
)

run_tests_without_building() {
  "${XCODEBUILD_CMD[@]}" >"$TEST_LOG" 2>&1
}

run_locked_tests_without_building() {
  verification_prune_ios_derived_data_if_needed "$KEY"
  verification_run_with_ios_simulator_lock "$TESTING_DEVICE_ID" run_tests_without_building
}

if verification_run_with_ios_task_lock "$KEY" run_locked_tests_without_building; then
    echo "✅ TEST SUCCEEDED"
    exit 0
fi

echo "❌ TEST FAILED"
echo ""
verification_print_failure_matches "$TEST_LOG" "error:|failed:|: FAILED|Testing failed:|encountered an error|Failed to (load|create|initialize)"
exit 1
