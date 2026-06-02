#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKEND_HOST="${SDD_FACTORY_BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${SDD_FACTORY_BACKEND_PORT:-8000}"
BACKEND_BASE="http://${BACKEND_HOST}:${BACKEND_PORT}"

python_cmd() {
  if command -v python3 >/dev/null 2>&1; then
    printf '%s\n' python3
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    printf '%s\n' python
    return 0
  fi
  return 1
}

submit_via_ingress() {
  local py
  py="$(python_cmd)" || return 1
  local payload_file
  payload_file="$(mktemp)"
  local response_file
  response_file="$(mktemp)"
  trap 'rm -f "${payload_file}" "${response_file}"' RETURN
  PYTHONPATH="${REPO_ROOT}${PYTHONPATH:+:${PYTHONPATH}}" "${py}" - "$@" >"${payload_file}" <<'PY'
import json
import sys

from backend.tools.write_result import build_parser, build_result_document, resolve_submission_context

parser = build_parser()
args = parser.parse_args(sys.argv[1:])
context = resolve_submission_context(work_item_id=args.work_item_id)
document = build_result_document(args, context.role_name)
print(json.dumps(document, sort_keys=True))
PY
  local http_code
  if ! http_code="$(
    curl -sS \
    -X POST \
    -H 'Content-Type: application/json' \
    --data-binary "@${payload_file}" \
    -o "${response_file}" \
    -w '%{http_code}' \
    "${BACKEND_BASE}/roles/submit-result"
  )"; then
    return 10
  fi
  if [[ "${http_code}" =~ ^2 ]]; then
    return 0
  fi
  cat "${response_file}" >&2 || true
  return 20
}

submit_status=0
submit_via_ingress "$@" || submit_status=$?
if [[ "${submit_status}" -eq 0 ]]; then
  exit 0
fi
if [[ "${submit_status}" -eq 10 ]]; then
  echo "SDD_RESULT_INGRESS_ERROR: transport failure; do not retry via manual RESULT.json or direct writer scripts" >&2
  exit 10
fi

exit "${submit_status}"
