"""Adapters for deterministic verification commands."""

from __future__ import annotations

from pathlib import Path

from backend.tools.command_runner import CommandResult, CommandRunner


class VerificationAdapter:
    def __init__(self, runner: CommandRunner, repo_root: Path) -> None:
        self.runner = runner
        self.repo_root = repo_root

    def run_test(self, task_key: str) -> CommandResult:
        return self.runner.run(["bash", "scripts/run-test.sh", task_key], cwd=self.repo_root)

    def run_lint(self, task_key: str) -> CommandResult:
        return self.runner.run(["bash", "scripts/run-lint.sh", task_key], cwd=self.repo_root)

    def run_build(self, task_key: str) -> CommandResult:
        return self.runner.run(["bash", "scripts/run-build.sh", task_key], cwd=self.repo_root)
