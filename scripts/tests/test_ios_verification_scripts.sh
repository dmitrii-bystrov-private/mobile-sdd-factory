#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

export SDD_WORKDIR="$WORKDIR"
export TESTING_DEVICE_ID="SIM-123"

KEY="IOS-TEST-VERIFY"
TASK_ROOT="$WORKDIR/$KEY"
REPO_DIR="$TASK_ROOT/repo"
SPEC_DIR="$TASK_ROOT/spec"
TOOLS_DIR="$REPO_DIR/Tools/buildscripts"
mkdir -p "$REPO_DIR" "$SPEC_DIR" "$TOOLS_DIR"

cat >"$TOOLS_DIR/load-tuist-env.sh" <<'EOF'
#!/usr/bin/env bash
export LOADED_TUIST_ENV=1
EOF

XCODEBUILD_LOG="$WORKDIR/xcodebuild.log"
LOCK_CHECK_LOG="$WORKDIR/lock-check.log"
JQ_LOG="$WORKDIR/jq.log"
LINT_LOG="$WORKDIR/lint.log"

cat >"$WORKDIR/xcodebuild" <<EOF
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "\$*" >>"$XCODEBUILD_LOG"
if [[ " \$* " == *" test-without-building "* ]]; then
  if [[ ! -d "$SDD_WORKDIR/.locks/ios-simulator-SIM-123.lock" ]]; then
    echo "missing simulator lock during test-without-building" >&2
    exit 1
  fi
  if [[ ! -f "$SDD_WORKDIR/.locks/ios-simulator-SIM-123.lock/owner.pid" ]]; then
    echo "missing simulator lock owner pid" >&2
    exit 1
  fi
  printf 'locked %s\n' "\$*" >>"$LOCK_CHECK_LOG"
fi
exit 0
EOF
chmod +x "$WORKDIR/xcodebuild"

cat >"$WORKDIR/jq" <<'EOF'
#!/usr/bin/env python3
import json
import sys
from pathlib import Path

args = sys.argv[1:]
raw = False
if args and args[0] == "-r":
    raw = True
    args = args[1:]
expr = args[0]
path = Path(args[1])
payload = json.loads(path.read_text())

def out(value):
    if raw and isinstance(value, str):
        sys.stdout.write(value)
    else:
        sys.stdout.write(json.dumps(value))

if expr == '.test_selection.mode // "broad"':
    out(payload.get("test_selection", {}).get("mode", "broad"))
elif expr == '.test_selection.selectors[]? // empty':
    for item in payload.get("test_selection", {}).get("selectors", []):
        print(item)
elif expr == '.build_products_policy // "rebuild"':
    out(payload.get("build_products_policy", "rebuild"))
elif expr == '.impact_mapping.preferred_scheme // empty':
    out(payload.get("impact_mapping", {}).get("preferred_scheme", ""))
elif expr == '.phases[]? // empty':
    for item in payload.get("phases", []):
        print(item)
elif expr == '.prepare.policy // "required"':
    out(payload.get("prepare", {}).get("policy", "required"))
elif expr == '.mode // ""':
    out(payload.get("mode", ""))
elif expr == '.head // ""':
    out(payload.get("head", ""))
else:
    raise SystemExit(f"unsupported jq expr: {expr}")
EOF
chmod +x "$WORKDIR/jq"

cat >"$WORKDIR/git" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "rev-parse" && "${2:-}" == "HEAD" ]]; then
  printf 'abc123\n'
  exit 0
fi
exit 1
EOF
chmod +x "$WORKDIR/git"

cat >"$WORKDIR/run-lint.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "\$*" >>"$LINT_LOG"
EOF
chmod +x "$WORKDIR/run-lint.sh"

PATH="$WORKDIR:$PATH"

mkdir -p "$REPO_DIR/bin"
MISE_LOG="$WORKDIR/mise.log"
MISE_FAIL_ONCE_MARKER="$WORKDIR/mise-install-failed-once"
cat >"$REPO_DIR/bin/mise" <<EOF
#!/usr/bin/env bash
set -euo pipefail
printf '%s|LOADED_TUIST_ENV=%s\n' "\$*" "\${LOADED_TUIST_ENV:-}" >>"$MISE_LOG"
if [[ "\$*" == "exec -- tuist install" && ! -f "$MISE_FAIL_ONCE_MARKER" ]]; then
  touch "$MISE_FAIL_ONCE_MARKER"
  echo "error: Failed to find credentials for 'https://github.com' in keychain: status -128" >&2
  exit 1
fi
exit 0
EOF
chmod +x "$REPO_DIR/bin/mise"

cat >"$SPEC_DIR/verification-strategy.json" <<'EOF'
{
  "impact_mapping": {
    "preferred_scheme": "Finom"
  },
  "test_selection": {
    "mode": "broad",
    "selectors": []
  },
  "build_products_policy": "rebuild",
  "phases": [
    "build_for_testing",
    "test_without_building",
    "lint"
  ]
}
EOF

bash "$REPO_ROOT/scripts/ios-prepare.sh" "$KEY" >"$WORKDIR/prepare.stdout"
if [[ "$(grep -c 'exec -- tuist install|LOADED_TUIST_ENV=1' "$MISE_LOG")" -ne 2 ]]; then
  echo "tuist install should retry once after headless keychain failure" >&2
  cat "$MISE_LOG" >&2
  exit 1
