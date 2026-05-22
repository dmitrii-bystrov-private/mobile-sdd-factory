#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

export SDD_WORKDIR="$WORKDIR"

KEY="ANDR-TEST-VERIFY"
TASK_ROOT="$WORKDIR/$KEY"
REPO_DIR="$TASK_ROOT/repo"
SPEC_DIR="$TASK_ROOT/spec"
mkdir -p "$REPO_DIR" "$SPEC_DIR"

cat >"$REPO_DIR/gradlew" <<EOF
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "\$*" >>"$WORKDIR/gradle.log"
exit 0
EOF
chmod +x "$REPO_DIR/gradlew"

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

if expr == '.prepare.policy // "required"':
    out(payload.get("prepare", {}).get("policy", "required"))
elif expr == '.mode // ""':
    out(payload.get("mode", ""))
elif expr == '.phases[]? // empty':
    for item in payload.get("phases", []):
        print(item)
elif expr == '.build_selection.gradle_build_tasks[]? // empty':
    for item in payload.get("build_selection", {}).get("gradle_build_tasks", []):
        print(item)
elif expr == '.test_selection.gradle_test_tasks[]? // empty':
    for item in payload.get("test_selection", {}).get("gradle_test_tasks", []):
        print(item)
elif expr == '.test_selection.gradle_lint_tasks[]? // empty':
    for item in payload.get("test_selection", {}).get("gradle_lint_tasks", []):
        print(item)
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

PATH="$WORKDIR:$PATH"

cat >"$SPEC_DIR/verification-strategy.json" <<'EOF'
{
  "prepare": {
    "policy": "reuse_if_available"
  },
  "mode": "android_impacted_module_gate",
  "phases": [
    "prepare",
    "build",
    "test",
    "lint"
  ],
  "build_selection": {
    "gradle_build_tasks": [
      ":feature:payments:assemble"
    ]
  },
  "test_selection": {
    "gradle_test_tasks": [
      ":feature:payments:test"
    ],
    "gradle_lint_tasks": [
      ":feature:payments:lint"
    ]
  }
}
EOF

bash "$REPO_ROOT/scripts/android-prepare.sh" "$KEY" >"$WORKDIR/prepare.stdout"
grep -q 'ANDROID PREPARE SUCCEEDED' "$WORKDIR/prepare.stdout"
grep -q -- '--version' "$WORKDIR/gradle.log"

: >"$WORKDIR/gradle.log"
bash "$REPO_ROOT/scripts/android-build.sh" "$KEY" >"$WORKDIR/build.stdout"
grep -q ':feature:payments:assemble' "$WORKDIR/gradle.log"

: >"$WORKDIR/gradle.log"
bash "$REPO_ROOT/scripts/android-test.sh" "$KEY" >"$WORKDIR/test.stdout"
grep -q ':feature:payments:test' "$WORKDIR/gradle.log"

: >"$WORKDIR/gradle.log"
bash "$REPO_ROOT/scripts/android-lint.sh" "$KEY" >"$WORKDIR/lint.stdout"
grep -q ':feature:payments:lint' "$WORKDIR/gradle.log"

cat >"$SPEC_DIR/verification-strategy.json" <<'EOF'
{
  "prepare": {
    "policy": "reuse_if_available"
  },
  "mode": "android_docs_only_skip",
  "phases": []
}
EOF

bash "$REPO_ROOT/scripts/android-verify.sh" "$KEY" >"$WORKDIR/docs-only.stdout"
grep -q 'ANDROID VERIFICATION SKIPPED' "$WORKDIR/docs-only.stdout"

cat >"$SPEC_DIR/verification-strategy.json" <<'EOF'
{
  "prepare": {
    "policy": "reuse_if_available"
  },
  "mode": "android_impacted_module_gate",
  "phases": [
    "prepare",
    "build",
    "test",
    "lint"
  ],
  "build_selection": {
    "gradle_build_tasks": [
      ":feature:payments:assemble"
    ]
  },
  "test_selection": {
    "gradle_test_tasks": [
      ":feature:payments:test"
    ],
    "gradle_lint_tasks": [
      ":feature:payments:lint"
    ]
  }
}
EOF

cat >"$WORKDIR/android-build.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
printf 'build %s\n' "\$*" >>"$WORKDIR/phases.log"
EOF
chmod +x "$WORKDIR/android-build.sh"

cat >"$WORKDIR/android-test.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
printf 'test %s\n' "\$*" >>"$WORKDIR/phases.log"
EOF
chmod +x "$WORKDIR/android-test.sh"

cat >"$WORKDIR/android-lint.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
printf 'lint %s\n' "\$*" >>"$WORKDIR/phases.log"
EOF
chmod +x "$WORKDIR/android-lint.sh"

cat >"$WORKDIR/android-prepare.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
printf 'prepare %s\n' "\$*" >>"$WORKDIR/phases.log"
EOF
chmod +x "$WORKDIR/android-prepare.sh"

mkdir -p "$WORKDIR/shims/lib"
ln -s "$WORKDIR/android-build.sh" "$WORKDIR/shims/android-build.sh"
ln -s "$WORKDIR/android-test.sh" "$WORKDIR/shims/android-test.sh"
ln -s "$WORKDIR/android-lint.sh" "$WORKDIR/shims/android-lint.sh"
ln -s "$WORKDIR/android-prepare.sh" "$WORKDIR/shims/android-prepare.sh"
ln -s "$REPO_ROOT/scripts/lib/verification_context.sh" "$WORKDIR/shims/lib/verification_context.sh"

ANDROID_VERIFY_SHIM="$WORKDIR/android-verify.sh"
sed "s|SCRIPT_DIR=.*|SCRIPT_DIR=\"$WORKDIR/shims\"|" "$REPO_ROOT/scripts/android-verify.sh" >"$ANDROID_VERIFY_SHIM"
chmod +x "$ANDROID_VERIFY_SHIM"

: >"$WORKDIR/phases.log"
bash "$ANDROID_VERIFY_SHIM" "$KEY"
grep -q '^prepare ANDR-TEST-VERIFY$' "$WORKDIR/phases.log"
grep -q '^build ANDR-TEST-VERIFY$' "$WORKDIR/phases.log"
grep -q '^test ANDR-TEST-VERIFY$' "$WORKDIR/phases.log"
grep -q '^lint ANDR-TEST-VERIFY$' "$WORKDIR/phases.log"

echo "android verification script tests passed"
