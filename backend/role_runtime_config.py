"""Session-scoped runtime configuration for launcher-backed roles."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from backend.coordinator.intake import IntakeError
from backend.role_baselines import role_baselines_by_name
from backend.runtime_defaults import load_runtime_defaults
from factory.doctor.runtime_capabilities import build_runtime_capabilities

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
    role_baselines = role_baselines_by_name()
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
        role_baseline = role_baselines.get(role_name)
        baseline_model = (
            role_baseline.model
            if role_baseline is not None and role_baseline.model in model_ids
            else None
        )

        operator_default_model = (
            operator_role_default.get("model")
            if operator_role_default.get("runner") in {None, "", runner}
            else None
        )
        default_model = (
            operator_default_model
            or baseline_model
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
        baseline_effort = (
            role_baseline.effort
            if role_baseline is not None
            and baseline_model == model
            and (
                not supported_efforts
                or role_baseline.effort in supported_efforts
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
            or baseline_effort
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

    baseline = role_baselines_by_name().get(role_name)
    if baseline is None:
        return []
    return list(baseline.mcp_servers)
