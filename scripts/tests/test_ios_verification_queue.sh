#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
QUEUE_ROOT="$(mktemp -d)"
first_pid=""
second_pid=""
cleanup() {
  touch "$QUEUE_ROOT/release"
  for queue_pid in "$first_pid" "$second_pid"; do
    if [[ -n "$queue_pid" ]]; then
      kill "$queue_pid" 2>/dev/null || true
      wait "$queue_pid" 2>/dev/null || true
    fi
  done
  rm -rf "$QUEUE_ROOT"
}
trap cleanup EXIT
export SDD_WORKDIR="$QUEUE_ROOT/workdir"
export TESTING_DEVICE_ID="SIM-QUEUE"
export SDD_IOS_DEFAULT_SCHEME="QueueApp"
export SDD_IOS_WORKSPACE_NAME="QueueApp.xcworkspace"
export QUEUE_ROOT
unset SDD_IOS_SIMULATOR_LOCK_ROOT SDD_IOS_TASK_LOCK_ROOT SDD_IOS_VERIFICATION_RUN_ID
mkdir -p "$QUEUE_ROOT/bin"
export PATH="$QUEUE_ROOT/bin:$PATH"
cat >"$QUEUE_ROOT/bin/git" <<'SH'
#!/usr/bin/env bash
printf 'queue-sha\n'
SH
cat >"$QUEUE_ROOT/bin/xcodebuild" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
key="IOS-QUEUE-2"
if [[ "$*" == *IOS-QUEUE-1* ]]; then key="IOS-QUEUE-1"; fi
printf 'start %s\n' "$key" >>"$QUEUE_ROOT/order"
if [[ "$key" == "IOS-QUEUE-1" ]]; then
  touch "$QUEUE_ROOT/first-started"
  while [[ ! -f "$QUEUE_ROOT/release" ]]; do sleep 0.05; done
fi
printf 'finish %s\n' "$key" >>"$QUEUE_ROOT/order"
if [[ -f "$QUEUE_ROOT/fail" ]]; then exit 65; fi
SH
chmod +x "$QUEUE_ROOT/bin/git" "$QUEUE_ROOT/bin/xcodebuild"
for index in 1 2; do
  queue_task="$SDD_WORKDIR/IOS-QUEUE-$index"
  mkdir -p "$queue_task/repo/Tools/buildscripts" "$queue_task/spec"
  printf '{"work_item_id":%s,"phases":["test_without_building"]}\n' "$index" >"$queue_task/spec/verification-strategy.json"
done

bash "$REPO_ROOT/scripts/ios-verify.sh" IOS-QUEUE-1 >"$QUEUE_ROOT/first.log" 2>&1 &
first_pid=$!
for _ in $(seq 1 200); do
  [[ -f "$QUEUE_ROOT/first-started" ]] && break
  sleep 0.05
done
[[ -f "$QUEUE_ROOT/first-started" ]]
bash "$REPO_ROOT/scripts/ios-verify.sh" IOS-QUEUE-2 >"$QUEUE_ROOT/second.log" 2>&1 &
second_pid=$!
for _ in $(seq 1 200); do
  if rg -q 'SDD_PROGRESS:.*Waiting for iOS simulator' "$QUEUE_ROOT/second.log"; then break; fi
  sleep 0.05
done
rg -q 'SDD_PROGRESS:.*Waiting for iOS simulator' "$QUEUE_ROOT/second.log"
! rg -q 'start IOS-QUEUE-2' "$QUEUE_ROOT/order"
PYTHONPATH="$REPO_ROOT" "$REPO_ROOT/.venv/bin/python" - <<'PY'
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
from factory.ios_verification_state import read_active_run
task = Path(os.environ['SDD_WORKDIR']) / 'IOS-QUEUE-2'
state = read_active_run(task, 2, datetime.now(UTC) - timedelta(minutes=1))
assert state and state['state'] == 'waiting_for_resource', state
assert state['phase'] == 'test_without_building'
assert state['resource']['name'] == 'iOS simulator SIM-QUEUE'
PY
touch "$QUEUE_ROOT/release"
wait "$first_pid"
first_pid=""
wait "$second_pid"
second_pid=""
expected=$'start IOS-QUEUE-1\nfinish IOS-QUEUE-1\nstart IOS-QUEUE-2\nfinish IOS-QUEUE-2'
[[ "$(cat "$QUEUE_ROOT/order")" == "$expected" ]]
[[ ! -d "$SDD_WORKDIR/.locks/ios-simulator-SIM-QUEUE.lock" ]]
touch "$QUEUE_ROOT/fail"
if bash "$REPO_ROOT/scripts/ios-verify.sh" IOS-QUEUE-2 >"$QUEUE_ROOT/failed.log" 2>&1; then
  echo 'Failed native command was reported as successful' >&2
  exit 1
fi
"$REPO_ROOT/.venv/bin/python" - <<'PY'
import json, os
from pathlib import Path
for key, code in [('IOS-QUEUE-1', 0), ('IOS-QUEUE-2', 1)]:
 state=json.loads((Path(os.environ['SDD_WORKDIR']) / key / 'tmp/verification/ios/execution-state.json').read_text())
 assert state['state'] == 'finished' and state['exit_code'] == code, state
PY
if bash -c 'source "$1/scripts/lib/verification_context.sh"; KEY=IOS-QUEUE-1; nested() { verification_run_with_ios_simulator_lock "$TESTING_DEVICE_ID" true; }; verification_run_with_ios_simulator_lock "$TESTING_DEVICE_ID" nested' _ "$REPO_ROOT" >"$QUEUE_ROOT/recursive.log" 2>&1; then
  echo 'Real recursive acquisition was not rejected' >&2
  exit 1
fi
rg -q 'Recursive iOS simulator lock acquisition' "$QUEUE_ROOT/recursive.log"
[[ ! -d "$SDD_WORKDIR/.locks/ios-simulator-SIM-QUEUE.lock" ]]
echo 'iOS verification queue passed: serialized execution, native wait state, completion, failure and real recursion.'
