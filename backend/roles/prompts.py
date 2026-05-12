"""Prompt assembly helpers for persistent roles."""

from __future__ import annotations

import json


def base_role_prompt(role_name: str) -> str:
    return (
        "You are a persistent SDD Factory role.\n"
        f"Role: {role_name}\n"
        "Operate only on coordinator-routed work with deterministic hydration.\n"
    )


def role_handoff_prompt(
    role_name: str,
    instruction: str,
    hydration_payload: dict[str, str | int | None],
) -> str:
    return (
        f"{base_role_prompt(role_name)}\n"
        "Current routed work:\n"
        f"{instruction}\n\n"
        "Hydration payload:\n"
        f"{json.dumps(hydration_payload, indent=2, sort_keys=True)}\n"
    )
