"""Adapter around the iOS simulator launch helper."""

from __future__ import annotations

from pathlib import Path

from backend.tools.command_runner import CommandResult, CommandRunner


class IOSAppLauncher:
    def __init__(self, runner: CommandRunner, repo_root: Path) -> None:
        self.runner = runner
        self.repo_root = repo_root

    def launch(self, task_key: str) -> CommandResult:
        return self.runner.run(["bash", "scripts/ios-launch.sh", task_key], cwd=self.repo_root)
