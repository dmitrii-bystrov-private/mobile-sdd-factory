#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

BACKEND_HOST="${SDD_FACTORY_BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${SDD_FACTORY_BACKEND_PORT:-8000}"
UI_HOST="${SDD_FACTORY_UI_HOST:-127.0.0.1}"
UI_PORT="${SDD_FACTORY_UI_PORT:-4173}"
API_BASE="http://${BACKEND_HOST}:${BACKEND_PORT}"
UI_BASE="http://${UI_HOST}:${UI_PORT}"

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

wait_http() {
  local url="$1"
  local label="$2"
  local attempts="${3:-60}"
  local i
  for ((i=1; i<=attempts; i++)); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "Timed out waiting for ${label} at ${url}" >&2
  return 1
}

cleanup() {
  local code=$?
  trap - EXIT INT TERM
  if [[ -n "${UI_PID:-}" ]] && kill -0 "$UI_PID" >/dev/null 2>&1; then
    kill "$UI_PID" >/dev/null 2>&1 || true
    wait "$UI_PID" >/dev/null 2>&1 || true
  fi
  if [[ -n "${BACKEND_PID:-}" ]] && kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
    kill "$BACKEND_PID" >/dev/null 2>&1 || true
    wait "$BACKEND_PID" >/dev/null 2>&1 || true
  fi
  exit "$code"
}

need_cmd npm
need_cmd curl

if [[ ! -x "${REPO_ROOT}/.venv/bin/uvicorn" ]]; then
  echo "Missing backend launcher: ${REPO_ROOT}/.venv/bin/uvicorn" >&2
  exit 1
fi

trap cleanup EXIT INT TERM

cd "$REPO_ROOT"
"${REPO_ROOT}/.venv/bin/uvicorn" backend.api.app:create_app \
  --factory \
  --host "$BACKEND_HOST" \
  --port "$BACKEND_PORT" &
BACKEND_PID=$!

(
  cd "${REPO_ROOT}/ui"
  VITE_SDD_FACTORY_API_BASE="$API_BASE" npm run dev -- --host "$UI_HOST" --port "$UI_PORT" --strictPort
) &
UI_PID=$!

wait_http "${API_BASE}/sessions" "backend API"
wait_http "${UI_BASE}" "UI"

echo "SDD Factory backend: ${API_BASE}"
echo "SDD Factory UI: ${UI_BASE}"
echo "Press Ctrl+C to stop both processes."

while true; do
  if ! kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
    wait "$BACKEND_PID"
  fi
  if ! kill -0 "$UI_PID" >/dev/null 2>&1; then
    wait "$UI_PID"
  fi
  sleep 1
done
