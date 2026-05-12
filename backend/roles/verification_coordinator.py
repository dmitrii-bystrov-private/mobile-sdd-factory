"""Verification-coordinator role helpers."""

from __future__ import annotations

from backend.roles.prompts import base_role_prompt


def verification_coordinator_prompt() -> str:
    return base_role_prompt("verification-coordinator")
