#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/verification_context.sh"
KEY="${1:-}"
shift || true
verification_prune_ios_derived_data_if_needed "$KEY" local "$@"
