#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

INCLUDE_LIVE=0

usage() {
  cat <<'EOF'
Usage: bash scripts/run-supported-tests.sh [--live]

Runs the supported Constellation: Agent Runtime test rail:
  - backend regression suite
  - UI production build
  - shell regression tests for scripts/
  - supported operator acceptance harnesses

Optional:
  --live    also run the high-signal live runtime acceptance harnesses
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --live)
      INCLUDE_LIVE=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

run_step() {
  local label="$1"
  shift
  echo ""
  echo "==> ${label}"
  "$@"
}

cd "${REPO_ROOT}"

run_step "Backend regression suite" \
  ./.venv/bin/python -m unittest discover -s tests/backend -p 'test_*.py'

run_step "UI production build" \
  bash -lc "cd ui && npm run build"

run_step "Shell regression: ADF to Markdown" \
  bash scripts/tests/test_adf_to_md.sh

run_step "Shell regression: snapshot formatters" \
  bash scripts/tests/test_snapshot_formatters.sh

run_step "Shell regression: snapshot errors" \
  bash scripts/tests/test_snapshot_errors.sh

run_step "Operator acceptance: happy path" \
  bash factory/acceptance/run-happy-path-acceptance.sh

run_step "Operator acceptance: follow-up reopen" \
  bash factory/acceptance/run-followup-reopen-acceptance.sh

run_step "Operator acceptance: MR follow-up" \
  bash factory/acceptance/run-mr-followup-acceptance.sh

run_step "Operator acceptance: delivery" \
  bash factory/acceptance/run-delivery-acceptance.sh

if [[ "${INCLUDE_LIVE}" -eq 1 ]]; then
  run_step "Browser smoke: UI surfaces" \
    bash factory/acceptance/run-ui-surface-smoke.sh

  run_step "Live runtime acceptance: story flow" \
    env PYTHONPATH="${REPO_ROOT}${PYTHONPATH:+:${PYTHONPATH}}" ./.venv/bin/python factory/acceptance/run-real-story-runtime-acceptance.py

  run_step "Live runtime acceptance: Codex quality loop" \
    env PYTHONPATH="${REPO_ROOT}${PYTHONPATH:+:${PYTHONPATH}}" ./.venv/bin/python factory/acceptance/run-real-codex-quality-loop-validation.py
fi

echo ""
if [[ "${INCLUDE_LIVE}" -eq 1 ]]; then
  echo "Supported test rail passed, including live acceptance."
else
  echo "Supported test rail passed."
fi
