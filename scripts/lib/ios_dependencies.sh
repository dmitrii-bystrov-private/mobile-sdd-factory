#!/usr/bin/env bash
set -euo pipefail

ios_install_locked_dependencies() {
  local repo_dir="$1"
  local mise_cmd="$2"

  if [[ ! -f "$repo_dir/Tuist/Package.resolved" ]]; then
    echo "error: Missing Tuist/Package.resolved; refresh and commit the lockfile before preparation" >&2
    return 1
  fi

  (cd "$repo_dir" && GIT_TERMINAL_PROMPT=0 "$mise_cmd" exec -- tuist install --force-resolved-versions)
}
