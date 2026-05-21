#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

PLAN_DIR="$WORKDIR/plan"
mkdir -p "$PLAN_DIR"

cat >"$PLAN_DIR/index.md" <<'EOF'
# Example Decomposition

## Execution order

1. [Build typed cache registry core](./01-build-typed-cache-registry-core.md)
2. [Update mocks and regression coverage](./02-update-mocks-and-regression-coverage.md)
EOF

cat >"$PLAN_DIR/01-build-typed-cache-registry-core.md" <<'EOF'
# Build typed cache registry core
EOF

cat >"$PLAN_DIR/02-update-mocks-and-regression-coverage.md" <<'EOF'
# Update mocks and regression coverage
EOF

ACLl_LOG="$WORKDIR/acli.log"
CREATE_LOG="$WORKDIR/create.log"

cat >"$WORKDIR/acli" <<EOF
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "\$*" >>"$ACLl_LOG"
if [[ "\$1 \$2 \$3" == "jira workitem search" ]]; then
  printf '[]\n'
  exit 0
fi
exit 1
EOF
chmod +x "$WORKDIR/acli"

cat >"$WORKDIR/create-subtask.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "\$*" >>"$CREATE_LOG"
if [[ "\$1" != "--parent" ]]; then
  echo "bad args" >&2
  exit 1
fi
title=""
while [[ \$# -gt 0 ]]; do
  case "\$1" in
    --title)
      title="\$2"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done
case "\$title" in
  "Build typed cache registry core") echo "IOS-90001" ;;
  "Update mocks and regression coverage") echo "IOS-90002" ;;
  *) echo "UNKNOWN" ;;
esac
EOF
chmod +x "$WORKDIR/create-subtask.sh"

PATH="$WORKDIR:$PATH" \
CREATE_SUBTASK_SCRIPT="$WORKDIR/create-subtask.sh" \
bash "$REPO_ROOT/scripts/create-subtasks-batch.sh" --parent IOS-12345 --plan-dir "$PLAN_DIR" >"$WORKDIR/stdout.log"

grep -q 'Found 2 task(s)' "$WORKDIR/stdout.log"
grep -q 'IOS-90001' "$WORKDIR/stdout.log"
grep -q 'IOS-90002' "$WORKDIR/stdout.log"
grep -q -- '--title Build typed cache registry core' "$CREATE_LOG"
grep -q -- '--title Update mocks and regression coverage' "$CREATE_LOG"

echo "create-subtasks-batch parser test passed"
