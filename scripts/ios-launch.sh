#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/verification_context.sh
source "$SCRIPT_DIR/lib/verification_context.sh"

KEY="${1:?Usage: ios-launch.sh <TASK-KEY>}"
REPO_DIR="$(verification_resolve_repo_dir "$KEY")"
SCHEME="$(verification_ios_scheme "$KEY")"
WORKSPACE="$(verification_ios_workspace "$REPO_DIR")"

cd "$REPO_DIR"
verification_prepare_ios_launch_context "$KEY"
verification_source_ios_env "$REPO_DIR"

DEVICE_ID="${IOS_RUN_DEVICE_ID:-${TESTING_DEVICE_ID:-}}"
if [[ -z "$DEVICE_ID" ]]; then
  echo "⚠️  IOS_RUN_DEVICE_ID is not set"
  echo ""
  echo "  Run the following to find your simulator ID:"
  echo "  xcrun simctl list devices available | grep iPhone"
  echo ""
  echo "  Then set a simulator for manual launches:"
  echo "  export IOS_RUN_DEVICE_ID=\"your-device-uuid\""
  exit 1
fi

command -v xcodebuild >/dev/null 2>&1 || { echo "Missing required command: xcodebuild" >&2; exit 1; }
command -v xcrun >/dev/null 2>&1 || { echo "Missing required command: xcrun" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "Missing required command: python3" >&2; exit 1; }

BUILD_LOG="$SDD_IOS_LAUNCH_LOGS_PATH/build.log"
SIMCTL_LOG="$SDD_IOS_LAUNCH_LOGS_PATH/simctl.log"
PRODUCTS_DIR="$SDD_IOS_LAUNCH_DERIVED_DATA_PATH/Build/Products/Debug-iphonesimulator"

echo "⏳ Building $SCHEME for iOS Simulator $DEVICE_ID..."
build_for_launch() {
  verification_prune_ios_derived_data_if_needed "$KEY"
  xcodebuild \
    -workspace "$WORKSPACE" \
    -scheme "$SCHEME" \
    -configuration Debug \
    -destination "platform=iOS Simulator,id=$DEVICE_ID" \
    -derivedDataPath "$SDD_IOS_LAUNCH_DERIVED_DATA_PATH" \
    -clonedSourcePackagesDirPath "$SDD_IOS_CLONED_SOURCE_PACKAGES_PATH" \
    build \
    CODE_SIGN_IDENTITY="" \
    CODE_SIGNING_REQUIRED=NO >"$BUILD_LOG" 2>&1
}

if ! verification_run_with_ios_task_lock "$KEY" build_for_launch; then
  echo "❌ IOS APP BUILD FAILED"
  verification_print_failure_matches "$BUILD_LOG" "error:|fatal error:|Testing failed:|encountered an error"
  exit 1
fi

resolve_app_path() {
  if [[ -n "${SDD_IOS_LAUNCH_APP_PATH:-}" ]]; then
    if [[ -d "$SDD_IOS_LAUNCH_APP_PATH" ]]; then
      printf '%s\n' "$SDD_IOS_LAUNCH_APP_PATH"
      return 0
    fi
    echo "SDD_IOS_LAUNCH_APP_PATH does not point to an .app directory: $SDD_IOS_LAUNCH_APP_PATH" >&2
    return 1
  fi

  local exact_app="$PRODUCTS_DIR/$SCHEME.app"
  if [[ -d "$exact_app" ]]; then
    printf '%s\n' "$exact_app"
    return 0
  fi

  local apps=()
  while IFS= read -r app_path; do
    apps+=("$app_path")
  done < <(find "$PRODUCTS_DIR" -maxdepth 1 -type d -name "*.app" -print 2>/dev/null | sort)

  if [[ "${#apps[@]}" -eq 1 ]]; then
    printf '%s\n' "${apps[0]}"
    return 0
  fi

  if [[ "${#apps[@]}" -eq 0 ]]; then
    echo "No .app bundle found under $PRODUCTS_DIR" >&2
  else
    echo "Multiple .app bundles found under $PRODUCTS_DIR; set SDD_IOS_LAUNCH_APP_PATH explicitly:" >&2
    printf '  %s\n' "${apps[@]}" >&2
  fi
  return 1
}

APP_PATH="$(resolve_app_path)"
BUNDLE_ID="$(python3 - "$APP_PATH/Info.plist" <<'PY'
import plistlib
import sys

with open(sys.argv[1], "rb") as handle:
    payload = plistlib.load(handle)
bundle_id = payload.get("CFBundleIdentifier")
if not bundle_id:
    raise SystemExit("CFBundleIdentifier is missing from app Info.plist")
print(bundle_id)
PY
)"

launch_app() {
  {
    echo "device=$DEVICE_ID"
    echo "app=$APP_PATH"
    echo "bundle_id=$BUNDLE_ID"
    xcrun simctl boot "$DEVICE_ID" || true
    xcrun simctl bootstatus "$DEVICE_ID" -b
    open -a Simulator --args -CurrentDeviceUDID "$DEVICE_ID" || true
    xcrun simctl install "$DEVICE_ID" "$APP_PATH"
    xcrun simctl terminate "$DEVICE_ID" "$BUNDLE_ID" || true
    xcrun simctl launch "$DEVICE_ID" "$BUNDLE_ID"
  } >"$SIMCTL_LOG" 2>&1
}

echo "⏳ Installing and launching $BUNDLE_ID on simulator $DEVICE_ID..."
if verification_run_with_ios_simulator_lock "$DEVICE_ID" launch_app; then
  echo "✅ IOS APP LAUNCHED"
  echo "Device: $DEVICE_ID"
  echo "Bundle: $BUNDLE_ID"
  exit 0
fi

echo "❌ IOS APP LAUNCH FAILED"
verification_print_failure_matches "$SIMCTL_LOG" "error:|failed|Unable|No such|Invalid"
exit 1
