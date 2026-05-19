#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

BACKEND_HOST="${SDD_FACTORY_UI_SMOKE_BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${SDD_FACTORY_UI_SMOKE_BACKEND_PORT:-8012}"
UI_HOST="${SDD_FACTORY_UI_SMOKE_UI_HOST:-127.0.0.1}"
UI_PORT="${SDD_FACTORY_UI_SMOKE_UI_PORT:-4177}"
API_URL="http://${BACKEND_HOST}:${BACKEND_PORT}"
UI_URL="http://${UI_HOST}:${UI_PORT}"

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

wait_playwright_browser() {
  local attempts="${1:-20}"
  local i
  for ((i=1; i<=attempts; i++)); do
    if playwright-cli list | grep -q 'status: open'; then
      return 0
    fi
    sleep 1
  done
  echo "Timed out waiting for playwright browser session." >&2
  return 1
}

wait_snapshot_contains() {
  local output_path="$1"
  local expected="$2"
  local attempts="${3:-20}"
  local i
  for ((i=1; i<=attempts; i++)); do
    playwright-cli snapshot >"${output_path}"
    if grep -q "${expected}" "${output_path}"; then
      return 0
    fi
    sleep 1
  done
  echo "Timed out waiting for snapshot text: ${expected}" >&2
  return 1
}

cleanup() {
  local code=$?
  trap - EXIT INT TERM
  if command -v playwright-cli >/dev/null 2>&1; then
    playwright-cli close-all >/dev/null 2>&1 || true
    playwright-cli kill-all >/dev/null 2>&1 || true
  fi
  if [[ -n "${STACK_PID:-}" ]] && kill -0 "$STACK_PID" >/dev/null 2>&1; then
    kill "$STACK_PID" >/dev/null 2>&1 || true
    wait "$STACK_PID" >/dev/null 2>&1 || true
  fi
  rm -f "${STACK_LOG:-}" "${RUNS_SNAPSHOT:-}" "${SETTINGS_SNAPSHOT:-}" "${HEALTH_SNAPSHOT:-}" "${CONSOLE_LOG:-}"
  exit "$code"
}

need_cmd curl
need_cmd playwright-cli

trap cleanup EXIT INT TERM

STACK_LOG="$(mktemp)"
RUNS_SNAPSHOT="$(mktemp)"
SETTINGS_SNAPSHOT="$(mktemp)"
HEALTH_SNAPSHOT="$(mktemp)"
CONSOLE_LOG="$(mktemp)"

cd "${REPO_ROOT}"
env \
  SDD_FACTORY_BACKEND_HOST="${BACKEND_HOST}" \
  SDD_FACTORY_BACKEND_PORT="${BACKEND_PORT}" \
  SDD_FACTORY_UI_HOST="${UI_HOST}" \
  SDD_FACTORY_UI_PORT="${UI_PORT}" \
  bash factory/run-local-stack.sh >"${STACK_LOG}" 2>&1 &
STACK_PID=$!

wait_http "${API_URL}/sessions" "backend API"
wait_http "${UI_URL}" "UI"

playwright-cli close-all >/dev/null 2>&1 || true
playwright-cli kill-all >/dev/null 2>&1 || true

playwright-cli open "${UI_URL}" >/dev/null
wait_playwright_browser
playwright-cli snapshot >"${RUNS_SNAPSHOT}"
playwright-cli console >"${CONSOLE_LOG}"

grep -q 'heading "Operator Console"' "${RUNS_SNAPSHOT}"
grep -q 'heading "New Workflow Run"' "${RUNS_SNAPSHOT}"
grep -q 'heading "Factory Queue"' "${RUNS_SNAPSHOT}"
if grep -q 'Failed to fetch' "${CONSOLE_LOG}"; then
  echo "UI surface smoke saw a failed fetch in browser console." >&2
  exit 1
fi

playwright-cli click e26 >/dev/null
wait_snapshot_contains "${SETTINGS_SNAPSHOT}" 'heading "Project Settings"'
grep -q 'heading "Runtime Defaults"' "${SETTINGS_SNAPSHOT}"
grep -q 'heading "Shared Knowledge"' "${SETTINGS_SNAPSHOT}"

playwright-cli goto "${UI_URL}" >/dev/null
wait_snapshot_contains "${RUNS_SNAPSHOT}" 'heading "New Workflow Run"'
playwright-cli click e29 >/dev/null
wait_snapshot_contains "${HEALTH_SNAPSHOT}" 'heading "Environment Health"'
grep -q 'heading "Capabilities"' "${HEALTH_SNAPSHOT}"
grep -q 'heading "Bootstrap Guidance"' "${HEALTH_SNAPSHOT}"

echo "UI surface smoke passed."
