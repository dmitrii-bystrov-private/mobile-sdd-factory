"""Prompt assembly helpers for role handoffs."""

from __future__ import annotations


def base_role_prompt(role_name: str) -> str:
    return (
        "You are a persistent Constellation: Agent Runtime role.\n"
        f"Role: {role_name}\n"
        "Use AGENTS.md as your durable role contract and ROUTED_WORK.md as the current task payload.\n"
    )


def role_handoff_prompt(
    role_name: str,
    instruction: str,
    hydration_payload: dict[str, str | int | None],
    prompt_mode: str = "full",
) -> str:
    work_item_id = hydration_payload.get("work_item_id")
    work_item_id_text = str(work_item_id).strip() if work_item_id is not None else ""

    if prompt_mode == "live_bootstrap":
        return (
            "Read AGENTS.md/CLAUDE.md in the current directory once now and use it as your durable role contract.\n"
            "Read HYDRATION.json for machine-readable routed IDs and paths.\n\n"
            "Current routed work:\n"
            f"{instruction}\n\n"
        )

    if prompt_mode == "live_continuation":
        return (
            "Continue from your existing role context.\n"
            "Read the updated HYDRATION.json for machine-readable routed IDs and paths.\n"
            "If this work was already in progress before an interruption, resume and finish it instead of restarting from zero.\n\n"
            "Current routed work:\n"
            f"{instruction}\n\n"
        )

    if prompt_mode == "bootstrap":
        prefix = (
            f"{base_role_prompt(role_name)}\n"
            "Bootstrap instructions:\n"
            "- Read AGENTS.md/CLAUDE.md in the current directory once now.\n"
            "- Read HYDRATION.json for machine-readable routed IDs and paths.\n\n"
        )
    elif prompt_mode == "continuation":
        prefix = (
            "Continue from your existing role context.\n"
            "Read the updated HYDRATION.json for machine-readable routed IDs and paths.\n\n"
        )
    else:
        prefix = (
            f"{base_role_prompt(role_name)}\n"
            "Read AGENTS.md/CLAUDE.md and HYDRATION.json in the current directory before acting.\n\n"
        )

    work_item_line = (
        f"Routed work item: {work_item_id_text}.\n\n"
        if work_item_id_text
        else ""
    )
    return (
        f"{prefix}"
        f"{work_item_line}"
        "Current routed work:\n"
        f"{instruction}\n"
    )