fi
grep -q 'exec -- tuist generate --no-open|LOADED_TUIST_ENV=1' "$MISE_LOG"
grep -q 'keychain credential lookup; retrying once' "$WORKDIR/prepare.stdout"
grep -q 'IOS PREPARE SUCCEEDED' "$WORKDIR/prepare.stdout"
if [[ -e "$TASK_ROOT/tmp/verification/ios/logs/pod-install.log" ]]; then
  echo "pod install log should not be created for SPM-only iOS prepare" >&2
  exit 1
fi

bash "$REPO_ROOT/scripts/ios-test-without-building.sh" "$KEY" >"$WORKDIR/broad.stdout"
grep -q 'test-without-building' "$XCODEBUILD_LOG"
grep -q '^locked ' "$LOCK_CHECK_LOG"
if [[ -d "$SDD_WORKDIR/.locks/ios-simulator-SIM-123.lock" ]]; then
  echo "simulator lock should be released after test-without-building" >&2
  exit 1
fi
if grep -q -- '-only-testing:' "$XCODEBUILD_LOG"; then
  echo "unexpected only-testing selector in broad mode" >&2
  exit 1
fi

cat >"$SPEC_DIR/verification-strategy.json" <<'EOF'
{
  "impact_mapping": {
    "preferred_scheme": "Finom"
  },
  "test_selection": {
    "mode": "only_testing",
    "selectors": [
      "FinomTests/ObservationListServiceTests",
      "FinomTests/ObservationListViewModelTests"
    ]
  },
  "build_products_policy": "rebuild",
  "phases": [
    "test_without_building"
  ]
}
EOF

: >"$XCODEBUILD_LOG"
bash "$REPO_ROOT/scripts/ios-test-without-building.sh" "$KEY" >"$WORKDIR/targeted.stdout"
grep -q -- '-only-testing:FinomTests/ObservationListServiceTests' "$XCODEBUILD_LOG"
grep -q -- '-only-testing:FinomTests/ObservationListViewModelTests' "$XCODEBUILD_LOG"

cat >"$SPEC_DIR/verification-strategy.json" <<'EOF'
{
  "impact_mapping": {
    "preferred_scheme": "Finom"
  },
  "test_selection": {
    "mode": "broad",
    "selectors": []
  },
  "build_products_policy": "reuse_if_same_head",
  "phases": [
    "build_for_testing"
  ]
}
EOF

mkdir -p "$TASK_ROOT/tmp/verification/ios/derived-data/Build"
cat >"$TASK_ROOT/tmp/verification/ios/build-for-testing.marker.json" <<'EOF'
{"head":"abc123","policy":"reuse_if_same_head"}
EOF

: >"$XCODEBUILD_LOG"
bash "$REPO_ROOT/scripts/ios-build-for-testing.sh" "$KEY" >"$WORKDIR/reuse.stdout"
grep -q 'BUILD-FOR-TESTING REUSED' "$WORKDIR/reuse.stdout"
if [[ -s "$XCODEBUILD_LOG" ]]; then
  echo "xcodebuild should not run when build-for-testing is reusable" >&2
  exit 1
fi

cat >"$SPEC_DIR/verification-strategy.json" <<'EOF'
{
  "impact_mapping": {
    "preferred_scheme": "Finom"
  },
  "test_selection": {
    "mode": "broad",
    "selectors": []
  },
  "build_products_policy": "rebuild",
  "phases": [
    "build_for_testing",
    "test_without_building",
    "lint"
  ]
}
EOF

cat >"$WORKDIR/ios-build-for-testing.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
printf 'build-for-testing %s\n' "\$*" >>"$WORKDIR/phases.log"
EOF
chmod +x "$WORKDIR/ios-build-for-testing.sh"

cat >"$WORKDIR/ios-test-without-building.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
printf 'test-without-building %s\n' "\$*" >>"$WORKDIR/phases.log"
EOF
chmod +x "$WORKDIR/ios-test-without-building.sh"

mkdir -p "$WORKDIR/shims"
mkdir -p "$WORKDIR/shims/lib"
ln -s "$WORKDIR/ios-build-for-testing.sh" "$WORKDIR/shims/ios-build-for-testing.sh"
ln -s "$WORKDIR/ios-test-without-building.sh" "$WORKDIR/shims/ios-test-without-building.sh"
ln -s "$WORKDIR/run-lint.sh" "$WORKDIR/shims/run-lint.sh"
ln -s "$REPO_ROOT/scripts/lib/verification_context.sh" "$WORKDIR/shims/lib/verification_context.sh"

IOS_VERIFY_SHIM="$WORKDIR/ios-verify.sh"
sed "s|SCRIPT_DIR=.*|SCRIPT_DIR=\"$WORKDIR/shims\"|" "$REPO_ROOT/scripts/ios-verify.sh" >"$IOS_VERIFY_SHIM"
chmod +x "$IOS_VERIFY_SHIM"

: >"$WORKDIR/phases.log"
: >"$LINT_LOG"
bash "$IOS_VERIFY_SHIM" "$KEY"
grep -q '^build-for-testing IOS-TEST-VERIFY$' "$WORKDIR/phases.log"
grep -q '^test-without-building IOS-TEST-VERIFY$' "$WORKDIR/phases.log"
grep -q '^IOS-TEST-VERIFY$' "$LINT_LOG"

echo "ios verification script tests passed"
