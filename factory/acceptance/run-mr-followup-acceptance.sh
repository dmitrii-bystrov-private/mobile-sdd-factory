#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${SCRIPT_DIR}/shell-run-root.sh"

PORT="${SDD_FACTORY_ACCEPTANCE_PORT:-8015}"
TASK_KEY="IOS-ACCEPT-MR-001"
TMP_ROOT="$(make_shell_acceptance_tmp_root "${REPO_ROOT}" "mr-followup-acceptance")"
WORKDIR_ROOT="${TMP_ROOT}/workdir"
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
  exec env PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}" "${REPO_ROOT}/.venv/bin/python" factory/acceptance/run-mr-followup-acceptance.py
fi

CREATE_PAYLOAD='{"task_key":"IOS-ACCEPT-MR-001","workflow_profile":"oneshot","prepare":true,"policy":{"self_review_policy":"required","boy_scout_policy":"disabled","doc_harvest_policy":"disabled"}}'
CREATE_RESPONSE="$(curl -fsS -X POST "${BASE_URL}/sessions" -H 'content-type: application/json' -d "${CREATE_PAYLOAD}")"
SESSION_ID="$(jq -r '.session.id' <<<"${CREATE_RESPONSE}")"
jq -e '.followup_event_type == "implementation_requested"' <<<"${CREATE_RESPONSE}" >/dev/null

curl -fsS -X POST "${BASE_URL}/roles/output" -H 'content-type: application/json' \
  -d "{\"session_id\":${SESSION_ID},\"role_name\":\"implementer\",\"output_type\":\"completed\",\"payload\":{\"summary\":\"implementation done\"}}" \
  | jq -e '.followup_event_type == "self_review_requested"' >/dev/null

curl -fsS -X POST "${BASE_URL}/roles/output" -H 'content-type: application/json' \
  -d "{\"session_id\":${SESSION_ID},\"role_name\":\"code-reviewer\",\"output_type\":\"passed\",\"payload\":{\"summary\":\"clean review\"}}" \
  | jq -e '.followup_event_type == "verification_requested"' >/dev/null

curl -fsS -X POST "${BASE_URL}/roles/output" -H 'content-type: application/json' \
  -d "{\"session_id\":${SESSION_ID},\"role_name\":\"verification-coordinator\",\"output_type\":\"passed\",\"payload\":{\"summary\":\"verification passed\",\"result\":\"passed\"}}" \
  | jq -e '.followup_event_type == "send_to_test_completed"' >/dev/null

curl -fsS -X POST "${BASE_URL}/operator/ingest-mr-comments" -H 'content-type: application/json' \
  -d "{\"session_id\":${SESSION_ID},\"platform\":\"ios\",\"mr_id\":\"2942\"}" \
  | jq -e '.followup_event_type == "mr_comments_analysis_requested"' >/dev/null

PLAN_DIR="${WORKDIR_ROOT}/${TASK_KEY}/plan"
mkdir -p "${PLAN_DIR}"
cat >"${PLAN_DIR}/index.md" <<'EOF'
# Execution Task List

| # | Task | Depends on | Status |
|---|------|------------|--------|
| 01 | [Address MR feedback](./01-address-mr-feedback.md) | — | ☐ |
EOF
cat >"${PLAN_DIR}/01-address-mr-feedback.md" <<'EOF'
# Address MR feedback

## What to implement
Apply the grouped MR follow-up changes.
EOF
cat >"${WORKDIR_ROOT}/${TASK_KEY}/statuses.md" <<'EOF'
# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-ACCEPT-MR-001 | Story | Parent story | Ready for test |
| IOS-90001 | Sub-task | Address MR feedback | To Do |
| IOS-90002 | Sub-task | Cleanup review leftovers | Ready for test |
EOF

curl -fsS -X POST "${BASE_URL}/roles/output" -H 'content-type: application/json' \
  -d "{\"session_id\":${SESSION_ID},\"role_name\":\"mr-comments-analyst-worker\",\"output_type\":\"completed\",\"payload\":{\"summary\":\"grouped MR comments into actionable follow-up themes\"}}" \
  | jq -e '.followup_event_type == "subtask_implementation_requested"' >/dev/null

curl -fsS -X POST "${BASE_URL}/roles/output" -H 'content-type: application/json' \
  -d "{\"session_id\":${SESSION_ID},\"role_name\":\"implementer\",\"output_type\":\"completed\",\"payload\":{\"summary\":\"mr follow-up done\",\"subtask_key\":\"IOS-90001\"}}" \
  | jq -e '.followup_event_type == "self_review_requested"' >/dev/null

curl -fsS -X POST "${BASE_URL}/roles/output" -H 'content-type: application/json' \
  -d "{\"session_id\":${SESSION_ID},\"role_name\":\"code-reviewer\",\"output_type\":\"passed\",\"payload\":{\"summary\":\"clean review after mr follow-up\"}}" \
  | jq -e '.followup_event_type == "verification_requested"' >/dev/null

FINAL_RESPONSE="$(curl -fsS -X POST "${BASE_URL}/roles/output" -H 'content-type: application/json' \
  -d "{\"session_id\":${SESSION_ID},\"role_name\":\"verification-coordinator\",\"output_type\":\"passed\",\"payload\":{\"summary\":\"verification passed after mr follow-up\",\"result\":\"passed\"}}")"
jq -e '.followup_event_type == "send_to_test_completed"' <<<"${FINAL_RESPONSE}" >/dev/null
jq -e '.session.status == "completed"' <<<"${FINAL_RESPONSE}" >/dev/null

ARTIFACTS_RESPONSE="$(curl -fsS "${BASE_URL}/artifacts?session_id=${SESSION_ID}")"
jq -e '([.items[].artifact_type] | index("mr_comments_markdown")) != null' <<<"${ARTIFACTS_RESPONSE}" >/dev/null
jq -e '([.items[].artifact_type] | index("jira_subtasks_summary")) != null' <<<"${ARTIFACTS_RESPONSE}" >/dev/null

echo "MR follow-up operator acceptance passed for session ${SESSION_ID}."
