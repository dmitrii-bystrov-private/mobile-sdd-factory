"""Project-local operator defaults for runtime role configuration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

KNOWN_ROLE_NAMES = [
    "implementer",
    "bug-fixer",
    "task-coordinator",
    "verification-coordinator",
    "code-reviewer",
    "code-scout",
    "proposal-context-worker",
    "requirements-clarifier-worker",
    "acceptance-criteria-worker",
    "constraints-worker",
    "spec-verifier-worker",
    "story-spec-worker",
    "task-decomposer-worker",
]


SETTINGS_DIR_NAME = ".sdd-factory"
LOCAL_SETTINGS_FILENAME = "settings.local.json"


def known_role_names() -> list[str]:
    return sorted(KNOWN_ROLE_NAMES)


def settings_file_path(repo_root: Path) -> Path:
    return repo_root / SETTINGS_DIR_NAME / LOCAL_SETTINGS_FILENAME


def load_runtime_defaults(repo_root: Path) -> dict[str, Any]:
    path = settings_file_path(repo_root)
    payload = _load_json_dict(path)
    runtime_defaults = payload.get("runtime_defaults") if isinstance(payload, dict) else None
    if not isinstance(runtime_defaults, dict):
        runtime_defaults = {}
    role_defaults = runtime_defaults.get("role_defaults")
    if not isinstance(role_defaults, dict):
        role_defaults = {}
    normalized_role_defaults: dict[str, dict[str, str | None]] = {}
    for role_name, value in role_defaults.items():
        if not isinstance(role_name, str) or not isinstance(value, dict):
            continue
        normalized_role_defaults[role_name] = {
            "runner": _string_or_none(value.get("runner")),
            "model": _string_or_none(value.get("model")),
            "effort": _string_or_none(value.get("effort")),
        }
    return {
        "default_runner": _string_or_none(runtime_defaults.get("default_runner")),
        "role_defaults": normalized_role_defaults,
        "known_roles": known_role_names(),
        "source_path": str(path),
    }


def save_runtime_defaults(
    repo_root: Path,
    *,
    default_runner: str | None,
    role_defaults: dict[str, dict[str, str | None]],
) -> dict[str, Any]:
    path = settings_file_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized_role_defaults: dict[str, dict[str, str]] = {}
    for role_name, value in role_defaults.items():
        if role_name not in KNOWN_ROLE_NAMES or not isinstance(value, dict):
            continue
        normalized_value = {
            "runner": _string_or_none(value.get("runner")) or "",
            "model": _string_or_none(value.get("model")) or "",
            "effort": _string_or_none(value.get("effort")) or "",
        }
        if any(normalized_value.values()):
            normalized_role_defaults[role_name] = normalized_value
    payload = {
        "runtime_defaults": {
            "default_runner": _string_or_none(default_runner),
            "role_defaults": normalized_role_defaults,
        }
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return load_runtime_defaults(repo_root)


def _load_json_dict(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _string_or_none(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None
