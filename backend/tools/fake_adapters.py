"""Fake adapters for live acceptance and local operator-surface validation."""

from __future__ import annotations

from pathlib import Path

from backend.tools.command_runner import CommandResult


class FakeJiraAdapter:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.status_by_task: dict[str, str] = {}
        self.created_issue_counter = 0

    def resolve_parent(self, task_key: str) -> CommandResult:
        return CommandResult(
            command=["fake_resolve_parent", task_key],
            returncode=0,
            stdout=f"{task_key}\n",
            stderr="",
        )

    def get_issue_type(self, task_key: str) -> CommandResult:
        return CommandResult(
            command=["fake_get_issue_type", task_key],
            returncode=0,
            stdout="Story\n",
            stderr="",
        )

    def get_issue_status(self, task_key: str) -> CommandResult:
        status = self.status_by_task.get(task_key, "In Progress")
        return CommandResult(
            command=["fake_get_issue_status", task_key],
            returncode=0,
            stdout=f'{{"fields": {{"status": {{"name": "{status}"}}}}}}\n',
            stderr="",
        )

    def create_subtasks(self, task_key: str, plan_dir: Path) -> CommandResult:
        return CommandResult(
            command=["fake_create_subtasks", task_key, str(plan_dir)],
            returncode=0,
            stdout=(
                "Created subtasks:\n"
                "01    IOS-90001     Build data source\n"
                "02    IOS-90002     Wire presentation layer\n"
            ),
            stderr="",
        )

    def create_issue(
        self,
        project: str,
        issue_type: str,
        summary: str,
        description_file: Path,
    ) -> CommandResult:
        del issue_type, description_file
        self.created_issue_counter += 1
        issue_key = f"{project}-{95000 + self.created_issue_counter}"
        return CommandResult(
            command=["fake_create_issue", project, summary],
            returncode=0,
            stdout=f"{issue_key} https://jira.example.com/browse/{issue_key}\n",
            stderr="",
        )

    def send_to_test(self, task_key: str) -> CommandResult:
        return CommandResult(
            command=["fake_send_to_test", task_key],
            returncode=0,
            stdout=f"Done: {task_key} -> Ready for test\n",
            stderr="",
        )


class FakeSnapshotAdapter:
    def __init__(self, repo_root: Path, workdir_root: Path) -> None:
        self.repo_root = repo_root
        self.workdir_root = workdir_root

    def run(self, task_key: str) -> CommandResult:
        task_dir = self.workdir_root / task_key
        repo_dir = task_dir / "repo"
        repo_claude_path = repo_dir / "CLAUDE.md"
        repo_claude_dir = repo_dir / ".claude"
        knowledge_dir = repo_dir / "knowledge"
        spec_dir = task_dir / "spec"
        task_dir.mkdir(parents=True, exist_ok=True)
        repo_dir.mkdir(parents=True, exist_ok=True)
        repo_claude_dir.mkdir(parents=True, exist_ok=True)
        knowledge_dir.mkdir(parents=True, exist_ok=True)
        spec_dir.mkdir(parents=True, exist_ok=True)

        if not repo_claude_path.exists():
            repo_claude_path.write_text(
                "# Project Conventions\n\n"
                "- Placeholder project-local conventions for fake acceptance snapshots.\n"
            )

        readme_path = knowledge_dir / "README.md"
        if not readme_path.exists():
            readme_path.write_text(
                "# Knowledge\n\n"
                "Project-local knowledge base for fake acceptance snapshots.\n"
            )

        statuses_path = task_dir / "statuses.md"
        if not statuses_path.exists():
            statuses_path.write_text("- [ ] Subtask 1\n- [x] Subtask 2\n")

        diff_path = spec_dir / "diff.md"
        if not diff_path.exists():
            diff_path.write_text(
                "# Structured Diff\n\n"
                "## Summary\n\n"
                "- Placeholder acceptance diff for live operator validation.\n\n"
                "## Raw Diff\n\n"
                "```diff\n"
                "+ placeholder change\n"
                "```\n"
            )

        return CommandResult(
            command=["fake_snapshot", task_key],
            returncode=0,
            stdout="snapshot ok\n",
            stderr="",
        )


class FakeGitLabAdapter:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root

    def create_mr(self, task_key: str) -> CommandResult:
        return CommandResult(
            command=["fake_create_mr", task_key],
            returncode=0,
            stdout=(
                f"Pushing branch for {task_key}\n"
                f"https://gitlab.example.com/mobile/{task_key}/-/merge_requests/42\n"
            ),
            stderr="",
        )

    def fetch_mr_comments(self, platform: str, mr_id: str) -> CommandResult:
        return CommandResult(
            command=["fake_fetch_mr_comments", platform, mr_id],
            returncode=0,
            stdout=(
                f"# Unresolved MR discussions: !{mr_id} (1 total)\n\n"
                "## Discussion 1 — file.swift:10\n\n"
                "**Reviewer:** Placeholder MR follow-up comment\n\n"
            ),
            stderr="",
        )
