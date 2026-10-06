#!/usr/bin/env python3
"""Shared acceptance runtime defaults for live role configurations."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable


_DEFAULTS_PATH = Path(__file__).with_name("runtime-defaults.json")


def _load_defaults() -> dict:
    payload = json.loads(_DEFAULTS_PATH.read_text())
    if not isinstance(payload, dict):
        raise RuntimeError(f"Invalid acceptance runtime defaults in {_DEFAULTS_PATH}")
    return payload


def acceptance_default_runner() -> str:
    env_value = os.environ.get("SDD_FACTORY_ACCEPTANCE_DEFAULT_RUNNER", "").strip()
    if env_value:
        return env_value
    payload = _load_defaults()
    configured = str(payload.get("default_runner", "claude")).strip()
    return configured or "claude"


def acceptance_runner_config(runner: str) -> dict[str, str]:
    normalized_runner = runner.strip() or acceptance_default_runner()
    payload = _load_defaults()
    runner_defaults = payload.get("runner_defaults", {})
    if not isinstance(runner_defaults, dict):
        raise RuntimeError(f"Invalid runner_defaults in {_DEFAULTS_PATH}")
    configured = runner_defaults.get(normalized_runner, {})
    if not isinstance(configured, dict):
        configured = {}

    env_prefix = f"SDD_FACTORY_ACCEPTANCE_{normalized_runner.upper()}"
    model = str(
        os.environ.get(f"{env_prefix}_MODEL")
        or configured.get("model")
        or ("sonnet" if normalized_runner == "claude" else "gpt-5.3-codex-spark")
    ).strip()
    effort = str(
        os.environ.get(f"{env_prefix}_EFFORT")
        or configured.get("effort")
        or "medium"
    ).strip()

    return {
        "runner": normalized_runner,
        "model": model,
        "effort": effort,
    }


def acceptance_role_config(
    role_names: Iterable[str],
    *,
    runner_overrides: dict[str, str] | None = None,
) -> dict[str, dict[str, str]]:
    role_config: dict[str, dict[str, str]] = {}
    default_runner = acceptance_default_runner()
    for role_name in role_names:
        runner = (runner_overrides or {}).get(role_name, default_runner)
        role_config[role_name] = acceptance_runner_config(runner)
    return role_config
