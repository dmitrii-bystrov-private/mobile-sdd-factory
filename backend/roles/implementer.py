"""Implementer role helpers."""

from __future__ import annotations

from backend.roles.prompts import base_role_prompt


def implementer_prompt() -> str:
    return base_role_prompt("implementer")
