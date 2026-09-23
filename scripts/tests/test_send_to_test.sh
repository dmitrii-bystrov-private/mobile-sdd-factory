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
  key="\$4"
  case "\$key" in
    IOS-READY)
      status="Ready for test"
      ;;
    IOS-TESTDONE)
      status="TestDone"
      ;;
    IOS-INPROGRESS)
      status="In Progress"
      ;;
    *)
      status="To Do"
      ;;
  esac
  cat <<JSON
{
  "data": [
    {
      "key": "\$key",
      "status": {
        "name": "\$status"
      }
    }
  ]
}
JSON
  exit 0
fi
if [[ "\$1 \$2 \$3" == "jira workitem transition" && "\$*" != *"--transition-id"* ]]; then
  cat <<'JSON'
{
  "data": {
    "transitions": [
      {
        "id": "241",
        "name": "Ready for test",
        "toName": "Ready for test"
      }
    ]
  }
}
JSON
  exit 0
fi
if [[ "\$1 \$2 \$3" == "jira workitem transition" && "\$*" == *"--transition-id 241"* ]]; then
  cat <<'JSON'
{
  "ok": true
}
JSON
  exit 0
fi
if [[ "\$1 \$2 \$3" == "jira workitem update" ]]; then
  echo "send-to-test.sh must not use update --status" >&2
  exit 1
fi
exit 1
EOF
chmod +x "$WORKDIR/twg"

PATH="$WORKDIR:$PATH" bash "$REPO_ROOT/scripts/send-to-test.sh" IOS-READY >"$WORKDIR/ready.stdout"
grep -q "Already done: IOS-READY is already in testing-or-later status: Ready for test" "$WORKDIR/ready.stdout"

PATH="$WORKDIR:$PATH" bash "$REPO_ROOT/scripts/send-to-test.sh" IOS-TESTDONE >"$WORKDIR/testdone.stdout"
grep -q "Already done: IOS-TESTDONE is already in testing-or-later status: TestDone" "$WORKDIR/testdone.stdout"

PATH="$WORKDIR:$PATH" bash "$REPO_ROOT/scripts/send-to-test.sh" IOS-INPROGRESS >"$WORKDIR/inprogress.stdout"
grep -q "Done: IOS-INPROGRESS → Ready for test" "$WORKDIR/inprogress.stdout"

grep -q "jira workitem get IOS-READY --fields status -o json" "$TWG_LOG"
grep -q "jira workitem get IOS-TESTDONE --fields status -o json" "$TWG_LOG"
grep -q "jira workitem transition --id IOS-INPROGRESS -o json" "$TWG_LOG"
grep -q "jira workitem transition --id IOS-INPROGRESS --transition-id 241 -o json" "$TWG_LOG"
if grep -q "jira workitem update" "$TWG_LOG"; then
  echo "send-to-test.sh called update --status" >&2
  cat "$TWG_LOG" >&2
  exit 1
fi

echo "send-to-test transition tests passed"
