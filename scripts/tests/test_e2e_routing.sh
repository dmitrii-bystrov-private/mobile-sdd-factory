#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEST_ROOT"' EXIT
mkdir -p "$TEST_ROOT/bin" "$TEST_ROOT/workdir/QA-100/repo"
export QA_TEST_ROOT="$TEST_ROOT"
export SDD_WORKDIR="$TEST_ROOT/workdir"
export E2E_DIR="$TEST_ROOT/workdir/QA-100/repo"
export PATH="$TEST_ROOT/bin:$PATH"

cat > "$TEST_ROOT/bin/twg" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$QA_TEST_ROOT/twg.log"
if [[ "$*" == *'workitem get'* ]]; then
  jq -n --arg status "$(cat "$QA_TEST_ROOT/status")" \
    '{key:"QA-100",fields:{summary:"Update mobile tests",issuetype:{name:"Story",subtask:false},status:{name:$status}}}'
elif [[ "$*" == *'--transition-id'* ]]; then
  case "$*" in
    *'--transition-id 1'*) echo 'IN PROGRESS QA' > "$QA_TEST_ROOT/status" ;;
    *'--transition-id 2'*) echo 'CODE REVIEW QA' > "$QA_TEST_ROOT/status" ;;
    *'--transition-id 3'*) echo 'Done' > "$QA_TEST_ROOT/status" ;;
  esac
  echo '{"data":{}}'
elif [[ "$*" == *'workitem transition'* ]]; then
  if [[ "${QA_TEST_MISSING_REVIEW:-0}" == 1 ]]; then
    echo '{"data":{"transitions":[{"id":"3","toName":"Resolved"}]}}'
  else
    echo '{"data":{"transitions":[{"id":"1","toName":"IN PROGRESS QA"},{"id":"2","toName":"CODE REVIEW QA"},{"id":"3","toName":"Done"}]}}'
  fi
else
  echo 'Unexpected Jira mutation' >&2
  exit 1
fi
SH
cat > "$TEST_ROOT/bin/glab" <<'SH'
#!/usr/bin/env bash
exit 1
SH
cat > "$TEST_ROOT/bin/git" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$QA_TEST_ROOT/git.log"
exec /usr/bin/git "$@"
SH
chmod +x "$TEST_ROOT/bin/"*

echo 'TO DO QA' > "$TEST_ROOT/status"
bash "$REPO_ROOT/scripts/send-to-test.sh" QA-100 > "$TEST_ROOT/output"
[[ "$(cat "$TEST_ROOT/status")" == 'CODE REVIEW QA' ]]
rg -q -- '--transition-id 1' "$TEST_ROOT/twg.log"
rg -q -- '--transition-id 2' "$TEST_ROOT/twg.log"
cp "$TEST_ROOT/twg.log" "$TEST_ROOT/first.log"
bash "$REPO_ROOT/scripts/send-to-test.sh" QA-100 > "$TEST_ROOT/output"
[[ "$(rg -c -- '--transition-id' "$TEST_ROOT/twg.log")" == 2 ]]

echo 'IN PROGRESS QA' > "$TEST_ROOT/status"
if QA_TEST_MISSING_REVIEW=1 bash "$REPO_ROOT/scripts/send-to-test.sh" QA-100 > "$TEST_ROOT/output" 2>&1; then
  echo 'QA delivery accepted a mobile Resolved fallback' >&2
  exit 1
fi
[[ "$(cat "$TEST_ROOT/status")" == 'IN PROGRESS QA' ]]
bash "$REPO_ROOT/scripts/complete-subtask.sh" QA-100 > "$TEST_ROOT/output"
[[ "$(cat "$TEST_ROOT/status")" == 'Done' ]]
if rg -q -- 'fields-json|workitem update|field update-metadata' "$TEST_ROOT/twg.log"; then
  echo 'QA transitions touched mobile resolution/fix-version fields' >&2
  exit 1
fi

git -C "$E2E_DIR" init -q -b feature/QA-100
git -C "$E2E_DIR" -c user.name=Acceptance -c user.email=acceptance@example.invalid commit -q --allow-empty -m baseline
if bash "$REPO_ROOT/scripts/create-mr.sh" QA-100 > "$TEST_ROOT/output" 2> "$TEST_ROOT/error"; then
  echo 'QA MR accepted absent verification receipts' >&2
  exit 1
fi
rg -q 'Cannot prepare QA merge request:.*e2e-verdict.json' "$TEST_ROOT/error"
if rg -q '(^| )push( |$)' "$TEST_ROOT/git.log"; then
  echo 'QA branch was pushed before evidence validation' >&2
  exit 1
fi
echo 'QA shell routing passed: transitions, idempotency, field isolation and pre-push gate.'
