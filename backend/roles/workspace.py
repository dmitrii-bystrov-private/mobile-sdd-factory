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


def _task_artifacts_root(workdir_root: Path, task_key: str) -> Path:
    return workdir_root / "factory-artifacts" / task_key


def _role_relevant_paths(role_name: str) -> list[str]:
    if role_name == "implementer":
        return [
            "- Task repo worktree: `{task_repo_root}`",
            "- Task snapshot metadata: `{task_snapshot_root}`",
            "- Task artifacts and coordinator outputs: `{task_artifacts_root}`",
            "- Main repo scripts: `{repo_root}/scripts`",
            "- Shared knowledge base: `{repo_root}/knowledge`",
        ]
    if role_name == "verification-coordinator":
        return [
            "- Task repo worktree: `{task_repo_root}`",
            "- Task artifacts and verification outputs: `{task_artifacts_root}`",
            "- Build/test/lint wrappers: `{repo_root}/scripts/run-build.sh`, `{repo_root}/scripts/run-test.sh`, `{repo_root}/scripts/run-lint.sh`",
            "- Shared knowledge base: `{repo_root}/knowledge`",
        ]
    if role_name == "code-reviewer":
        return [
            "- Task repo worktree: `{task_repo_root}`",
            "- Task snapshot metadata: `{task_snapshot_root}`",
            "- Task artifacts and review outputs: `{task_artifacts_root}`",
            "- Project conventions: `{repo_root}/CLAUDE.md`, `{repo_root}/.claude/`",
            "- Shared knowledge base: `{repo_root}/knowledge`",
        ]
    if role_name == "story-spec-worker":
        return [
            "- Task repo worktree: `{task_repo_root}`",
            "- Task snapshot metadata: `{task_snapshot_root}`",
            "- Task artifacts and planning outputs: `{task_artifacts_root}`",
            "- Project conventions and templates: `{repo_root}/CLAUDE.md`, `{repo_root}/.claude/`",
            "- Shared knowledge base: `{repo_root}/knowledge`",
        ]
    if role_name == "bug-analysis-worker":
        return [
            "- Task repo worktree: `{task_repo_root}`",
            "- Task snapshot metadata: `{task_snapshot_root}`",
            "- Task artifacts and bug-analysis outputs: `{task_artifacts_root}`",
            "- Project conventions and templates: `{repo_root}/CLAUDE.md`, `{repo_root}/.claude/`",
            "- Shared knowledge base: `{repo_root}/knowledge`",
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
    if role_name == "story-spec-worker":
        return [
            "- You execute one bounded story-spec preparation task for one task session.",
            "- Produce the routed planning/spec result and then stop; you do not remain the owner of later implementation work.",
            "- You should not assume persistence across unrelated tasks or later implementation rounds.",
        ]
    if role_name == "bug-analysis-worker":
        return [
            "- You execute one bounded bug-analysis task for one task session.",
            "- Produce the routed analysis result and then stop; you do not remain the owner of later implementation work.",
            "- You should not assume persistence across unrelated tasks or later implementation rounds.",
        ]
    return [
        "- You operate only on coordinator-routed work for one task session.",
        "- You should not infer responsibilities outside your current role.",
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
            task_artifacts_root=_task_artifacts_root(workdir_root, task_key),
        )
        for line in _role_relevant_paths(role_name)
    ]
    responsibility = _role_responsibility(role_name)
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
        ]
    ) + "\n"


class RoleWorkspaceManager:
    """Create isolated persistent workspaces for long-running roles."""

    def __init__(self, runtime_root: Path, repo_root: Path, workdir_root: Path) -> None:
        self.runtime_root = runtime_root
        self.repo_root = repo_root
        self.workdir_root = workdir_root

    def session_root(self, task_key: str) -> Path:
        return self.runtime_root / "role-workspaces" / task_key

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
