#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKEND_BASE="${SDD_FACTORY_BACKEND_URL:-http://${SDD_FACTORY_BACKEND_HOST:-127.0.0.1}:${SDD_FACTORY_BACKEND_PORT:-8000}}"

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

submit_via_ingress "$@"
submit_status=$?
if [[ "${submit_status}" -eq 0 ]]; then
  exit 0
fi
if [[ "${submit_status}" -ne 10 ]]; then
  exit "${submit_status}"
fi

echo "SDD_RESULT_INGRESS_FALLBACK: transport failure; falling back to file-based RESULT.json write" >&2
export SDD_RESULT_SUBMISSION_PATH="file-fallback"

if command -v python3 >/dev/null 2>&1; then
  exec python3 "${REPO_ROOT}/scripts/write-result.py" "$@"
fi

if command -v python >/dev/null 2>&1; then
  exec python "${REPO_ROOT}/scripts/write-result.py" "$@"
fi

echo "Missing required interpreter: python3 (or python)" >&2
exit 127
