"""Fake adapters for live acceptance and local operator-surface validation."""

from __future__ import annotations

from pathlib import Path
import subprocess

from backend.tools.command_runner import CommandResult


class FakeJiraAdapter:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.status_by_task: dict[str, str] = {}
        self.created_issue_counter = 0
        self.completed_subtasks: list[str] = []

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

    def complete_subtask(self, task_key: str) -> CommandResult:
        self.completed_subtasks.append(task_key)
        self.status_by_task[task_key] = "Ready for test"
        return CommandResult(
            command=["fake_complete_subtask", task_key],
            returncode=0,
            stdout=f"Done: {task_key} -> Ready for test\n",
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

    def _ensure_clean_task_git_repo(self, task_dir: Path) -> None:
        git_dir = task_dir / ".git"
        gitignore_path = task_dir / ".gitignore"
        gitignore_path.write_text(
            "\n".join(
                [
                    "runtime/",
                    "tmp/",
                    "spec/",
                    "plan/",
                    "statuses.md",
                    "description.md",
                    "comments.md",
                    "",
                ]
            )
        )
        if git_dir.exists():
            return
        subprocess.run(["git", "init", "-q", str(task_dir)], check=True)
        subprocess.run(["git", "-C", str(task_dir), "config", "user.name", "Acceptance Runner"], check=True)
        subprocess.run(
            ["git", "-C", str(task_dir), "config", "user.email", "acceptance@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(task_dir), "add", ".gitignore", "repo"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(task_dir), "commit", "-q", "-m", "Initialize acceptance task snapshot"],
            check=True,
        )

    def run(self, task_key: str) -> CommandResult:
        task_dir = self.workdir_root / task_key
        repo_dir = task_dir / "repo"
        repo_claude_path = repo_dir / "CLAUDE.md"
        repo_claude_dir = repo_dir / ".claude"
        spec_dir = task_dir / "spec"
        placeholder_change_path = repo_dir / "placeholder_change.txt"
        task_dir.mkdir(parents=True, exist_ok=True)
        repo_dir.mkdir(parents=True, exist_ok=True)
        repo_claude_dir.mkdir(parents=True, exist_ok=True)
        spec_dir.mkdir(parents=True, exist_ok=True)

        if not repo_claude_path.exists():
            repo_claude_path.write_text(
                "# Project Conventions\n\n"
                "- Placeholder project-local conventions for fake acceptance snapshots.\n"
            )

        if not placeholder_change_path.exists():
            placeholder_change_path.write_text(
                "STATUS=todo\n"
                "DETAIL=placeholder acceptance change is still pending\n"
            )

        statuses_path = task_dir / "statuses.md"
        if not statuses_path.exists():
            statuses_path.write_text("- [ ] Subtask 1\n- [x] Subtask 2\n")

        description_path = task_dir / "description.md"
        if not description_path.exists():
            description_path.write_text(
                "# Task Description\n\n"
                "Apply the acceptance placeholder change by editing `repo/placeholder_change.txt`.\n"
                "Replace `STATUS=todo` with `STATUS=done` and update the detail line to mention the acceptance change was applied.\n"
            )

        comments_path = task_dir / "comments.md"
        if not comments_path.exists():
            comments_path.write_text(
                "# Comments\n\n"
                "- Keep the change narrow and limited to `repo/placeholder_change.txt`.\n"
                "- Do not modify unrelated files during this acceptance task.\n"
            )

        diff_path = spec_dir / "diff.md"
        if not diff_path.exists():
            diff_path.write_text(
                "# Structured Diff\n\n"
                "## Summary\n\n"
                "- Apply the placeholder acceptance change in `repo/placeholder_change.txt`.\n\n"
                "## Raw Diff\n\n"
                "```diff\n"
                "--- repo/placeholder_change.txt\n"
                "+++ repo/placeholder_change.txt\n"
                "@@\n"
                "-STATUS=todo\n"
                "-DETAIL=placeholder acceptance change is still pending\n"
                "+STATUS=done\n"
                "+DETAIL=placeholder acceptance change applied in acceptance validation\n"
                "```\n"
            )

        self._ensure_clean_task_git_repo(task_dir)

        return CommandResult(
            command=["fake_snapshot", task_key],
            returncode=0,
            stdout="snapshot ok\n",
            stderr="",
        )


class FakeGitLabAdapter:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.commit_requests: list[tuple[str, str | None]] = []

    def commit_task_state(self, task_key: str, context: str | None = None) -> CommandResult:
        self.commit_requests.append((task_key, context))
        suffix = f" ({context})" if context else ""
        return CommandResult(
            command=["fake_commit_task_state", task_key, context or ""],
            returncode=0,
            stdout=f"Committed: {task_key}{suffix}\n",
            stderr="",
        )

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
