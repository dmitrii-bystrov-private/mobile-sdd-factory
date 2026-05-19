"""Session-scoped runtime configuration for launcher-backed roles."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from backend.coordinator.intake import IntakeError
from backend.runtime_defaults import load_runtime_defaults
from factory.doctor.runtime_capabilities import build_runtime_capabilities


ROLE_DEFAULT_SOURCE_MAP = {
    "implementer": "implementer",
    "bug-fixer": "bug-fixer",
    "task-coordinator": None,
    "verification-coordinator": "final-verifier",
    "code-reviewer": "code-reviewer",
    "code-scout": "code-scout",
    "mr-comments-analyst-worker": "mr-comments-analyst",
    "doc-harvest-worker": "doc-harvest",
    "proposal-context-worker": "context-collector",
    "requirements-clarifier-worker": "requirements-clarifier",
    "acceptance-criteria-worker": "acceptance-criteria-writer",
    "constraints-worker": "constraints-definer",
    "spec-verifier-worker": "spec-verifier",
    "story-spec-worker": None,
    "task-decomposer-worker": "task-decomposer",
}

_CLAUDE_SCOPED_MCP_RUNNER: Final[str] = "claude"


def normalize_role_runtime_config(
    *,
    repo_root: Path,
    role_names: list[str],
    provided: dict[str, dict[str, str]] | None,
) -> dict[str, dict[str, str]]:
    capabilities = build_runtime_capabilities(repo_root=repo_root)
    operator_defaults = load_runtime_defaults(repo_root)
    runners_by_name = {item["runner"]: item for item in capabilities["runners"]}
    legacy_defaults = {item["role_name"]: item for item in capabilities["legacy_role_defaults"]}
    available_runners = set(capabilities["available_runners"])
    configured_default_runner = operator_defaults.get("default_runner")
    default_runner = (
        configured_default_runner
        or capabilities["default_runner"]
        or ("claude" if "claude" in runners_by_name else next(iter(runners_by_name), "claude"))
    )
    operator_role_defaults = operator_defaults.get("role_defaults", {})

    unknown_roles = sorted(set((provided or {}).keys()) - set(role_names))
    if unknown_roles:
        raise IntakeError(f"Role runtime config contains unknown roles: {', '.join(unknown_roles)}")

    normalized: dict[str, dict[str, str]] = {}
    for role_name in role_names:
        override = dict((provided or {}).get(role_name, {}))
        operator_role_default = operator_role_defaults.get(role_name, {})
        runner = override.get("runner") or operator_role_default.get("runner") or default_runner
        if runner not in runners_by_name:
            raise IntakeError(f"Unsupported runner for {role_name}: {runner}")
        if runner not in available_runners:
            raise IntakeError(f"Runner for {role_name} is not available locally: {runner}")

        runner_capability = runners_by_name[runner]
        models = runner_capability.get("models", [])
        model_ids = [item["id"] for item in models]
        legacy_key = ROLE_DEFAULT_SOURCE_MAP.get(role_name)
        legacy_default = legacy_defaults.get(legacy_key) if legacy_key is not None else None
        legacy_default_model = (
            (legacy_default or {}).get("model")
            if (legacy_default or {}).get("model") in model_ids
            else None
        )

        operator_default_model = (
            operator_role_default.get("model")
            if operator_role_default.get("runner") in {None, "", runner}
            else None
        )
        default_model = (
            operator_default_model
            or legacy_default_model
            or ("sonnet" if runner == "claude" and "sonnet" in model_ids else None)
            or (model_ids[0] if model_ids else None)
        )
        model = override.get("model") or default_model
        if model is None:
            raise IntakeError(f"Could not determine a default model for {role_name}")
        if model not in model_ids:
            raise IntakeError(f"Unsupported model for {role_name} on {runner}: {model}")

        model_capability = next(item for item in models if item["id"] == model)
        supported_efforts = list(model_capability.get("supported_efforts", []))
        legacy_default_effort = (
            (legacy_default or {}).get("effort")
            if legacy_default_model == model
            and (
                not supported_efforts
                or (legacy_default or {}).get("effort") in supported_efforts
            )
            else None
        )
        effort = (
            override.get("effort")
            or (
                operator_role_default.get("runner") == runner
                and operator_role_default.get("model") in {None, "", model}
                and operator_role_default.get("effort")
            )
            or legacy_default_effort
            or model_capability.get("default_effort")
            or ("medium" if "medium" in supported_efforts else (supported_efforts[0] if supported_efforts else None))
        )
        if effort is None:
            raise IntakeError(f"Could not determine a default effort for {role_name}")
        if supported_efforts and effort not in supported_efforts:
            raise IntakeError(f"Unsupported effort for {role_name} on {runner}/{model}: {effort}")

        normalized[role_name] = {
            "runner": runner,
            "model": model,
            "effort": effort,
        }
    return normalized


def resolve_role_mcp_servers(
    *,
    repo_root: Path,
    role_name: str,
    runner: str,
) -> list[str]:
    if runner != _CLAUDE_SCOPED_MCP_RUNNER:
        return []

    if role_name == "proposal-context-worker":
        merged: list[str] = []
        for legacy_role_name in ("proposal-collector", "context-collector"):
            agent_path = repo_root / ".claude" / "agents" / f"{legacy_role_name}.md"
            if not agent_path.is_file():
                continue
            for server_name in _parse_agent_mcp_servers(agent_path):
                if server_name not in merged:
                    merged.append(server_name)
        return merged

    legacy_role_name = ROLE_DEFAULT_SOURCE_MAP.get(role_name)
    if not legacy_role_name:
        return []

    agent_path = repo_root / ".claude" / "agents" / f"{legacy_role_name}.md"
    if not agent_path.is_file():
        return []

    return _parse_agent_mcp_servers(agent_path)


def _parse_agent_mcp_servers(agent_path: Path) -> list[str]:
    in_frontmatter = False
    current_list_key: str | None = None
    mcp_servers: list[str] = []

    for raw_line in agent_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if line.strip() == "---":
            if not in_frontmatter:
                in_frontmatter = True
                continue
            break
        if not in_frontmatter:
            continue
        stripped = line.strip()
        if current_list_key == "mcpServers" and stripped.startswith("- "):
            mcp_servers.append(stripped[2:].strip())
            continue
        current_list_key = None
        if stripped.startswith("mcpServers:"):
            value = stripped.split(":", 1)[1].strip()
            if value == "[]":
                mcp_servers = []
            else:
                current_list_key = "mcpServers"
    return mcp_servers
