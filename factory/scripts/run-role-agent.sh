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
resume_mode="${SDD_FACTORY_ROLE_RESUME_MODE:-}"
native_session_id="${SDD_FACTORY_ROLE_SESSION_ID:-}"
resume_prompt=""
claude_settings_file="${SDD_FACTORY_CLAUDE_SETTINGS:-}"
claude_mcp_config="${SDD_FACTORY_CLAUDE_MCP_CONFIG:-}"
settings_file=""
mcp_config_file=""

# Older backend processes do not export native IDs; adopt only an exact validated binding.
if [[ -z "$native_session_id" && -n "$repo_root" && -x "$repo_root/.venv/bin/python" ]] &&
   [[ "$resume_mode" == native || -f RUNTIME_CHECKPOINT.json ]]; then
  identity="$(PYTHONPATH="$repo_root${PYTHONPATH:+:$PYTHONPATH}" "$repo_root/.venv/bin/python" - "$launcher_name" <<'PY'
from pathlib import Path
import sys
from backend.roles.session_history import launcher_identity
identity, resume = launcher_identity(Path.cwd(), sys.argv[1], True)
print((identity or "-") + " " + ("native" if resume else "fresh"))
PY
)"
  read -r native_session_id native_state <<< "$identity"
  [[ "$native_session_id" != - ]] || native_session_id=""
  if [[ "$native_state" == native ]]; then resume_mode=native; else resume_mode=""; fi
fi
if [[ -f RUNTIME_CHECKPOINT.json && -n "$repo_root" && -x "$repo_root/.venv/bin/python" ]]; then
  SDD_WORKDIR="$workdir_root" PYTHONPATH="$repo_root${PYTHONPATH:+:$PYTHONPATH}" \
    "$repo_root/.venv/bin/python" -m backend.coordinator.runtime_checkpoint
  resume_prompt="Read RESUME_CONTEXT.json for current factory state and recorded operator decisions. Wait for current routed work from HYDRATION.json; do not reuse earlier terminal results or start task actions from the resumed conversation."
fi

if [[ -n "$claude_settings_file" ]]; then
  settings_file="$claude_settings_file"
elif [[ -n "$task_repo_root" ]]; then
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

if [[ -n "$claude_mcp_config" ]]; then
  mcp_config_file="$claude_mcp_config"
elif [[ -n "$task_repo_root" && -f "$task_repo_root/.mcp.json" ]]; then
  mcp_config_file="$task_repo_root/.mcp.json"
elif [[ -n "$repo_root" && -f "$repo_root/.mcp.json" ]]; then
  mcp_config_file="$repo_root/.mcp.json"
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
    if [[ -n "$mcp_config_file" ]]; then
      args+=("--mcp-config" "$mcp_config_file")
    fi
    if [[ "$resume_mode" == "native" ]]; then
      [[ -n "$native_session_id" ]] || { echo "Missing bound Claude session ID" >&2; exit 1; }
      if [[ -n "$resume_prompt" ]]; then
        exec claude --resume "$native_session_id" "${args[@]}" "$resume_prompt"
      fi
      exec claude --resume "$native_session_id" "${args[@]}"
    fi
    if [[ -n "$native_session_id" ]]; then
      args+=("--session-id" "$native_session_id")
    fi
    if [[ -n "$resume_prompt" ]]; then exec claude "${args[@]}" "$resume_prompt"; fi
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
    if [[ -n "$repo_root" ]]; then
      args+=("--add-dir" "$repo_root")
    fi
    if [[ -n "$task_repo_root" ]]; then
      args+=("--add-dir" "$task_repo_root")
    fi
    if [[ -n "$workdir_root" ]]; then
      args+=("--add-dir" "$workdir_root")
    fi
    args+=("-s" "danger-full-access")
    args+=("-a" "never")
    if [[ "$resume_mode" == "native" ]]; then
      [[ -n "$native_session_id" ]] || { echo "Missing bound Codex session ID" >&2; exit 1; }
      if [[ -n "$resume_prompt" ]]; then
        exec codex "${args[@]}" resume "$native_session_id" "$resume_prompt"
      fi
      exec codex "${args[@]}" resume "$native_session_id"
    fi
    if [[ -n "$resume_prompt" ]]; then exec codex "${args[@]}" "$resume_prompt"; fi
    exec codex "${args[@]}"
    ;;
  sh)
    exec sh
    ;;
  *)
    exec "$launcher_name"
    ;;
esac
