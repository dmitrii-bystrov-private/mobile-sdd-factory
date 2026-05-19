#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

usage() {
  cat <<'EOF'
Usage: bash scripts/dev.sh <command>

Supported convenience commands:
  ui             Start the local backend/UI stack and open the operator UI
  stack          Start the local backend/UI stack without opening a browser
  test           Run the supported test rail
  test-live      Run the supported test rail plus live acceptance
  doctor         Run environment doctor
  bootstrap      Run bootstrap guidance
  help           Show this help

Examples:
  bash scripts/dev.sh ui
  bash scripts/dev.sh test
  bash scripts/dev.sh test-live
EOF
}

command_name="${1:-help}"
shift || true

if [[ $# -gt 0 ]]; then
  echo "Unexpected arguments for command '${command_name}': $*" >&2
  usage >&2
  exit 1
fi

cd "$REPO_ROOT"

case "$command_name" in
  ui)
    exec bash factory/open-local-ui.sh
    ;;
  stack)
    exec bash factory/run-local-stack.sh
    ;;
  test)
    exec bash scripts/run-supported-tests.sh
    ;;
  test-live)
    exec bash scripts/run-supported-tests.sh --live
    ;;
  doctor)
    exec bash factory/doctor/run-doctor.sh
    ;;
  bootstrap)
    exec bash factory/doctor/run-bootstrap-guide.sh
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    echo "Unknown command: ${command_name}" >&2
    usage >&2
    exit 1
    ;;
esac
