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

    def get_issue_status(self, task_key: str) -> CommandResult:
        return self.runner.run(
            [
                "acli",
                "jira",
                "workitem",
                "view",
                task_key,
                "--fields",
                "status",
                "--json",
            ],
            cwd=self.repo_root,
        )

    def create_subtasks(self, task_key: str, plan_dir: Path) -> CommandResult:
        return self.runner.run(
            [
                "bash",
                "scripts/create-subtasks-batch.sh",
                "--parent",
                task_key,
                "--plan-dir",
                str(plan_dir),
            ],
            cwd=self.repo_root,
        )

    def create_issue(
        self,
        project: str,
        issue_type: str,
        summary: str,
        description_file: Path,
    ) -> CommandResult:
        return self.runner.run(
            [
                "bash",
                "scripts/create-issue.sh",
                "--project",
                project,
                "--type",
                issue_type,
                "--summary",
                summary,
                "--description-file",
                str(description_file),
            ],
            cwd=self.repo_root,
        )

    def send_to_test(self, task_key: str) -> CommandResult:
        return self.runner.run(["bash", "scripts/commit-and-resolve.sh", task_key], cwd=self.repo_root)
