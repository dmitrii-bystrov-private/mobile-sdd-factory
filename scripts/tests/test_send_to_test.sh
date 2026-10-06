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
    IOS-CODEREVIEW)
      status="Code review"
      ;;
    IOS-RESOLVED)
      status="Resolved"
      ;;
    IOS-TESTDONE)
      status="TestDone"
      ;;
    IOS-INPROGRESS)
      status="In Progress"
      ;;
    IOS-REOPENED)
      status="Reopened"
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
  transition_key=""
  previous_arg=""
  for arg in "\$@"; do
    if [[ "\$previous_arg" == "--id" ]]; then
      transition_key="\$arg"
      break
    fi
    previous_arg="\$arg"
  done
  if [[ "\$transition_key" == "IOS-REOPENED" ]]; then
    cat <<'JSON'
{
  "data": {
    "transitions": [
      {
        "id": "121",
        "name": "Resolved",
        "toName": "Resolved"
      }
    ]
  }
}
JSON
    exit 0
  fi
  cat <<'JSON'
{
  "data": {
    "transitions": [
      {
        "id": "241",
        "name": "Ready for test",
        "toName": "Ready for test"
      },
      {
        "id": "271",
        "name": "Code review",
        "toName": "Code review"
      },
      {
        "id": "121",
        "name": "Resolved",
        "toName": "Resolved"
      },
      {
        "id": "221",
        "name": "In Progress",
        "toName": "In Progress"
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
if [[ "\$1 \$2 \$3" == "jira workitem transition" && "\$*" == *"--transition-id 271"* ]]; then
  cat <<'JSON'
{
  "ok": true
}
JSON
  exit 0
fi
if [[ "\$1 \$2 \$3" == "jira workitem transition" && "\$*" == *"--transition-id 121"* ]]; then
  if [[ "\$*" != *"--fields-json"* || "\$*" != *'"resolution":{"name":"Done"}'* ]]; then
    echo "resolved transition must set resolution" >&2
    printf '%s\n' "\$*" >&2
    exit 1
  fi
  if [[ "\$*" != *"IOS-REOPENED"* && "\$*" != *"Stories improvements"* ]]; then
    echo "resolved subtask transition must set Stories improvements fix version" >&2
    printf '%s\n' "\$*" >&2
    exit 1
  fi
  cat <<'JSON'
{
  "ok": true
}
JSON
  exit 0
fi
if [[ "\$1 \$2 \$3" == "jira workitem transition" && "\$*" == *"--transition-id 221"* ]]; then
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
grep -q "Already done: IOS-READY is already in code-review-or-later status: Ready for test" "$WORKDIR/ready.stdout"

PATH="$WORKDIR:$PATH" bash "$REPO_ROOT/scripts/send-to-test.sh" IOS-CODEREVIEW >"$WORKDIR/code-review.stdout"
grep -q "Already done: IOS-CODEREVIEW is already in code-review-or-later status: Code review" "$WORKDIR/code-review.stdout"

PATH="$WORKDIR:$PATH" bash "$REPO_ROOT/scripts/send-to-test.sh" IOS-TESTDONE >"$WORKDIR/testdone.stdout"
grep -q "Already done: IOS-TESTDONE is already in code-review-or-later status: TestDone" "$WORKDIR/testdone.stdout"

PATH="$WORKDIR:$PATH" bash "$REPO_ROOT/scripts/send-to-test.sh" IOS-INPROGRESS >"$WORKDIR/inprogress.stdout"
grep -q "Done: IOS-INPROGRESS → Code review" "$WORKDIR/inprogress.stdout"

PATH="$WORKDIR:$PATH" bash "$REPO_ROOT/scripts/send-to-test.sh" IOS-REOPENED >"$WORKDIR/reopened.stdout"
grep -q "Done: IOS-REOPENED → Resolved" "$WORKDIR/reopened.stdout"

PATH="$WORKDIR:$PATH" bash "$REPO_ROOT/scripts/complete-subtask.sh" IOS-RESOLVED >"$WORKDIR/subtask-resolved.stdout"
grep -q "Already done: IOS-RESOLVED is already in resolved-or-later status: Resolved" "$WORKDIR/subtask-resolved.stdout"

PATH="$WORKDIR:$PATH" bash "$REPO_ROOT/scripts/complete-subtask.sh" IOS-READY >"$WORKDIR/subtask-ready.stdout"
grep -q "Done: IOS-READY → Resolved" "$WORKDIR/subtask-ready.stdout"

PATH="$WORKDIR:$PATH" bash "$REPO_ROOT/scripts/complete-subtask.sh" IOS-TODO >"$WORKDIR/subtask-todo.stdout"
grep -q "Done: IOS-TODO → Resolved" "$WORKDIR/subtask-todo.stdout"

grep -q "jira workitem get IOS-READY --fields status -o json" "$TWG_LOG"
grep -q "jira workitem get IOS-CODEREVIEW --fields status -o json" "$TWG_LOG"
grep -q "jira workitem get IOS-TESTDONE --fields status -o json" "$TWG_LOG"
grep -q "jira workitem get IOS-REOPENED --fields status -o json" "$TWG_LOG"
grep -q "jira workitem transition --id IOS-INPROGRESS -o json" "$TWG_LOG"
grep -q "jira workitem transition --id IOS-INPROGRESS --transition-id 271 -o json" "$TWG_LOG"
grep -q "jira workitem transition --id IOS-REOPENED --transition-id 121 --fields-json" "$TWG_LOG"
grep -q "jira workitem get IOS-RESOLVED --fields status -o json" "$TWG_LOG"
grep -q "jira workitem transition --id IOS-READY --transition-id 121 --fields-json" "$TWG_LOG"
grep -q "jira workitem transition --id IOS-TODO --transition-id 221 -o json" "$TWG_LOG"
grep -q "jira workitem transition --id IOS-TODO --transition-id 121 --fields-json" "$TWG_LOG"
if grep -q "jira workitem update" "$TWG_LOG"; then
  echo "send-to-test.sh called update --status" >&2
  cat "$TWG_LOG" >&2
  exit 1
fi

echo "send-to-test transition tests passed"
