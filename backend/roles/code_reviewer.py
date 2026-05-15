"""Code reviewer role helpers."""

from __future__ import annotations

from backend.roles.prompts import base_role_prompt


def code_reviewer_prompt() -> str:
    return base_role_prompt("code-reviewer")
