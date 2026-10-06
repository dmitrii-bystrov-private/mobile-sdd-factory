#!/usr/bin/env bash

make_shell_acceptance_tmp_root() {
  local repo_root="$1"
  local slug="$2"
  local shell_root="${repo_root}/.runtime/test-runs-shell"

  mkdir -p "${shell_root}"
  mktemp -d "${shell_root}/${slug}.XXXXXX"
}
