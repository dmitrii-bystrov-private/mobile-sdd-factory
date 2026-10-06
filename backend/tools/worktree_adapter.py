"""Helpers for task-local worktree paths and filesystem lookups."""

from __future__ import annotations

from pathlib import Path


class WorktreeAdapter:
    def __init__(self, workdir_root: Path) -> None:
        self.workdir_root = workdir_root

    def task_root(self, task_key: str) -> Path:
        return self.workdir_root / task_key

    def repo_dir(self, task_key: str) -> Path:
        return self.task_root(task_key) / "repo"
