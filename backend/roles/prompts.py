"""Prompt assembly helpers for persistent roles."""

from __future__ import annotations


def base_role_prompt(role_name: str) -> str:
    return (
        "You are a persistent SDD Factory role.\n"
        f"Role: {role_name}\n"
        "Operate only on coordinator-routed work with deterministic hydration.\n"
    )
