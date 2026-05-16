#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

PORT="${SDD_FACTORY_ACCEPTANCE_PORT:-8012}"
TASK_KEY="IOS-ACCEPT-001"
WORKDIR_ROOT="${REPO_ROOT}/workdir"
TASK_ROOT="${WORKDIR_ROOT}/${TASK_KEY}"
mkdir -p "${TASK_ROOT}/tmp"
TMP_ROOT="$(mktemp -d "${TASK_ROOT}/tmp/happy-path-acceptance.XXXXXX")"
DB_PATH="${TMP_ROOT}/acceptance.sqlite3"
RUNTIME_ROOT="${WORKDIR_ROOT}"
BASE_URL="http://127.0.0.1:${PORT}"
SERVER_LOG="${TMP_ROOT}/server.log"

cleanup() {
  if [[ -n "${SERVER_PID:-}" ]] && kill -0 "${SERVER_PID}" 2>/dev/null; then
    kill "${SERVER_PID}" 2>/dev/null || true
    wait "${SERVER_PID}" 2>/dev/null || true
  fi
  rm -rf "${TMP_ROOT}"
}
trap cleanup EXIT

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

need_cmd jq
need_cmd curl
need_cmd "${REPO_ROOT}/.venv/bin/python"

cd "${REPO_ROOT}"

env \
  SDD_FACTORY_DB_PATH="${DB_PATH}" \
  SDD_FACTORY_RUNTIME_BACKEND="recording" \
  SDD_FACTORY_RUNTIME_ROOT="${RUNTIME_ROOT}" \
  SDD_WORKDIR="${WORKDIR_ROOT}" \
  SDD_FACTORY_USE_FAKE_ADAPTERS="true" \
  ./.venv/bin/uvicorn backend.api.app:create_app --factory --host 127.0.0.1 --port "${PORT}" \
  >"${SERVER_LOG}" 2>&1 &
SERVER_PID=$!

for _ in $(seq 1 40); do
  if curl -fsS "${BASE_URL}/sessions" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done

if ! curl -fsS "${BASE_URL}/sessions" >/dev/null 2>&1; then
  echo "Acceptance backend failed to bind locally; falling back to in-process operator-route acceptance." >&2
  cat "${SERVER_LOG}" >&2 || true
  wait "${SERVER_PID}" 2>/dev/null || true
  SERVER_PID=""
  exec "${REPO_ROOT}/.venv/bin/python" factory/acceptance/run-happy-path-acceptance.py
fi

CREATE_PAYLOAD='{"task_key":"IOS-ACCEPT-001","workflow_profile":"oneshot","policy":{"self_review_policy":"required","boy_scout_policy":"disabled","doc_harvest_policy":"disabled"}}'
CREATE_RESPONSE="$(curl -fsS -X POST "${BASE_URL}/sessions" -H 'content-type: application/json' -d "${CREATE_PAYLOAD}")"
SESSION_ID="$(jq -r '.session.id' <<<"${CREATE_RESPONSE}")"

PREPARE_RESPONSE="$(curl -fsS -X POST "${BASE_URL}/sessions/prepare" -H 'content-type: application/json' -d "{\"task_key\":\"${TASK_KEY}\"}")"
jq -e '.followup_event_type == "implementation_requested"' <<<"${PREPARE_RESPONSE}" >/dev/null

curl -fsS -X POST "${BASE_URL}/roles/output" -H 'content-type: application/json' \
  -d "{\"session_id\":${SESSION_ID},\"role_name\":\"implementer\",\"output_type\":\"completed\",\"payload\":{\"summary\":\"implementation done\"}}" \
  | jq -e '.followup_event_type == "self_review_requested"' >/dev/null

curl -fsS -X POST "${BASE_URL}/roles/output" -H 'content-type: application/json' \
  -d "{\"session_id\":${SESSION_ID},\"role_name\":\"code-reviewer\",\"output_type\":\"passed\",\"payload\":{\"summary\":\"clean review\"}}" \
  | jq -e '.followup_event_type == "verification_requested"' >/dev/null

curl -fsS -X POST "${BASE_URL}/roles/output" -H 'content-type: application/json' \
  -d "{\"session_id\":${SESSION_ID},\"role_name\":\"verification-coordinator\",\"output_type\":\"failed\",\"payload\":{\"summary\":\"verification failed\",\"failures\":[\"lint\"]}}" \
  | jq -e '.followup_event_type == "verification_correction_requested"' >/dev/null

curl -fsS -X POST "${BASE_URL}/roles/output" -H 'content-type: application/json' \
  -d "{\"session_id\":${SESSION_ID},\"role_name\":\"implementer\",\"output_type\":\"completed\",\"payload\":{\"summary\":\"verification correction done\"}}" \
  | jq -e '.followup_event_type == "verification_requested"' >/dev/null

FINAL_RESPONSE="$(curl -fsS -X POST "${BASE_URL}/roles/output" -H 'content-type: application/json' \
  -d "{\"session_id\":${SESSION_ID},\"role_name\":\"verification-coordinator\",\"output_type\":\"passed\",\"payload\":{\"summary\":\"verification passed\"}}")"
jq -e '.mapped_event_type == "verification_passed"' <<<"${FINAL_RESPONSE}" >/dev/null
jq -e '.followup_event_type == "task_completed"' <<<"${FINAL_RESPONSE}" >/dev/null
jq -e '.session.status == "completed"' <<<"${FINAL_RESPONSE}" >/dev/null

EVENTS_RESPONSE="$(curl -fsS "${BASE_URL}/events?session_id=${SESSION_ID}")"
jq -e '
  [.items[].event_type] == [
    "task_started",
    "task_session_reused",
    "task_prepared",
    "role_input_dispatched",
    "implementation_requested",
    "implementation_completed",
    "role_input_dispatched",
    "self_review_requested",
    "self_review_passed",
    "role_input_dispatched",
    "verification_requested",
    "verification_failed",
    "role_input_dispatched",
    "verification_correction_requested",
    "implementation_completed",
    "role_input_dispatched",
    "verification_requested",
    "verification_passed",
    "task_completed"
  ]
' <<<"${EVENTS_RESPONSE}" >/dev/null

ARTIFACTS_RESPONSE="$(curl -fsS "${BASE_URL}/artifacts?session_id=${SESSION_ID}")"
jq -e '([.items[].artifact_type] | index("role_prompt")) != null' <<<"${ARTIFACTS_RESPONSE}" >/dev/null
jq -e '([.items[].artifact_type] | index("self_review_summary")) != null' <<<"${ARTIFACTS_RESPONSE}" >/dev/null

echo "Happy-path operator acceptance passed for session ${SESSION_ID}."
