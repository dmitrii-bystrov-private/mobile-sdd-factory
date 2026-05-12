#!/usr/bin/env bash
set -euo pipefail

KEY="${1:?Usage: run-lint.sh <TASK-KEY>}"
REPO_DIR="${SDD_WORKDIR}/${KEY}/repo"

cd "$REPO_DIR"

if [[ -d "Tools/buildscripts" ]]; then
    bash Tools/buildscripts/lint.sh
else
    bash scripts/android-lint.sh
fi
