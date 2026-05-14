"""Adapters around existing Jira-oriented shell helpers."""

from __future__ import annotations

from pathlib import Path

from backend.tools.command_runner import CommandResult, CommandRunner


class JiraAdapter:
    def __init__(self, runner: CommandRunner, repo_root: Path) -> None:
        self.runner = runner
        self.repo_root = repo_root

    def resolve_parent(self, task_key: str) -> CommandResult:
        return self.runner.run(["bash", "scripts/get-issue-parent.sh", task_key], cwd=self.repo_root)

    def get_issue_type(self, task_key: str) -> CommandResult:
        return self.runner.run(["bash", "scripts/get-issue-type.sh", task_key], cwd=self.repo_root)

    def send_to_test(self, task_key: str) -> CommandResult:
        return self.runner.run(["bash", "scripts/commit-and-resolve.sh", task_key], cwd=self.repo_root)
