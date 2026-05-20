#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

BACKEND_HOST="${SDD_FACTORY_BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${SDD_FACTORY_BACKEND_PORT:-8000}"
UI_HOST="${SDD_FACTORY_UI_HOST:-127.0.0.1}"
UI_PORT="${SDD_FACTORY_UI_PORT:-4173}"
UI_BASE="http://${UI_HOST}:${UI_PORT}"

usage() {
  cat <<'EOF'
Usage: bash factory/open-local-ui.sh

Starts the supported local backend/UI stack, waits for the UI to become ready,
opens the operator console in the default browser, and keeps the stack attached
until you press Ctrl+C.
EOF
}

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

open_browser() {
  local url="$1"
  if [[ -n "${BROWSER:-}" ]]; then
    "${BROWSER}" "$url" >/dev/null 2>&1 &
    return 0
  fi
  if command -v open >/dev/null 2>&1; then
    open "$url" >/dev/null 2>&1 &
    return 0
  fi
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$url" >/dev/null 2>&1 &
    return 0
  fi
  echo "UI is ready at ${url}, but no browser opener was found." >&2
  return 1
}

cleanup() {
  local code=$?
  trap - EXIT INT TERM
  if [[ -n "${STACK_PID:-}" ]] && kill -0 "$STACK_PID" >/dev/null 2>&1; then
    kill -INT "$STACK_PID" >/dev/null 2>&1 || true
    wait "$STACK_PID" >/dev/null 2>&1 || true
  fi
  exit "$code"
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -gt 0 ]]; then
  echo "Unknown argument: $1" >&2
  usage >&2
  exit 1
fi

need_cmd bash
need_cmd curl

trap cleanup EXIT INT TERM

cd "$REPO_ROOT"
bash factory/run-local-stack.sh &
STACK_PID=$!

wait_http "$UI_BASE" "UI"
open_browser "$UI_BASE" || true

echo "Opened Constellation: Agent Runtime UI: ${UI_BASE}"
echo "Press Ctrl+C to stop the local stack."

wait "$STACK_PID"
