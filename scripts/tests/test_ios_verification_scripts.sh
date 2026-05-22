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
JQ_LOG="$WORKDIR/jq.log"
LINT_LOG="$WORKDIR/lint.log"

cat >"$WORKDIR/xcodebuild" <<EOF
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "\$*" >>"$XCODEBUILD_LOG"
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

bash "$REPO_ROOT/scripts/ios-test-without-building.sh" "$KEY" >"$WORKDIR/broad.stdout"
grep -q 'test-without-building' "$XCODEBUILD_LOG"
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
