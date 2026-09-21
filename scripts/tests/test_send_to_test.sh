#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

TWG_LOG="$WORKDIR/twg.log"

cat >"$WORKDIR/twg" <<EOF
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "\$*" >>"$TWG_LOG"
if [[ "\$1 \$2 \$3" == "jira workitem get" ]]; then
  cat <<'JSON'
{
  "data": [
    {
      "key": "IOS-14098",
      "status": {
        "name": "Ready for test"
      }
    }
  ]
}
JSON
  exit 0
fi
if [[ "\$1 \$2 \$3" == "jira workitem update" ]]; then
  echo "send-to-test.sh must not update an issue that is already Ready for test" >&2
  exit 1
fi
exit 1
EOF
chmod +x "$WORKDIR/twg"

PATH="$WORKDIR:$PATH" bash "$REPO_ROOT/scripts/send-to-test.sh" IOS-14098 >"$WORKDIR/stdout.log"

grep -q "Already done: IOS-14098 is already Ready for test" "$WORKDIR/stdout.log"
grep -q "jira workitem get IOS-14098 --fields status -o json" "$TWG_LOG"
if grep -q "jira workitem update" "$TWG_LOG"; then
  echo "send-to-test.sh called update for an already-ready issue" >&2
  cat "$TWG_LOG" >&2
  exit 1
fi

echo "send-to-test idempotency test passed"
