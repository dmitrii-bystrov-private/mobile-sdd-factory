#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

export SDD_WORKDIR="$WORKDIR"
export GRADLE_USER_HOME="$WORKDIR/shared-gradle-home"

KEY="ANDR-TEST-VERIFY"
TASK_ROOT="$WORKDIR/$KEY"
REPO_DIR="$TASK_ROOT/repo"
SPEC_DIR="$TASK_ROOT/spec"
mkdir -p "$REPO_DIR" "$SPEC_DIR"
mkdir -p "$GRADLE_USER_HOME/caches/modules-2" "$GRADLE_USER_HOME/daemon"
printf '%s\n' 'seed-cache' >"$GRADLE_USER_HOME/caches/modules-2/seed.txt"
printf '%s\n' 'skip-daemon' >"$GRADLE_USER_HOME/daemon/daemon.log"

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
elif expr == '.test_selection.mode // "broad"':
    out(payload.get("test_selection", {}).get("mode", "broad"))
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

mkdir -p "$REPO_DIR/scripts"
cat >"$REPO_DIR/scripts/android-build.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' 'repo-build-targeted' >>"$WORKDIR/repo-script.log"
echo "✅ BUILD SUCCESSFUL"
EOF
chmod +x "$REPO_DIR/scripts/android-build.sh"

cat >"$REPO_DIR/scripts/android-test.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' 'repo-test-targeted' >>"$WORKDIR/repo-script.log"
echo "✅ TEST SUCCESSFUL"
EOF
chmod +x "$REPO_DIR/scripts/android-test.sh"

cat >"$REPO_DIR/scripts/android-lint.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' 'repo-lint-targeted' >>"$WORKDIR/repo-script.log"
echo "✅ LINT SUCCESSFUL"
EOF
chmod +x "$REPO_DIR/scripts/android-lint.sh"

bash "$REPO_ROOT/scripts/android-prepare.sh" "$KEY" >"$WORKDIR/prepare.stdout"
grep -q 'ANDROID PREPARE SUCCEEDED' "$WORKDIR/prepare.stdout"
grep -q 'Seeding task-local Gradle home' "$WORKDIR/prepare.stdout"
grep -q -- '--version' "$WORKDIR/gradle.log"
grep -q 'seed-cache' "$TASK_ROOT/tmp/verification/android/gradle-user-home/caches/modules-2/seed.txt"
test ! -e "$TASK_ROOT/tmp/verification/android/gradle-user-home/daemon/daemon.log"

: >"$WORKDIR/repo-script.log"
bash "$REPO_ROOT/scripts/android-build.sh" "$KEY" >"$WORKDIR/build.stdout"
grep -q '^repo-build-targeted$' "$WORKDIR/repo-script.log"

: >"$WORKDIR/repo-script.log"
bash "$REPO_ROOT/scripts/android-test.sh" "$KEY" >"$WORKDIR/test.stdout"
grep -q '^repo-test-targeted$' "$WORKDIR/repo-script.log"

: >"$WORKDIR/repo-script.log"
bash "$REPO_ROOT/scripts/android-lint.sh" "$KEY" >"$WORKDIR/lint.stdout"
grep -q '^repo-lint-targeted$' "$WORKDIR/repo-script.log"

cat >"$SPEC_DIR/verification-strategy.json" <<'EOF'
{
  "prepare": {
    "policy": "reuse_if_available"
  },
  "mode": "android_impacted_module_gate",
  "phases": [
    "prepare",
    "lint"
  ],
  "test_selection": {
    "mode": "targeted_tasks",
    "gradle_test_tasks": [
      ":feature:payments:test"
    ]
  }
}
EOF

rm -f "$REPO_DIR/scripts/android-build.sh"
if bash "$REPO_ROOT/scripts/android-build.sh" "$KEY" >"$WORKDIR/build-missing.stdout" 2>&1; then
  echo "expected android-build.sh to fail when repo-local build script is missing"
  exit 1
fi
grep -q 'Missing repo-local Android build contract' "$WORKDIR/build-missing.stdout"

cat >"$REPO_DIR/scripts/android-build.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' 'repo-build' >>"$WORKDIR/repo-script.log"
echo "✅ BUILD SUCCESSFUL"
EOF
chmod +x "$REPO_DIR/scripts/android-build.sh"

rm -f "$REPO_DIR/scripts/android-test.sh"
if bash "$REPO_ROOT/scripts/android-test.sh" "$KEY" >"$WORKDIR/test-missing.stdout" 2>&1; then
  echo "expected android-test.sh to fail when repo-local test script is missing"
  exit 1
fi
grep -q 'Missing repo-local Android test contract' "$WORKDIR/test-missing.stdout"

cat >"$REPO_DIR/scripts/android-test.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' 'repo-test' >>"$WORKDIR/repo-script.log"
echo "✅ TEST SUCCESSFUL"
EOF
chmod +x "$REPO_DIR/scripts/android-test.sh"

rm -f "$REPO_DIR/scripts/android-lint.sh"
if bash "$REPO_ROOT/scripts/android-lint.sh" "$KEY" >"$WORKDIR/lint-missing.stdout" 2>&1; then
  echo "expected android-lint.sh to fail when repo-local lint script is missing"
  exit 1
fi
grep -q 'Missing repo-local Android lint contract' "$WORKDIR/lint-missing.stdout"

cat >"$REPO_DIR/scripts/android-lint.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' 'repo-lint-broad' >>"$WORKDIR/repo-script.log"
echo "✅ LINT SUCCESSFUL"
EOF
chmod +x "$REPO_DIR/scripts/android-lint.sh"

cat >"$SPEC_DIR/verification-strategy.json" <<'EOF'
{
  "prepare": {
    "policy": "reuse_if_available"
  },
  "mode": "android_broad_safe_gate",
  "phases": [
    "prepare",
    "build",
    "test",
    "lint"
  ],
  "build_selection": {
    "mode": "skip",
    "gradle_build_tasks": []
  },
  "test_selection": {
    "mode": "broad",
    "gradle_test_tasks": [
      "test"
    ]
  }
}
EOF

: >"$WORKDIR/repo-script.log"
bash "$REPO_ROOT/scripts/android-build.sh" "$KEY" >"$WORKDIR/repo-build.stdout"
grep -q '^repo-build$' "$WORKDIR/repo-script.log"

: >"$WORKDIR/repo-script.log"
bash "$REPO_ROOT/scripts/android-test.sh" "$KEY" >"$WORKDIR/repo-test.stdout"
grep -q '^repo-test$' "$WORKDIR/repo-script.log"

: >"$WORKDIR/repo-script.log"
bash "$REPO_ROOT/scripts/android-lint.sh" "$KEY" >"$WORKDIR/repo-lint.stdout"
grep -q '^repo-lint-broad$' "$WORKDIR/repo-script.log"

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
