#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

export SDD_WORKDIR="$WORKDIR"
export IOS_RUN_DEVICE_ID="RUN-SIM-123"
export SDD_IOS_DEFAULT_SCHEME="CustomApp"
export SDD_IOS_WORKSPACE_NAME="CustomApp-Tuist.xcworkspace"

KEY="IOS-TEST-LAUNCH"
TASK_ROOT="$WORKDIR/$KEY"
REPO_DIR="$TASK_ROOT/repo"
TOOLS_DIR="$REPO_DIR/Tools/buildscripts"
mkdir -p "$REPO_DIR" "$TOOLS_DIR"

cat >"$TOOLS_DIR/load-tuist-env.sh" <<'EOF'
#!/usr/bin/env bash
export LOADED_TUIST_ENV=1
EOF

XCODEBUILD_LOG="$WORKDIR/xcodebuild.log"
XCRUN_LOG="$WORKDIR/xcrun.log"
OPEN_LOG="$WORKDIR/open.log"

cat >"$WORKDIR/xcodebuild" <<EOF
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "\$*" >>"$XCODEBUILD_LOG"
derived_data=""
while [[ \$# -gt 0 ]]; do
  case "\$1" in
    -derivedDataPath)
      derived_data="\$2"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done
if [[ -z "\$derived_data" ]]; then
  echo "missing derived data path" >&2
  exit 1
fi
app_dir="\$derived_data/Build/Products/Debug-iphonesimulator/CustomApp.app"
mkdir -p "\$app_dir"
cat >"\$app_dir/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key>
  <string>com.example.CustomApp</string>
</dict>
</plist>
PLIST
EOF
chmod +x "$WORKDIR/xcodebuild"

cat >"$WORKDIR/xcrun" <<EOF
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "\$*" >>"$XCRUN_LOG"
if [[ "\$1" != "simctl" ]]; then
  echo "expected simctl" >&2
  exit 1
fi
if [[ "\$2" == "install" || "\$2" == "launch" ]]; then
  if [[ ! -d "$SDD_WORKDIR/.locks/ios-simulator-RUN-SIM-123.lock" ]]; then
    echo "missing simulator lock during \$2" >&2
    exit 1
  fi
fi
exit 0
EOF
chmod +x "$WORKDIR/xcrun"

cat >"$WORKDIR/open" <<EOF
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "\$*" >>"$OPEN_LOG"
EOF
chmod +x "$WORKDIR/open"

PATH="$WORKDIR:$PATH" bash "$REPO_ROOT/scripts/ios-launch.sh" "$KEY" >"$WORKDIR/stdout.log"

grep -q 'IOS APP LAUNCHED' "$WORKDIR/stdout.log"
grep -q -- '-workspace CustomApp-Tuist.xcworkspace' "$XCODEBUILD_LOG"
grep -q -- '-scheme CustomApp' "$XCODEBUILD_LOG"
grep -q -- "-derivedDataPath $TASK_ROOT/tmp/verification/ios/derived-data" "$XCODEBUILD_LOG"
grep -q -- "-clonedSourcePackagesDirPath $TASK_ROOT/tmp/verification/ios/cloned-source-packages" "$XCODEBUILD_LOG"
test ! -d "$TASK_ROOT/tmp/launch/ios/derived-data"
grep -q 'simctl boot RUN-SIM-123' "$XCRUN_LOG"
grep -q 'simctl bootstatus RUN-SIM-123 -b' "$XCRUN_LOG"
grep -q 'simctl install RUN-SIM-123' "$XCRUN_LOG"
grep -q 'simctl terminate RUN-SIM-123 com.example.CustomApp' "$XCRUN_LOG"
grep -q 'simctl launch RUN-SIM-123 com.example.CustomApp' "$XCRUN_LOG"

if [[ -d "$SDD_WORKDIR/.locks/ios-simulator-RUN-SIM-123.lock" ]]; then
  echo "simulator lock should be released after launch" >&2
  exit 1
fi

echo "ios launch script test passed"
