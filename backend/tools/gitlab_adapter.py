"""Adapters for GitLab-related shell workflows."""

from __future__ import annotations

from pathlib import Path

from backend.tools.command_runner import CommandResult, CommandRunner


class GitLabAdapter:
    def __init__(self, runner: CommandRunner, repo_root: Path) -> None:
        self.runner = runner
        self.repo_root = repo_root

    def commit_task_state(self, task_key: str, context: str | None = None) -> CommandResult:
        command = ["bash", "scripts/commit-task-state.sh", task_key]
        if context:
            command.append(context)
        return self.runner.run(command, cwd=self.repo_root)

    def create_mr(self, task_key: str) -> CommandResult:
        return self.runner.run(["bash", "scripts/create-mr.sh", task_key], cwd=self.repo_root)
