#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUNTIME_DIR="${REPO_ROOT}/.runtime"
PID_FILE="${RUNTIME_DIR}/backend.pid"
LOG_FILE="${RUNTIME_DIR}/backend.log"
BACKEND_HOST="${SDD_FACTORY_BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${SDD_FACTORY_BACKEND_PORT:-8000}"
BACKEND_URL="http://${BACKEND_HOST}:${BACKEND_PORT}/sessions"

usage() {
  cat <<EOF
Usage: bash scripts/backend.sh <start|stop|restart|status|logs>
EOF
}

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

backend_pid() {
  if [[ -f "${PID_FILE}" ]]; then
    cat "${PID_FILE}"
  fi
}

pid_is_running() {
  local pid="$1"
  [[ -n "${pid}" ]] && kill -0 "${pid}" >/dev/null 2>&1
}

wait_http() {
  local attempts="${1:-30}"
  local i
  for ((i=1; i<=attempts; i++)); do
    if curl -fsS "${BACKEND_URL}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

start_backend() {
  mkdir -p "${RUNTIME_DIR}"
  local pid
  pid="$(backend_pid || true)"
  if [[ -n "${pid}" ]] && pid_is_running "${pid}"; then
    echo "Backend already running with pid ${pid}"
    return 0
  fi
  : >"${LOG_FILE}"
  (
    cd "${REPO_ROOT}"
    nohup ./.venv/bin/uvicorn backend.api.app:create_app --factory --host "${BACKEND_HOST}" --port "${BACKEND_PORT}" \
      >>"${LOG_FILE}" 2>&1 < /dev/null &
    echo $! > "${PID_FILE}"
  )
  if ! wait_http 30; then
    echo "Backend failed to start; log follows:" >&2
    cat "${LOG_FILE}" >&2 || true
    exit 1
  fi
  echo "Backend started on ${BACKEND_URL} (pid $(backend_pid))"
}

stop_backend() {
  local pid
  pid="$(backend_pid || true)"
  if [[ -z "${pid}" ]]; then
    echo "Backend is not running"
    return 0
  fi
  if pid_is_running "${pid}"; then
    kill "${pid}" >/dev/null 2>&1 || true
    for _ in {1..15}; do
      if ! pid_is_running "${pid}"; then
        break
      fi
      sleep 1
    done
    if pid_is_running "${pid}"; then
      kill -9 "${pid}" >/dev/null 2>&1 || true
    fi
  fi
  rm -f "${PID_FILE}"
  echo "Backend stopped"
}

status_backend() {
  local pid
  pid="$(backend_pid || true)"
  if [[ -n "${pid}" ]] && pid_is_running "${pid}"; then
    echo "Backend running with pid ${pid}"
    if curl -fsS "${BACKEND_URL}" >/dev/null 2>&1; then
      echo "Health: ok (${BACKEND_URL})"
    else
      echo "Health: not responding (${BACKEND_URL})"
      exit 1
    fi
    return 0
  fi
  echo "Backend stopped"
  exit 1
}

show_logs() {
  if [[ -f "${LOG_FILE}" ]]; then
    tail -n 200 "${LOG_FILE}"
  fi
}

need_cmd curl

case "${1:-}" in
  start)
    start_backend
    ;;
  stop)
    stop_backend
    ;;
  restart)
    stop_backend
    start_backend
    ;;
  status)
    status_backend
    ;;
  logs)
    show_logs
    ;;
  *)
    usage >&2
    exit 1
    ;;
esac
