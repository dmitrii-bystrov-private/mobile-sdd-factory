#!/usr/bin/env bash
set -euo pipefail

launcher_name="${SDD_FACTORY_ROLE_RUNNER:-${SDD_FACTORY_AGENT_EXECUTABLE:-}}"

if [[ -z "$launcher_name" ]]; then
  if command -v claude >/dev/null 2>&1; then
    launcher_name="claude"
  elif command -v codex >/dev/null 2>&1; then
    launcher_name="codex"
  else
    launcher_name="sh"
  fi
fi

role_name="${SDD_FACTORY_ROLE_NAME:-role}"
task_key="${SDD_FACTORY_TASK_KEY:-task}"
repo_root="${SDD_FACTORY_REPO_ROOT:-}"
task_repo_root="${SDD_FACTORY_TASK_REPO_ROOT:-}"
workdir_root="${SDD_FACTORY_WORKDIR_ROOT:-}"
lifecycle="${SDD_FACTORY_ROLE_LIFECYCLE:-persistent}"
role_model="${SDD_FACTORY_ROLE_MODEL:-}"
role_effort="${SDD_FACTORY_ROLE_EFFORT:-}"
settings_file=""

if [[ -n "$task_repo_root" ]]; then
  if [[ -f "$task_repo_root/.claude/settings.local.json" ]]; then
    settings_file="$task_repo_root/.claude/settings.local.json"
  elif [[ -f "$task_repo_root/.claude/settings.json" ]]; then
    settings_file="$task_repo_root/.claude/settings.json"
  fi
fi

if [[ -z "$settings_file" && -n "$repo_root" ]]; then
  if [[ -f "$repo_root/.claude/settings.local.json" ]]; then
    settings_file="$repo_root/.claude/settings.local.json"
  elif [[ -f "$repo_root/.claude/settings.json" ]]; then
    settings_file="$repo_root/.claude/settings.json"
  fi
fi

printf "SDD_FACTORY_AGENT_BOOTSTRAP launcher=%s role=%s task=%s lifecycle=%s\n" "$launcher_name" "$role_name" "$task_key" "$lifecycle"

case "$launcher_name" in
  claude)
    args=(
      "--permission-mode" "auto"
      "--strict-mcp-config"
      "--name" "${role_name}:${task_key}"
    )
    if [[ -n "$role_model" ]]; then
      args+=("--model" "$role_model")
    fi
    if [[ -n "$role_effort" ]]; then
      args+=("--effort" "$role_effort")
    fi
    if [[ -n "$repo_root" ]]; then
      args+=("--add-dir" "$repo_root")
    fi
    if [[ -n "$task_repo_root" ]]; then
      args+=("--add-dir" "$task_repo_root")
    fi
    if [[ -n "$workdir_root" ]]; then
      args+=("--add-dir" "$workdir_root")
    fi
    if [[ -n "$settings_file" ]]; then
      args+=("--settings" "$settings_file")
    fi
    exec claude "${args[@]}"
    ;;
  codex)
    args=()
    if [[ -n "$role_model" ]]; then
      args+=("-m" "$role_model")
    fi
    if [[ -n "$role_effort" ]]; then
      args+=("-c" "model_reasoning_effort=\"$role_effort\"")
    fi
    exec codex "${args[@]}"
    ;;
  sh)
    exec sh
    ;;
  *)
    exec "$launcher_name"
    ;;
esac
