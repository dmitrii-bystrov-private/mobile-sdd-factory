"""Session-scoped runtime configuration for launcher-backed roles."""

from __future__ import annotations

from pathlib import Path

from backend.coordinator.intake import IntakeError
from factory.doctor.runtime_capabilities import build_runtime_capabilities


ROLE_DEFAULT_SOURCE_MAP = {
    "implementer": "implementer",
    "bug-fixer": "bug-fixer",
    "task-coordinator": None,
    "verification-coordinator": "final-verifier",
    "code-reviewer": "code-reviewer",
    "proposal-context-worker": "proposal-collector",
    "requirements-clarifier-worker": "requirements-clarifier",
    "acceptance-criteria-worker": "acceptance-criteria-writer",
    "constraints-worker": "constraints-definer",
    "spec-verifier-worker": "spec-verifier",
    "story-spec-worker": None,
    "task-decomposer-worker": "task-decomposer",
}


def normalize_role_runtime_config(
    *,
    repo_root: Path,
    role_names: list[str],
    provided: dict[str, dict[str, str]] | None,
) -> dict[str, dict[str, str]]:
    capabilities = build_runtime_capabilities(repo_root=repo_root)
    runners_by_name = {item["runner"]: item for item in capabilities["runners"]}
    legacy_defaults = {item["role_name"]: item for item in capabilities["legacy_role_defaults"]}
    available_runners = set(capabilities["available_runners"])
    default_runner = capabilities["default_runner"] or ("claude" if "claude" in runners_by_name else next(iter(runners_by_name), "claude"))

    unknown_roles = sorted(set((provided or {}).keys()) - set(role_names))
    if unknown_roles:
        raise IntakeError(f"Role runtime config contains unknown roles: {', '.join(unknown_roles)}")

    normalized: dict[str, dict[str, str]] = {}
    for role_name in role_names:
        override = dict((provided or {}).get(role_name, {}))
        runner = override.get("runner") or default_runner
        if runner not in runners_by_name:
            raise IntakeError(f"Unsupported runner for {role_name}: {runner}")
        if runner not in available_runners:
            raise IntakeError(f"Runner for {role_name} is not available locally: {runner}")

        runner_capability = runners_by_name[runner]
        models = runner_capability.get("models", [])
        model_ids = [item["id"] for item in models]
        legacy_key = ROLE_DEFAULT_SOURCE_MAP.get(role_name)
        legacy_default = legacy_defaults.get(legacy_key) if legacy_key is not None else None

        default_model = (
            (legacy_default or {}).get("model")
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
        effort = (
            override.get("effort")
            or (legacy_default or {}).get("effort")
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
