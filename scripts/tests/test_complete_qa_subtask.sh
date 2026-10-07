#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CHECK_ROOT="$(mktemp -d)"
trap 'rm -rf "$CHECK_ROOT"' EXIT
export CHECK_ROOT
cat >"$CHECK_ROOT/twg" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$CHECK_ROOT/calls"
state="$(cat "$CHECK_ROOT/status")"
if [[ "$1 $2 $3" == 'jira workitem get' ]]; then
  jq -nc --arg key "$4" --arg status "$state" '{data:[{key:$key,status:{name:$status}}]}'
elif [[ "$1 $2 $3" == 'jira workitem transition' && "$*" != *--transition-id* ]]; then
  case "$state" in
    'TO DO QA') id=4; target='IN PROGRESS QA';;
    'IN PROGRESS QA') id=41; target='CODE REVIEW QA';;
    'CODE REVIEW QA') id=101; target=Done;;
    *) echo 'Attempted to change a closed subtask' >&2; exit 1;;
  esac
  jq -nc --arg id "$id" --arg target "$target" '{data:{transitions:[{id:$id,name:$target,toName:$target}]}}'
else
  case "$state:$*" in
    'TO DO QA:'*'--transition-id 4'*) target='IN PROGRESS QA';;
    'IN PROGRESS QA:'*'--transition-id 41'*) target='CODE REVIEW QA';;
    'CODE REVIEW QA:'*'--transition-id 101'*) target=Done;;
    *) echo 'Wrong workflow step' >&2; exit 1;;
  esac
  printf '%s\n' "$target" >"$CHECK_ROOT/status"
  printf '{"ok":true}\n'
fi
SH
chmod +x "$CHECK_ROOT/twg"
for status in 'TO DO QA' 'IN PROGRESS QA' 'CODE REVIEW QA'; do
  printf '%s\n' "$status" >"$CHECK_ROOT/status"
  PATH="$CHECK_ROOT:$PATH" bash "$REPO_ROOT/scripts/complete-subtask.sh" QA-CHECK >"$CHECK_ROOT/result"
  [[ "$(cat "$CHECK_ROOT/status")" == Done ]]
done
for status in Done "Won't Do" 'Won’t Do' Closed Cancelled; do
  printf '%s\n' "$status" >"$CHECK_ROOT/status"
  : >"$CHECK_ROOT/calls"
  PATH="$CHECK_ROOT:$PATH" bash "$REPO_ROOT/scripts/complete-subtask.sh" QA-CHECK >"$CHECK_ROOT/result"
  [[ "$(cat "$CHECK_ROOT/status")" == "$status" ]]
  ! rg -q 'jira workitem transition' "$CHECK_ROOT/calls"
done
echo 'QA subtask completion passed: workflow steps, closed/cancelled no-op and idempotent retry.'
