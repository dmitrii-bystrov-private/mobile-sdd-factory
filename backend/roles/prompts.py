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
    if role_name == "bug-fixer":
        return (
            "Role-specific rules:\n"
            "- Preserve bug-specific context across analysis, fix, and follow-up rounds inside this same persistent role session.\n"
            "- In `analysis-only` mode, read task description/comments first, investigate the code path, write or update `spec/bug-analysis.md`, and stop before product-code changes when confidence is low or the routed pass is analysis-only.\n"
            "- In `fix-only` mode, read the saved `spec/bug-analysis.md` first and use it as the durable bug context for the fix.\n"
            "- If an `Issues file:` path is routed, treat it as the primary narrow-scope input for this round.\n"
            "- If `Follow-up comments:` are routed, prioritize the latest follow-up comments over redoing the original bug analysis from scratch.\n"
            "- Keep bug-fix follow-up and correction rounds tightly scoped to the routed issues/comments unless a tiny directly-related adjustment is required.\n"
            "- Leave workflow-level test+lint verification to the coordinator.\n\n"
        )
    if role_name == "code-reviewer":
        return (
            "Role-specific rules:\n"
            "- Start from the current diff and review only the touched changes.\n"
            "- If previous review summaries are provided, read them first and do not re-flag already raised issues.\n"
            "- Read only the convention sources relevant to the touched diff area.\n"
            "- Keep the output compact and optimized for a narrow fixer pass.\n\n"
        )
    if role_name == "proposal-context-worker":
        return (
            "Role-specific rules:\n"
            "- Treat this role as a bounded one-shot worker: collect proposal/context foundations, write the routed result, and exit.\n"
            "- Read snapshot description/comments first; read repo sources only when they are directly needed to ground the proposal/context result.\n"
            "- Keep the output compact and downstream-oriented so the later story-spec worker can build on it instead of redoing the same discovery.\n\n"
        )
    if role_name == "requirements-clarifier-worker":
        return (
            "Role-specific rules:\n"
            "- Treat this role as a bounded one-shot worker: clarify requirements, write the routed result, and exit.\n"
            "- Start from the proposal/context foundations and resolve ambiguities, assumptions, edge cases, and out-of-scope boundaries needed for implementation.\n"
            "- Keep the output compact and downstream-oriented so the later story-spec worker can focus on implementation structure rather than unresolved requirements.\n\n"
        )
    if role_name == "acceptance-criteria-worker":
        return (
            "Role-specific rules:\n"
            "- Treat this role as a bounded one-shot worker: prepare acceptance criteria, write the routed result, and exit.\n"
            "- Start from the proposal plus clarified requirements and cover happy paths, edge cases, and error scenarios needed for later implementation and verification.\n"
            "- Keep the output compact and downstream-oriented so the later story-spec worker can focus on implementation structure rather than behavioral coverage gaps.\n\n"
        )
    if role_name == "verification-coordinator":
        return (
            "Role-specific rules:\n"
            "- Run only the workflow-level deterministic verification gate for the current task.\n"
            "- Use `run-test.sh` and `run-lint.sh`; do not run `run-build.sh` here.\n"
            "- Treat every verification round as a fresh gate and refresh the verification evidence.\n"
            "- Do not modify code, tests, docs, or prompts; summarize failures and stop.\n\n"
        )
    return ""


def role_handoff_prompt(
    role_name: str,
    instruction: str,
    hydration_payload: dict[str, str | int | None],
    prompt_mode: str = "full",
) -> str:
    if prompt_mode == "live_bootstrap":
        return (
            "Read AGENTS.md/CLAUDE.md in the current directory now and use it as the primary durable role contract for this session.\n"
            "Do not rebuild your role from scratch outside that file unless the coordinator explicitly tells you to.\n\n"
            "Read `HYDRATION.json` in the current directory for machine-readable per-round context before acting.\n\n"
            "Current routed work:\n"
            f"{instruction}\n\n"
        )
    if prompt_mode == "live_continuation":
        return (
            "Continue from your existing AGENTS.md-based role context in this persistent task session.\n"
            "Use the new routed work below without reinitializing your full role definition from scratch.\n\n"
            "If the same routed work was already in progress before an interruption, resume and finish that unfinished work now instead of restarting the analysis from zero.\n\n"
            "Refresh your per-round machine-readable context from `HYDRATION.json` in the current directory before acting.\n\n"
            "Current routed work:\n"
            f"{instruction}\n\n"
        )
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
        "Preferred terminal outcome path:\n"
        "- Write `RESULT.json` in the current directory using the same JSON object you would place after `SDD_OUTPUT:`.\n"
        "- For example: `{\"output_type\":\"completed\",\"payload\":{\"summary\":\"short result\"}}`\n"
        "- Use `failed` plus `failures` when verification/correction output must report failures.\n\n"
        "When you reach a terminal outcome for this routed work, emit one line in this exact form:\n"
        'SDD_OUTPUT: {"output_type":"completed","payload":{"summary":"short result"}}\n'
        "For verification failures, emit:\n"
        'SDD_OUTPUT: {"output_type":"failed","payload":{"summary":"short result","failures":["..."]}}\n\n'
        "Hydration payload:\n"
        f"{json.dumps(hydration_payload, indent=2, sort_keys=True)}\n"
    )
