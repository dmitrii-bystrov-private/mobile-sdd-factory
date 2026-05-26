#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if command -v python3 >/dev/null 2>&1; then
  exec python3 "${REPO_ROOT}/scripts/write-result.py" "$@"
fi

if command -v python >/dev/null 2>&1; then
  exec python "${REPO_ROOT}/scripts/write-result.py" "$@"
fi

echo "Missing required interpreter: python3 (or python)" >&2
exit 127
