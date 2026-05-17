#!/usr/bin/env bash
# Usage: bash scripts/cleanup.sh
#
# Project-scoped cleanup for definitely closed Jira tasks.
# The cleanup policy matches the backend operator flow:
#   1. Stops live runtime for matching task sessions if present
#   2. Removes task runtime residue and runner-private session residue
#   3. Removes task artifacts and worktree/task directory for closed tasks
#   4. Deletes matching task sessions from the local factory database

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}" \
  "$PYTHON_BIN" "$REPO_ROOT/factory/cleanup/run-closed-task-cleanup.py"
