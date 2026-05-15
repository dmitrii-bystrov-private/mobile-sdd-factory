"""Prompt assembly helpers for persistent roles."""

from __future__ import annotations

import json


def base_role_prompt(role_name: str) -> str:
    return (
        "You are a persistent SDD Factory role.\n"
        f"Role: {role_name}\n"
        "Operate only on coordinator-routed work with deterministic hydration.\n"
    )


def role_runtime_rules(role_name: str) -> str:
    if role_name == "implementer":
        return (
            "Role-specific rules:\n"
            "- Read all routed spec inputs completely before writing code.\n"
            "- Use RAG tools first for code exploration; use plain filesystem search only for structural queries.\n"
            "- If the routed work is a narrow correction pass, keep scope limited to the listed issues unless a tiny directly-related change is required.\n"
            "- Do not run workflow-level build/test/lint gates here unless the routed work explicitly requires a narrow task-specific check.\n"
            "- Final test+lint gate remains deferred to the coordinator.\n\n"
        )
    return ""


def role_handoff_prompt(
    role_name: str,
    instruction: str,
    hydration_payload: dict[str, str | int | None],
    prompt_mode: str = "full",
) -> str:
    if prompt_mode == "bootstrap":
        prefix = (
            f"{base_role_prompt(role_name)}\n"
            "Bootstrap instructions:\n"
            "- Read AGENTS.md/CLAUDE.md in the current directory now.\n"
            "- Establish your role context from that durable file and keep it across later routed work.\n"
            "- On later rounds, do not reread the whole world from zero unless the coordinator explicitly tells you to.\n\n"
        )
    elif prompt_mode == "continuation":
        prefix = (
            f"Continue from your existing {role_name} role context in this persistent task session.\n"
            "Do not reinitialize from scratch. Use your existing role context plus the new routed work below.\n\n"
        )
    else:
        prefix = f"{base_role_prompt(role_name)}\n"
    return (
        f"{prefix}"
        f"{role_runtime_rules(role_name)}"
        "Current routed work:\n"
        f"{instruction}\n\n"
        "For intermediate progress updates, you may emit:\n"
        'SDD_PROGRESS: {"status":"in_progress","message":"short progress update","progress":25}\n'
        "If you hit a runtime/tooling problem and need operator visibility, emit:\n"
        'SDD_ERROR: {"summary":"short error summary","details":"optional detail"}\n\n'
        "When you reach a terminal outcome for this routed work, emit one line in this exact form:\n"
        'SDD_OUTPUT: {"output_type":"completed","payload":{"summary":"short result"}}\n'
        "For verification failures, emit:\n"
        'SDD_OUTPUT: {"output_type":"failed","payload":{"summary":"short result","failures":["..."]}}\n\n'
        "Hydration payload:\n"
        f"{json.dumps(hydration_payload, indent=2, sort_keys=True)}\n"
    )
