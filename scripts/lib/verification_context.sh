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

verification_prepare_ios_launch_context() {
  local key="$1"
  verification_prepare_ios_context "$key"

  local context_root="${SDD_WORKDIR}/${key}/tmp/launch/ios"
  export SDD_IOS_LAUNCH_CONTEXT_ROOT="$context_root"
  export SDD_IOS_LAUNCH_DERIVED_DATA_PATH="$SDD_IOS_DERIVED_DATA_PATH"
  export SDD_IOS_LAUNCH_LOGS_PATH="$context_root/logs"

  mkdir -p \
    "$SDD_IOS_LAUNCH_LOGS_PATH"
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

verification_resolve_mise_cmd() {
  local repo_dir="$1"
  if [[ -x "$repo_dir/bin/mise" ]]; then
    printf '%s\n' "$repo_dir/bin/mise"
    return 0
  fi
  if command -v mise >/dev/null 2>&1; then
    command -v mise
    return 0
  fi
  echo "mise not found (expected $repo_dir/bin/mise or a global mise)" >&2
  return 1
}

verification_run_with_ios_simulator_lock() (
  local device_id="$1"
  shift

  local safe_device_id
  safe_device_id="$(printf '%s' "$device_id" | sed 's/[^A-Za-z0-9_.-]/_/g')"
  local lock_root="${SDD_IOS_SIMULATOR_LOCK_ROOT:-${SDD_WORKDIR}/.locks}"
  local lock_dir="$lock_root/ios-simulator-${safe_device_id}.lock"
  local pid_file="$lock_dir/owner.pid"
  local owner_file="$lock_dir/owner.txt"
  local wait_logged=0

  mkdir -p "$lock_root"
  while ! mkdir "$lock_dir" 2>/dev/null; do
    local owner_pid=""
    if [[ -f "$pid_file" ]]; then
      owner_pid="$(cat "$pid_file" 2>/dev/null || true)"
    fi
    if [[ -n "$owner_pid" ]] && ! kill -0 "$owner_pid" 2>/dev/null; then
      rm -rf "$lock_dir"
      continue
    fi
    if [[ "$wait_logged" -eq 0 ]]; then
      echo "⏳ Waiting for iOS simulator lock: $device_id"
      wait_logged=1
    fi
    sleep 2
  done

  printf '%s\n' "${BASHPID-$$}" >"$pid_file"
  printf 'device=%s task=%s started_at=%s\n' "$device_id" "${KEY:-unknown}" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"$owner_file"
  trap 'rm -rf "$lock_dir"' EXIT INT TERM

  "$@"
)

verification_safe_lock_name() {
  printf '%s' "$1" | sed 's/[^A-Za-z0-9_.-]/_/g'
}

verification_ios_task_lock_dir() {
  local key="$1"
  local safe_key
  safe_key="$(verification_safe_lock_name "$key")"
  local lock_root="${SDD_IOS_TASK_LOCK_ROOT:-${SDD_WORKDIR}/.locks}"
  printf '%s\n' "$lock_root/ios-task-${safe_key}.lock"
}

verification_ios_task_lock_is_active() {
  local key="$1"
  local lock_dir
  lock_dir="$(verification_ios_task_lock_dir "$key")"
  local pid_file="$lock_dir/owner.pid"

  if [[ ! -d "$lock_dir" ]]; then
    return 1
  fi

  local owner_pid=""
  if [[ -f "$pid_file" ]]; then
    owner_pid="$(cat "$pid_file" 2>/dev/null || true)"
  fi
  if [[ -n "$owner_pid" ]] && kill -0 "$owner_pid" 2>/dev/null; then
    return 0
  fi

  rm -rf "$lock_dir"
  return 1
}

verification_run_with_ios_task_lock() (
  local key="$1"
  shift

  local lock_dir
  lock_dir="$(verification_ios_task_lock_dir "$key")"
  local lock_root
  lock_root="$(dirname "$lock_dir")"
  local pid_file="$lock_dir/owner.pid"
  local owner_file="$lock_dir/owner.txt"
  local wait_logged=0

  mkdir -p "$lock_root"
  while ! mkdir "$lock_dir" 2>/dev/null; do
    if ! verification_ios_task_lock_is_active "$key"; then
      continue
    fi
    if [[ "$wait_logged" -eq 0 ]]; then
      echo "⏳ Waiting for iOS task lock: $key"
      wait_logged=1
    fi
    sleep 2
  done

  printf '%s\n' "${BASHPID-$$}" >"$pid_file"
  printf 'task=%s started_at=%s\n' "$key" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"$owner_file"
  trap 'rm -rf "$lock_dir"' EXIT INT TERM

  "$@"
)

verification_ios_derived_data_task_key() {
  local path="$1"
  basename "$(dirname "$(dirname "$(dirname "$(dirname "$path")")")")"
}

verification_path_mtime() {
  local path="$1"
  stat -f '%m' "$path" 2>/dev/null || stat -c '%Y' "$path" 2>/dev/null || printf '0\n'
}

verification_available_disk_kb() {
  local path="$1"
  df -Pk "$path" | awk 'NR == 2 {print $4}'
}

verification_prune_ios_derived_data_if_needed() {
  local current_key="$1"

  if [[ "${IOS_DERIVED_DATA_PRUNE_ENABLED:-1}" == "0" ]]; then
    return 0
  fi

  local min_free_gb="${IOS_MIN_FREE_DISK_GB:-50}"
  if [[ ! "$min_free_gb" =~ ^[0-9]+$ ]]; then
    echo "⚠️  IOS_MIN_FREE_DISK_GB must be an integer number of gigabytes; got: $min_free_gb" >&2
    return 1
  fi

  local min_free_kb=$((min_free_gb * 1024 * 1024))
  local available_kb
  available_kb="$(verification_available_disk_kb "$SDD_WORKDIR")"
  if [[ -z "$available_kb" || ! "$available_kb" =~ ^[0-9]+$ ]]; then
    echo "⚠️  Unable to determine free disk space for $SDD_WORKDIR" >&2
    return 1
  fi

  if (( available_kb >= min_free_kb )); then
    return 0
  fi

  echo "⚠️  Low disk space before iOS operation: $((available_kb / 1024 / 1024))GB free, target is ${min_free_gb}GB."
  echo "🧹 Pruning task-local iOS DerivedData caches from older sibling tasks..."

  local current_path="${SDD_WORKDIR}/${current_key}/tmp/verification/ios/derived-data"
  local candidates=()
  local derived_data_path
  while IFS= read -r derived_data_path; do
    [[ -d "$derived_data_path" ]] || continue
    [[ "$derived_data_path" != "$current_path" ]] || continue
    local task_key
    task_key="$(verification_ios_derived_data_task_key "$derived_data_path")"
    [[ -n "$task_key" ]] || continue
    if verification_ios_task_lock_is_active "$task_key"; then
      echo "  Skipping active iOS task cache: $task_key"
      continue
    fi
    candidates+=("$(verification_path_mtime "$derived_data_path") $derived_data_path")
  done < <(find "$SDD_WORKDIR" -path "*/tmp/verification/ios/derived-data" -type d -print 2>/dev/null)

  if [[ "${#candidates[@]}" -eq 0 ]]; then
    echo "⚠️  No removable sibling iOS DerivedData caches found."
    return 0
  fi

  local removed_any=0
  local sorted_candidate
  while IFS= read -r sorted_candidate; do
    [[ -n "$sorted_candidate" ]] || continue
    derived_data_path="${sorted_candidate#* }"
    [[ -d "$derived_data_path" ]] || continue
    local task_key
    task_key="$(verification_ios_derived_data_task_key "$derived_data_path")"
    rm -rf "$derived_data_path"
    removed_any=1
    echo "  Removed iOS DerivedData cache for $task_key"

    available_kb="$(verification_available_disk_kb "$SDD_WORKDIR")"
    if [[ "$available_kb" =~ ^[0-9]+$ ]] && (( available_kb >= min_free_kb )); then
      echo "✅ Disk space target reached: $((available_kb / 1024 / 1024))GB free."
      return 0
    fi
  done < <(printf '%s\n' "${candidates[@]}" | sort -n)

  available_kb="$(verification_available_disk_kb "$SDD_WORKDIR")"
  if [[ "$available_kb" =~ ^[0-9]+$ ]]; then
    if (( removed_any == 1 )); then
      echo "⚠️  Disk space after pruning is $((available_kb / 1024 / 1024))GB, still below target ${min_free_gb}GB."
    fi
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
  local scheme="${SDD_IOS_DEFAULT_SCHEME:-}"
  local resolved=""

  if resolved="$(verification_strategy_json_value "$key" '.impact_mapping.preferred_scheme // empty' 2>/dev/null)" && [[ -n "$resolved" ]]; then
    scheme="$resolved"
  fi

  if [[ -z "$scheme" ]]; then
    echo "Missing iOS scheme: set SDD_IOS_DEFAULT_SCHEME or provide impact_mapping.preferred_scheme in verification-strategy.json" >&2
    return 1
  fi

  printf '%s\n' "$scheme"
}

verification_ios_workspace() {
  local repo_dir="${1:-.}"
  if [[ -n "${SDD_IOS_WORKSPACE_NAME:-}" ]]; then
    printf '%s\n' "$SDD_IOS_WORKSPACE_NAME"
    return 0
  fi

  local workspaces=()
  while IFS= read -r workspace; do
    workspaces+=("$(basename "$workspace")")
  done < <(find "$repo_dir" -maxdepth 1 -name "*.xcworkspace" -print | sort)

  if [[ "${#workspaces[@]}" -eq 1 ]]; then
    printf '%s\n' "${workspaces[0]}"
    return 0
  fi
  if [[ "${#workspaces[@]}" -eq 0 ]]; then
    echo "Missing iOS workspace: set SDD_IOS_WORKSPACE_NAME or add a .xcworkspace at the repo root" >&2
  else
    echo "Multiple iOS workspaces found; set SDD_IOS_WORKSPACE_NAME explicitly" >&2
  fi
  return 1
}
