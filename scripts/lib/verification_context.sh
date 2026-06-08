#!/usr/bin/env bash
set -euo pipefail

verification_resolve_repo_dir() {
  local key="$1"
  local repo_dir="${SDD_WORKDIR}/${key}/repo"
  if [[ ! -d "$repo_dir" ]]; then
    echo "Missing task repo: $repo_dir" >&2
    exit 1
  fi
  printf '%s\n' "$repo_dir"
}

verification_is_ios_repo() {
  local repo_dir="$1"
  [[ -d "$repo_dir/Tools/buildscripts" ]]
}

verification_prepare_ios_context() {
  local key="$1"
  local context_root="${SDD_WORKDIR}/${key}/tmp/verification/ios"
  export SDD_IOS_VERIFICATION_CONTEXT_ROOT="$context_root"
  export SDD_IOS_DERIVED_DATA_PATH="$context_root/derived-data"
  export SDD_IOS_XCRESULT_ROOT="$context_root/xcresult"
  export SDD_IOS_CLONED_SOURCE_PACKAGES_PATH="$context_root/cloned-source-packages"
  export SDD_IOS_VERIFICATION_LOGS_PATH="$context_root/logs"

  mkdir -p \
    "$SDD_IOS_DERIVED_DATA_PATH" \
    "$SDD_IOS_XCRESULT_ROOT" \
    "$SDD_IOS_CLONED_SOURCE_PACKAGES_PATH" \
    "$SDD_IOS_VERIFICATION_LOGS_PATH"
}

verification_prepare_android_context() {
  local key="$1"
  local context_root="${SDD_WORKDIR}/${key}/tmp/verification/android"
  export SDD_ANDROID_VERIFICATION_CONTEXT_ROOT="$context_root"
  export SDD_ANDROID_GRADLE_USER_HOME="$context_root/gradle-user-home"
  export SDD_ANDROID_VERIFICATION_LOGS_PATH="$context_root/logs"

  mkdir -p \
    "$SDD_ANDROID_GRADLE_USER_HOME" \
    "$SDD_ANDROID_VERIFICATION_LOGS_PATH"
}

verification_source_ios_env() {
  local repo_dir="$1"
  if [[ -d "$repo_dir/bin" ]]; then
    export PATH="$repo_dir/bin:$PATH"
  fi
  local loader="$repo_dir/Tools/buildscripts/load-tuist-env.sh"
  if [[ -f "$loader" ]]; then
    # shellcheck source=/dev/null
    source "$loader"
  fi
}

verification_print_failure_matches() {
  local log_path="$1"
  local pattern="$2"
  grep -E "$pattern" "$log_path" | grep -v '^$' || true
}

verification_strategy_path() {
  local key="$1"
  printf '%s\n' "${SDD_WORKDIR}/${key}/spec/verification-strategy.json"
}

verification_strategy_json_value() {
  local key="$1"
  local jq_expr="$2"
  local strategy_path
  strategy_path="$(verification_strategy_path "$key")"
  if [[ ! -f "$strategy_path" ]]; then
    return 1
  fi
  jq -r "$jq_expr" "$strategy_path"
}

verification_strategy_json_lines() {
  local key="$1"
  local jq_expr="$2"
  local strategy_path
  strategy_path="$(verification_strategy_path "$key")"
  if [[ ! -f "$strategy_path" ]]; then
    return 1
  fi
  jq -r "$jq_expr" "$strategy_path"
}

verification_ios_scheme() {
  local key="$1"
  local scheme="Finom"
  local resolved=""

  if resolved="$(verification_strategy_json_value "$key" '.impact_mapping.preferred_scheme // empty' 2>/dev/null)" && [[ -n "$resolved" ]]; then
    scheme="$resolved"
  fi

  printf '%s\n' "$scheme"
}
