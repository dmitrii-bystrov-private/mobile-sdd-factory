"""Persistent role workspace scaffolding."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True, slots=True)
class RoleWorkspace:
    role_name: str
    directory: Path
    agents_path: Path
    claude_path: Path


def _task_snapshot_root(workdir_root: Path, task_key: str) -> Path:
    return workdir_root / task_key


def _task_repo_root(workdir_root: Path, task_key: str) -> Path:
    return _task_snapshot_root(workdir_root, task_key) / "repo"


def _task_runtime_root(workdir_root: Path, task_key: str) -> Path:
    return _task_snapshot_root(workdir_root, task_key) / "runtime"


def _task_tmp_root(workdir_root: Path, task_key: str) -> Path:
    return _task_snapshot_root(workdir_root, task_key) / "tmp"


def _task_knowledge_root(workdir_root: Path, task_key: str) -> Path:
    return _task_repo_root(workdir_root, task_key) / "knowledge"


def _task_artifacts_root(workdir_root: Path, task_key: str) -> Path:
    return workdir_root / "factory-artifacts" / task_key


def _role_relevant_paths(role_name: str) -> list[str]:
    if role_name == "implementer":
        return [
            "- Task repo worktree: `{task_repo_root}`",
            "- Task snapshot metadata: `{task_snapshot_root}`",
            "- Task-local runtime root: `{task_runtime_root}`",
            "- Task-local temp root: `{task_tmp_root}`",
            "- Task artifacts and coordinator outputs: `{task_artifacts_root}`",
            "- Main repo scripts: `{repo_root}/scripts`",
            "- Project conventions: `{task_repo_root}/CLAUDE.md`, `{task_repo_root}/.claude/`",
            "- Project knowledge base: `{task_knowledge_root}`",
        ]
    if role_name == "bug-fixer":
        return [
            "- Task repo worktree: `{task_repo_root}`",
            "- Task snapshot metadata: `{task_snapshot_root}`",
            "- Task description and comments: `{task_snapshot_root}/description.md`, `{task_snapshot_root}/comments.md`",
            "- Bug analysis report target: `{task_snapshot_root}/spec/bug-analysis.md`",
            "- Task-local runtime root: `{task_runtime_root}`",
            "- Task-local temp root: `{task_tmp_root}`",
            "- Task artifacts and bug analysis outputs: `{task_artifacts_root}`",
            "- Main repo scripts: `{repo_root}/scripts`",
            "- Project conventions: `{task_repo_root}/CLAUDE.md`, `{task_repo_root}/.claude/`",
            "- Project knowledge base: `{task_knowledge_root}`",
        ]
    if role_name == "verification-coordinator":
        return [
            "- Task repo worktree: `{task_repo_root}`",
            "- Task-local runtime root: `{task_runtime_root}`",
            "- Task-local temp root: `{task_tmp_root}`",
            "- Task artifacts and verification outputs: `{task_artifacts_root}`",
            "- Build/test/lint wrappers: `{repo_root}/scripts/run-build.sh`, `{repo_root}/scripts/run-test.sh`, `{repo_root}/scripts/run-lint.sh`",
            "- Final verification report target: `{task_snapshot_root}/spec/final-verification.md`",
            "- Project knowledge base: `{task_knowledge_root}`",
        ]
    if role_name == "code-reviewer":
        return [
            "- Task repo worktree: `{task_repo_root}`",
            "- Task snapshot metadata: `{task_snapshot_root}`",
            "- Task-local runtime root: `{task_runtime_root}`",
            "- Task-local temp root: `{task_tmp_root}`",
            "- Task artifacts and review outputs: `{task_artifacts_root}`",
            "- Project conventions: `{task_repo_root}/CLAUDE.md`, `{task_repo_root}/.claude/`",
            "- Project knowledge base: `{task_knowledge_root}`",
        ]
    if role_name == "proposal-context-worker":
        return [
            "- Task snapshot metadata: `{task_snapshot_root}`",
            "- Proposal target: `{task_snapshot_root}/spec/proposal.md`",
            "- Context directory: `{task_snapshot_root}/spec/context`",
            "- Task repo worktree: `{task_repo_root}`",
            "- Task-local runtime root: `{task_runtime_root}`",
            "- Task-local temp root: `{task_tmp_root}`",
            "- Project conventions and templates: `{task_repo_root}/CLAUDE.md`, `{task_repo_root}/.claude/`",
            "- Project knowledge base: `{task_knowledge_root}`",
        ]
    if role_name == "requirements-clarifier-worker":
        return [
            "- Task snapshot metadata: `{task_snapshot_root}`",
            "- Proposal input: `{task_snapshot_root}/spec/proposal.md`",
            "- Requirements target: `{task_snapshot_root}/spec/requirements.md`",
            "- Context directory: `{task_snapshot_root}/spec/context`",
            "- Task repo worktree: `{task_repo_root}`",
            "- Task-local runtime root: `{task_runtime_root}`",
            "- Task-local temp root: `{task_tmp_root}`",
            "- Project conventions and templates: `{task_repo_root}/CLAUDE.md`, `{task_repo_root}/.claude/`",
            "- Project knowledge base: `{task_knowledge_root}`",
        ]
    if role_name == "acceptance-criteria-worker":
        return [
            "- Task snapshot metadata: `{task_snapshot_root}`",
            "- Proposal input: `{task_snapshot_root}/spec/proposal.md`",
            "- Requirements input: `{task_snapshot_root}/spec/requirements.md`",
            "- Acceptance criteria target: `{task_snapshot_root}/spec/acceptance_criteria.md`",
            "- Context directory: `{task_snapshot_root}/spec/context`",
            "- Task repo worktree: `{task_repo_root}`",
            "- Task-local runtime root: `{task_runtime_root}`",
            "- Task-local temp root: `{task_tmp_root}`",
            "- Project conventions and templates: `{task_repo_root}/CLAUDE.md`, `{task_repo_root}/.claude/`",
            "- Project knowledge base: `{task_knowledge_root}`",
        ]
    if role_name == "story-spec-worker":
        return [
            "- Task repo worktree: `{task_repo_root}`",
            "- Task snapshot metadata: `{task_snapshot_root}`",
            "- Task-local runtime root: `{task_runtime_root}`",
            "- Task-local temp root: `{task_tmp_root}`",
            "- Task artifacts and planning outputs: `{task_artifacts_root}`",
            "- Project conventions and templates: `{task_repo_root}/CLAUDE.md`, `{task_repo_root}/.claude/`",
            "- Project knowledge base: `{task_knowledge_root}`",
            "- Completion boundary: stop after producing the routed planning/spec result for this task session.",
        ]
    return [
        "- Task snapshot metadata: `{task_snapshot_root}`",
        "- Task artifacts: `{task_artifacts_root}`",
        "- Main repo scripts: `{repo_root}/scripts`",
    ]


def _role_responsibility(role_name: str) -> list[str]:
    if role_name == "implementer":
        return [
            "- You execute routed implementation work for one task session.",
            "- You focus only on the currently assigned work item.",
            "- You should not reason about other agents or hidden orchestration concerns.",
        ]
    if role_name == "bug-fixer":
        return [
            "- You execute unified bug work for one bug task session.",
            "- You retain bug-specific context across analysis, fix, and follow-up rounds.",
            "- You should not reason about other agents or hidden orchestration concerns.",
        ]
    if role_name == "verification-coordinator":
        return [
            "- You execute routed verification work for one task session.",
            "- You validate changes through deterministic checks and review the resulting evidence.",
            "- You should not take ownership of implementation work except through explicit coordinator routing.",
        ]
    if role_name == "code-reviewer":
        return [
            "- You execute routed code review work for one task session.",
            "- You review only the routed task changes and produce compact review outcomes.",
            "- Across repeated passes, retain reviewer context for the same task instead of reinitializing from zero.",
        ]
    if role_name == "proposal-context-worker":
        return [
            "- You execute one bounded proposal/context preparation task for one story session.",
            "- Produce the routed proposal/context result and then stop; you do not remain the owner of later planning or implementation work.",
            "- You should not assume persistence across unrelated tasks or later implementation rounds.",
        ]
    if role_name == "requirements-clarifier-worker":
        return [
            "- You execute one bounded requirements-clarification task for one story session.",
            "- Produce the routed requirements result and then stop; you do not remain the owner of later planning or implementation work.",
            "- You should not assume persistence across unrelated tasks or later implementation rounds.",
        ]
    if role_name == "acceptance-criteria-worker":
        return [
            "- You execute one bounded acceptance-criteria preparation task for one story session.",
            "- Produce the routed acceptance-criteria result and then stop; you do not remain the owner of later planning or implementation work.",
            "- You should not assume persistence across unrelated tasks or later implementation rounds.",
        ]
    if role_name == "story-spec-worker":
        return [
            "- You execute one bounded story-spec preparation task for one task session.",
            "- Produce the routed planning/spec result and then stop; you do not remain the owner of later implementation work.",
            "- You should not assume persistence across unrelated tasks or later implementation rounds.",
        ]
    return [
        "- You operate only on coordinator-routed work for one task session.",
        "- You should not infer responsibilities outside your current role.",
    ]


def _role_operating_rules(role_name: str) -> list[str]:
    if role_name == "implementer":
        return [
            "- Read all routed spec inputs before writing code.",
            "- Use RAG tools first for code exploration; fall back to filesystem search only for structural queries.",
            "- If the routed input is a narrow correction pass, keep scope limited to the listed issues unless a tiny directly related change is required.",
            "- Do not run workflow-level `run-build.sh`, `run-test.sh`, or `run-lint.sh` unless the routed work explicitly requires a narrow task-specific check.",
            "- Treat final test+lint verification as deferred to the coordinator.",
        ]
    if role_name == "bug-fixer":
        return [
            "- Preserve bug-specific context across analysis, fix, and follow-up rounds.",
            "- Support the routed bug modes inside one runtime identity: `analysis-only` before code changes, then `fix-only` for implementation, correction, and follow-up rounds.",
            "- In `analysis-only` mode, read task description/comments first, investigate the code path, write or update `spec/bug-analysis.md`, and stop before product-code changes when confidence is low or when the coordinator routed an analysis-only pass.",
            "- In `fix-only` mode, read the saved `spec/bug-analysis.md` first and treat it as the durable bug context unless a routed issues file or follow-up comments narrow the scope further.",
            "- If an `Issues file:` path is routed, treat it as the primary narrow-scope input for this round and keep the fix limited to those listed issues unless a tiny directly-related adjustment is required.",
            "- If `Follow-up comments:` are routed, prioritize the latest follow-up comments over redoing the original bug analysis from scratch.",
            "- Keep the current bug task scoped to the routed pass, saved bug analysis, and latest follow-up context.",
            "- Write or update `spec/bug-analysis.md` in bug-analysis rounds; keep final workflow-level verification deferred to the coordinator.",
            "- Treat final test+lint verification as deferred to the coordinator.",
        ]
    if role_name == "verification-coordinator":
        return [
            "- Run only deterministic verification work for the routed task session.",
            "- Treat `run-test.sh` and `run-lint.sh` as the workflow-level verification gate; do not run `run-build.sh` here.",
            "- Always treat each verification round as a fresh deterministic gate and refresh the verification evidence.",
            "- Keep the role evidence-first: summarize failures, but do not attempt fixes.",
            "- Do not modify product code.",
        ]
    if role_name == "code-reviewer":
        return [
            "- Review only the routed diff and conventions relevant to that diff.",
            "- Read previous review summaries first when they are provided and do not re-flag the same issue twice.",
            "- Read only the convention files relevant to the touched diff area; do not broaden the review scope speculatively.",
            "- Keep outputs compact and fixer-oriented.",
            "- Do not re-flag issues that were already raised in previous review passes when that context is provided.",
        ]
    if role_name == "proposal-context-worker":
        return [
            "- Treat this role as a bounded one-shot worker: collect proposal/context foundations, write the routed result, and exit.",
            "- Read snapshot description/comments first; read repo sources only when they are directly needed to ground the proposal/context result.",
            "- Keep the output compact and downstream-oriented so the later story-spec worker can build on it instead of redoing the same discovery.",
        ]
    if role_name == "requirements-clarifier-worker":
        return [
            "- Treat this role as a bounded one-shot worker: clarify requirements, write the routed result, and exit.",
            "- Start from the proposal/context foundations and resolve ambiguities, assumptions, edge cases, and out-of-scope boundaries needed for implementation.",
            "- Keep the output compact and downstream-oriented so the later story-spec worker can focus on implementation structure rather than unresolved requirements.",
        ]
    if role_name == "acceptance-criteria-worker":
        return [
            "- Treat this role as a bounded one-shot worker: prepare acceptance criteria, write the routed result, and exit.",
            "- Start from the proposal plus clarified requirements and cover happy paths, edge cases, and error scenarios needed for later implementation and verification.",
            "- Keep the output compact and downstream-oriented so the later story-spec worker can focus on implementation structure rather than behavioral coverage gaps.",
        ]
    if role_name == "story-spec-worker":
        return [
            "- Treat this role as a bounded one-shot worker: launch, produce the routed spec result, and exit.",
            "- Read only the planning/spec inputs relevant to the current task.",
            "- Do not retain ownership after the planning/spec result is produced.",
        ]
    return [
        "- Stay within the routed task scope and use coordinator instructions as the active payload.",
    ]


def build_role_agents_md(
    *,
    role_name: str,
    task_key: str,
    repo_root: Path,
    workdir_root: Path,
) -> str:
    relevant_paths = [
        line.format(
            repo_root=repo_root,
            task_snapshot_root=_task_snapshot_root(workdir_root, task_key),
            task_repo_root=_task_repo_root(workdir_root, task_key),
            task_runtime_root=_task_runtime_root(workdir_root, task_key),
            task_tmp_root=_task_tmp_root(workdir_root, task_key),
            task_knowledge_root=_task_knowledge_root(workdir_root, task_key),
            task_artifacts_root=_task_artifacts_root(workdir_root, task_key),
        )
        for line in _role_relevant_paths(role_name)
    ]
    responsibility = _role_responsibility(role_name)
    operating_rules = _role_operating_rules(role_name)
    return "\n".join(
        [
            f"# {role_name} AGENTS",
            "",
            "## Role",
            "",
            f"- Role name: `{role_name}`",
            f"- Task session: `{task_key}`",
            "",
            "## Responsibility",
            "",
            *responsibility,
            "",
            "## Relevant Paths",
            "",
            *relevant_paths,
            "",
            "## Runtime Rules",
            "",
            "- Start from this role workspace and keep your work scoped to the routed task session.",
            "- Re-read this file after context compaction or if role boundaries become unclear.",
            "- Use coordinator hydration and routed work instructions as the current task payload.",
            "- Treat this file as durable role context; treat routed handoff prompts as per-work instructions.",
            "",
            "## Operating Rules",
            "",
            *operating_rules,
        ]
    ) + "\n"


class RoleWorkspaceManager:
    """Create isolated persistent workspaces for long-running roles."""

    def __init__(self, runtime_root: Path, repo_root: Path, workdir_root: Path) -> None:
        self.runtime_root = runtime_root
        self.repo_root = repo_root
        self.workdir_root = workdir_root

    def session_root(self, task_key: str) -> Path:
        return _task_runtime_root(self.workdir_root, task_key) / "role-workspaces"

    def role_directory(self, task_key: str, role_name: str) -> Path:
        return self.session_root(task_key) / role_name

    def ensure_role_workspace(self, task_key: str, role_name: str) -> RoleWorkspace:
        directory = self.role_directory(task_key, role_name)
        directory.mkdir(parents=True, exist_ok=True)

        agents_path = directory / "AGENTS.md"
        agents_path.write_text(
            build_role_agents_md(
                role_name=role_name,
                task_key=task_key,
                repo_root=self.repo_root,
                workdir_root=self.workdir_root,
            )
        )

        claude_path = directory / "CLAUDE.md"
        if claude_path.exists() or claude_path.is_symlink():
            claude_path.unlink()
        relative_target = os.path.relpath(agents_path, start=directory)
        claude_path.symlink_to(relative_target)

        return RoleWorkspace(
            role_name=role_name,
            directory=directory,
            agents_path=agents_path,
            claude_path=claude_path,
        )
