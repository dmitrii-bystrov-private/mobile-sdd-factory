from pathlib import Path
import json
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import call, patch

from backend.api.sse import SessionEventBus
from backend import session_policy as session_policy_module
from backend.coordinator.intake import IntakeError
from backend.coordinator.service import CoordinatorService
from backend.coordinator.subtasks import SnapshotSubtask
from backend.models.enums import DispatchStatus, RoleStatus, SessionStatus
from backend.models.work_item import WorkItemStatus
from backend.roles.contracts import (
    ALLOWED_STAGE_ROLE_TARGETS,
    BUG_FIXER_ROLE,
    CONVENTION_REVIEWER_ROLE,
    DOCUMENTATION_REVIEWER_ROLE,
    DOC_HARVEST_ROLE,
    DEFAULT_SESSION_ROLES,
    ACCEPTANCE_CRITERIA_WORKER_ROLE,
    CONSTRAINTS_WORKER_ROLE,
    IMPLEMENTER_ROLE,
    PERSISTENT_SESSION_ROLES,
    PROPOSAL_CONTEXT_WORKER_ROLE,
    REQUIREMENTS_CLARIFIER_WORKER_ROLE,
    REQUIREMENTS_REVIEWER_ROLE,
    SPEC_VERIFIER_WORKER_ROLE,
    TASK_DECOMPOSER_WORKER_ROLE,
    VERIFICATION_COORDINATOR_ROLE,
)
from backend.roles.launcher import RoleLauncherManager
from backend.role_runtime_config import normalize_role_runtime_config
from backend.roles.workspace import RoleWorkspaceManager
from backend.session_backend.recording_backend import RecordingSessionBackend
from backend.session_backend.tmux_backend import TmuxSessionBackend
from backend.session_backend.runtime_models import RuntimeRoleHandle, RuntimeSessionHandle
from backend.state.artifact_repository import ArtifactRepository
from backend.state.db import Database
from backend.state.dispatch_repository import DispatchRepository
from backend.state.event_repository import EventRepository
from backend.state.role_repository import RoleRepository
from backend.state.session_repository import SessionRepository
from backend.state.work_item_repository import WorkItemRepository
from backend.tools.command_runner import CommandResult
from backend.tools.write_result import build_result_document, write_result_file


def decomposition_payload(summary: str, task_breakdown: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "summary": summary,
        "plan_index_markdown": (
            "# Execution Task List\n\n"
            "| # | Task | Depends on | Status |\n"
            "|---|------|------------|--------|\n"
            "| 01 | [Build data source](./01-build-data-source.md) | — | ☐ |\n"
        ),
        "plan_task_files": [
            {
                "filename": "01-build-data-source.md",
                "content": (
                    "# Build data source\n\n"
                    "## What to implement\n"
                    "Create the feature data source.\n\n"
                    "## Validation\n"
                    "The data source exists and is wired into the intended flow.\n"
                ),
            }
        ],
    }
    if task_breakdown is not None:
        payload["task_breakdown"] = task_breakdown
    return payload


class FakeJiraAdapter:
    def __init__(self) -> None:
        self.status_by_task: dict[str, str] = {}
        self.created_issue_counter = 0
        self.completed_subtasks: list[str] = []

    def resolve_parent(self, task_key: str) -> CommandResult:
        return CommandResult(
            command=["resolve_parent", task_key],
            returncode=0,
            stdout=f"{task_key}\n",
            stderr="",
        )

    def get_issue_type(self, task_key: str) -> CommandResult:
        return CommandResult(
            command=["get_issue_type", task_key],
            returncode=0,
            stdout="Story\n",
            stderr="",
        )

    def get_issue_status(self, task_key: str) -> CommandResult:
        status = self.status_by_task.get(task_key, "In Progress")
        return CommandResult(
            command=["get_issue_status", task_key],
            returncode=0,
            stdout=json.dumps({"fields": {"status": {"name": status}}}),
            stderr="",
        )

    def create_subtasks(self, task_key: str, plan_dir: Path) -> CommandResult:
        return CommandResult(
            command=["create_subtasks", task_key, str(plan_dir)],
            returncode=0,
            stdout="Created subtasks:\n01    IOS-90001     Build data source\n",
            stderr="",
        )

    def complete_subtask(self, task_key: str) -> CommandResult:
        self.completed_subtasks.append(task_key)
        self.status_by_task[task_key] = "Ready for test"
        return CommandResult(
            command=["complete_subtask", task_key],
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
        issue_key = f"{project}-{91000 + self.created_issue_counter}"
        return CommandResult(
            command=["create_issue", project, summary],
            returncode=0,
            stdout=f"{issue_key} https://jira.example.com/browse/{issue_key}\n",
            stderr="",
        )

    def send_to_test(self, task_key: str) -> CommandResult:
        return CommandResult(
            command=["send_to_test", task_key],
            returncode=0,
            stdout=f"Done: {task_key} -> Ready for test\n",
            stderr="",
        )


class FakeSnapshotAdapter:
    def __init__(self, workdir_root: Path | None = None) -> None:
        self.workdir_root = workdir_root
        self.calls: list[str] = []
        self.statuses_by_task: dict[str, str] = {}
        self.statuses_sequences_by_task: dict[str, list[str]] = {}
        self.failures_by_task: dict[str, CommandResult] = {}

    def set_statuses_output(self, task_key: str, content: str) -> None:
        self.statuses_by_task[task_key] = content

    def set_statuses_sequence(self, task_key: str, contents: list[str]) -> None:
        self.statuses_sequences_by_task[task_key] = list(contents)

    def set_failure(self, task_key: str, *, stdout: str = "", stderr: str = "snapshot failed\n") -> None:
        self.failures_by_task[task_key] = CommandResult(
            command=["snapshot", task_key],
            returncode=1,
            stdout=stdout,
            stderr=stderr,
        )

    def run(self, task_key: str) -> CommandResult:
        self.calls.append(task_key)
        if task_key in self.failures_by_task:
            return self.failures_by_task[task_key]
        if self.workdir_root is not None and task_key in self.statuses_sequences_by_task:
            sequence = self.statuses_sequences_by_task[task_key]
            content = sequence.pop(0) if len(sequence) > 1 else sequence[0]
            task_dir = self.workdir_root / task_key
            task_dir.mkdir(parents=True, exist_ok=True)
            (task_dir / "statuses.md").write_text(content)
        elif self.workdir_root is not None and task_key in self.statuses_by_task:
            task_dir = self.workdir_root / task_key
            task_dir.mkdir(parents=True, exist_ok=True)
            (task_dir / "statuses.md").write_text(self.statuses_by_task[task_key])
        return CommandResult(
            command=["snapshot", task_key],
            returncode=0,
            stdout="snapshot ok\n",
            stderr="",
        )


class FakeGitLabAdapter:
    def __init__(self) -> None:
        self.commit_requests: list[tuple[str, str | None]] = []

    def commit_task_state(self, task_key: str, context: str | None = None) -> CommandResult:
        self.commit_requests.append((task_key, context))
        return CommandResult(
            command=["commit_task_state", task_key, context or ""],
            returncode=0,
            stdout=f"Committed: {task_key}\n",
            stderr="",
        )

    def create_mr(self, task_key: str) -> CommandResult:
        return CommandResult(
            command=["create_mr", task_key],
            returncode=0,
            stdout=(
                f"Pushing branch for {task_key}\n"
                f"https://gitlab.example.com/mobile/{task_key}/-/merge_requests/42\n"
            ),
            stderr="",
        )

class AutoRecoveryRecordingBackend(RecordingSessionBackend):
    def __init__(self) -> None:
        super().__init__()
        self.spawn_generation: dict[tuple[str, str], int] = {}
        self.role_alive: dict[str, bool] = {}
        self.fail_spawn_for: set[tuple[str, str]] = set()

    def spawn_role(
        self,
        session: RuntimeSessionHandle,
        role_name: str,
        start_directory: Path | None = None,
        launch_command: list[str] | None = None,
    ):
        del start_directory
        key = (session.session_id, role_name)
        if key in self.fail_spawn_for:
            raise RuntimeError(f"spawn failed for {role_name}")
        generation = self.spawn_generation.get(key, 0) + 1
        self.spawn_generation[key] = generation
        role_id = f"{session.session_id}:{role_name}:{generation}"
        self.spawn_commands[role_id] = list(launch_command or [])
        self.role_alive[role_id] = True
        return RuntimeRoleHandle(
            role_id=role_id,
            session_id=session.session_id,
            backend_name="recording",
        )

    def is_role_alive(self, role) -> bool:
        return self.role_alive.get(role.role_id, False)

    def mark_dead(self, role_id: str) -> None:
        self.role_alive[role_id] = False

    def stop_role(self, role) -> None:
        self.role_alive[role.role_id] = False
        super().stop_role(role)

    def stop_session(self, session) -> None:
        prefix = f"{session.session_id}:"
        for role_id in list(self.role_alive):
            if role_id.startswith(prefix):
                self.role_alive[role_id] = False
        super().stop_session(session)


class DispatchTraceRecordingBackend(RecordingSessionBackend):
    def __init__(self, *, fail_send: bool = False, delivery_state: str = "retried") -> None:
        super().__init__()
        self.fail_send = fail_send
        self.delivery_state = delivery_state
        self.tmux_submit_traces: dict[str, list[dict[str, str]]] = {}

    def send_input(self, role: RuntimeRoleHandle, text: str) -> None:
        if self.fail_send:
            raise RuntimeError("simulated send failure")
        super().send_input(role, text)
        self.tmux_submit_traces.setdefault(role.role_id, []).append(
            {
                "source": "direct",
                "submit_style": "plain-enter-two-call",
                "submit_key": "Enter",
                "runner": "codex",
                "retry_count": "1" if self.delivery_state == "retried" else "0",
                "delivery_state": self.delivery_state,
            }
        )

    def get_tmux_submit_traces(self, role_id: str) -> list[dict[str, str]]:
        return list(self.tmux_submit_traces.get(role_id, []))


class SessionCreationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self._original_review_default = session_policy_module.COMMON_DEFAULTS["review_policy"]
        self._original_doc_harvest_default = session_policy_module.COMMON_DEFAULTS["doc_harvest_policy"]
        session_policy_module.COMMON_DEFAULTS["review_policy"] = "disabled"
        session_policy_module.COMMON_DEFAULTS["doc_harvest_policy"] = "disabled"
        self.db_path = Path(self.temp_dir.name) / "factory.sqlite3"
        self.database = Database(self.db_path)
        self.database.initialize()

        self.session_repository = SessionRepository(self.database)
        self.role_repository = RoleRepository(self.database)
        self.event_repository = EventRepository(self.database)
        self.artifact_repository = ArtifactRepository(self.database)
        self.work_item_repository = WorkItemRepository(self.database)
        self.dispatch_repository = DispatchRepository(self.database)
        self.session_backend = RecordingSessionBackend()
        self.event_bus = SessionEventBus()
        self.snapshot_adapter = FakeSnapshotAdapter(Path(self.temp_dir.name))
        self.jira_adapter = FakeJiraAdapter()
        self.gitlab_adapter = FakeGitLabAdapter()
        self.coordinator = CoordinatorService(
            session_repository=self.session_repository,
            role_repository=self.role_repository,
            event_repository=self.event_repository,
            artifact_repository=self.artifact_repository,
            work_item_repository=self.work_item_repository,
            dispatch_repository=self.dispatch_repository,
            session_backend=self.session_backend,
            default_roles=DEFAULT_SESSION_ROLES,
            jira_adapter=self.jira_adapter,
            snapshot_adapter=self.snapshot_adapter,
            gitlab_adapter=self.gitlab_adapter,
            artifacts_root=Path(self.temp_dir.name) / "artifacts",
            workdir_root=Path(self.temp_dir.name),
            event_bus=self.event_bus,
            role_workspace_manager=RoleWorkspaceManager(
                runtime_root=Path(self.temp_dir.name),
                repo_root=Path(self.temp_dir.name) / "repo-root",
                workdir_root=Path(self.temp_dir.name),
            ),
            role_launcher_manager=RoleLauncherManager(
                repo_root=Path(self.temp_dir.name) / "repo-root",
                workdir_root=Path(self.temp_dir.name),
                launcher_command=["sh"],
            ),
            post_create_subtask_snapshot_refresh_delay_seconds=0,
        )

    def tearDown(self) -> None:
        session_policy_module.COMMON_DEFAULTS["review_policy"] = self._original_review_default
        session_policy_module.COMMON_DEFAULTS["doc_harvest_policy"] = self._original_doc_harvest_default
        self.temp_dir.cleanup()

    def write_statuses_file(self, task_key: str, content: str) -> None:
        task_dir = Path(self.temp_dir.name) / task_key
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "statuses.md").write_text(content)

    def write_passed_verification_outcome(self, task_key: str) -> None:
        spec_dir = Path(self.temp_dir.name) / task_key / "spec"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "verification-outcome.json").write_text(
            json.dumps({"status": "passed", "task_key": task_key}) + "\n"
        )

    def test_create_task_session_creates_roles_and_event(self) -> None:
        session, event, created = self.coordinator.create_task_session(
            "IOS-30000",
            workflow_profile="bug_full",
            policy={"test_policy": "required"},
        )
        roles = self.role_repository.list_for_session(session.id)

        self.assertTrue(created)
        self.assertEqual("task_started", event.event_type)
        self.assertEqual("active", session.status.value)
        self.assertEqual("bug_full", session.workflow_profile)
        self.assertEqual("required", session.policy["test_policy"])

    def test_cleanup_task_soft_removes_runtime_and_tmp_but_keeps_task_directory(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30000CLEAN",
            workflow_profile="oneshot",
            policy={},
        )
        task_root = Path(self.temp_dir.name) / "IOS-30000CLEAN"
        runtime_dir = task_root / "runtime"
        tmp_dir = task_root / "tmp"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)

        result = self.coordinator.cleanup_task(session.id, cleanup_mode="soft")

        self.assertTrue(result["cleaned"])
        self.assertFalse(result["deleted_session"])
        self.assertTrue(task_root.exists())
        self.assertFalse(runtime_dir.exists())
        self.assertFalse(tmp_dir.exists())
        self.assertIsNotNone(self.session_repository.get_by_id(session.id))

    def test_cleanup_task_full_removes_session_and_task_directory_when_closed(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30000FULL",
            workflow_profile="oneshot",
            policy={},
        )
        self.jira_adapter.status_by_task["IOS-30000FULL"] = "Resolved"
        task_root = Path(self.temp_dir.name) / "IOS-30000FULL"
        repo_dir = task_root / "repo"
        repo_dir.mkdir(parents=True, exist_ok=True)
        (repo_dir / "placeholder.txt").write_text("x")

        result = self.coordinator.cleanup_task(session.id, cleanup_mode="full")

        self.assertTrue(result["cleaned"])
        self.assertTrue(result["deleted_session"])
        self.assertFalse(task_root.exists())
        self.assertIsNone(self.session_repository.get_by_id(session.id))

    def test_cleanup_task_smart_uses_soft_for_open_tasks(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30000SMARTOPEN",
            workflow_profile="oneshot",
            policy={},
        )
        task_root = Path(self.temp_dir.name) / "IOS-30000SMARTOPEN"
        runtime_dir = task_root / "runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)

        result = self.coordinator.cleanup_task(session.id, cleanup_mode="smart")

        self.assertTrue(result["cleaned"])
        self.assertFalse(result["deleted_session"])
        self.assertEqual("soft", result["cleanup_mode"])
        self.assertTrue(task_root.exists())
        self.assertFalse(runtime_dir.exists())

    def test_cleanup_task_smart_uses_full_for_closed_tasks(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30000SMARTCLOSED",
            workflow_profile="oneshot",
            policy={},
        )
        self.jira_adapter.status_by_task["IOS-30000SMARTCLOSED"] = "Resolved"
        task_root = Path(self.temp_dir.name) / "IOS-30000SMARTCLOSED"
        repo_dir = task_root / "repo"
        repo_dir.mkdir(parents=True, exist_ok=True)
        (repo_dir / "placeholder.txt").write_text("x")

        result = self.coordinator.cleanup_task(session.id, cleanup_mode="smart")

        self.assertTrue(result["cleaned"])
        self.assertTrue(result["deleted_session"])
        self.assertEqual("full", result["cleanup_mode"])
        self.assertFalse(task_root.exists())

    def test_cleanup_task_removes_claude_project_session_directory(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30000CLAUDE",
            workflow_profile="oneshot",
            policy={},
        )
        fake_home = Path(self.temp_dir.name) / "home"
        claude_dir = (
            fake_home
            / ".claude"
            / "projects"
            / "-Users-d-bystrov-Projects-Finom-workdir-IOS-30000CLAUDE-repo"
        )
        claude_dir.mkdir(parents=True, exist_ok=True)
        (claude_dir / "session.jsonl").write_text("{}\n")

        with patch("backend.coordinator.service.Path.home", return_value=fake_home):
            result = self.coordinator.cleanup_task(session.id, cleanup_mode="soft")

        self.assertTrue(result["cleaned"])
        self.assertFalse(claude_dir.exists())
        self.assertTrue(
            any(".claude/projects" in path for path in result["removed_paths"]),
            "expected claude project residue to be reported",
        )

    def test_cleanup_task_removes_codex_session_file_by_cwd_match(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30000CODEX",
            workflow_profile="oneshot",
            policy={},
        )
        fake_home = Path(self.temp_dir.name) / "home"
        codex_session_dir = fake_home / ".codex" / "sessions" / "2026" / "05" / "17"
        codex_session_dir.mkdir(parents=True, exist_ok=True)
        session_file = codex_session_dir / "rollout-test.jsonl"
        session_file.write_text(
            json.dumps(
                {
                    "timestamp": "2026-05-17T20:00:00Z",
                    "type": "session_meta",
                    "payload": {
                        "cwd": f"~/workdir/{session.task_key}/runtime/role-workspaces/implementer"
                    },
                }
            )
            + "\n"
        )

        with patch("backend.coordinator.service.Path.home", return_value=fake_home):
            result = self.coordinator.cleanup_task(session.id, cleanup_mode="soft")

        self.assertTrue(result["cleaned"])
        self.assertFalse(session_file.exists())
        self.assertFalse(codex_session_dir.exists())
        self.assertTrue(
            any(".codex/sessions" in path for path in result["removed_paths"]),
            "expected codex session residue to be reported",
        )

    def test_cleanup_task_removes_codex_shell_snapshots_for_matching_session(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30000CODEXSNAPSHOT",
            workflow_profile="oneshot",
            policy={},
        )
        fake_home = Path(self.temp_dir.name) / "home"
        codex_session_dir = fake_home / ".codex" / "sessions" / "2026" / "05" / "17"
        codex_session_dir.mkdir(parents=True, exist_ok=True)
        session_id = "019ede66-1a8b-74c0-b684-8ecee29eba43"
        session_file = codex_session_dir / "rollout-test.jsonl"
        session_file.write_text(
            json.dumps(
                {
                    "timestamp": "2026-05-17T20:00:00Z",
                    "type": "session_meta",
                    "payload": {
                        "id": session_id,
                        "cwd": f"/tmp/workdir/{session.task_key}/runtime/role-workspaces/implementer",
                    },
                }
            )
            + "\n"
        )
        snapshots_dir = fake_home / ".codex" / "shell_snapshots"
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        matching_snapshot = snapshots_dir / f"{session_id}.123.sh"
        other_snapshot = snapshots_dir / "019ede66-other.123.sh"
        matching_snapshot.write_text("matching")
        other_snapshot.write_text("other")

        with patch("backend.coordinator.service.Path.home", return_value=fake_home):
            result = self.coordinator.cleanup_task(session.id, cleanup_mode="soft")

        self.assertTrue(result["cleaned"])
        self.assertFalse(session_file.exists())
        self.assertFalse(matching_snapshot.exists())
        self.assertTrue(other_snapshot.exists())
        self.assertTrue(
            any(".codex/shell_snapshots" in path for path in result["removed_paths"]),
            "expected codex shell snapshot residue to be reported",
        )

    def test_cleanup_closed_tasks_finds_orphan_runner_private_residue(self) -> None:
        task_key = "IOS-39999"
        fake_home = Path(self.temp_dir.name) / "home"
        claude_dir = (
            fake_home
            / ".claude"
            / "projects"
            / f"-Users-d-bystrov-Projects-Finom-workdir-{task_key}-runtime-role-workspaces-implementer"
        )
        claude_dir.mkdir(parents=True, exist_ok=True)
        (claude_dir / "session.jsonl").write_text("{}\n")
        self.jira_adapter.status_by_task[task_key] = "Resolved"

        with patch("backend.coordinator.service.Path.home", return_value=fake_home):
            results = self.coordinator.cleanup_closed_tasks()

        matching_result = next(
            item for item in results if item["task_key"] == task_key
        )
        self.assertFalse(claude_dir.exists())
        self.assertTrue(
            any(".claude/projects" in path for path in matching_result["removed_paths"]),
            "expected orphan claude project residue to be reported",
        )

    def test_collect_role_output_escalates_launcher_selection_blocker_to_operator(self) -> None:
        fixture = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "interactive_selection_blocker_fixture.py"
        )
        tmux_backend = TmuxSessionBackend(
            mode="tmux",
            runtime_root=Path(self.temp_dir.name),
        )
        self.coordinator = CoordinatorService(
            session_repository=self.session_repository,
            role_repository=self.role_repository,
            event_repository=self.event_repository,
            artifact_repository=self.artifact_repository,
            work_item_repository=self.work_item_repository,
            session_backend=tmux_backend,
            default_roles=DEFAULT_SESSION_ROLES,
            jira_adapter=FakeJiraAdapter(),
            snapshot_adapter=self.snapshot_adapter,
            gitlab_adapter=FakeGitLabAdapter(),
            artifacts_root=Path(self.temp_dir.name) / "artifacts",
            workdir_root=Path(self.temp_dir.name),
            event_bus=self.event_bus,
            role_workspace_manager=RoleWorkspaceManager(
                runtime_root=Path(self.temp_dir.name),
                repo_root=Path(self.temp_dir.name) / "repo-root",
                workdir_root=Path(self.temp_dir.name),
            ),
            role_launcher_manager=RoleLauncherManager(
                repo_root=Path(self.temp_dir.name) / "repo-root",
                workdir_root=Path(self.temp_dir.name),
                launcher_command=["python3", "-u", str(fixture)],
            ),
        )
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30001",
            workflow_profile="oneshot",
            policy={
                "review_policy": "disabled",
                                "doc_harvest_policy": "disabled",
            },
        )
        self.coordinator.prepare_task_session("IOS-30001")

        updated_session = session
        chunk_count = 0
        for _ in range(20):
            updated_session, _, chunk_count = self.coordinator.collect_role_output(
                session_id=session.id,
                role_name="implementer",
            )
            if updated_session.status.value == "waiting_for_operator":
                break
            time.sleep(0.2)

        self.assertEqual("waiting_for_operator", updated_session.status.value)
        self.assertEqual("implementation_requested", updated_session.current_stage)
        self.assertGreaterEqual(chunk_count, 2)
        work_items = self.work_item_repository.list_for_session(session.id)
        self.assertTrue(
            any(item.status.value == "waiting_for_operator" for item in work_items),
            "expected an assigned work item to be escalated to waiting_for_operator",
        )
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.assertIsNotNone(implementer_role)
        runtime_session_id = implementer_role.runtime_handle.split(":", 1)[0]
        tmux_backend.stop_session(RuntimeSessionHandle(session_id=runtime_session_id))

    def test_normalize_role_runtime_config_prefers_saved_project_defaults(self) -> None:
        repo_root = Path(self.temp_dir.name) / "repo-root"
        settings_dir = repo_root / ".sdd-factory"
        settings_dir.mkdir(parents=True, exist_ok=True)
        (settings_dir / "settings.local.json").write_text(
            json.dumps(
                {
                    "runtime_defaults": {
                        "default_runner": "claude",
                        "role_defaults": {
                            "implementer": {
                                "runner": "claude",
                                "model": "sonnet",
                                "effort": "high",
                            }
                        },
                    }
                }
            )
        )

        normalized = normalize_role_runtime_config(
            repo_root=repo_root,
            role_names=["implementer"],
            provided=None,
        )

        self.assertEqual(
            {
                "runner": "claude",
                "model": "sonnet",
                "effort": "high",
            },
            normalized["implementer"],
        )

    def test_normalize_role_runtime_config_skips_incompatible_legacy_model_for_runner(self) -> None:
        repo_root = Path(self.temp_dir.name) / "repo-root"
        settings_dir = repo_root / ".sdd-factory"
        settings_dir.mkdir(parents=True, exist_ok=True)
        (settings_dir / "settings.local.json").write_text(
            json.dumps(
                {
                    "runtime_defaults": {
                        "default_runner": "codex",
                    }
                }
            )
        )

        with patch(
            "backend.role_runtime_config.build_runtime_capabilities",
            return_value={
                "available_runners": ["claude", "codex"],
                "default_runner": "claude",
                "runners": [
                    {
                        "runner": "claude",
                        "models": [
                            {
                                "id": "sonnet",
                                "supported_efforts": ["medium", "high"],
                                "default_effort": "medium",
                            }
                        ],
                    },
                    {
                        "runner": "codex",
                        "models": [
                            {
                                "id": "gpt-5.3-codex-spark",
                                "supported_efforts": ["medium", "high"],
                                "default_effort": "medium",
                            }
                        ],
                    },
                ],
                "role_defaults": [
                    {
                        "role_name": "proposal-context-worker",
                        "model": "sonnet",
                        "effort": "high",
                        "mcp_servers": ["ios-rag", "android-rag", "frontend-rag"],
                        "source": "backend.role_baselines",
                    }
                ],
            },
        ):
            normalized = normalize_role_runtime_config(
                repo_root=repo_root,
                role_names=["proposal-context-worker"],
                provided=None,
            )

        self.assertEqual(
            {
                "runner": "codex",
                "model": "gpt-5.3-codex-spark",
                "effort": "medium",
            },
            normalized["proposal-context-worker"],
        )

    def test_story_session_accepts_role_config_for_planning_and_optional_lanes(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30001",
            workflow_profile="story_full",
            policy={
                "review_policy": "enabled",
                                "doc_harvest_policy": "enabled",
                "requirements_clarification_mode": "ask-selectively",
            },
            role_config={
                "proposal-context-worker": {
                    "runner": "claude",
                    "model": "sonnet",
                    "effort": "medium",
                },
                "requirements-clarifier-worker": {
                    "runner": "claude",
                    "model": "sonnet",
                    "effort": "medium",
                },
                "convention-reviewer": {
                    "runner": "claude",
                    "model": "sonnet",
                    "effort": "high",
                },
                "requirements-reviewer": {
                    "runner": "claude",
                    "model": "sonnet",
                    "effort": "high",
                },
                "doc-harvest-worker": {
                    "runner": "claude",
                    "model": "sonnet",
                    "effort": "medium",
                },
            },
        )

        self.assertEqual(
            {
                "runner": "claude",
                "model": "sonnet",
                "effort": "medium",
            },
            session.role_config["proposal-context-worker"],
        )
        self.assertEqual(
            {
                "runner": "claude",
                "model": "sonnet",
                "effort": "high",
            },
            session.role_config["convention-reviewer"],
        )
        self.assertIn("requirements-reviewer", session.role_config)
        self.assertEqual(
            {
                "runner": "claude",
                "model": "sonnet",
                "effort": "medium",
            },
            session.role_config["doc-harvest-worker"],
        )

    def test_send_operator_runtime_input_reactivates_waiting_session_without_new_handoff(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30002",
            workflow_profile="oneshot",
            policy={
                "review_policy": "disabled",
                                "doc_harvest_policy": "disabled",
            },
        )
        self.coordinator.prepare_task_session("IOS-30002")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            'SDD_ERROR: {"summary":"tool failed","details":"command exited 1"}',
        )
        self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )

        updated_session, event = self.coordinator.send_operator_runtime_input(
            session_id=session.id,
            text="1",
        )

        self.assertEqual("operator_runtime_input_sent", event.event_type)
        self.assertEqual("active", updated_session.status.value)
        self.assertEqual("implementer", updated_session.current_owner)
        self.assertEqual(
            ["1"],
            self.session_backend.get_sent_inputs(implementer_role.runtime_handle)[-1:],
        )
        self.assertEqual("1", event.payload.get("operator_reply"))
        self.assertEqual("implementation_requested", event.payload.get("continuation_stage"))

    def test_operator_reply_to_dual_review_correction_is_persisted_for_later_reviews(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30002DUALREPLY",
            workflow_profile="story_full",
            policy={
                "review_policy": "enabled",
                                "doc_harvest_policy": "disabled",
            },
        )
        self.coordinator.prepare_task_session("IOS-30002DUALREPLY")
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        assert implementer_role is not None
        work_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="convention_review_correction",
            title="Convention review corrections for IOS-30002DUALREPLY",
            owner_role_id=implementer_role.id,
            status=WorkItemStatus.WAITING_FOR_OPERATOR,
        )
        self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="convention_review_correction_requested",
            current_owner=None,
        )
        self.session_repository.update_status(session.id, SessionStatus.WAITING_FOR_OPERATOR)

        _updated_session, event = self.coordinator.send_operator_runtime_input(
            session_id=session.id,
            text="Use class-style screen keys; the snake_case values are not authoritative.",
        )

        self.assertEqual("operator_runtime_input_sent", event.event_type)
        self.assertEqual(work_item.id, event.payload.get("work_item_id"))
        self.assertEqual(
            "convention_review_correction_requested",
            event.payload.get("continuation_stage"),
        )
        self.assertEqual(
            "Use class-style screen keys; the snake_case values are not authoritative.",
            event.payload.get("operator_reply"),
        )

    def test_send_operator_runtime_input_sends_live_reply_to_alive_one_shot_role(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30002B",
            workflow_profile="story_full",
            policy={
                "requirements_clarification_mode": "ask-selectively",
            },
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="requirements_requested",
            current_owner="requirements-clarifier-worker",
        )
        session = self.session_repository.update_status(session.id, SessionStatus.WAITING_FOR_OPERATOR)
        role = self.role_repository.get_by_name(session.id, "requirements-clarifier-worker")
        self.assertIsNotNone(role)
        work_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="requirements",
            title="Requirements clarification for IOS-30002B",
            owner_role_id=role.id,
            source_event_id=1,
            priority=10,
            status=WorkItemStatus.WAITING_FOR_OPERATOR,
        )

        updated_session, event = self.coordinator.send_operator_runtime_input(
            session_id=session.id,
            text="Do it the same way as the frontend does",
        )

        self.assertEqual("operator_runtime_input_sent", event.event_type)
        self.assertEqual("active", updated_session.status.value)
        self.assertEqual("requirements-clarifier-worker", updated_session.current_owner)
        sent = self.session_backend.get_sent_inputs(role.runtime_handle)
        self.assertTrue(sent)
        self.assertIn("Operator answer:", sent[-1])
        self.assertIn("Do it the same way as the frontend does", sent[-1])
        self.assertNotIn("Read ROUTED_WORK.md", sent[-1])
        refreshed_item = self.work_item_repository.get_by_id(work_item.id)
        self.assertEqual(WorkItemStatus.ASSIGNED, refreshed_item.status)
        self.assertEqual(work_item.id, int(event.payload.get("work_item_id") or 0))

    def test_send_operator_runtime_input_redispatches_one_shot_role_only_when_runtime_is_dead(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30002C",
            workflow_profile="story_full",
            policy={
                "requirements_clarification_mode": "ask-selectively",
            },
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="requirements_requested",
            current_owner="requirements-clarifier-worker",
        )
        session = self.session_repository.update_status(session.id, SessionStatus.WAITING_FOR_OPERATOR)
        role = self.role_repository.get_by_name(session.id, "requirements-clarifier-worker")
        self.assertIsNotNone(role)
        work_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="requirements",
            title="Requirements clarification for IOS-30002C",
            owner_role_id=role.id,
            source_event_id=1,
            priority=10,
            status=WorkItemStatus.WAITING_FOR_OPERATOR,
        )
        runtime_role = RuntimeRoleHandle(
            role_id=role.runtime_handle,
            session_id=self.coordinator._runtime_session_id_for_role(role, session),
            backend_name=role.runtime_backend,
        )
        self.session_backend.stop_role(runtime_role)

        updated_session, event = self.coordinator.send_operator_runtime_input(
            session_id=session.id,
            text="Do it the same way as the frontend does",
        )

        self.assertEqual("operator_runtime_input_sent", event.event_type)
        self.assertEqual("active", updated_session.status.value)
        self.assertEqual("requirements-clarifier-worker", updated_session.current_owner)
        sent = self.session_backend.get_sent_inputs(role.runtime_handle)
        self.assertTrue(sent)
        self.assertIn("Operator reply received in this live session.", sent[-1])
        self.assertIn("Do it the same way as the frontend does", sent[-1])
        refreshed_item = self.work_item_repository.get_by_id(work_item.id)
        self.assertEqual(WorkItemStatus.ASSIGNED, refreshed_item.status)

    def test_get_interactive_state_summary_uses_latest_runtime_error(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003",
            workflow_profile="oneshot",
            policy={
                "review_policy": "disabled",
                                "doc_harvest_policy": "disabled",
            },
        )
        self.coordinator.prepare_task_session("IOS-30003")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            'SDD_ERROR: {"summary":"interactive selection required","details":"operator choice needed","needs_operator_input":true}',
        )
        self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )

        summary = self.coordinator.get_interactive_state_summary(session.id)

        self.assertTrue(summary["available"])
        self.assertEqual("implementer", summary["role_name"])
        self.assertEqual("implementation_requested", summary["current_stage"])
        self.assertEqual("interactive selection required", summary["summary"])
        self.assertEqual("operator choice needed", summary["details"])
        self.assertEqual("session_escalated_to_operator", summary["source_event_type"])
        self.assertTrue(summary["needs_operator_input"])
        self.assertIsNone(summary["resume_strategy"])

    def test_get_interactive_state_summary_clears_after_operator_runtime_input(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004",
            workflow_profile="oneshot",
            policy={
                "review_policy": "disabled",
                                "doc_harvest_policy": "disabled",
            },
        )
        self.coordinator.prepare_task_session("IOS-30004")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            'SDD_ERROR: {"summary":"interactive selection required","details":"operator choice needed","needs_operator_input":true}',
        )
        self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )

        self.coordinator.send_operator_runtime_input(
            session_id=session.id,
            text="1",
        )
        summary = self.coordinator.get_interactive_state_summary(session.id)

        self.assertFalse(summary["available"])
        self.assertFalse(summary["needs_operator_input"])

    def test_story_planning_replayed_blocker_is_ignored_after_operator_reply(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004REQREPLAY",
            workflow_profile="story_full",
        )
        requirements_role = self.role_repository.get_by_name(
            session.id,
            REQUIREMENTS_CLARIFIER_WORKER_ROLE,
        )
        self.assertIsNotNone(requirements_role)
        work_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="requirements",
            title="Requirements clarification for IOS-30004REQREPLAY",
            owner_role_id=requirements_role.id,
            priority=10,
            status=WorkItemStatus.ASSIGNED,
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="requirements_requested",
            current_owner=REQUIREMENTS_CLARIFIER_WORKER_ROLE,
        )
        session = self.session_repository.update_status(session.id, SessionStatus.ACTIVE)

        role_workspace = self.coordinator.role_workspace_manager.role_directory(  # type: ignore[union-attr]
            session.task_key,
            REQUIREMENTS_CLARIFIER_WORKER_ROLE,
        )
        result_path = role_workspace / "RESULT.json"
        blocked_document = build_result_document(
            SimpleNamespace(
                role=REQUIREMENTS_CLARIFIER_WORKER_ROLE,
                output_type="completed",
                output=str(result_path),
                work_item_id=work_item.id,
                summary="Requirements clarification needed",
                details="Need one deviceId decision.",
                next_step="Answer the open question.",
                failure=[],
                missing_input=[],
                pending_decision=["Choose the deviceId enrollment behavior."],
                blocker_question=["Should deviceId perform write-side enrollment?"],
                needs_operator_input=True,
            )
        )
        write_result_file(result_path, blocked_document)

        waiting_session, _, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name=REQUIREMENTS_CLARIFIER_WORKER_ROLE,
        )
        self.assertEqual(1, chunk_count)
        self.assertEqual(SessionStatus.WAITING_FOR_OPERATOR, waiting_session.status)

        resumed_session, _ = self.coordinator.send_operator_runtime_input(
            session_id=session.id,
            text="Use read-only deviceId support for now.",
        )
        self.assertEqual(SessionStatus.ACTIVE, resumed_session.status)

        write_result_file(result_path, blocked_document)
        updated_session, _, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name=REQUIREMENTS_CLARIFIER_WORKER_ROLE,
        )
        summary = self.coordinator.get_interactive_state_summary(session.id)
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual(1, chunk_count)
        self.assertEqual(SessionStatus.ACTIVE, updated_session.status)
        self.assertEqual("requirements_requested", updated_session.current_stage)
        self.assertFalse(summary["available"])
        self.assertTrue(
            any(
                item.event_type == "stale_role_output_ignored"
                and item.payload.get("reason") == "replayed_blocker_after_operator_reply"
                for item in events
            )
        )

    def test_get_interactive_state_summary_hides_stale_blocker_when_session_is_active(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004ACTIVE",
            workflow_profile="oneshot",
            policy={
                "review_policy": "disabled",
                                "doc_harvest_policy": "disabled",
            },
        )
        self.coordinator.prepare_task_session("IOS-30004ACTIVE")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            'SDD_ERROR: {"summary":"interactive selection required","details":"operator choice needed","needs_operator_input":true}',
        )
        self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )
        self.session_repository.update_status(session.id, SessionStatus.ACTIVE)

        summary = self.coordinator.get_interactive_state_summary(session.id)

        self.assertFalse(summary["available"])
        self.assertFalse(summary["needs_operator_input"])

    def test_get_interactive_state_summary_runtime_error_does_not_require_operator_input(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004RUNTIME",
            workflow_profile="oneshot",
            policy={
                "review_policy": "disabled",
                                "doc_harvest_policy": "disabled",
            },
        )
        self.coordinator.prepare_task_session("IOS-30004RUNTIME")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            'SDD_ERROR: {"summary":"tool failed","details":"command exited 1","needs_operator_input":false}',
        )
        self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )

        summary = self.coordinator.get_interactive_state_summary(session.id)

        self.assertTrue(summary["available"])
        self.assertEqual("tool failed", summary["summary"])
        self.assertFalse(summary["needs_operator_input"])
        self.assertIsNone(summary["resume_strategy"])

    def test_get_interactive_state_summary_exposes_resume_strategy(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004MCP",
            workflow_profile="oneshot",
            policy={
                "review_policy": "disabled",
                                "doc_harvest_policy": "disabled",
            },
        )
        self.coordinator.prepare_task_session("IOS-30004MCP")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            'SDD_ERROR: {"summary":"required mcp access unavailable","details":"restore vpn","resume_strategy":"reactivate_only"}',
        )
        self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )

        summary = self.coordinator.get_interactive_state_summary(session.id)

        self.assertTrue(summary["available"])
        self.assertEqual("required mcp access unavailable", summary["summary"])
        self.assertEqual("reactivate_only", summary["resume_strategy"])
        self.assertFalse(summary["needs_operator_input"])

    def test_create_task_session_creates_role_workspaces(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30000W",
            workflow_profile="oneshot",
            policy={"review_policy": "required"},
        )

        self.assertIsNotNone(session.id)
        for role_name in DEFAULT_SESSION_ROLES + [CONVENTION_REVIEWER_ROLE, REQUIREMENTS_REVIEWER_ROLE]:
            role_dir = Path(self.temp_dir.name) / "IOS-30000W" / "runtime" / "role-workspaces" / role_name
            agents_path = role_dir / "AGENTS.md"
            claude_path = role_dir / "CLAUDE.md"
            self.assertTrue(role_dir.is_dir())
            self.assertTrue(agents_path.is_file())
            self.assertTrue(claude_path.is_symlink())
            self.assertEqual("AGENTS.md", claude_path.readlink().as_posix())
            agents_text = agents_path.read_text()
            self.assertIn(f"Role name: `{role_name}`", agents_text)
            self.assertIn("Task session: `IOS-30000W`", agents_text)

        implementer_agents = (
            Path(self.temp_dir.name)
            / "IOS-30000W"
            / "runtime"
            / "role-workspaces"
            / "implementer"
            / "AGENTS.md"
        ).read_text()
        self.assertIn("Task repo worktree:", implementer_agents)
        self.assertIn("Use RAG tools first for code exploration", implementer_agents)
        self.assertIn("Read all routed spec inputs before writing code.", implementer_agents)
        self.assertIn(
            "Do not run build, test, or lint verification. Submit your implementation result; verification happens after this role finishes.",
            implementer_agents,
        )
        verification_agents = (
            Path(self.temp_dir.name)
            / "IOS-30000W"
            / "runtime"
            / "role-workspaces"
            / "verification-coordinator"
            / "AGENTS.md"
        ).read_text()
        self.assertIn("run-test.sh", verification_agents)
        self.assertIn("Final verification report target:", verification_agents)
        self.assertIn("do not run `run-build.sh` here", verification_agents)
        self.assertIn("Do not modify product code.", verification_agents)
        reviewer_agents = (
            Path(self.temp_dir.name)
            / "IOS-30000W"
            / "runtime"
            / "role-workspaces"
            / CONVENTION_REVIEWER_ROLE
            / "AGENTS.md"
        ).read_text()
        self.assertIn("Primary project guidance:", reviewer_agents)
        self.assertIn("Do not run build, test, or lint verification.", reviewer_agents)
        self.assertIn("Keep outputs compact and fixer-oriented.", reviewer_agents)

    def test_create_task_session_creates_bug_fixer_workspace_contract(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30000BUGW",
            workflow_profile="bug_full",
            policy={"test_policy": "required"},
        )

        self.assertIsNotNone(session.id)
        bug_fixer_agents = (
            Path(self.temp_dir.name)
            / "IOS-30000BUGW"
            / "runtime"
            / "role-workspaces"
            / BUG_FIXER_ROLE
            / "AGENTS.md"
        ).read_text()
        self.assertIn("Task description and comments:", bug_fixer_agents)
        self.assertIn("Bug analysis report target:", bug_fixer_agents)
        self.assertIn("Support the routed bug modes inside one runtime identity", bug_fixer_agents)
        self.assertIn("In `analysis-only` mode, read task description/comments first", bug_fixer_agents)
        self.assertIn("If an `Issues file:` path is routed, treat it as the primary scoped input", bug_fixer_agents)
        self.assertIn("fix the root cause cleanly and avoid regressions", bug_fixer_agents)
        self.assertIn("If `Follow-up comments:` are routed, prioritize the latest follow-up comments", bug_fixer_agents)

    def test_create_task_session_creates_role_launch_scripts(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30000L",
            workflow_profile="oneshot",
            policy=None,
        )

        self.assertIsNotNone(session.id)
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        launch_script = (
            Path(self.temp_dir.name)
            / "IOS-30000L"
            / "runtime"
            / "role-workspaces"
            / "implementer"
            / "launch-role.sh"
        )
        self.assertTrue(launch_script.is_file())
        script_text = launch_script.read_text()
        self.assertIn("SDD_FACTORY_TASK_KEY=IOS-30000L", script_text)
        self.assertIn("SDD_FACTORY_ROLE_NAME=implementer", script_text)
        self.assertIn('exec sh', script_text)
        spawn_command = self.session_backend.get_spawn_command(implementer_role.runtime_handle)
        self.assertEqual([str(launch_script)], spawn_command)

    def test_default_role_launcher_uses_repo_bootstrap_script(self) -> None:
        workspace_manager = RoleWorkspaceManager(
            runtime_root=Path(self.temp_dir.name),
            repo_root=Path(self.temp_dir.name) / "repo-root-default-launcher",
            workdir_root=Path(self.temp_dir.name),
        )
        launcher_manager = RoleLauncherManager(
            repo_root=Path(self.temp_dir.name) / "repo-root-default-launcher",
            workdir_root=Path(self.temp_dir.name),
        )
        workspace = workspace_manager.ensure_role_workspace("IOS-30000AUTO", "implementer")
        launch_plan = launcher_manager.ensure_launch_plan(
            task_key="IOS-30000AUTO",
            workspace=workspace,
        )

        script_text = launch_plan.launcher_script.read_text()
        self.assertIn("SDD_FACTORY_WORKDIR_ROOT=", script_text)
        self.assertIn("SDD_FACTORY_TASK_REPO_ROOT=", script_text)
        self.assertIn("/factory/scripts/run-role-agent.sh", script_text)
        self.assertIn("SDD_FACTORY_ROLE_LAUNCHER_READY", script_text)

    def test_role_workspace_scaffolds_task_output_directories(self) -> None:
        workspace_manager = RoleWorkspaceManager(
            runtime_root=Path(self.temp_dir.name),
            repo_root=Path(self.temp_dir.name) / "repo-root-output-dirs",
            workdir_root=Path(self.temp_dir.name),
        )

        workspace_manager.ensure_role_workspace("IOS-30000OUTPUTDIRS", "convention-reviewer")

        task_root = Path(self.temp_dir.name) / "IOS-30000OUTPUTDIRS"
        self.assertTrue((task_root / "tmp").is_dir())
        self.assertTrue((task_root / "review" / "convention").is_dir())
        self.assertTrue((task_root / "review" / "requirements").is_dir())
        self.assertTrue((task_root / "review" / "documentation").is_dir())
        self.assertTrue((task_root / "spec" / "context").is_dir())

    def test_launcher_plan_can_mark_native_resume_mode(self) -> None:
        workspace_manager = RoleWorkspaceManager(
            runtime_root=Path(self.temp_dir.name),
            repo_root=Path(self.temp_dir.name) / "repo-root-resume-launcher",
            workdir_root=Path(self.temp_dir.name),
        )
        launcher_manager = RoleLauncherManager(
            repo_root=Path(self.temp_dir.name) / "repo-root-resume-launcher",
            workdir_root=Path(self.temp_dir.name),
        )
        workspace = workspace_manager.ensure_role_workspace("IOS-30000RESUME", "implementer")
        launch_plan = launcher_manager.ensure_launch_plan(
            task_key="IOS-30000RESUME",
            workspace=workspace,
            role_config={"runner": "claude", "model": "sonnet", "effort": "medium"},
            resume_mode="native",
        )

        script_text = launch_plan.launcher_script.read_text()
        self.assertIn("SDD_FACTORY_ROLE_RESUME_MODE=native", script_text)

    def test_preferred_runtime_resume_mode_uses_native_only_for_codex(self) -> None:
        self.assertEqual(
            "native",
            self.coordinator._preferred_runtime_resume_mode({"runner": "codex"}),
        )
        self.assertIsNone(
            self.coordinator._preferred_runtime_resume_mode({"runner": "claude"}),
        )
        self.assertIsNone(self.coordinator._preferred_runtime_resume_mode(None))

    def test_create_task_session_is_idempotent_for_existing_key(self) -> None:
        first_session, _, _ = self.coordinator.create_task_session(
            "IOS-30001",
            workflow_profile="oneshot",
            policy=None,
        )
        second_session, event, created = self.coordinator.create_task_session(
            "IOS-30001",
            workflow_profile="oneshot",
            policy=None,
        )
        roles = self.role_repository.list_for_session(first_session.id)

        self.assertFalse(created)
        self.assertEqual(first_session.id, second_session.id)
        self.assertEqual("task_session_reused", event.event_type)
        self.assertEqual(2, len(roles))

    def test_create_task_session_rejects_conflicting_existing_policy(self) -> None:
        self.coordinator.create_task_session(
            "IOS-30001A",
            workflow_profile="oneshot",
            policy=None,
        )

        with self.assertRaisesRegex(IntakeError, "different stored policy"):
            self.coordinator.create_task_session(
                "IOS-30001A",
                workflow_profile="oneshot",
                policy={"review_policy": "required"},
            )

    def test_prepare_task_session_runs_intake_and_registers_artifacts(self) -> None:
        session, event, created, details = self.coordinator.prepare_task_session("IOS-30002")
        artifacts = self.artifact_repository.list_for_session(session.id)
        work_items = self.work_item_repository.list_for_session(session.id)
        refreshed_session = self.session_repository.get_by_task_key("IOS-30002")
        events = self.event_repository.list_for_session(session.id)

        self.assertTrue(created)
        self.assertEqual("task_prepared", event.event_type)
        self.assertEqual("IOS-30002", details["resolved_task_key"])
        self.assertEqual("Story", details["issue_type"])
        self.assertEqual(0, details["snapshot_exit_code"])
        self.assertEqual("implementation_requested", details["followup_event_type"])
        self.assertEqual(4, len(artifacts))
        self.assertEqual(1, len(work_items))
        self.assertEqual("Initial implementation for IOS-30002", work_items[0].title)
        self.assertEqual("implementation_requested", refreshed_session.current_stage)
        self.assertEqual("implementer", refreshed_session.current_owner)
        self.assertEqual(
            [
                "task_started",
                "task_prepared",
                "role_input_delivery_confirmed",
                "role_input_dispatched",
                "implementation_requested",
            ],
            [item.event_type for item in events],
        )
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.assertEqual(1, implementer_role.last_hydration_version)
        sent_inputs = self.session_backend.get_sent_inputs(implementer_role.runtime_handle)
        self.assertEqual(1, len(sent_inputs))
        self.assertIn("Start implementation work for IOS-30002.", sent_inputs[0])
        self.assertIn("Read AGENTS.md/CLAUDE.md in the current directory once now", sent_inputs[0])
        self.assertIn("Read HYDRATION.json for machine-readable routed IDs and paths.", sent_inputs[0])
        self.assertNotIn("Role-specific rules:", sent_inputs[0])
        self.assertNotIn("Use RAG tools first for code exploration", sent_inputs[0])

    def test_prepare_task_session_marks_snapshot_failure_as_failed_intake(self) -> None:
        self.snapshot_adapter.set_failure(
            "IOS-30002FAIL",
            stderr=(
                "Running iOS bootstrap...\n"
                "error: Failed to find credentials for 'https://github.com' in keychain: status -128\n"
                "ERROR: iOS bootstrap: 'tuist install' failed\n"
            ),
        )

        session, event, created, details = self.coordinator.prepare_task_session("IOS-30002FAIL")
        artifacts = self.artifact_repository.list_for_session(session.id)
        work_items = self.work_item_repository.list_for_session(session.id)

        self.assertTrue(created)
        self.assertEqual("task_preparation_failed", event.event_type)
        self.assertEqual("failed", session.status.value)
        self.assertEqual("intake_failed", session.current_stage)
        self.assertIsNone(session.current_owner)
        self.assertEqual(1, details["snapshot_exit_code"])
        self.assertIsNone(details["followup_event_type"])
        self.assertEqual([], work_items)
        self.assertIn("Task bootstrap failed", event.payload["summary"])
        self.assertIn("tuist install", event.payload["details"])
        self.assertIn("snapshot.stdout.log", event.payload["stdout_path"])
        self.assertIn("snapshot.stderr.log", event.payload["stderr_path"])
        self.assertTrue(any(item.artifact_type == "snapshot_stdout" for item in artifacts))
        self.assertTrue(any(item.artifact_type == "snapshot_stderr" for item in artifacts))

    def test_prepare_task_session_reuses_existing_policy_aware_session(self) -> None:
        session, _, created = self.coordinator.create_task_session(
            "IOS-30002A",
            workflow_profile="oneshot",
            policy={
                "review_policy": "required",
                                "doc_harvest_policy": "enabled",
            },
        )

        prepared_session, event, prepared_created, details = self.coordinator.prepare_task_session("IOS-30002A")

        self.assertTrue(created)
        self.assertFalse(prepared_created)
        self.assertEqual(session.id, prepared_session.id)
        self.assertEqual("oneshot", prepared_session.workflow_profile)
        self.assertEqual("required", prepared_session.policy["review_policy"])
        self.assertEqual("task_prepared", event.event_type)
        self.assertEqual("implementation_requested", details["followup_event_type"])

    def test_prepare_task_session_routes_bug_full_into_bug_analysis(self) -> None:
        session, _, created = self.coordinator.create_task_session(
            "IOS-30002BUG",
            workflow_profile="bug_full",
            policy={"test_policy": "required"},
        )

        prepared_session, event, prepared_created, details = self.coordinator.prepare_task_session("IOS-30002BUG")
        work_items = self.work_item_repository.list_for_session(prepared_session.id)
        events = self.event_repository.list_for_session(prepared_session.id)
        bug_fixer_role = self.role_repository.get_by_name(prepared_session.id, BUG_FIXER_ROLE)
        sent_inputs = self.session_backend.get_sent_inputs(bug_fixer_role.runtime_handle)

        self.assertTrue(created)
        self.assertFalse(prepared_created)
        self.assertEqual(session.id, prepared_session.id)
        self.assertEqual("task_prepared", event.event_type)
        self.assertEqual("bug_analysis_requested", details["followup_event_type"])
        self.assertEqual("bug_analysis_requested", prepared_session.current_stage)
        self.assertEqual(BUG_FIXER_ROLE, prepared_session.current_owner)
        self.assertEqual("bug_analysis", work_items[0].work_type)
        self.assertEqual(
            [
                "task_started",
                "task_session_reused",
                "task_prepared",
                "role_input_delivery_confirmed",
                "role_input_dispatched",
                "bug_analysis_requested",
            ],
            [item.event_type for item in events],
        )
        self.assertEqual(1, len(sent_inputs))
        self.assertIn("Mode: analysis-only", sent_inputs[0])
        self.assertIn("Analyze bug IOS-30002BUG before implementation.", sent_inputs[0])
        self.assertIn("Test policy for this session: required.", sent_inputs[0])
        self.assertNotIn("Role-specific rules:", sent_inputs[0])
        self.assertNotIn("In `analysis-only` mode, read task description/comments first", sent_inputs[0])
        self.assertNotIn('"bug_analysis_report_path"', sent_inputs[0])

    def test_implementation_completed_moves_session_to_verification(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30003")

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual("verification_requested", updated_session.current_stage)
        self.assertEqual("verification-coordinator", updated_session.current_owner)
        self.assertEqual("verification_requested", followup_event.event_type)
        self.assertEqual([("IOS-30003", "implementation pass")], self.gitlab_adapter.commit_requests)
        self.assertEqual(
            ["completed", "assigned"],
            [work_items[0].status.value, work_items[1].status.value],
        )
        self.assertEqual(
            [
                "task_started",
                "task_prepared",
                "role_input_delivery_confirmed",
                "role_input_dispatched",
                "implementation_requested",
                "implementation_completed",
                "git_commit_completed",
                "role_input_delivery_confirmed",
                "role_input_dispatched",
                "verification_requested",
            ],
            [item.event_type for item in events],
        )
        verification_role = self.role_repository.get_by_name(session.id, "verification-coordinator")
        self.assertEqual(1, verification_role.last_hydration_version)
        sent_inputs = self.session_backend.get_sent_inputs(verification_role.runtime_handle)
        self.assertEqual(1, len(sent_inputs))
        self.assertIn("Run deterministic verification for IOS-30003.", sent_inputs[0])
        self.assertIn("Read AGENTS.md/CLAUDE.md in the current directory once now", sent_inputs[0])
        self.assertNotIn("Role-specific rules:", sent_inputs[0])
        self.assertNotIn("Start from the routed verification strategy file", sent_inputs[0])
        self.assertNotIn("For iOS strategies, prefer the routed `bash scripts/ios-verify.sh", sent_inputs[0])
        self.assertNotIn("verification_report_path", sent_inputs[0])
        self.assertNotIn("verification_strategy_path", sent_inputs[0])

    def test_verification_dispatch_materializes_strategy_file(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30003VERSTRAT")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )

        strategy_path = Path(self.temp_dir.name) / "IOS-30003VERSTRAT" / "spec" / "verification-strategy.json"
        self.assertTrue(strategy_path.exists())
        strategy = json.loads(strategy_path.read_text())
        self.assertEqual("android", strategy["platform"])
        self.assertEqual("android_broad_safe_gate", strategy["mode"])
        self.assertEqual(["prepare", "build", "test", "lint"], strategy["phases"])

    def test_verification_dispatch_materializes_android_strategy_context(self) -> None:
        task_root = Path(self.temp_dir.name) / "ANDR-30003VERCTX"
        repo_root = task_root / "repo"
        module_root = repo_root / "feature" / "payments"
        module_root.mkdir(parents=True, exist_ok=True)
        (repo_root / "gradlew").write_text("#!/usr/bin/env bash\nexit 0\n")
        (module_root / "build.gradle.kts").write_text("plugins {}\n")
        spec_root = task_root / "spec"
        spec_root.mkdir(parents=True, exist_ok=True)
        (spec_root / "diff.md").write_text(
            "# Diff Artifact: ANDR-30003VERCTX\n\n"
            "## Changed Files\n\n"
            "| Status | Path |\n"
            "|---|---|\n"
            "| modified | feature/payments/src/main/java/com/example/PaymentViewModel.kt |\n"
        )
        session, _, _, _ = self.coordinator.prepare_task_session("ANDR-30003VERCTX")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )

        strategy_path = task_root / "spec" / "verification-strategy.json"
        strategy = json.loads(strategy_path.read_text())
        scripts_root = Path(self.temp_dir.name) / "repo-root" / "scripts"
        self.assertEqual("android", strategy["platform"])
        self.assertEqual("android_impacted_module_gate", strategy["mode"])
        self.assertEqual([f"bash {scripts_root / 'android-verify.sh'} {session.task_key}"], strategy["commands"])
        self.assertEqual(["prepare", "build", "test", "lint"], strategy["phases"])
        self.assertEqual("reuse_if_available", strategy["prepare"]["policy"])
        self.assertEqual([":feature:payments"], strategy["impact_mapping"]["impacted_modules"])
        self.assertEqual([":feature:payments:assemble"], strategy["build_selection"]["gradle_build_tasks"])
        self.assertEqual([":feature:payments:test"], strategy["test_selection"]["gradle_test_tasks"])
        self.assertEqual([], strategy["test_selection"]["gradle_lint_tasks"])
        self.assertEqual(
            str(task_root / "tmp" / "verification" / "android" / "gradle-user-home"),
            strategy["android_context"]["gradle_user_home_path"],
        )

    def test_verification_dispatch_marks_android_docs_only_skip(self) -> None:
        task_root = Path(self.temp_dir.name) / "ANDR-30003VERDOCS"
        repo_root = task_root / "repo"
        repo_root.mkdir(parents=True, exist_ok=True)
        spec_root = task_root / "spec"
        spec_root.mkdir(parents=True, exist_ok=True)
        (spec_root / "diff.md").write_text(
            "# Diff Artifact: ANDR-30003VERDOCS\n\n"
            "## Changed Files\n\n"
            "| Status | Path |\n"
            "|---|---|\n"
            "| modified | docs/verification.md |\n"
        )
        session, _, _, _ = self.coordinator.prepare_task_session("ANDR-30003VERDOCS")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )

        strategy_path = task_root / "spec" / "verification-strategy.json"
        strategy = json.loads(strategy_path.read_text())
        self.assertEqual("android_docs_only_skip", strategy["mode"])
        self.assertEqual([], strategy["phases"])
        self.assertTrue(strategy["signals"]["docs_only"])
        self.assertEqual("high", strategy["impact_mapping"]["confidence"])
        self.assertFalse(strategy["impact_mapping"]["fallback_required"])

    def test_verification_dispatch_materializes_ios_strategy_context(self) -> None:
        task_root = Path(self.temp_dir.name) / "IOS-30003VERIOS"
        repo_root = task_root / "repo" / "Tools" / "buildscripts"
        repo_root.mkdir(parents=True, exist_ok=True)
        spec_root = task_root / "spec"
        spec_root.mkdir(parents=True, exist_ok=True)
        (spec_root / "diff.md").write_text(
            "# Diff Artifact: IOS-30003VERIOS\n\n"
            "## Changed Files\n\n"
            "| Status | Path |\n"
            "|---|---|\n"
            "| modified | Finom/FinomTests/Sources/Feature/ExampleTests.swift |\n"
        )
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30003VERIOS")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )

        strategy_path = task_root / "spec" / "verification-strategy.json"
        self.assertTrue(strategy_path.exists())
        strategy = json.loads(strategy_path.read_text())
        scripts_root = Path(self.temp_dir.name) / "repo-root" / "scripts"
        self.assertEqual("ios", strategy["platform"])
        self.assertEqual("ios_test_scope_gate", strategy["mode"])
        self.assertEqual([f"bash {scripts_root / 'ios-verify.sh'} {session.task_key}"], strategy["commands"])
        self.assertEqual(
            ["prepare", "build_for_testing", "test_without_building", "lint"],
            strategy["phases"],
        )
        self.assertEqual("reuse_if_available", strategy["prepare"]["policy"])
        self.assertEqual("reuse_if_same_head", strategy["build_products_policy"])
        self.assertTrue(strategy["signals"]["tests_only"])
        self.assertEqual("only_testing", strategy["test_selection"]["mode"])
        self.assertIn("FinomTests/ExampleTests", strategy["test_selection"]["selectors"])
        self.assertEqual(["FinomApp"], strategy["impact_mapping"]["impacted_areas"])
        self.assertEqual("high", strategy["impact_mapping"]["confidence"])
        self.assertFalse(strategy["impact_mapping"]["fallback_required"])
        self.assertEqual(["Finom"], strategy["impact_mapping"]["impacted_schemes"])
        self.assertEqual(["FinomTests"], strategy["impact_mapping"]["impacted_test_targets"])
        self.assertEqual(
            str(task_root / "tmp" / "verification" / "ios" / "derived-data"),
            strategy["ios_context"]["derived_data_path"],
        )

    def test_verification_dispatch_marks_single_ios_area_impact_mapping(self) -> None:
        task_root = Path(self.temp_dir.name) / "IOS-30003VERAREA"
        repo_root = task_root / "repo" / "Tools" / "buildscripts"
        repo_root.mkdir(parents=True, exist_ok=True)
        spec_root = task_root / "spec"
        spec_root.mkdir(parents=True, exist_ok=True)
        (spec_root / "diff.md").write_text(
            "# Diff Artifact: IOS-30003VERAREA\n\n"
            "## Changed Files\n\n"
            "| Status | Path |\n"
            "|---|---|\n"
            "| modified | FinomCore/Sources/ObservationList/ObservationListService.swift |\n"
        )
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30003VERAREA")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )

        strategy_path = task_root / "spec" / "verification-strategy.json"
        strategy = json.loads(strategy_path.read_text())
        self.assertEqual("ios_impacted_area_gate", strategy["mode"])
        self.assertEqual(["FinomCore"], strategy["impact_mapping"]["impacted_areas"])
        self.assertEqual("high", strategy["impact_mapping"]["confidence"])
        self.assertFalse(strategy["impact_mapping"]["fallback_required"])
        self.assertEqual("Finom", strategy["impact_mapping"]["preferred_scheme"])
        self.assertEqual(["FinomTests"], strategy["test_selection"]["test_targets"])

    def test_verification_dispatch_marks_ios_prepare_sensitive_changes_required(self) -> None:
        task_root = Path(self.temp_dir.name) / "IOS-30003VERPREP"
        repo_root = task_root / "repo" / "Tools" / "buildscripts"
        repo_root.mkdir(parents=True, exist_ok=True)
        spec_root = task_root / "spec"
        spec_root.mkdir(parents=True, exist_ok=True)
        (spec_root / "diff.md").write_text(
            "# Diff Artifact: IOS-30003VERPREP\n\n"
            "## Changed Files\n\n"
            "| Status | Path |\n"
            "|---|---|\n"
            "| modified | Project.swift |\n"
        )
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30003VERPREP")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )

        strategy_path = task_root / "spec" / "verification-strategy.json"
        strategy = json.loads(strategy_path.read_text())
        self.assertEqual("ios_broad_safe_gate", strategy["mode"])
        self.assertEqual("required", strategy["prepare"]["policy"])
        self.assertEqual("rebuild", strategy["build_products_policy"])
        self.assertTrue(strategy["signals"]["prepare_sensitive"])
        self.assertTrue(strategy["impact_mapping"]["fallback_required"])
        self.assertEqual("low", strategy["impact_mapping"]["confidence"])

    def test_verification_dispatch_marks_ios_docs_only_skip(self) -> None:
        task_root = Path(self.temp_dir.name) / "IOS-30003VERDOCS"
        repo_root = task_root / "repo" / "Tools" / "buildscripts"
        repo_root.mkdir(parents=True, exist_ok=True)
        spec_root = task_root / "spec"
        spec_root.mkdir(parents=True, exist_ok=True)
        (spec_root / "diff.md").write_text(
            "# Diff Artifact: IOS-30003VERDOCS\n\n"
            "## Changed Files\n\n"
            "| Status | Path |\n"
            "|---|---|\n"
            "| modified | FinomCore/FinomCore/App Core/README.md |\n"
        )
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30003VERDOCS")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )

        strategy_path = task_root / "spec" / "verification-strategy.json"
        strategy = json.loads(strategy_path.read_text())
        self.assertEqual("ios_docs_only_skip", strategy["mode"])
        self.assertEqual([], strategy["phases"])
        self.assertTrue(strategy["signals"]["docs_only"])
        self.assertEqual("high", strategy["impact_mapping"]["confidence"])
        self.assertFalse(strategy["impact_mapping"]["fallback_required"])

    def test_ios_verification_report_includes_impact_mapping(self) -> None:
        task_root = Path(self.temp_dir.name) / "IOS-30003VERREPORT"
        repo_root = task_root / "repo" / "Tools" / "buildscripts"
        repo_root.mkdir(parents=True, exist_ok=True)
        spec_root = task_root / "spec"
        spec_root.mkdir(parents=True, exist_ok=True)
        (spec_root / "diff.md").write_text(
            "# Diff Artifact: IOS-30003VERREPORT\n\n"
            "## Changed Files\n\n"
            "| Status | Path |\n"
            "|---|---|\n"
            "| modified | FinomCore/Sources/ObservationList/ObservationListService.swift |\n"
        )
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30003VERREPORT")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )
        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={"summary": "all checks passed"},
        )

        verification_report = task_root / "spec" / "final-verification.md"
        report_text = verification_report.read_text()

        self.assertEqual("send_to_test_completed", updated_session.current_stage)
        self.assertEqual("send_to_test_completed", followup_event.event_type)
        self.assertIn("### Impact Mapping", report_text)
        self.assertIn("Impacted areas: FinomCore", report_text)
        self.assertIn("Impacted schemes: Finom", report_text)
        self.assertIn("Impacted test targets: FinomTests", report_text)

    def test_implementation_completed_routes_to_convention_reviewer_when_review_gate_required(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003R",
            workflow_profile="oneshot",
            policy={
                "review_policy": "required",
                                "doc_harvest_policy": "enabled",
            },
        )
        prepared_session, _, _, _ = self.coordinator.prepare_task_session("IOS-30003R")

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=prepared_session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )
        review_items = [
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "convention_review"
        ]
        reviewer_role = self.role_repository.get_by_name(session.id, CONVENTION_REVIEWER_ROLE)
        sent_inputs = self.session_backend.get_sent_inputs(reviewer_role.runtime_handle)

        self.assertEqual("convention_review_requested", updated_session.current_stage)
        self.assertEqual(CONVENTION_REVIEWER_ROLE, updated_session.current_owner)
        self.assertEqual("convention_review_requested", followup_event.event_type)
        self.assertEqual(1, len(review_items))
        self.assertEqual(1, len(sent_inputs))
        self.assertIn("Run convention review for IOS-30003R.", sent_inputs[0])
        self.assertNotIn("Role-specific rules:", sent_inputs[0])
        self.assertNotIn("Primary project guidance", sent_inputs[0])
        self.assertNotIn("review_scope", sent_inputs[0])
        self.assertNotIn("write-result.sh", sent_inputs[0])
        self.assertNotIn("--work-item-id", sent_inputs[0])

    def test_dual_review_passes_route_to_verification(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003RP",
            workflow_profile="oneshot",
            policy={
                "review_policy": "required",
                                "doc_harvest_policy": "enabled",
            },
        )
        prepared_session, _, _, _ = self.coordinator.prepare_task_session("IOS-30003RP")
        self.coordinator.handle_operator_event(
            session_id=prepared_session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )

        updated_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=prepared_session.id,
            role_name=CONVENTION_REVIEWER_ROLE,
            output_type="passed",
            payload={"summary": "clean convention review"},
        )
        self.assertEqual("convention_review_passed", mapped_event.event_type)
        self.assertEqual("requirements_review_requested", followup_event.event_type)
        self.assertEqual("requirements_review_requested", updated_session.current_stage)

        updated_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=prepared_session.id,
            role_name=REQUIREMENTS_REVIEWER_ROLE,
            output_type="passed",
            payload={"summary": "clean requirements review"},
        )
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual("requirements_review_passed", mapped_event.event_type)
        self.assertEqual("verification_requested", followup_event.event_type)
        self.assertEqual("verification_requested", updated_session.current_stage)
        self.assertEqual("verification-coordinator", updated_session.current_owner)
        self.assertTrue(any(item.artifact_type == "convention_review_report_markdown" for item in artifacts))
        self.assertTrue(any(item.artifact_type == "requirements_review_report_markdown" for item in artifacts))
        outcome_artifact = next(item for item in artifacts if item.artifact_type == "requirements_review_outcome_json")
        self.assertEqual("internal_review", outcome_artifact.metadata["report_family"])
        self.assertEqual("requirements", outcome_artifact.metadata["review_lane"])
        self.assertEqual("passed", outcome_artifact.metadata["status"])
        outcome_path = Path(self.temp_dir.name) / "IOS-30003RP" / "review" / "requirements" / "outcome.json"
        self.assertTrue(outcome_path.exists())
        self.assertEqual("passed", json.loads(outcome_path.read_text())["status"])

    def test_verification_completed_requires_explicit_result(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30003VERSTRICT")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )

        with self.assertRaisesRegex(
            IntakeError,
            "Verification output must include payload.result set to 'passed' or 'failed'",
        ):
            self.coordinator.handle_role_output(
                session_id=session.id,
                role_name=VERIFICATION_COORDINATOR_ROLE,
                output_type="completed",
                payload={"summary": "all green"},
            )

    def test_convention_reviewer_output_failed_routes_to_correction(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003RF",
            workflow_profile="oneshot",
            policy={
                "review_policy": "required",
                                "doc_harvest_policy": "enabled",
            },
        )
        prepared_session, _, _, _ = self.coordinator.prepare_task_session("IOS-30003RF")
        self.coordinator.handle_operator_event(
            session_id=prepared_session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )

        updated_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=prepared_session.id,
            role_name=CONVENTION_REVIEWER_ROLE,
            output_type="failed",
            payload={
                "summary": "issues remain",
                "issues": [
                    {
                        "severity": "warning",
                        "file": "Sources/Feature/FlowController.swift",
                        "problem": "Retry state is still duplicated across two branches.",
                        "required_change": "Consolidate the retry state handling behind one branch.",
                        "why_it_matters": "Keeping the duplicate state path makes future regressions more likely.",
                        "required_direction": "Use one shared retry path for the touched flow instead of parallel branches.",
                        "non_goals": "Do not broaden this correction into unrelated flow-controller cleanup.",
                        "evidence": "The touched branch now stores retry state both before and after the shared helper call.",
                        "suggested_approach": "Route both call sites back through the existing shared retry helper instead of carrying a second local branch.",
                        "test_expectations": "Re-run the retry-state unit coverage and confirm both branches still converge on one state path.",
                    }
                ],
            },
        )
        artifacts = self.artifact_repository.list_for_session(session.id)
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        sent_inputs = self.session_backend.get_sent_inputs(implementer_role.runtime_handle)

        self.assertEqual("convention_review_issues_found", mapped_event.event_type)
        self.assertEqual("convention_review_correction_requested", followup_event.event_type)
        self.assertEqual("convention_review_correction_requested", updated_session.current_stage)
        self.assertEqual("implementer", updated_session.current_owner)
        report_artifact = next(item for item in artifacts if item.artifact_type == "convention_review_report_markdown")
        self.assertEqual("internal_review", report_artifact.metadata["report_family"])
        self.assertEqual("convention", report_artifact.metadata["review_lane"])
        self.assertEqual("report", report_artifact.metadata["artifact_role"])
        self.assertEqual("issues_found", report_artifact.metadata["status"])
        hydration_path = (
            Path(self.temp_dir.name)
            / "IOS-30003RF"
            / "runtime"
            / "role-workspaces"
            / IMPLEMENTER_ROLE
            / "HYDRATION.json"
        )
        hydration = json.loads(hydration_path.read_text())
        self.assertEqual("convention_review", hydration["correction_source"])
        self.assertIn("issues_file_path", hydration)
        self.assertIn("correction_report_path", hydration)
        self.assertIn("pass-01.md", hydration["correction_report_path"])
        review_report = (Path(self.temp_dir.name) / "IOS-30003RF" / "review" / "convention" / "pass-01.md").read_text()
        self.assertIn("- Why it matters: Keeping the duplicate state path makes future regressions more likely.", review_report)
        self.assertIn("- Required direction: Use one shared retry path for the touched flow instead of parallel branches.", review_report)
        self.assertIn("- Non-goals: Do not broaden this correction into unrelated flow-controller cleanup.", review_report)
        self.assertIn("- Evidence: The touched branch now stores retry state both before and after the shared helper call.", review_report)
        self.assertIn("- Suggested approach: Route both call sites back through the existing shared retry helper instead of carrying a second local branch.", review_report)
        self.assertIn("- Test expectations: Re-run the retry-state unit coverage and confirm both branches still converge on one state path.", review_report)
        outcome_path = Path(self.temp_dir.name) / "IOS-30003RF" / "review" / "convention" / "outcome.json"
        self.assertTrue(outcome_path.exists())
        self.assertEqual("issues_found", json.loads(outcome_path.read_text())["status"])

    def test_review_correction_completion_reenters_full_review_gate(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003RC",
            workflow_profile="oneshot",
            policy={
                "review_policy": "required",
                                "doc_harvest_policy": "disabled",
            },
        )
        prepared_session, _, _, _ = self.coordinator.prepare_task_session("IOS-30003RC")
        self.coordinator.handle_operator_event(
            session_id=prepared_session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )
        self.coordinator.handle_role_output(
            session_id=prepared_session.id,
            role_name=CONVENTION_REVIEWER_ROLE,
            output_type="passed",
            payload={"summary": "clean convention review"},
        )
        self.coordinator.handle_role_output(
            session_id=prepared_session.id,
            role_name=REQUIREMENTS_REVIEWER_ROLE,
            output_type="failed",
            payload={"summary": "missing edge case"},
        )

        updated_session, _mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=prepared_session.id,
            role_name=IMPLEMENTER_ROLE,
            output_type="completed",
            payload={"summary": "requirements review fix done"},
        )

        self.assertEqual("convention_review_requested", updated_session.current_stage)
        self.assertEqual(CONVENTION_REVIEWER_ROLE, updated_session.current_owner)
        self.assertEqual("convention_review_requested", followup_event.event_type)

    def test_dual_review_recheck_includes_operator_guidance_from_prior_correction(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003DUALGUIDE",
            workflow_profile="story_full",
            policy={
                "review_policy": "enabled",
                                "doc_harvest_policy": "disabled",
            },
        )
        prepared_session, _, _, _ = self.coordinator.prepare_task_session("IOS-30003DUALGUIDE")
        operator_event = self.event_repository.append(
            session_id=session.id,
            event_type="operator_runtime_input_sent",
            producer_type="operator",
            payload={
                "role_name": IMPLEMENTER_ROLE,
                "work_item_id": 2105,
                "current_stage": "convention_review_correction_requested",
                "continuation_stage": "convention_review_correction_requested",
                "input_length": 79,
                "operator_reply": (
                    "Use class-style screen keys; the snake_case screen tags are downstream artifacts "
                    "and not authoritative."
                ),
            },
        )

        instruction, hydration = self.coordinator._dual_review_dispatch_context(  # noqa: SLF001
            prepared_session,
            lane="requirements",
        )

        self.assertIn("Authoritative operator decisions from prior escalations in this session", instruction)
        self.assertIn("Use class-style screen keys", instruction)
        self.assertIn("do not re-flag", instruction)
        self.assertEqual(operator_event.id, hydration["operator_reply_event_id"])
        self.assertIn("snake_case screen tags", str(hydration["operator_reply"]))
        self.assertIn("operator_guided_recheck", str(hydration["review_cycle_resolution"]))
        self.assertIn("operator_resolution_history", hydration)

    def test_dual_review_recheck_includes_operator_guidance_from_implementation_escalation(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003DUALIMPLGUIDE",
            workflow_profile="story_full",
            policy={
                "review_policy": "enabled",
                                "doc_harvest_policy": "disabled",
            },
        )
        prepared_session, _, _, _ = self.coordinator.prepare_task_session("IOS-30003DUALIMPLGUIDE")
        operator_event = self.event_repository.append(
            session_id=session.id,
            event_type="operator_runtime_input_sent",
            producer_type="operator",
            payload={
                "role_name": IMPLEMENTER_ROLE,
                "work_item_id": 2860,
                "current_stage": "subtask_implementation_requested",
                "continuation_stage": "subtask_implementation_requested",
                "input_length": 135,
                "operator_reply": (
                    "The real target is CardAlmostOrdered, not CardsAlmostReady. "
                    "Do not add a no-op mask to CardsAlmostReady."
                ),
            },
        )

        instruction, hydration = self.coordinator._dual_review_dispatch_context(  # noqa: SLF001
            prepared_session,
            lane="requirements",
        )

        self.assertIn("Authoritative operator decisions from prior escalations in this session", instruction)
        self.assertIn("The real target is CardAlmostOrdered", instruction)
        self.assertIn("Do not add a no-op mask to CardsAlmostReady", instruction)
        self.assertEqual(operator_event.id, hydration["operator_reply_event_id"])
        self.assertIn("CardAlmostOrdered", str(hydration["operator_reply"]))
        self.assertIn("operator_guided_recheck", str(hydration["review_cycle_resolution"]))
        self.assertIn("operator_resolution_history", hydration)

    def test_bug_analysis_completed_moves_session_to_implementation(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003BUG",
            workflow_profile="bug_full",
            policy={"test_policy": "required"},
        )
        self.coordinator.prepare_task_session("IOS-30003BUG")

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="bug_analysis_completed",
            payload={
                "summary": "Likely missing state reset in coordinator",
                "test_strategy": "Add regression test for repeated resume path",
            },
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        events = self.event_repository.list_for_session(session.id)
        bug_fixer_role = self.role_repository.get_by_name(session.id, BUG_FIXER_ROLE)
        bug_fixer_inputs = self.session_backend.get_sent_inputs(bug_fixer_role.runtime_handle)

        self.assertEqual("implementation_requested", updated_session.current_stage)
        self.assertEqual(BUG_FIXER_ROLE, updated_session.current_owner)
        self.assertEqual("implementation_requested", followup_event.event_type)
        self.assertEqual(
            ["completed", "assigned"],
            [work_items[0].status.value, work_items[1].status.value],
        )
        self.assertEqual(
            [
                "task_started",
                "task_session_reused",
                "task_prepared",
                "role_input_delivery_confirmed",
                "role_input_dispatched",
                "bug_analysis_requested",
                "bug_analysis_completed",
                "role_input_delivery_confirmed",
                "role_input_dispatched",
                "implementation_requested",
            ],
            [item.event_type for item in events],
        )
        self.assertEqual(2, len(bug_fixer_inputs))
        self.assertIn("Mode: fix-only", bug_fixer_inputs[-1])
        self.assertIn("Implement the bug fix for IOS-30003BUG", bug_fixer_inputs[-1])
        self.assertIn(
            "Bug analysis summary: Likely missing state reset in coordinator",
            bug_fixer_inputs[-1],
        )
        self.assertIn("Continue from your existing role context.", bug_fixer_inputs[-1])
        self.assertNotIn('"bug_analysis_report_path"', bug_fixer_inputs[-1])
        self.assertNotIn('"bug_mode": "fix-only"', bug_fixer_inputs[-1])
        self.assertNotIn("In `fix-only` mode, read the saved `spec/bug-analysis.md` first", bug_fixer_inputs[-1])
        bug_fixer_hydration = json.loads(
            (
                Path(self.temp_dir.name)
                / "IOS-30003BUG"
                / "runtime"
                / "role-workspaces"
                / BUG_FIXER_ROLE
                / "HYDRATION.json"
            ).read_text()
        )
        self.assertEqual("fix-only", bug_fixer_hydration["bug_mode"])

    def test_prepare_task_session_routes_story_full_into_proposal_context(self) -> None:
        session, _, created = self.coordinator.create_task_session(
            "IOS-30002STORY",
            workflow_profile="story_full",
            policy=None,
        )

        prepared_session, event, prepared_created, details = self.coordinator.prepare_task_session("IOS-30002STORY")
        work_items = self.work_item_repository.list_for_session(prepared_session.id)
        events = self.event_repository.list_for_session(prepared_session.id)
        proposal_role = self.role_repository.get_by_name(prepared_session.id, PROPOSAL_CONTEXT_WORKER_ROLE)
        sent_inputs = self.session_backend.get_sent_inputs(proposal_role.runtime_handle)

        self.assertTrue(created)
        self.assertFalse(prepared_created)
        self.assertEqual(session.id, prepared_session.id)
        self.assertEqual("task_prepared", event.event_type)
        self.assertEqual("proposal_context_requested", details["followup_event_type"])
        self.assertEqual("proposal_context_requested", prepared_session.current_stage)
        self.assertEqual(PROPOSAL_CONTEXT_WORKER_ROLE, prepared_session.current_owner)
        self.assertEqual("proposal_context", work_items[0].work_type)
        self.assertEqual(
            [
                "task_started",
                "task_session_reused",
                "task_prepared",
                "role_input_delivery_confirmed",
                "role_input_dispatched",
                "proposal_context_requested",
            ],
            [item.event_type for item in events],
        )
        self.assertEqual(1, len(sent_inputs))
        self.assertIn(
            "Produce the proposal and context package for story IOS-30002STORY before downstream planning and decomposition.",
            sent_inputs[0],
        )
        self.assertNotIn("Role-specific rules:", sent_inputs[0])
        launch_script = (
            Path(self.temp_dir.name)
            / "IOS-30002STORY"
            / "runtime"
            / "role-workspaces"
            / PROPOSAL_CONTEXT_WORKER_ROLE
            / "launch-role.sh"
        )
        self.assertTrue(launch_script.is_file())
        launch_script_text = launch_script.read_text()
        proposal_agents = (
            Path(self.temp_dir.name)
            / "IOS-30002STORY"
            / "runtime"
            / "role-workspaces"
            / PROPOSAL_CONTEXT_WORKER_ROLE
            / "AGENTS.md"
        ).read_text()
        self.assertIn("Proposal target:", proposal_agents)
        self.assertIn("Required snapshot inputs:", proposal_agents)
        self.assertIn("Context directory:", proposal_agents)
        self.assertIn("Required context output:", proposal_agents)
        self.assertIn("one bounded proposal-context pass", proposal_agents)
        self.assertIn("Read `description.md` and `comments.md`", proposal_agents)
        self.assertIn("comments.md` as the fresher source", proposal_agents)
        self.assertIn("operator-provided context references rather than mandatory fetched inputs", proposal_agents)
        self.assertIn("SDD_FACTORY_ROLE_LIFECYCLE=one-shot", launch_script_text)
        self.assertIn("lifecycle=%s", launch_script_text)

    def test_proposal_context_link_warning_emits_event_and_artifact_for_external_links(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30002LINKS",
            workflow_profile="story_full",
        )
        task_root = Path(self.temp_dir.name) / session.task_key
        task_root.mkdir(parents=True, exist_ok=True)
        (task_root / "description.md").write_text(
            "Reference spec: https://example.com/spec\nAnd Notion: https://workspace.notion.so/page\n"
        )
        (task_root / "comments.md").write_text(
            "Fresh comment with same external ref https://example.com/spec and local note.\n"
        )

        self.coordinator._emit_proposal_context_link_warning(session)

        events = self.event_repository.list_for_session(session.id)
        artifacts = self.artifact_repository.list_for_session(session.id)
        self.assertEqual("proposal_external_links_detected", events[-1].event_type)
        self.assertEqual(2, events[-1].payload["link_count"])
        warning_artifact = next(
            artifact for artifact in artifacts if artifact.artifact_type == "proposal_external_links_warning"
        )
        warning_text = Path(warning_artifact.path).read_text()
        self.assertIn("https://example.com/spec", warning_text)
        self.assertIn("notion.so/page", warning_text)

    def test_proposal_context_completed_moves_story_session_to_requirements(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003PC",
            workflow_profile="story_full",
            policy={"requirements_clarification_mode": "ask-a-lot"},
        )
        self.coordinator.prepare_task_session("IOS-30003PC")

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={"summary": "Scope clarified", "context_findings": "Reuse existing presenter flow"},
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        requirements_role = self.role_repository.get_by_name(session.id, REQUIREMENTS_CLARIFIER_WORKER_ROLE)
        sent_inputs = self.session_backend.get_sent_inputs(requirements_role.runtime_handle)
        role_workspace = self.coordinator.role_workspace_manager.role_directory(  # type: ignore[union-attr]
            session.task_key,
            REQUIREMENTS_CLARIFIER_WORKER_ROLE,
        )
        hydration = json.loads((role_workspace / "HYDRATION.json").read_text())

        self.assertEqual("requirements_requested", updated_session.current_stage)
        self.assertEqual(REQUIREMENTS_CLARIFIER_WORKER_ROLE, updated_session.current_owner)
        self.assertEqual("requirements_requested", followup_event.event_type)
        outcome_path = Path(self.temp_dir.name) / "IOS-30003PC" / "spec" / "proposal_context-outcome.json"
        self.assertTrue(outcome_path.exists())
        self.assertEqual("completed", json.loads(outcome_path.read_text())["status"])
        self.assertEqual(
            [("proposal_context", "completed"), ("requirements", "assigned")],
            sorted((item.work_type, item.status.value) for item in work_items),
        )
        self.assertEqual(1, len(sent_inputs))
        self.assertIn("Clarify the implementation requirements for story IOS-30003PC.", sent_inputs[0])
        self.assertIn("Clarification mode for this session: ask-a-lot.", sent_inputs[0])
        self.assertIn("Proposal/context summary: Scope clarified", sent_inputs[0])
        self.assertIn("Key context findings: Reuse existing presenter flow", sent_inputs[0])
        self.assertIn("Context package available under `spec/context/`", sent_inputs[0])
        self.assertEqual("ask-a-lot", hydration["requirements_clarification_mode"])
        self.assertNotIn("feature_overview_path", hydration)
        self.assertTrue(hydration["proposal_path"].endswith("spec/proposal.md"))
        self.assertNotIn("documentation_path", hydration)
        self.assertNotIn("implementation_patterns_path", hydration)
        self.assertNotIn("preconditions_path", hydration)

    def test_proposal_context_completed_syncs_context_outputs_from_role_workspace(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003CTX",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30003CTX")
        proposal_workspace = self.coordinator.role_workspace_manager.role_directory(  # type: ignore[union-attr]
            session.task_key,
            PROPOSAL_CONTEXT_WORKER_ROLE,
        )
        feature_overview = proposal_workspace / "spec" / "context" / "feature-overview.md"
        feature_overview.parent.mkdir(parents=True, exist_ok=True)
        feature_overview.write_text("# Feature Overview\n\nGrounded context.\n")

        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={
                "summary": "Scope clarified",
                "outputs": ["spec/proposal.md", "spec/context/feature-overview.md", "RESULT.json"],
            },
        )

        synced_feature_overview = Path(self.temp_dir.name) / session.task_key / "spec" / "context" / "feature-overview.md"
        self.assertTrue(synced_feature_overview.is_file())
        self.assertEqual("# Feature Overview\n\nGrounded context.\n", synced_feature_overview.read_text())

    def test_requirements_hydration_includes_only_existing_story_context_files(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003CTXSEL",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30003CTXSEL")
        proposal_workspace = self.coordinator.role_workspace_manager.role_directory(  # type: ignore[union-attr]
            session.task_key,
            PROPOSAL_CONTEXT_WORKER_ROLE,
        )
        feature_overview = proposal_workspace / "spec" / "context" / "feature-overview.md"
        relevant_code = proposal_workspace / "spec" / "context" / "relevant-code.md"
        feature_overview.parent.mkdir(parents=True, exist_ok=True)
        feature_overview.write_text("# Feature Overview\n\nGrounded context.\n")
        relevant_code.write_text("# Relevant Code\n\nGrounded code context.\n")

        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={
                "summary": "Scope clarified",
                "outputs": [
                    "spec/proposal.md",
                    "spec/context/feature-overview.md",
                    "spec/context/relevant-code.md",
                    "RESULT.json",
                ],
            },
        )
        requirements_workspace = self.coordinator.role_workspace_manager.role_directory(  # type: ignore[union-attr]
            session.task_key,
            REQUIREMENTS_CLARIFIER_WORKER_ROLE,
        )
        hydration = json.loads((requirements_workspace / "HYDRATION.json").read_text())

        self.assertTrue(hydration["feature_overview_path"].endswith("spec/context/feature-overview.md"))
        self.assertTrue(hydration["relevant_code_path"].endswith("spec/context/relevant-code.md"))
        self.assertNotIn("documentation_path", hydration)
        self.assertNotIn("implementation_patterns_path", hydration)
        self.assertNotIn("preconditions_path", hydration)

    def test_bug_fixer_followup_hydration_omits_missing_optional_input_paths(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003BUGHYD",
            workflow_profile="bug_full",
            policy=None,
        )
        bug_fixer_role = self.role_repository.get_by_name(session.id, BUG_FIXER_ROLE)
        assert bug_fixer_role is not None

        hydration = self.coordinator._sanitize_dispatch_hydration(  # type: ignore[attr-defined]
            self.coordinator._default_extra_hydration_for_dispatch(  # type: ignore[attr-defined]
                session,
                bug_fixer_role,
                "qa_reopen_requested",
            )
        )

        self.assertEqual("fix-only", hydration["bug_mode"])
        self.assertNotIn("bug_analysis_report_path", hydration)
        self.assertNotIn("followup_comments_path", hydration)
        self.assertNotIn("followup_plan_index_path", hydration)
        self.assertNotIn("followup_plan_directory_path", hydration)

    def test_requirements_completed_moves_story_session_to_acceptance_criteria(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003REQ",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30003REQ")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={"summary": "Scope clarified"},
        )

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="requirements_completed",
            payload={"summary": "Requirements clarified", "assumptions": "Reuse existing screen state"},
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        acceptance_role = self.role_repository.get_by_name(session.id, ACCEPTANCE_CRITERIA_WORKER_ROLE)
        sent_inputs = self.session_backend.get_sent_inputs(acceptance_role.runtime_handle)

        self.assertEqual("acceptance_criteria_requested", updated_session.current_stage)
        self.assertEqual(ACCEPTANCE_CRITERIA_WORKER_ROLE, updated_session.current_owner)
        self.assertEqual("active", updated_session.status.value)
        self.assertEqual("acceptance_criteria_requested", followup_event.event_type)
        outcome_path = Path(self.temp_dir.name) / "IOS-30003REQ" / "spec" / "requirements-outcome.json"
        self.assertTrue(outcome_path.exists())
        self.assertEqual("completed", json.loads(outcome_path.read_text())["status"])
        self.assertEqual(
            [
                ("acceptance_criteria", "assigned"),
                ("proposal_context", "completed"),
                ("requirements", "completed"),
            ],
            sorted((item.work_type, item.status.value) for item in work_items),
        )
        self.assertEqual(1, len(sent_inputs))
        self.assertIn("Prepare explicit acceptance criteria for story IOS-30003REQ.", sent_inputs[0])
        self.assertIn("WHEN-THEN-SHALL criteria", sent_inputs[0])
        self.assertIn("Requirements summary: Requirements clarified", sent_inputs[0])
        self.assertIn("Explicit assumptions: Reuse existing screen state", sent_inputs[0])

    def test_requirements_completed_with_operator_input_parks_story_session(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003REQPARK",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30003REQPARK")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={"summary": "Scope clarified"},
        )

        updated_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=REQUIREMENTS_CLARIFIER_WORKER_ROLE,
            output_type="completed",
            payload={
                "summary": "Requirements clarification needs operator confirmation.",
                "needs_operator_input": True,
                "pending_decisions": ["Pick the public API shape."],
            },
        )
        work_items = self.work_item_repository.list_for_session(session.id)

        self.assertEqual("story_planning_blocked", mapped_event.event_type)
        self.assertIsNotNone(followup_event)
        self.assertEqual("session_escalated_to_operator", followup_event.event_type)
        self.assertEqual(SessionStatus.WAITING_FOR_OPERATOR, updated_session.status)
        self.assertEqual("requirements_requested", updated_session.current_stage)
        self.assertEqual(REQUIREMENTS_CLARIFIER_WORKER_ROLE, updated_session.current_owner)
        self.assertEqual(
            [
                ("proposal_context", "completed"),
                ("requirements", "waiting_for_operator"),
            ],
            sorted((item.work_type, item.status.value) for item in work_items),
        )

    def test_story_planning_blocked_output_requires_explicit_signal(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003REQINVALID",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30003REQINVALID")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={"summary": "Scope clarified"},
        )

        with self.assertRaisesRegex(
            IntakeError,
            "requirements-clarifier-worker blocked output must include payload.summary, payload.details, payload.next_step, or structured blocker lists",
        ):
            self.coordinator.handle_role_output(
                session_id=session.id,
                role_name=REQUIREMENTS_CLARIFIER_WORKER_ROLE,
                output_type="failed",
                payload={},
            )

    def test_acceptance_criteria_failed_parks_story_session(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003ACCPARK",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30003ACCPARK")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={"summary": "Scope clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="requirements_completed",
            payload={"summary": "Requirements clarified"},
        )

        updated_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=ACCEPTANCE_CRITERIA_WORKER_ROLE,
            output_type="failed",
            payload={
                "summary": "Acceptance criteria blocked by missing requirement decisions.",
                "needs_operator_input": True,
                "failures": ["Requirements clarification is explicitly blocked."],
            },
        )
        work_items = self.work_item_repository.list_for_session(session.id)

        self.assertEqual("story_planning_blocked", mapped_event.event_type)
        self.assertIsNotNone(followup_event)
        self.assertEqual("session_escalated_to_operator", followup_event.event_type)
        self.assertEqual(SessionStatus.WAITING_FOR_OPERATOR, updated_session.status)
        self.assertEqual("acceptance_criteria_requested", updated_session.current_stage)
        self.assertEqual(ACCEPTANCE_CRITERIA_WORKER_ROLE, updated_session.current_owner)
        self.assertEqual(
            [
                ("acceptance_criteria", "waiting_for_operator"),
                ("proposal_context", "completed"),
                ("requirements", "completed"),
            ],
            sorted((item.work_type, item.status.value) for item in work_items),
        )

    def test_acceptance_criteria_completed_moves_story_session_to_constraints(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003ACC",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30003ACC")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={"summary": "Scope clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="requirements_completed",
            payload={"summary": "Requirements clarified"},
        )

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="acceptance_criteria_completed",
            payload={"summary": "Acceptance prepared", "highlighted_cases": "Retry + empty state"},
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        constraints_role = self.role_repository.get_by_name(session.id, CONSTRAINTS_WORKER_ROLE)
        sent_inputs = self.session_backend.get_sent_inputs(constraints_role.runtime_handle)

        self.assertEqual("constraints_requested", updated_session.current_stage)
        self.assertEqual(CONSTRAINTS_WORKER_ROLE, updated_session.current_owner)
        self.assertEqual("constraints_requested", followup_event.event_type)
        outcome_path = Path(self.temp_dir.name) / "IOS-30003ACC" / "spec" / "acceptance_criteria-outcome.json"
        self.assertTrue(outcome_path.exists())
        self.assertEqual("completed", json.loads(outcome_path.read_text())["status"])
        self.assertEqual(
            [
                ("acceptance_criteria", "completed"),
                ("constraints", "assigned"),
                ("proposal_context", "completed"),
                ("requirements", "completed"),
            ],
            sorted((item.work_type, item.status.value) for item in work_items),
        )
        self.assertEqual(1, len(sent_inputs))
        self.assertIn("Prepare grounded implementation constraints for story IOS-30003ACC.", sent_inputs[0])
        self.assertIn("`spec/context/project.md` as architectural ground truth", sent_inputs[0])
        self.assertIn("Acceptance criteria summary: Acceptance prepared", sent_inputs[0])
        self.assertIn("Highlighted cases: Retry + empty state", sent_inputs[0])

    def test_constraints_completed_moves_story_session_to_spec_verification(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003CONSTR",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30003CONSTR")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={"summary": "Scope clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="requirements_completed",
            payload={"summary": "Requirements clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="acceptance_criteria_completed",
            payload={"summary": "Acceptance prepared"},
        )

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="constraints_completed",
            payload={"summary": "Respect analytics + assembly conventions", "key_constraints": "Reuse existing assembly pattern and analytics hooks"},
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        verifier_role = self.role_repository.get_by_name(session.id, SPEC_VERIFIER_WORKER_ROLE)
        sent_inputs = self.session_backend.get_sent_inputs(verifier_role.runtime_handle)

        self.assertEqual("spec_verification_requested", updated_session.current_stage)
        self.assertEqual(SPEC_VERIFIER_WORKER_ROLE, updated_session.current_owner)
        self.assertEqual("spec_verification_requested", followup_event.event_type)
        self.assertEqual(
            [
                ("acceptance_criteria", "completed"),
                ("constraints", "completed"),
                ("proposal_context", "completed"),
                ("requirements", "completed"),
                ("spec_verification", "assigned"),
            ],
            sorted((item.work_type, item.status.value) for item in work_items),
        )
        self.assertEqual("running", verifier_role.status.value)
        self.assertEqual(1, len(sent_inputs))
        self.assertIn("Verify the assembled planning package for story IOS-30003CONSTR", sent_inputs[0])
        self.assertIn("Constraints summary: Respect analytics + assembly conventions", sent_inputs[0])
        self.assertIn("Key constraints: Reuse existing assembly pattern and analytics hooks", sent_inputs[0])

    def test_spec_verification_completed_moves_story_session_to_task_decomposition(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003VERIFY",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30003VERIFY")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={"summary": "Scope clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="requirements_completed",
            payload={"summary": "Requirements clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="acceptance_criteria_completed",
            payload={"summary": "Acceptance prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="constraints_completed",
            payload={"summary": "Constraints prepared"},
        )

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="spec_verification_completed",
            payload={"summary": "Planning package is coherent", "verified_focus": "navigation + state ownership"},
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        decomposer_role = self.role_repository.get_by_name(session.id, TASK_DECOMPOSER_WORKER_ROLE)
        sent_inputs = self.session_backend.get_sent_inputs(decomposer_role.runtime_handle)

        self.assertEqual("task_decomposition_requested", updated_session.current_stage)
        self.assertEqual(TASK_DECOMPOSER_WORKER_ROLE, updated_session.current_owner)
        self.assertEqual("task_decomposition_requested", followup_event.event_type)
        self.assertEqual(
            [
                ("acceptance_criteria", "completed"),
                ("constraints", "completed"),
                ("proposal_context", "completed"),
                ("requirements", "completed"),
                ("spec_verification", "completed"),
                ("task_decomposition", "assigned"),
            ],
            sorted((item.work_type, item.status.value) for item in work_items),
        )
        self.assertEqual(1, len(sent_inputs))
        self.assertIn("Prepare task decomposition for story IOS-30003VERIFY before implementation starts.", sent_inputs[0])
        self.assertIn("Planning verification summary: Planning package is coherent", sent_inputs[0])
        self.assertIn("Verified focus: navigation + state ownership", sent_inputs[0])
        outcome_path = Path(self.temp_dir.name) / "IOS-30003VERIFY" / "spec" / "spec-verification-outcome.json"
        self.assertTrue(outcome_path.exists())
        self.assertEqual("completed", json.loads(outcome_path.read_text())["status"])

    def test_spec_verification_failed_escalates_story_session_to_operator(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003VERIFYBLOCK",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30003VERIFYBLOCK")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={"summary": "Scope clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="requirements_completed",
            payload={"summary": "Requirements clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="acceptance_criteria_completed",
            payload={"summary": "Acceptance prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="constraints_completed",
            payload={"summary": "Constraints prepared"},
        )

        updated_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=SPEC_VERIFIER_WORKER_ROLE,
            output_type="failed",
            payload={
                "summary": "Planning blockers require operator decisions.",
                "details": "Two contradictory scope choices remain unresolved.",
                "blocker_questions": [
                    "Should notifications remain inline or move to a separate settings screen?",
                    "Must offline draft persistence be required in v1?",
                ],
            },
        )
        work_items = self.work_item_repository.list_for_session(session.id)

        self.assertEqual("story_planning_blocked", mapped_event.event_type)
        self.assertEqual("session_escalated_to_operator", followup_event.event_type)
        self.assertEqual("waiting_for_operator", updated_session.status.value)
        self.assertEqual("spec_verification_requested", updated_session.current_stage)
        self.assertEqual(SPEC_VERIFIER_WORKER_ROLE, updated_session.current_owner)
        self.assertTrue(bool(followup_event.payload.get("needs_operator_input")))
        self.assertIn("Questions:", str(followup_event.payload.get("details")))
        self.assertIn("Should notifications remain inline", str(followup_event.payload.get("details")))
        self.assertTrue(any(item.work_type == "spec_verification" and item.status.value == "waiting_for_operator" for item in work_items))
        outcome_path = Path(self.temp_dir.name) / "IOS-30003VERIFYBLOCK" / "spec" / "spec-verification-outcome.json"
        self.assertTrue(outcome_path.exists())
        self.assertEqual("blocked", json.loads(outcome_path.read_text())["status"])

    def test_spec_verification_blockers_require_runtime_input_in_interactive_summary(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003SVINPUT",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30003SVINPUT")
        for event_type, summary in [
            ("proposal_context_completed", "Scope clarified"),
            ("requirements_completed", "Requirements clarified"),
            ("acceptance_criteria_completed", "Acceptance prepared"),
            ("constraints_completed", "Constraints prepared"),
        ]:
            self.coordinator.handle_operator_event(
                session_id=session.id,
                event_type=event_type,
                payload={"summary": summary},
            )

        self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=SPEC_VERIFIER_WORKER_ROLE,
            output_type="failed",
            payload={
                "summary": "Planning blockers require operator decisions.",
                "details": "Two contradictory scope choices remain unresolved.",
                "blocker_questions": ["Choose notification model"],
            },
        )

        summary = self.coordinator.get_interactive_state_summary(session.id)

        self.assertTrue(summary["available"])
        self.assertEqual("spec_verification_blocked", summary["source_reason"])
        self.assertEqual(SPEC_VERIFIER_WORKER_ROLE, summary["role_name"])
        self.assertTrue(summary["needs_operator_input"])
        self.assertIn("Choose notification model", str(summary["details"]))

    def test_interactive_summary_recovers_spec_verification_questions_from_legacy_blank_escalation(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003SVLEGACY",
            workflow_profile="story_full",
            policy=None,
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="spec_verification_requested",
            current_owner=SPEC_VERIFIER_WORKER_ROLE,
        )
        self.session_repository.update_status(session.id, SessionStatus.WAITING_FOR_OPERATOR)
        self.event_repository.append(
            session_id=session.id,
            event_type="story_planning_blocked",
            producer_type="role",
            payload={
                "summary": "Planning verification failed",
                "work_item_id": 123,
                "blocker_questions": ["Which repository should own the durable state?"],
            },
        )
        self.event_repository.append(
            session_id=session.id,
            event_type="session_escalated_to_operator",
            producer_type="coordinator",
            payload={
                "reason": "spec_verification_blocked",
                "role_name": SPEC_VERIFIER_WORKER_ROLE,
                "work_item_id": 123,
                "summary": "Planning verification failed",
                "details": "",
                "needs_operator_input": True,
                "current_stage": "spec_verification_requested",
            },
        )

        summary = self.coordinator.get_interactive_state_summary(session.id)

        self.assertTrue(summary["available"])
        self.assertIn("Which repository should own the durable state?", str(summary["details"]))

    def test_interactive_summary_ignores_stale_blocker_from_previous_stage(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003STALEBLOCKER",
            workflow_profile="oneshot",
            policy=None,
        )
        self.event_repository.append(
            session_id=session.id,
            event_type="session_escalated_to_operator",
            producer_type="coordinator",
            payload={
                "reason": "runtime_error",
                "role_name": IMPLEMENTER_ROLE,
                "current_stage": "requirements_review_correction_requested",
                "summary": "Old correction conflict",
                "details": "This was already resolved.",
                "needs_operator_input": True,
            },
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="mr_handoff_failed",
            current_owner=None,
        )
        self.session_repository.update_status(session.id, SessionStatus.WAITING_FOR_OPERATOR)

        summary = self.coordinator.get_interactive_state_summary(session.id)

        self.assertFalse(summary["available"])
        self.assertFalse(summary["needs_operator_input"])

    def test_spec_verifier_blocked_output_requires_summary_or_questions(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003SVINVALID",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30003SVINVALID")
        for event_type, summary in [
            ("proposal_context_completed", "Scope clarified"),
            ("requirements_completed", "Requirements clarified"),
            ("acceptance_criteria_completed", "Acceptance prepared"),
            ("constraints_completed", "Constraints prepared"),
        ]:
            self.coordinator.handle_operator_event(
                session_id=session.id,
                event_type=event_type,
                payload={"summary": summary},
            )

        with self.assertRaisesRegex(
            IntakeError,
            "Spec verification blocked output must include payload.summary or payload.blocker_questions",
        ):
            self.coordinator.handle_role_output(
                session_id=session.id,
                role_name=SPEC_VERIFIER_WORKER_ROLE,
                output_type="failed",
                payload={},
            )

    def test_spec_verification_completed_records_direct_task_decomposition_handoff(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003STORY",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30003STORY")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={"summary": "Scope clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="requirements_completed",
            payload={"summary": "Requirements clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="acceptance_criteria_completed",
            payload={"summary": "Acceptance prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="constraints_completed",
            payload={"summary": "Constraints prepared"},
        )

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="spec_verification_completed",
            payload={"summary": "Planning verified"},
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        events = self.event_repository.list_for_session(session.id)
        decomposer_role = self.role_repository.get_by_name(session.id, TASK_DECOMPOSER_WORKER_ROLE)
        sent_inputs = self.session_backend.get_sent_inputs(decomposer_role.runtime_handle)

        self.assertEqual("task_decomposition_requested", updated_session.current_stage)
        self.assertEqual(TASK_DECOMPOSER_WORKER_ROLE, updated_session.current_owner)
        self.assertEqual("task_decomposition_requested", followup_event.event_type)
        self.assertEqual(
            [
                ("acceptance_criteria", "completed"),
                ("constraints", "completed"),
                ("proposal_context", "completed"),
                ("requirements", "completed"),
                ("spec_verification", "completed"),
                ("task_decomposition", "assigned"),
            ],
            sorted((item.work_type, item.status.value) for item in work_items),
        )
        self.assertEqual(
            [
                "task_started",
                "task_session_reused",
                "task_prepared",
                "role_input_delivery_confirmed",
                "role_input_dispatched",
                "proposal_context_requested",
                "proposal_context_completed",
                "role_input_delivery_confirmed",
                "role_input_dispatched",
                "requirements_requested",
                "requirements_completed",
                "role_input_delivery_confirmed",
                "role_input_dispatched",
                "acceptance_criteria_requested",
                "acceptance_criteria_completed",
                "role_input_delivery_confirmed",
                "role_input_dispatched",
                "constraints_requested",
                "constraints_completed",
                "role_input_delivery_confirmed",
                "role_input_dispatched",
                "spec_verification_requested",
                "spec_verification_completed",
                "role_input_delivery_confirmed",
                "role_input_dispatched",
                "task_decomposition_requested",
            ],
            [item.event_type for item in events],
        )
        self.assertEqual(1, len(sent_inputs))
        self.assertIn("Prepare task decomposition for story IOS-30003STORY before implementation starts.", sent_inputs[0])
        self.assertIn("Produce a temporary `plan/index.md` plus self-contained `plan/NN-*.md` task package only for Jira subtask materialization", sent_inputs[0])

    def test_task_decomposition_completed_moves_session_to_subtask_creation_checkpoint(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003DECOMP",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30003DECOMP")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={"summary": "Scope clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="requirements_completed",
            payload={"summary": "Requirements clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="acceptance_criteria_completed",
            payload={"summary": "Acceptance prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="constraints_completed",
            payload={"summary": "Constraints prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="spec_verification_completed",
            payload={"summary": "Planning verified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="story_spec_completed",
            payload={"summary": "Need a new screen plus navigation wiring"},
        )
        self.write_statuses_file(
            "IOS-30003DECOMP",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30003DECOMP | Story | Parent story | In Progress |
| IOS-30030 | Sub-task | Already done one | Ready for test |
| IOS-30031 | Sub-task | Already done two | Released |
""",
        )

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="task_decomposition_completed",
            payload=decomposition_payload(
                "Split into execution chunks",
                task_breakdown="Networking, state, UI wiring",
            ),
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        events = self.event_repository.list_for_session(session.id)
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        implementer_inputs = self.session_backend.get_sent_inputs(implementer_role.runtime_handle)
        decomposer_role = self.role_repository.get_by_name(session.id, TASK_DECOMPOSER_WORKER_ROLE)

        self.assertEqual("subtask_creation_requested", updated_session.current_stage)
        self.assertIsNone(updated_session.current_owner)
        self.assertEqual("waiting_for_operator", updated_session.status.value)
        self.assertEqual("jira_subtasks_created", followup_event.event_type)
        self.assertEqual("stopped", decomposer_role.status.value)
        self.assertEqual(
            [
                ("acceptance_criteria", "completed"),
                ("constraints", "completed"),
                ("implementation", "waiting_for_operator"),
                ("proposal_context", "completed"),
                ("requirements", "completed"),
                ("spec_verification", "completed"),
                ("task_decomposition", "completed"),
            ],
            sorted((item.work_type, item.status.value) for item in work_items),
        )
        self.assertEqual(
            [
                "task_started",
                "task_session_reused",
                "task_prepared",
                "role_input_delivery_confirmed",
                "role_input_dispatched",
                "proposal_context_requested",
                "proposal_context_completed",
                "role_input_delivery_confirmed",
                "role_input_dispatched",
                "requirements_requested",
                "requirements_completed",
                "role_input_delivery_confirmed",
                "role_input_dispatched",
                "acceptance_criteria_requested",
                "acceptance_criteria_completed",
                "role_input_delivery_confirmed",
                "role_input_dispatched",
                "constraints_requested",
                "constraints_completed",
                "role_input_delivery_confirmed",
                "role_input_dispatched",
                "spec_verification_requested",
                "spec_verification_completed",
                "role_input_delivery_confirmed",
                "role_input_dispatched",
                "task_decomposition_requested",
                "story_spec_completed",
                "task_decomposition_completed",
                "jira_subtasks_created",
                "session_escalated_to_operator",
            ],
            [item.event_type for item in events],
        )
        self.assertEqual([], implementer_inputs)

    def test_task_decomposition_completed_writes_legacy_plan_package_when_provided(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003PLAN",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30003PLAN")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={"summary": "Scope clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="requirements_completed",
            payload={"summary": "Requirements clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="acceptance_criteria_completed",
            payload={"summary": "Acceptance prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="constraints_completed",
            payload={"summary": "Constraints prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="spec_verification_completed",
            payload={"summary": "Planning verified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="story_spec_completed",
            payload={"summary": "Need explicit decomposition package"},
        )
        self.write_statuses_file(
            "IOS-30003PLAN",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30003PLAN | Story | Parent story | In Progress |
| IOS-30032 | Sub-task | Existing subtask | Ready for test |
""",
        )

        self.write_statuses_file(
            "IOS-30003SUBAUTO",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30003SUBAUTO | Story | Parent story | In Progress |
| IOS-30040 | Sub-task | Build data source | To Do |
| IOS-30041 | Sub-task | Finish docs | Ready for test |
""",
        )

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="task_decomposition_completed",
            payload={
                "summary": "Decomposition prepared",
                "plan_index_markdown": "# Execution Task List\n\n| # | Task | Depends on | Status |\n|---|------|------------|--------|\n| 01 | [Build data source](./01-build-data-source.md) | — | ☐ |\n",
                "plan_tasks_manifest": {
                    "version": 1,
                    "tasks": [
                        {
                            "order": 1,
                            "filename": "01-build-data-source.md",
                            "title": "Build data source",
                        }
                    ],
                },
                "plan_task_files": [
                    {
                        "filename": "01-build-data-source.md",
                        "content": "# Build data source\n\n## What to implement\nCreate the feature data source.\n",
                    }
                ],
            },
        )
        artifacts = self.artifact_repository.list_for_session(session.id)
        plan_dir = Path(self.temp_dir.name) / "IOS-30003PLAN" / "plan"

        self.assertEqual("jira_subtasks_created", followup_event.event_type)
        self.assertEqual("subtask_creation_requested", updated_session.current_stage)
        self.assertEqual("waiting_for_operator", updated_session.status.value)
        self.assertFalse(plan_dir.exists())
        self.assertTrue(
            any(artifact.artifact_type == "task_decomposition_plan_index" for artifact in artifacts)
        )
        self.assertTrue(
            any(artifact.artifact_type == "task_decomposition_plan_manifest" for artifact in artifacts)
        )
        self.assertTrue(
            any(artifact.artifact_type == "task_decomposition_plan_package" for artifact in artifacts)
        )

    def test_task_decomposition_completed_requires_plan_package(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003PLANREQ",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30003PLANREQ")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={"summary": "Scope clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="requirements_completed",
            payload={"summary": "Requirements clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="acceptance_criteria_completed",
            payload={"summary": "Acceptance prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="constraints_completed",
            payload={"summary": "Constraints prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="spec_verification_completed",
            payload={"summary": "Planning verified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="story_spec_completed",
            payload={"summary": "Need explicit decomposition package"},
        )

        updated_session, event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="task_decomposition_completed",
            payload={"summary": "Decomposition prepared"},
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        decomposition_item = next(item for item in work_items if item.work_type == "task_decomposition")

        self.assertEqual("session_escalated_to_operator", event.event_type)
        self.assertEqual("task_decomposition_package_invalid", event.payload.get("reason"))
        self.assertEqual("task_decomposition_requested", updated_session.current_stage)
        self.assertEqual("waiting_for_operator", updated_session.status.value)
        self.assertEqual("waiting_for_operator", decomposition_item.status.value)

    def test_task_decomposition_completed_accepts_legacy_plan_paths_payload(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003PLANLEGACY",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30003PLANLEGACY")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={"summary": "Scope clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="requirements_completed",
            payload={"summary": "Requirements clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="acceptance_criteria_completed",
            payload={"summary": "Acceptance prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="constraints_completed",
            payload={"summary": "Constraints prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="spec_verification_completed",
            payload={"summary": "Planning verified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="story_spec_completed",
            payload={"summary": "Need explicit decomposition package"},
        )
        self.write_statuses_file(
            "IOS-30003PLANLEGACY",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30003PLANLEGACY | Story | Parent story | In Progress |
| IOS-30050 | Sub-task | Build data source | To Do |
""",
        )

        plan_dir = Path(self.temp_dir.name) / "IOS-30003PLANLEGACY" / "plan"
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / "index.md").write_text(
            "# Execution Task List\n\n"
            "| # | Task | Depends on | Status |\n"
            "|---|------|------------|--------|\n"
            "| 01 | [Build data source](./01-build-data-source.md) | — | ☐ |\n"
        )
        (plan_dir / "01-build-data-source.md").write_text(
            "# Build data source\n\n"
            "## What to implement\n"
            "Create the feature data source.\n"
        )

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="task_decomposition_completed",
            payload={
                "summary": "Legacy decomposition package prepared",
                "paths": [
                    "plan/index.md",
                    "plan/01-build-data-source.md",
                ],
            },
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        decomposition_item = next(item for item in work_items if item.work_type == "task_decomposition")

        self.assertEqual("subtask_implementation_requested", followup_event.event_type)
        self.assertEqual("subtask_implementation_requested", updated_session.current_stage)
        self.assertEqual("active", updated_session.status.value)
        self.assertEqual("completed", decomposition_item.status.value)
        self.assertFalse(plan_dir.exists())

    def test_task_decomposition_completed_accepts_legacy_plan_artifacts_payload(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003PLANARTIFACTS",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30003PLANARTIFACTS")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={"summary": "Scope clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="requirements_completed",
            payload={"summary": "Requirements clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="acceptance_criteria_completed",
            payload={"summary": "Acceptance prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="constraints_completed",
            payload={"summary": "Constraints prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="spec_verification_completed",
            payload={"summary": "Planning verified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="story_spec_completed",
            payload={"summary": "Need explicit decomposition package"},
        )
        self.write_statuses_file(
            "IOS-30003PLANARTIFACTS",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30003PLANARTIFACTS | Story | Parent story | In Progress |
| IOS-30051 | Sub-task | Build data source | To Do |
""",
        )

        plan_dir = Path(self.temp_dir.name) / "IOS-30003PLANARTIFACTS" / "plan"
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / "index.md").write_text(
            "# Execution Task List\n\n"
            "| # | Task | Depends on | Status |\n"
            "|---|------|------------|--------|\n"
            "| 01 | [Build data source](./01-build-data-source.md) | — | ☐ |\n"
        )
        (plan_dir / "01-build-data-source.md").write_text(
            "# Build data source\n\n"
            "## What to implement\n"
            "Create the feature data source.\n"
        )

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="task_decomposition_completed",
            payload={
                "summary": "Legacy decomposition artifacts prepared",
                "artifacts": [
                    "plan/index.md",
                    "plan/01-build-data-source.md",
                ],
            },
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        decomposition_item = next(item for item in work_items if item.work_type == "task_decomposition")

        self.assertEqual("subtask_implementation_requested", followup_event.event_type)
        self.assertEqual("subtask_implementation_requested", updated_session.current_stage)
        self.assertEqual("active", updated_session.status.value)
        self.assertEqual("completed", decomposition_item.status.value)
        self.assertFalse(plan_dir.exists())

    def test_task_decomposition_completed_materializes_legacy_artifacts_from_role_workspace(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003PLANROLEWS",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30003PLANROLEWS")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={"summary": "Scope clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="requirements_completed",
            payload={"summary": "Requirements clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="acceptance_criteria_completed",
            payload={"summary": "Acceptance prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="constraints_completed",
            payload={"summary": "Constraints prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="spec_verification_completed",
            payload={"summary": "Planning verified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="story_spec_completed",
            payload={"summary": "Need explicit decomposition package"},
        )
        self.write_statuses_file(
            "IOS-30003PLANROLEWS",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30003PLANROLEWS | Story | Parent story | In Progress |
| IOS-30052 | Sub-task | Build data source | To Do |
""",
        )

        role_plan_dir = self.coordinator.role_workspace_manager.role_directory(  # type: ignore[union-attr]
            "IOS-30003PLANROLEWS",
            TASK_DECOMPOSER_WORKER_ROLE,
        ) / "plan"
        role_plan_dir.mkdir(parents=True, exist_ok=True)
        (role_plan_dir / "index.md").write_text(
            "# Execution Task List\n\n"
            "| # | Task | Depends on | Status |\n"
            "|---|------|------------|--------|\n"
            "| 01 | [Build data source](./01-build-data-source.md) | — | ☐ |\n"
        )
        (role_plan_dir / "01-build-data-source.md").write_text(
            "# Build data source\n\n"
            "## What to implement\n"
            "Create the feature data source.\n"
        )

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="task_decomposition_completed",
            payload={
                "summary": "Legacy decomposition artifacts prepared",
                "artifacts": [
                    "plan/index.md",
                    "plan/01-build-data-source.md",
                ],
            },
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        decomposition_item = next(item for item in work_items if item.work_type == "task_decomposition")
        materialized_plan_dir = Path(self.temp_dir.name) / "IOS-30003PLANROLEWS" / "plan"

        self.assertEqual("subtask_implementation_requested", followup_event.event_type)
        self.assertEqual("subtask_implementation_requested", updated_session.current_stage)
        self.assertEqual("active", updated_session.status.value)
        self.assertEqual("completed", decomposition_item.status.value)
        self.assertFalse(materialized_plan_dir.exists())

    def test_create_subtasks_from_plan_records_batch_artifacts(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003SUBBATCH",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30003SUBBATCH")
        plan_dir = Path(self.temp_dir.name) / "IOS-30003SUBBATCH" / "plan"
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / "index.md").write_text(
            "# Execution Task List\n\n| # | Task | Depends on | Status |\n|---|------|------------|--------|\n| 01 | [Build data source](./01-build-data-source.md) | — | ☐ |\n"
        )
        (plan_dir / "tasks.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "tasks": [
                        {
                            "order": 1,
                            "filename": "01-build-data-source.md",
                            "title": "Build data source",
                        }
                    ],
                }
            )
        )
        (plan_dir / "01-build-data-source.md").write_text(
            "# Build data source\n\n## What to implement\nCreate the feature data source.\n"
        )

        updated_session, event, followup_event = self.coordinator.create_subtasks_from_plan(session.id)
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual(session.id, updated_session.id)
        self.assertEqual("jira_subtasks_created", event.event_type)
        self.assertEqual(["IOS-90001"], event.payload["created_subtask_keys"])
        self.assertIsNone(followup_event)
        self.assertFalse(plan_dir.exists())
        self.assertTrue(any(item.artifact_type == "jira_subtasks_stdout" for item in artifacts))
        self.assertTrue(any(item.artifact_type == "jira_subtasks_stderr" for item in artifacts))
        self.assertTrue(any(item.artifact_type == "jira_subtasks_summary" for item in artifacts))
        self.assertTrue(any(item.artifact_type == "subtasks_snapshot_stdout" for item in artifacts))
        self.assertTrue(any(item.artifact_type == "subtasks_snapshot_stderr" for item in artifacts))
        self.assertEqual(0, event.payload["snapshot_refresh_exit_code"])

    def test_create_subtasks_from_plan_retries_until_created_subtasks_appear_in_snapshot(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003SUBRETRY",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30003SUBRETRY")
        plan_dir = Path(self.temp_dir.name) / "IOS-30003SUBRETRY" / "plan"
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / "index.md").write_text(
            "# Execution Task List\n\n| # | Task | Depends on | Status |\n|---|------|------------|--------|\n| 01 | [Build data source](./01-build-data-source.md) | — | ☐ |\n"
        )
        (plan_dir / "01-build-data-source.md").write_text(
            "# Build data source\n\n## What to implement\nCreate the feature data source.\n"
        )
        self.snapshot_adapter.set_statuses_sequence(
            "IOS-30003SUBRETRY",
            [
                """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30003SUBRETRY | Story | Parent story | In Progress |
""",
                """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30003SUBRETRY | Story | Parent story | In Progress |
| IOS-90001 | Sub-task | Build data source | To Do |
""",
            ],
        )

        updated_session, event, followup_event = self.coordinator.create_subtasks_from_plan(session.id)

        self.assertEqual(session.id, updated_session.id)
        self.assertEqual("jira_subtasks_created", event.event_type)
        self.assertIsNone(followup_event)
        self.assertEqual(2, event.payload["snapshot_refresh_attempts"])
        self.assertTrue(event.payload["snapshot_refresh_matched_created_subtasks"])
        self.assertGreaterEqual(self.snapshot_adapter.calls.count("IOS-30003SUBRETRY"), 2)

    def test_create_subtasks_from_plan_waits_for_operator_after_bounded_snapshot_retry(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003SUBRETRYFAIL",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30003SUBRETRYFAIL")
        self.coordinator.post_create_subtask_snapshot_refresh_attempts = 2
        plan_dir = Path(self.temp_dir.name) / "IOS-30003SUBRETRYFAIL" / "plan"
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / "index.md").write_text(
            "# Execution Task List\n\n| # | Task | Depends on | Status |\n|---|------|------------|--------|\n| 01 | [Build data source](./01-build-data-source.md) | — | ☐ |\n"
        )
        (plan_dir / "01-build-data-source.md").write_text(
            "# Build data source\n\n## What to implement\nCreate the feature data source.\n"
        )
        self.snapshot_adapter.set_statuses_output(
            "IOS-30003SUBRETRYFAIL",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30003SUBRETRYFAIL | Story | Parent story | In Progress |
""",
        )

        updated_session, event, followup_event = self.coordinator.create_subtasks_from_plan(session.id)
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual("jira_subtasks_created", event.event_type)
        self.assertIsNone(followup_event)
        self.assertEqual(SessionStatus.WAITING_FOR_OPERATOR, updated_session.status)
        self.assertEqual("subtask_creation_requested", updated_session.current_stage)
        self.assertIsNone(updated_session.current_owner)
        self.assertEqual(2, event.payload["snapshot_refresh_attempts"])
        self.assertFalse(event.payload["snapshot_refresh_matched_created_subtasks"])
        self.assertTrue(
            any(
                item.event_type == "session_escalated_to_operator"
                and item.payload.get("reason") == "subtask_snapshot_missing_created_subtasks"
                for item in events
            )
        )

    def test_extract_created_subtask_keys_deduplicates_repeated_stdout_entries(self) -> None:
        stdout = (
            "Creating subtask 01: Build typed cache registry core\n"
            "  Created: IOS-12675\n"
            "Creating subtask 02: Wire typed cache registry usage\n"
            "  Created: IOS-12676\n"
            "Creating subtask 03: Remove legacy cache access paths\n"
            "  Created: IOS-12677\n"
            "\n"
            "Created subtasks:\n"
            "01    IOS-12675     Build typed cache registry core\n"
            "02    IOS-12676     Wire typed cache registry usage\n"
            "03    IOS-12677     Remove legacy cache access paths\n"
        )

        self.assertEqual(
            ["IOS-12675", "IOS-12676", "IOS-12677"],
            self.coordinator._extract_created_subtask_keys(stdout),
        )

    def test_create_subtasks_from_plan_auto_starts_subtask_graph_from_active_implementation(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003SUBAUTO",
            workflow_profile="story_full",
            policy={"review_policy": "disabled"},
        )
        self.coordinator.prepare_task_session("IOS-30003SUBAUTO")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={"summary": "Context prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="requirements_completed",
            payload={"summary": "Requirements prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="acceptance_criteria_completed",
            payload={"summary": "Acceptance prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="constraints_completed",
            payload={"summary": "Constraints prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="spec_verification_completed",
            payload={"summary": "Planning verified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="story_spec_completed",
            payload={"summary": "Need explicit decomposition package"},
        )
        self.write_statuses_file(
            "IOS-30003SUBAUTO",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30003SUBAUTO | Story | Parent story | In Progress |
| IOS-30040 | Sub-task | Build data source | To Do |
| IOS-30041 | Sub-task | Finish docs | Ready for test |
""",
        )
        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="task_decomposition_completed",
            payload={
                "summary": "Decomposition prepared",
                "plan_index_markdown": "# Execution Task List\n\n| # | Task | Depends on | Status |\n|---|------|------------|--------|\n| 01 | [Build data source](./01-build-data-source.md) | — | ☐ |\n",
                "plan_tasks_manifest": {
                    "version": 1,
                    "tasks": [
                        {
                            "order": 1,
                            "filename": "01-build-data-source.md",
                            "title": "Build data source",
                        }
                    ],
                },
                "plan_task_files": [
                    {
                        "filename": "01-build-data-source.md",
                        "content": "# Build data source\n\n## What to implement\nCreate the feature data source.\n",
                    }
                ],
            },
        )
        self.assertEqual("subtask_implementation_requested", followup_event.event_type)
        self.assertEqual("subtask_implementation_requested", updated_session.current_stage)
        self.assertEqual("active", updated_session.status.value)

    def test_start_subtask_graph_converts_story_implementation_into_subtask_lane(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003SUBTASK",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30003SUBTASK")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={"summary": "Context prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="requirements_completed",
            payload={"summary": "Requirements clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="acceptance_criteria_completed",
            payload={"summary": "Acceptance prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="constraints_completed",
            payload={"summary": "Constraints prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="spec_verification_completed",
            payload={"summary": "Planning verified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="story_spec_completed",
            payload={"summary": "Split into focused subtasks"},
        )
        self.write_statuses_file(
            "IOS-30003SUBTASK",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30003SUBTASK | Story | Parent story | In Progress |
| IOS-30013 | Sub-task | Already done one | Ready for test |
| IOS-30014 | Sub-task | Already done two | Released |
""",
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="task_decomposition_completed",
            payload=decomposition_payload("Execution chunks prepared"),
        )
        self.write_statuses_file(
            "IOS-30003SUBTASK",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30003SUBTASK | Story | Parent story | In Progress |
| IOS-30010 | Sub-task | Implement networking layer | To Do |
| IOS-30011 | Sub-task | Wire screen presentation | In Progress |
| IOS-30012 | Sub-task | Update docs | Ready for test |
""",
        )

        updated_session, event, followup_event = self.coordinator.start_subtask_graph(session.id)
        work_items = self.work_item_repository.list_for_session(session.id)
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        sent_inputs = self.session_backend.get_sent_inputs(implementer_role.runtime_handle)

        self.assertEqual("subtask_graph_requested", event.event_type)
        self.assertEqual("subtask_implementation_requested", followup_event.event_type)
        self.assertEqual("subtask_implementation_requested", updated_session.current_stage)
        self.assertEqual("implementer", updated_session.current_owner)
        self.assertEqual(
            sorted(
                [
                    ("acceptance_criteria", "completed"),
                    ("constraints", "completed"),
                    ("proposal_context", "completed"),
                    ("requirements", "completed"),
                    ("spec_verification", "completed"),
                    ("task_decomposition", "completed"),
                    ("subtask_implementation", "assigned"),
                    ("subtask_implementation", "unassigned"),
                ]
            ),
            sorted((item.work_type, item.status.value) for item in work_items),
        )
        self.assertIn("Implement subtask IOS-30010", sent_inputs[-1])
        self.assertIn("Use the refreshed Jira subtask snapshot as the source of truth for scope and status.", sent_inputs[-1])

    def test_subtask_completion_assigns_next_subtask_before_verification(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004SUBTASK",
            workflow_profile="story_full",
            policy={"review_policy": "disabled"},
        )
        self.coordinator.prepare_task_session("IOS-30004SUBTASK")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={"summary": "Context prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="requirements_completed",
            payload={"summary": "Requirements clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="acceptance_criteria_completed",
            payload={"summary": "Acceptance prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="constraints_completed",
            payload={"summary": "Constraints prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="spec_verification_completed",
            payload={"summary": "Planning verified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="story_spec_completed",
            payload={"summary": "Split into focused subtasks"},
        )
        self.write_statuses_file(
            "IOS-30004SUBTASK",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30004SUBTASK | Story | Parent story | In Progress |
| IOS-30022 | Sub-task | Already done one | Ready for test |
| IOS-30023 | Sub-task | Already done two | Released |
""",
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="task_decomposition_completed",
            payload=decomposition_payload("Execution chunks prepared"),
        )
        self.write_statuses_file(
            "IOS-30004SUBTASK",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30004SUBTASK | Story | Parent story | In Progress |
| IOS-30020 | Sub-task | Add data source | To Do |
| IOS-30021 | Sub-task | Wire view state | To Do |
""",
        )
        self.coordinator.start_subtask_graph(session.id)

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="subtask_completed",
            payload={"summary": "First subtask implemented"},
        )
        work_items = self.work_item_repository.list_for_session(session.id)

        self.assertEqual("subtask_implementation_requested", followup_event.event_type)
        self.assertEqual("subtask_implementation_requested", updated_session.current_stage)
        self.assertEqual([("IOS-30004SUBTASK", "subtask IOS-30020")], self.gitlab_adapter.commit_requests)
        self.assertEqual(["IOS-30020"], self.jira_adapter.completed_subtasks)
        self.assertEqual(
            ["assigned", "completed", "completed", "completed", "completed", "completed", "completed", "completed"],
            sorted(item.status.value for item in work_items),
        )

        final_session, final_followup = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="subtask_completed",
            payload={"summary": "Second subtask implemented"},
        )

        self.assertEqual("verification_requested", final_followup.event_type)
        self.assertEqual("verification_requested", final_session.current_stage)
        self.assertEqual(
            [
                ("IOS-30004SUBTASK", "subtask IOS-30020"),
                ("IOS-30004SUBTASK", "subtask IOS-30021"),
            ],
            self.gitlab_adapter.commit_requests,
        )
        self.assertEqual(["IOS-30020", "IOS-30021"], self.jira_adapter.completed_subtasks)

    def test_operator_can_skip_current_blocked_subtask_before_verification(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004SUBSKIP",
            workflow_profile="story_full",
            policy={"review_policy": "disabled"},
        )
        self.coordinator.prepare_task_session("IOS-30004SUBSKIP")
        for event_type in (
            "proposal_context_completed",
            "requirements_completed",
            "acceptance_criteria_completed",
            "constraints_completed",
            "spec_verification_completed",
            "story_spec_completed",
        ):
            self.coordinator.handle_operator_event(
                session_id=session.id,
                event_type=event_type,
                payload={"summary": "prepared"},
            )
        self.write_statuses_file(
            "IOS-30004SUBSKIP",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30004SUBSKIP | Story | Parent story | In Progress |
| IOS-30024 | Sub-task | Depends on another branch | To Do |
""",
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="task_decomposition_completed",
            payload=decomposition_payload("Execution chunks prepared"),
        )
        active_item = next(
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "subtask_implementation"
            and item.status == WorkItemStatus.ASSIGNED
        )
        self.work_item_repository.update_status(active_item.id, WorkItemStatus.WAITING_FOR_OPERATOR)
        self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="subtask_implementation_requested",
            current_owner=None,
        )
        self.session_repository.update_status(session.id, SessionStatus.WAITING_FOR_OPERATOR)

        updated_session, event, followup_event = self.coordinator.skip_current_subtask(
            session.id,
            "Blocked by a dependency subtask; defer this item for a later run.",
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        skipped_context_path = Path(self.temp_dir.name) / "IOS-30004SUBSKIP" / "spec" / "skipped-subtasks.md"

        self.assertEqual("subtask_implementation_skipped_by_operator", event.event_type)
        self.assertEqual("IOS-30024", event.payload["subtask_key"])
        self.assertEqual("verification_requested", followup_event.event_type)
        self.assertEqual("verification_requested", updated_session.current_stage)
        self.assertEqual([], self.jira_adapter.completed_subtasks)
        self.assertEqual([], self.gitlab_adapter.commit_requests)
        self.assertTrue(
            any(
                item.id == active_item.id and item.status == WorkItemStatus.COMPLETED
                for item in work_items
            )
        )
        self.assertTrue(skipped_context_path.is_file())
        self.assertIn("IOS-30024", skipped_context_path.read_text())

        instruction, hydration = self.coordinator._dual_review_dispatch_context(
            updated_session,
            lane="requirements",
        )

        self.assertIn("Operator-skipped/deferred Jira subtasks", instruction)
        self.assertEqual(str(skipped_context_path), hydration["skipped_subtasks_path"])
        self.assertIn("IOS-30024", hydration["skipped_subtasks"])

    def test_subtask_completion_refreshes_snapshot_and_rewrites_graph(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004SUBREFRESH",
            workflow_profile="story_full",
            policy={"review_policy": "disabled"},
        )
        self.coordinator.prepare_task_session("IOS-30004SUBREFRESH")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={"summary": "Context prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="requirements_completed",
            payload={"summary": "Requirements clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="acceptance_criteria_completed",
            payload={"summary": "Acceptance prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="constraints_completed",
            payload={"summary": "Constraints prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="spec_verification_completed",
            payload={"summary": "Planning verified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="story_spec_completed",
            payload={"summary": "Split into focused subtasks"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="task_decomposition_completed",
            payload=decomposition_payload("Execution chunks prepared"),
        )
        self.write_statuses_file(
            "IOS-30004SUBREFRESH",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30004SUBREFRESH | Story | Parent story | In Progress |
| IOS-30030 | Sub-task | Add data source | To Do |
| IOS-30031 | Sub-task | Wire view state | To Do |
""",
        )
        self.coordinator.start_subtask_graph(session.id)
        self.snapshot_adapter.set_statuses_output(
            "IOS-30004SUBREFRESH",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30004SUBREFRESH | Story | Parent story | In Progress |
| IOS-30030 | Sub-task | Add data source | Ready for test |
| IOS-30031 | Sub-task | Wire view state | To Do |
""",
        )

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="subtask_completed",
            payload={"summary": "First subtask implemented"},
        )

        artifacts = self.artifact_repository.list_for_session(session.id)
        subtask_graph_artifacts = [
            artifact for artifact in artifacts if artifact.artifact_type == "subtask_statuses_markdown"
        ]
        refresh_stdout_artifacts = [
            artifact for artifact in artifacts if artifact.artifact_type == "subtask_snapshot_refresh_stdout"
        ]
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual("subtask_implementation_requested", followup_event.event_type)
        self.assertEqual("subtask_implementation_requested", updated_session.current_stage)
        self.assertGreaterEqual(
            self.snapshot_adapter.calls.count("IOS-30004SUBREFRESH"),
            2,
        )
        self.assertGreaterEqual(len(subtask_graph_artifacts), 2)
        self.assertEqual(1, len(refresh_stdout_artifacts))
        self.assertTrue(
            any(event.event_type == "subtask_snapshot_refreshed" for event in events)
        )
        self.assertEqual(["IOS-30030"], self.jira_adapter.completed_subtasks)

    def test_subtask_completion_uses_refreshed_snapshot_as_remaining_source_of_truth(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004SUBTRUTH",
            workflow_profile="story_full",
            policy={"review_policy": "disabled"},
        )
        self.coordinator.prepare_task_session("IOS-30004SUBTRUTH")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={"summary": "Context prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="requirements_completed",
            payload={"summary": "Requirements clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="acceptance_criteria_completed",
            payload={"summary": "Acceptance prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="constraints_completed",
            payload={"summary": "Constraints prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="spec_verification_completed",
            payload={"summary": "Planning verified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="story_spec_completed",
            payload={"summary": "Split into focused subtasks"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="task_decomposition_completed",
            payload=decomposition_payload("Execution chunks prepared"),
        )
        self.write_statuses_file(
            "IOS-30004SUBTRUTH",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30004SUBTRUTH | Story | Parent story | In Progress |
| IOS-30040 | Sub-task | Add data source | To Do |
| IOS-30041 | Sub-task | Wire view state | To Do |
""",
        )
        self.coordinator.start_subtask_graph(session.id)
        self.snapshot_adapter.set_statuses_output(
            "IOS-30004SUBTRUTH",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30004SUBTRUTH | Story | Parent story | In Progress |
| IOS-30040 | Sub-task | Add data source | Ready for test |
| IOS-30041 | Sub-task | Wire view state | Released |
""",
        )

        final_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="subtask_completed",
            payload={"summary": "First subtask implemented"},
        )

        work_items = self.work_item_repository.list_for_session(session.id)

        self.assertEqual("verification_requested", followup_event.event_type)
        self.assertEqual("verification_requested", final_session.current_stage)
        self.assertEqual(
            0,
            len(
                [
                    item
                    for item in work_items
                    if item.work_type == "subtask_implementation"
                    and item.status.value == "unassigned"
                ]
            ),
        )
        self.assertEqual(["IOS-30040"], self.jira_adapter.completed_subtasks)

    def test_subtask_completion_transition_failure_escalates_for_operator(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004SUBFAIL",
            workflow_profile="story_full",
            policy={"review_policy": "disabled"},
        )
        self.coordinator.prepare_task_session("IOS-30004SUBFAIL")
        for event_type in (
            "proposal_context_completed",
            "requirements_completed",
            "acceptance_criteria_completed",
            "constraints_completed",
            "spec_verification_completed",
            "story_spec_completed",
        ):
            self.coordinator.handle_operator_event(
                session_id=session.id,
                event_type=event_type,
                payload={"summary": "prepared"},
            )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="task_decomposition_completed",
            payload=decomposition_payload("Execution chunks prepared"),
        )
        self.write_statuses_file(
            "IOS-30004SUBFAIL",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30004SUBFAIL | Story | Parent story | In Progress |
| IOS-30095 | Sub-task | Add data source | To Do |
""",
        )
        self.coordinator.start_subtask_graph(session.id)
        original_complete_subtask = self.jira_adapter.complete_subtask
        self.jira_adapter.complete_subtask = lambda task_key: CommandResult(
            command=["complete_subtask", task_key],
            returncode=1,
            stdout="",
            stderr="transition failed\n",
        )

        failed_session, failed_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="subtask_completed",
            payload={"summary": "Subtask implemented"},
        )
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual("subtask_transition_failed", failed_event.event_type)
        self.assertEqual("subtask_implementation_requested", failed_session.current_stage)
        self.assertEqual("waiting_for_operator", failed_session.status.value)
        self.assertTrue(any(item.artifact_type == "subtask_transition_stdout" for item in artifacts))
        self.assertTrue(any(item.artifact_type == "subtask_transition_stderr" for item in artifacts))
        self.jira_adapter.complete_subtask = original_complete_subtask

    def test_refresh_snapshot_reopens_completed_story_into_subtask_execution(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004REOPEN",
            workflow_profile="story_full",
            policy={"review_policy": "disabled"},
        )
        self.coordinator.prepare_task_session("IOS-30004REOPEN")
        for event_type in (
            "proposal_context_completed",
            "requirements_completed",
            "acceptance_criteria_completed",
            "constraints_completed",
            "spec_verification_completed",
            "story_spec_completed",
        ):
            self.coordinator.handle_operator_event(
                session_id=session.id,
                event_type=event_type,
                payload={"summary": "prepared"},
            )
        self.write_statuses_file(
            "IOS-30004REOPEN",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30004REOPEN | Story | Parent story | In Progress |
| IOS-30060 | Sub-task | Add data source | To Do |
| IOS-30061 | Sub-task | Wire view state | To Do |
""",
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="task_decomposition_completed",
            payload=decomposition_payload("Execution chunks prepared"),
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="subtask_completed",
            payload={"summary": "Implemented IOS-30060"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="subtask_completed",
            payload={"summary": "Implemented IOS-30061"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={"summary": "all green"},
        )

        self.snapshot_adapter.set_statuses_output(
            "IOS-30004REOPEN",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30004REOPEN | Story | Parent story | In Progress |
| IOS-30062 | Sub-task | Fix review feedback | To Do |
""",
        )

        updated_session, event, followup_event = self.coordinator.refresh_snapshot_and_continue(session.id)
        work_items = self.work_item_repository.list_for_session(session.id)

        self.assertEqual("snapshot_refreshed_by_operator", event.event_type)
        self.assertIsNotNone(followup_event)
        assert followup_event is not None
        self.assertEqual("subtask_implementation_requested", followup_event.event_type)
        self.assertEqual("subtask_implementation_requested", updated_session.current_stage)
        self.assertEqual("active", updated_session.status.value)
        self.assertTrue(
            any(
                item.work_type == "subtask_implementation"
                and "IOS-30062" in item.title
                and item.status.value == "assigned"
                for item in work_items
            )
        )

    def test_refresh_snapshot_and_continue_reopens_completed_story_without_decomposition_artifact(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004REOPENNOART",
            workflow_profile="story_full",
            policy=None,
        )
        self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="send_to_test_completed",
            current_owner=None,
        )
        self.session_repository.update_status(session.id, SessionStatus.COMPLETED)

        self.snapshot_adapter.set_statuses_output(
            "IOS-30004REOPENNOART",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30004REOPENNOART | Story | Parent story | In Progress |
| IOS-30063 | Sub-task | Fix review feedback | To Do |
""",
        )

        updated_session, event, followup_event = self.coordinator.refresh_snapshot_and_continue(session.id)
        work_items = self.work_item_repository.list_for_session(session.id)

        self.assertEqual("snapshot_refreshed_by_operator", event.event_type)
        self.assertIsNotNone(followup_event)
        assert followup_event is not None
        self.assertEqual("subtask_implementation_requested", followup_event.event_type)
        self.assertEqual("subtask_implementation_requested", updated_session.current_stage)
        self.assertEqual("active", updated_session.status.value)
        self.assertTrue(
            any(
                item.work_type == "subtask_implementation"
                and "IOS-30063" in item.title
                and item.status.value == "assigned"
                for item in work_items
            )
        )

    def test_refresh_snapshot_and_continue_reopens_completed_oneshot_into_subtask_execution(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004REOPENONESHOT",
            workflow_profile="oneshot",
            policy=None,
        )
        self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="send_to_test_completed",
            current_owner=None,
        )
        self.session_repository.update_status(session.id, SessionStatus.COMPLETED)

        self.snapshot_adapter.set_statuses_output(
            "IOS-30004REOPENONESHOT",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30004REOPENONESHOT | Story | Parent story | Ready for test |
| IOS-30064 | Sub-task | Address review follow-up | To Do |
""",
        )

        updated_session, event, followup_event = self.coordinator.refresh_snapshot_and_continue(session.id)
        work_items = self.work_item_repository.list_for_session(session.id)

        self.assertEqual("snapshot_refreshed_by_operator", event.event_type)
        self.assertIsNotNone(followup_event)
        assert followup_event is not None
        self.assertEqual("subtask_implementation_requested", followup_event.event_type)
        self.assertEqual("subtask_implementation_requested", updated_session.current_stage)
        self.assertEqual("active", updated_session.status.value)
        self.assertTrue(
            any(
                item.work_type == "subtask_implementation"
                and "IOS-30064" in item.title
                and item.status.value == "assigned"
                for item in work_items
            )
        )

    def test_prepare_task_session_resumes_existing_subtasks_for_new_oneshot_flow(self) -> None:
        self.snapshot_adapter.set_statuses_output(
            "IOS-30004INTAKERESUME",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30004INTAKERESUME | Story | Parent story | In Progress |
| IOS-30065 | Sub-task | Already implemented piece | Resolved |
| IOS-30066 | Sub-task | Remaining follow-up | To Do |
""",
        )

        session, event, created, details = self.coordinator.prepare_task_session(
            "IOS-30004INTAKERESUME",
            workflow_profile="oneshot",
        )
        work_items = self.work_item_repository.list_for_session(session.id)

        self.assertTrue(created)
        self.assertEqual("task_prepared", event.event_type)
        self.assertEqual("subtask_implementation_requested", details["followup_event_type"])
        self.assertEqual("subtask_implementation_requested", session.current_stage)
        self.assertEqual("active", session.status.value)
        self.assertTrue(
            any(
                item.work_type == "subtask_implementation"
                and "IOS-30066" in item.title
                and item.status.value == "assigned"
                for item in work_items
            )
        )
        self.assertTrue(
            any(
                recorded_event.event_type == "subtask_resume_detected_on_intake"
                for recorded_event in self.event_repository.list_for_session(session.id)
            )
        )

    def test_refresh_subtask_state_reconciles_remaining_queue_during_active_subtask_execution(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004REFRESHQUEUE",
            workflow_profile="story_full",
            policy={"review_policy": "disabled"},
        )
        self.coordinator.prepare_task_session("IOS-30004REFRESHQUEUE")
        for event_type in (
            "proposal_context_completed",
            "requirements_completed",
            "acceptance_criteria_completed",
            "constraints_completed",
            "spec_verification_completed",
            "story_spec_completed",
        ):
            self.coordinator.handle_operator_event(
                session_id=session.id,
                event_type=event_type,
                payload={"summary": "prepared"},
            )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="task_decomposition_completed",
            payload=decomposition_payload("Execution chunks prepared"),
        )
        self.write_statuses_file(
            "IOS-30004REFRESHQUEUE",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30004REFRESHQUEUE | Story | Parent story | In Progress |
| IOS-30070 | Sub-task | Build data source | To Do |
| IOS-30071 | Sub-task | Wire view state | To Do |
""",
        )
        self.coordinator.refresh_subtask_state(session.id)
        self.snapshot_adapter.set_statuses_output(
            "IOS-30004REFRESHQUEUE",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30004REFRESHQUEUE | Story | Parent story | In Progress |
| IOS-30070 | Sub-task | Build data source | To Do |
| IOS-30072 | Sub-task | Cover edge cases | To Do |
""",
        )

        updated_session, event, followup_event = self.coordinator.refresh_subtask_state(session.id)
        work_items = self.work_item_repository.list_for_session(session.id)

        self.assertEqual("subtask_state_refreshed_by_operator", event.event_type)
        self.assertIsNone(followup_event)
        self.assertEqual("subtask_implementation_requested", updated_session.current_stage)
        self.assertEqual("implementer", updated_session.current_owner)
        self.assertTrue(
            any(
                item.work_type == "subtask_implementation"
                and item.status.value == "assigned"
                and "IOS-30070" in item.title
                for item in work_items
            )
        )
        self.assertTrue(
            any(
                item.work_type == "subtask_implementation"
                and item.status.value == "unassigned"
                and "IOS-30072" in item.title
                for item in work_items
            )
        )
        self.assertFalse(
            any(
                item.work_type == "subtask_implementation"
                and item.status.value == "unassigned"
                and "IOS-30071" in item.title
                for item in work_items
            )
        )

    def test_reconcile_session_dispatch_assigns_next_unassigned_subtask_when_owner_has_no_active_item(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004RECONCILESUB",
            workflow_profile="story_full",
            policy={"review_policy": "disabled"},
        )
        self.coordinator.prepare_task_session("IOS-30004RECONCILESUB")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={"summary": "Context prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="requirements_completed",
            payload={"summary": "Requirements clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="acceptance_criteria_completed",
            payload={"summary": "Acceptance prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="constraints_completed",
            payload={"summary": "Constraints prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="spec_verification_completed",
            payload={"summary": "Planning verified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="story_spec_completed",
            payload={"summary": "Split into focused subtasks"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="task_decomposition_completed",
            payload=decomposition_payload("Execution chunks prepared"),
        )
        self.write_statuses_file(
            "IOS-30004RECONCILESUB",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30004RECONCILESUB | Story | Parent story | In Progress |
| IOS-30080 | Sub-task | Add data source | To Do |
| IOS-30081 | Sub-task | Wire view state | To Do |
""",
        )
        self.coordinator.start_subtask_graph(session.id)
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        assert implementer_role is not None
        work_items = self.work_item_repository.list_for_session(session.id)
        assigned_item = next(
            item
            for item in work_items
            if item.work_type == "subtask_implementation" and item.status.value == "assigned"
        )
        self.work_item_repository.update_status(assigned_item.id, WorkItemStatus.COMPLETED)
        broken_session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="subtask_implementation_requested",
            current_owner=IMPLEMENTER_ROLE,
        )
        broken_session = self.session_repository.update_status(broken_session.id, SessionStatus.ACTIVE)

        reconciled = self.coordinator._reconcile_session_dispatch(broken_session)
        work_items = self.work_item_repository.list_for_session(session.id)
        events = self.event_repository.list_for_session(session.id)

        self.assertTrue(reconciled)
        self.assertTrue(
            any(
                item.work_type == "subtask_implementation"
                and item.status.value == "assigned"
                and "IOS-30081" in item.title
                and item.owner_role_id == implementer_role.id
                for item in work_items
            )
        )
        self.assertTrue(any(item.event_type == "session_dispatch_reconciled" for item in events))

    def test_reconcile_session_dispatch_advances_passed_verification_without_active_work_item(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004RECONVERIFY",
            workflow_profile="oneshot",
            policy={"doc_harvest_policy": "enabled"},
        )
        self.coordinator.prepare_task_session("IOS-30004RECONVERIFY")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={"summary": "all checks passed"},
        )
        broken_session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="verification_requested",
            current_owner=VERIFICATION_COORDINATOR_ROLE,
        )
        broken_session = self.session_repository.update_status(broken_session.id, SessionStatus.ACTIVE)

        reconciled = self.coordinator._reconcile_session_dispatch(broken_session)
        updated_session = self.session_repository.get_by_id(session.id)
        events = self.event_repository.list_for_session(session.id)

        self.assertTrue(reconciled)
        self.assertIsNotNone(updated_session)
        assert updated_session is not None
        self.assertEqual("doc_harvest_requested", updated_session.current_stage)
        self.assertEqual(DOC_HARVEST_ROLE, updated_session.current_owner)
        self.assertTrue(any(item.event_type == "session_outcome_reconciled" for item in events))

    def test_reconcile_session_dispatch_advances_completed_doc_harvest_without_active_work_item(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004RECONDOC",
            workflow_profile="oneshot",
            policy={"doc_harvest_policy": "enabled"},
        )
        self.coordinator.prepare_task_session("IOS-30004RECONDOC")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={"summary": "all green"},
        )
        self.coordinator.complete_doc_harvest(
            session_id=session.id,
            summary="README updated.",
        )
        broken_session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="doc_harvest_requested",
            current_owner=DOC_HARVEST_ROLE,
        )
        broken_session = self.session_repository.update_status(broken_session.id, SessionStatus.ACTIVE)

        reconciled = self.coordinator._reconcile_session_dispatch(broken_session)
        updated_session = self.session_repository.get_by_id(session.id)
        events = self.event_repository.list_for_session(session.id)

        self.assertTrue(reconciled)
        self.assertIsNotNone(updated_session)
        assert updated_session is not None
        self.assertEqual("documentation_review_requested", updated_session.current_stage)
        self.assertEqual(SessionStatus.ACTIVE, updated_session.status)
        self.assertTrue(any(item.event_type == "session_outcome_reconciled" for item in events))

    def test_reconcile_session_dispatch_advances_completed_verification_correction(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004RECONVERFIX",
            workflow_profile="oneshot",
        )
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        assert implementer_role is not None
        correction_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="verification_correction",
            title="Verification corrections for IOS-30004RECONVERFIX",
            owner_role_id=implementer_role.id,
            status=WorkItemStatus.COMPLETED,
        )
        self.event_repository.append(
            session_id=session.id,
            event_type="verification_requested",
            producer_type="coordinator",
            payload={"work_item_id": 12, "summary": "older verification cycle"},
        )
        stale_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="verification_correction",
            title="Verification corrections for IOS-30004RECONVERFIX",
            owner_role_id=implementer_role.id,
            status=WorkItemStatus.ASSIGNED,
        )
        self.event_repository.append(
            session_id=session.id,
            event_type="implementation_completed",
            producer_type="role_output",
            producer_id=IMPLEMENTER_ROLE,
            payload={"work_item_id": correction_item.id, "summary": "fixes applied"},
        )
        broken_session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="verification_correction_requested",
            current_owner=IMPLEMENTER_ROLE,
        )
        broken_session = self.session_repository.update_status(broken_session.id, SessionStatus.ACTIVE)

        reconciled = self.coordinator._reconcile_session_dispatch(broken_session)
        updated_session = self.session_repository.get_by_id(session.id)
        work_items = self.work_item_repository.list_for_session(session.id)
        events = self.event_repository.list_for_session(session.id)

        self.assertTrue(reconciled)
        assert updated_session is not None
        self.assertEqual("verification_requested", updated_session.current_stage)
        self.assertEqual(VERIFICATION_COORDINATOR_ROLE, updated_session.current_owner)
        self.assertTrue(
            any(
                item.id == stale_item.id and item.status == WorkItemStatus.WAITING_FOR_OPERATOR
                for item in work_items
            )
        )
        self.assertTrue(any(item.event_type == "verification_requested" for item in events))
        self.assertTrue(any(item.event_type == "session_outcome_reconciled" for item in events))

    def test_verification_failed_moves_session_back_to_implementer(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30004")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_failed",
            payload={
                "failures": ["test", "lint"],
                "check_outputs": {
                    "run-test.sh": "Tests failed: presenter state mismatch",
                    "run-lint.sh": "Lint failed: unused import",
                },
            },
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual("verification_correction_requested", updated_session.current_stage)
        self.assertEqual("implementer", updated_session.current_owner)
        self.assertEqual("verification_correction_requested", followup_event.event_type)
        self.assertEqual(
            sorted(
                [
                    ("Verification corrections for IOS-30004", "assigned"),
                    ("Initial implementation for IOS-30004", "completed"),
                    ("Verification for IOS-30004", "completed"),
                ]
            ),
            sorted((item.title, item.status.value) for item in work_items),
        )
        self.assertEqual(
            [
                "task_started",
                "task_prepared",
                "role_input_delivery_confirmed",
                "role_input_dispatched",
                "implementation_requested",
                "implementation_completed",
                "git_commit_completed",
                "role_input_delivery_confirmed",
                "role_input_dispatched",
                "verification_requested",
                "verification_failed",
                "role_input_delivery_confirmed",
                "role_input_dispatched",
                "verification_correction_requested",
            ],
            [item.event_type for item in events],
        )
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.assertEqual(2, implementer_role.last_hydration_version)
        sent_inputs = self.session_backend.get_sent_inputs(implementer_role.runtime_handle)
        verification_report = Path(self.temp_dir.name) / "IOS-30004" / "spec" / "final-verification.md"
        self.assertEqual(2, len(sent_inputs))
        self.assertIn("Apply verification corrections for IOS-30004.", sent_inputs[-1])
        self.assertIn("Continue from your existing role context.", sent_inputs[-1])
        self.assertNotIn("fix the real root cause cleanly and avoid regressions", sent_inputs[-1])
        self.assertNotIn("Read AGENTS.md/CLAUDE.md in the current directory once now", sent_inputs[-1])
        self.assertTrue(verification_report.exists())
        self.assertIn("## Strategy", verification_report.read_text())
        self.assertIn("Mode: android_broad_safe_gate", verification_report.read_text())
        self.assertIn("### Commands", verification_report.read_text())
        self.assertIn("## Result", verification_report.read_text())
        self.assertIn("FAIL", verification_report.read_text())
        self.assertIn("## Output: run-test.sh", verification_report.read_text())
        self.assertIn("presenter state mismatch", verification_report.read_text())

    def test_verification_failed_overwrites_stale_report_and_closes_duplicate_items(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30004STALE")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )
        verifier_role = self.role_repository.get_by_name(session.id, VERIFICATION_COORDINATOR_ROLE)
        self.assertIsNotNone(verifier_role)
        assert verifier_role is not None
        duplicate_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="verification",
            title=f"Verification for {session.task_key}",
            owner_role_id=verifier_role.id,
            priority=90,
        )
        verification_report = Path(self.temp_dir.name) / session.task_key / "spec" / "final-verification.md"
        verification_report.parent.mkdir(parents=True, exist_ok=True)
        verification_report.write_text("# Final Verification\n\nold missing android-build.sh failure\n")

        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_failed",
            payload={
                "work_item_id": str(duplicate_item.id),
                "summary": "Verification failed",
                "failures": ["fresh Kotlin compile failure"],
            },
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        report_text = verification_report.read_text()

        self.assertIn("fresh Kotlin compile failure", report_text)
        self.assertNotIn("old missing android-build.sh failure", report_text)
        self.assertTrue(
            all(
                item.status == WorkItemStatus.COMPLETED
                for item in work_items
                if item.work_type == "verification"
            )
        )

    def test_verification_dispatch_includes_hydration_paths(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30004VERWRITER")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )

        verification_role = self.role_repository.get_by_name(session.id, VERIFICATION_COORDINATOR_ROLE)
        assert verification_role is not None
        sent_inputs = self.session_backend.get_sent_inputs(verification_role.runtime_handle)
        role_workspace = self.coordinator.role_workspace_manager.role_directory(  # type: ignore[union-attr]
            "IOS-30004VERWRITER",
            VERIFICATION_COORDINATOR_ROLE,
        )
        hydration = json.loads((role_workspace / "HYDRATION.json").read_text())

        self.assertEqual(1, len(sent_inputs))
        self.assertIn("Read HYDRATION.json", sent_inputs[0])
        self.assertEqual("verification_requested", hydration["current_stage"])
        self.assertEqual("verification", hydration["work_item_type"])
        self.assertIn("verification_report_path", hydration)

    def test_collect_role_output_accepts_helper_written_verification_failed_result(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30004VERHELPER")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )

        active_item = next(
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "verification" and item.status.value == "assigned"
        )
        verifier_workspace = self.coordinator.role_workspace_manager.role_directory(  # type: ignore[union-attr]
            session.task_key,
            VERIFICATION_COORDINATOR_ROLE,
        )
        result_path = verifier_workspace / "RESULT.json"
        document = build_result_document(
            SimpleNamespace(
                role="verification-coordinator",
                output_type="completed",
                output=str(result_path),
                work_item_id=active_item.id,
                result="failed",
                summary=None,
                details=None,
                failure=["build-for-testing failed"],
            )
        )
        write_result_file(result_path, document)

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name=VERIFICATION_COORDINATOR_ROLE,
        )
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual("verification_correction_requested", updated_session.current_stage)
        self.assertEqual(IMPLEMENTER_ROLE, updated_session.current_owner)
        self.assertFalse(result_path.exists())
        self.assertTrue(any(item.artifact_type == "role_result_json" for item in artifacts))

    def test_submit_role_result_document_accepts_verification_failed_result(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30004VERINGRESS")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )

        active_item = next(
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "verification" and item.status.value == "assigned"
        )
        updated_session, event, mapped_event_type, followup_event_type, ignored = (
            self.coordinator.submit_role_result_document(
                document={
                    "output_type": "completed",
                    "payload": {
                        "work_item_id": active_item.id,
                        "result": "failed",
                        "failures": ["build-for-testing failed"],
                    },
                }
            )
        )
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual("verification_failed", mapped_event_type)
        self.assertEqual("verification_correction_requested", followup_event_type)
        self.assertFalse(ignored)
        self.assertEqual("verification_correction_requested", updated_session.current_stage)
        self.assertEqual(IMPLEMENTER_ROLE, updated_session.current_owner)
        self.assertTrue(any(item.artifact_type == "role_result_json" for item in artifacts))

    def test_submit_role_result_document_accepts_documentation_review_after_runtime_error_escalation(
        self,
    ) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004DOCREVIEWINGRESS",
            workflow_profile="oneshot",
            policy={"doc_harvest_policy": "enabled", "review_policy": "disabled"},
        )
        self.coordinator.prepare_task_session("IOS-30004DOCREVIEWINGRESS")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={"summary": "all green"},
        )
        self.coordinator.complete_doc_harvest(
            session_id=session.id,
            summary="No documentation update needed.",
        )
        active_item = next(
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "documentation_review" and item.status == WorkItemStatus.ASSIGNED
        )
        self.work_item_repository.update_status(active_item.id, WorkItemStatus.WAITING_FOR_OPERATOR)
        self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="documentation_review_requested",
            current_owner=None,
        )
        self.session_repository.update_status(session.id, SessionStatus.WAITING_FOR_OPERATOR)

        updated_session, event, mapped_event_type, followup_event_type, ignored = (
            self.coordinator.submit_role_result_document(
                document={
                    "output_type": "passed",
                    "payload": {
                        "work_item_id": active_item.id,
                        "summary": "Documentation review passed.",
                    },
                }
            )
        )
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual("documentation_review_passed", mapped_event_type)
        self.assertIn(followup_event_type, {"mr_handoff_completed", "send_to_test_completed", "task_completed"})
        self.assertFalse(ignored)
        self.assertIn(updated_session.status.value, {"active", "completed"})
        self.assertFalse(any(item.event_type == "stale_role_output_ignored" for item in events))

    def test_submit_role_result_document_ignores_duplicate_completed_documentation_review_result(
        self,
    ) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004DOCREVIEWDUP",
            workflow_profile="oneshot",
            policy={"doc_harvest_policy": "enabled", "review_policy": "disabled"},
        )
        self.coordinator.prepare_task_session("IOS-30004DOCREVIEWDUP")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={"summary": "all green"},
        )
        self.coordinator.complete_doc_harvest(
            session_id=session.id,
            summary="No documentation update needed.",
        )
        active_item = next(
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "documentation_review" and item.status == WorkItemStatus.ASSIGNED
        )
        document = {
            "output_type": "passed",
            "payload": {
                "work_item_id": active_item.id,
                "summary": "Documentation review passed.",
            },
        }

        self.coordinator.submit_role_result_document(document=document)
        updated_session, _, _, _, ignored = self.coordinator.submit_role_result_document(document=document)
        events = self.event_repository.list_for_session(session.id)

        self.assertTrue(ignored)
        self.assertNotEqual(SessionStatus.WAITING_FOR_OPERATOR, updated_session.status)
        self.assertTrue(any(item.event_type == "stale_role_output_ignored" for item in events))
        self.assertFalse(
            any(
                item.event_type == "session_escalated_to_operator"
                and item.payload.get("reason") == "role_result_protocol_violation"
                for item in events
            )
        )

    def test_collect_role_output_ignores_late_runtime_error_for_completed_documentation_review_item(
        self,
    ) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004DOCREVIEWERR",
            workflow_profile="oneshot",
            policy={"doc_harvest_policy": "enabled", "review_policy": "disabled"},
        )
        self.coordinator.prepare_task_session("IOS-30004DOCREVIEWERR")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={"summary": "all green"},
        )
        self.coordinator.complete_doc_harvest(
            session_id=session.id,
            summary="No documentation update needed.",
        )
        active_item = next(
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "documentation_review" and item.status == WorkItemStatus.ASSIGNED
        )
        self.work_item_repository.update_status(active_item.id, WorkItemStatus.COMPLETED)
        doc_role = self.role_repository.get_by_name(session.id, DOCUMENTATION_REVIEWER_ROLE)
        assert doc_role is not None
        assert doc_role.runtime_handle is not None
        self.session_backend.queue_output(
            doc_role.runtime_handle,
            (
                "SDD_ERROR: {"
                "\"summary\":\"Result writer exited non-zero\","
                "\"details\":\"write-result.sh was interrupted\","
                f"\"dispatch_token\":\"hv2-wi{active_item.id}\""
                "}"
            ),
        )

        updated_session, _, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name=DOCUMENTATION_REVIEWER_ROLE,
        )
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual(1, chunk_count)
        self.assertNotEqual(SessionStatus.WAITING_FOR_OPERATOR, updated_session.status)
        self.assertTrue(
            any(
                item.event_type == "stale_role_output_ignored"
                and item.payload.get("reason") == "stale_runtime_error_for_inactive_work_item"
                for item in events
            )
        )
        self.assertFalse(any(item.event_type == "role_runtime_error_reported" for item in events))

    def test_collect_role_output_escalates_verification_completed_result_without_explicit_result(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30004VERNORESULT")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )

        verifier_workspace = self.coordinator.role_workspace_manager.role_directory(  # type: ignore[union-attr]
            session.task_key,
            VERIFICATION_COORDINATOR_ROLE,
        )
        result_path = verifier_workspace / "RESULT.json"
        result_path.write_text(
            json.dumps(
                {
                    "output_type": "completed",
                    "payload": {
                        "work_item_id": next(
                            item.id
                            for item in self.work_item_repository.list_for_session(session.id)
                            if item.work_type == "verification" and item.status.value == "assigned"
                        ),
                        "summary": "all green",
                    },
                }
            ),
            encoding="utf-8",
        )

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name=VERIFICATION_COORDINATOR_ROLE,
        )
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual(SessionStatus.WAITING_FOR_OPERATOR, updated_session.status)
        self.assertIsNone(updated_session.current_owner)
        self.assertTrue(any(item.event_type == "role_result_protocol_violation_reported" for item in events))

    def test_collect_role_output_escalates_verification_schema_violation_as_protocol_violation(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30004VERPROTO")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )

        verifier_workspace = self.coordinator.role_workspace_manager.role_directory(  # type: ignore[union-attr]
            session.task_key,
            VERIFICATION_COORDINATOR_ROLE,
        )
        result_path = verifier_workspace / "RESULT.json"
        result_path.write_text(
            json.dumps(
                {
                    "output_type": "completed",
                    "payload": {
                        "work_item_id": next(
                            item.id
                            for item in self.work_item_repository.list_for_session(session.id)
                            if item.work_type == "verification" and item.status.value == "assigned"
                        ),
                        "summary": "all green",
                    },
                }
            ),
            encoding="utf-8",
        )

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name=VERIFICATION_COORDINATOR_ROLE,
        )
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual(SessionStatus.WAITING_FOR_OPERATOR, updated_session.status)
        self.assertIsNone(updated_session.current_owner)
        self.assertTrue(any(item.event_type == "role_result_protocol_violation_reported" for item in events))
        escalations = [item for item in events if item.event_type == "session_escalated_to_operator"]
        self.assertTrue(escalations)
        self.assertEqual("role_result_protocol_violation", escalations[-1].payload.get("reason"))

    def test_enqueue_verification_respawns_stopped_verification_role(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30004VERSTOP")
        verifier_role = self.role_repository.get_by_name(session.id, VERIFICATION_COORDINATOR_ROLE)
        assert verifier_role is not None
        self.role_repository.update_runtime(
            verifier_role.id,
            runtime_backend=verifier_role.runtime_backend,
            runtime_handle=None,
            status=RoleStatus.STOPPED,
        )

        updated_session, _ = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )

        refreshed_role = self.role_repository.get_by_name(session.id, VERIFICATION_COORDINATOR_ROLE)
        assert refreshed_role is not None
        self.assertEqual(RoleStatus.RUNNING, refreshed_role.status)
        self.assertIsNotNone(refreshed_role.runtime_handle)
        self.assertEqual("verification_requested", updated_session.current_stage)
        self.assertEqual(VERIFICATION_COORDINATOR_ROLE, updated_session.current_owner)

    def test_subtask_dispatch_respawns_stopped_implementer_role(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30009RESPAWN",
            workflow_profile="story_full",
            policy={"review_policy": "disabled"},
        )
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        assert implementer_role is not None
        self.role_repository.update_runtime(
            implementer_role.id,
            runtime_backend=implementer_role.runtime_backend,
            runtime_handle=None,
            status=RoleStatus.STOPPED,
        )
        source_event = self.coordinator._append_event(  # type: ignore[attr-defined]
            session_id=session.id,
            event_type="jira_subtasks_refreshed",
            producer_type="operator",
            payload={"task_key": session.task_key},
        )
        initial_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="subtask_creation",
            title=f"Subtask creation for {session.task_key}",
            owner_role_id=implementer_role.id,
            source_event_id=source_event.id,
            priority=80,
        )
        followup_event = self.coordinator._enqueue_subtask_graph(  # type: ignore[attr-defined]
            session=session,
            source_event=source_event,
            initial_work_item=initial_item,
            subtasks=[
                SnapshotSubtask(
                    key="IOS-30100",
                    issue_type="Sub-task",
                    title="Already done chunk",
                    status="Ready for test",
                ),
                SnapshotSubtask(
                    key="IOS-30101",
                    issue_type="Sub-task",
                    title="Active chunk",
                    status="In Progress",
                ),
            ],
        )
        refreshed_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        updated_session = self.session_repository.get_by_id(session.id)
        assert refreshed_role is not None
        assert updated_session is not None

        self.assertEqual(RoleStatus.RUNNING, refreshed_role.status)
        self.assertIsNotNone(refreshed_role.runtime_handle)
        self.assertEqual("subtask_implementation_requested", followup_event.event_type)
        self.assertEqual("subtask_implementation_requested", updated_session.current_stage)
        self.assertEqual(IMPLEMENTER_ROLE, updated_session.current_owner)

    def test_collect_role_output_escalates_subtask_completion_without_subtask_key(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30009ESUBPROTO",
            workflow_profile="story_full",
            policy={"review_policy": "disabled"},
        )
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        assert implementer_role is not None
        active_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="subtask_implementation",
            title="Subtask implementation for IOS-30098: Missing addressed key",
            owner_role_id=implementer_role.id,
            priority=100,
        )
        active_session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="subtask_implementation_requested",
            current_owner=IMPLEMENTER_ROLE,
        )
        self.session_repository.update_status(active_session.id, SessionStatus.ACTIVE)
        self.coordinator._append_event(
            session_id=session.id,
            event_type="role_input_dispatched",
            producer_type="coordinator",
            payload={
                "role_name": IMPLEMENTER_ROLE,
                "work_item_id": active_item.id,
                "stage_name": "subtask_implementation_requested",
                "hydration_version": 1,
                "prompt_mode": "live_continuation",
            },
        )
        result_path = self.coordinator.role_workspace_manager.role_directory(  # type: ignore[union-attr]
            session.task_key,
            IMPLEMENTER_ROLE,
        ) / "RESULT.json"
        result_path.write_text(
            json.dumps(
                {
                    "output_type": "completed",
                    "payload": {
                        "work_item_id": active_item.id,
                        "summary": "completed subtask work without addressed key",
                    },
                }
            ),
            encoding="utf-8",
        )

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name=IMPLEMENTER_ROLE,
        )
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual(SessionStatus.WAITING_FOR_OPERATOR, updated_session.status)
        self.assertIsNone(updated_session.current_owner)
        self.assertFalse(result_path.exists())
        self.assertTrue(any(item.event_type == "role_result_protocol_violation_reported" for item in events))

    def test_documentation_precheck_flags_verbose_swift_inline_comment_blocks(self) -> None:
        repo_dir = Path(self.temp_dir.name) / "repo"
        source_path = repo_dir / "Sources" / "BusinessInfoPresenter.swift"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(
            "\n".join(
                [
                    "final class BusinessInfoPresenter {",
                    "    // In the invalid selected-company recovery flow, the register submit can be",
                    "    // rejected with a contract validation for a field the user cannot fix on this",
                    "    // screen. Retry once with a simplified payload before surfacing the error.",
                    "    // The condition intentionally keys off the stable class rather than a message.",
                    "    private func shouldRetrySimplifiedRegister() -> Bool { true }",
                    "}",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        findings = self.coordinator._documentation_precheck_findings(
            repo_dir,
            ["Sources/BusinessInfoPresenter.swift"],
        )

        titles = {str(item["title"]) for item in findings}
        self.assertIn("Verbose inline comment block", titles)
        self.assertIn("Inline comment explains task mechanics instead of a stable invariant", titles)

    def test_documentation_precheck_allows_short_swift_invariant_comments(self) -> None:
        repo_dir = Path(self.temp_dir.name) / "repo"
        source_path = repo_dir / "Sources" / "GenerationGuard.swift"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(
            "\n".join(
                [
                    "func applyResult() {",
                    "    // The generation is checked again on main because cancellation can happen",
                    "    // after the network result is accepted but before the UI callback runs.",
                    "    guard generation == currentGeneration else { return }",
                    "}",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        findings = self.coordinator._documentation_precheck_findings(
            repo_dir,
            ["Sources/GenerationGuard.swift"],
        )

        self.assertEqual([], findings)

    def test_collect_role_output_escalates_doc_harvest_without_summary_or_details(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021FHPROTO",
            workflow_profile="oneshot",
            policy={"doc_harvest_policy": "required"},
        )
        self.coordinator.prepare_task_session("IOS-30021FHPROTO")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={"summary": "all green"},
        )

        doc_item = next(
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "doc_harvest" and item.status.value == "assigned"
        )
        role_workspace = self.coordinator.role_workspace_manager.role_directory(  # type: ignore[union-attr]
            session.task_key,
            DOC_HARVEST_ROLE,
        )
        result_path = role_workspace / "RESULT.json"
        result_path.write_text(
            json.dumps(
                {
                    "output_type": "completed",
                    "payload": {
                        "work_item_id": doc_item.id,
                    },
                }
            ),
            encoding="utf-8",
        )

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name=DOC_HARVEST_ROLE,
        )
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual(SessionStatus.WAITING_FOR_OPERATOR, updated_session.status)
        self.assertIsNone(updated_session.current_owner)
        self.assertFalse(result_path.exists())
        self.assertTrue(any(item.event_type == "role_result_protocol_violation_reported" for item in events))

    def test_implementation_completed_uses_payload_work_item_id_over_stale_assigned_item(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004IMPLPAYLOAD",
            workflow_profile="oneshot",
        )
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        assert implementer_role is not None
        correction_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="verification_correction",
            title="Verification corrections for IOS-30004IMPLPAYLOAD",
            owner_role_id=implementer_role.id,
            status=WorkItemStatus.ASSIGNED,
        )
        stale_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="verification_correction",
            title="Verification corrections for IOS-30004IMPLPAYLOAD",
            owner_role_id=implementer_role.id,
            status=WorkItemStatus.ASSIGNED,
        )
        broken_session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="verification_correction_requested",
            current_owner=IMPLEMENTER_ROLE,
        )

        updated_session, followup_event = self.coordinator._handle_implementation_completed(
            broken_session,
            self.event_repository.append(
                session_id=session.id,
                event_type="implementation_completed",
                producer_type="role_output",
                producer_id=IMPLEMENTER_ROLE,
                payload={"work_item_id": correction_item.id, "summary": "fixes applied"},
            ),
        )
        work_items = self.work_item_repository.list_for_session(session.id)

        self.assertEqual("verification_requested", followup_event.event_type)
        self.assertEqual("verification_requested", updated_session.current_stage)
        self.assertEqual(VERIFICATION_COORDINATOR_ROLE, updated_session.current_owner)
        self.assertTrue(
            any(item.id == correction_item.id and item.status == WorkItemStatus.COMPLETED for item in work_items)
        )
        self.assertTrue(
            any(item.id == stale_item.id and item.status == WorkItemStatus.ASSIGNED for item in work_items)
        )

    def test_subtask_completed_uses_payload_work_item_id_over_stale_assigned_item(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004SUBTASKPAYLOAD",
            workflow_profile="story_full",
        )
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        assert implementer_role is not None
        target_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="subtask_implementation",
            title="Subtask implementation for IOS-39991: Target subtask",
            owner_role_id=implementer_role.id,
            status=WorkItemStatus.ASSIGNED,
        )
        stale_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="subtask_implementation",
            title="Subtask implementation for IOS-39992: Stale subtask",
            owner_role_id=implementer_role.id,
            status=WorkItemStatus.ASSIGNED,
        )
        broken_session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="subtask_implementation_requested",
            current_owner=IMPLEMENTER_ROLE,
        )

        updated_session, followup_event = self.coordinator._handle_subtask_completed(
            broken_session,
            self.event_repository.append(
                session_id=session.id,
                event_type="subtask_completed",
                producer_type="role_output",
                producer_id=IMPLEMENTER_ROLE,
                payload={
                    "work_item_id": target_item.id,
                    "subtask_key": "IOS-39991",
                    "summary": "subtask done",
                },
            ),
        )
        work_items = self.work_item_repository.list_for_session(session.id)

        self.assertEqual("subtask_implementation_requested", followup_event.event_type)
        self.assertEqual("subtask_implementation_requested", updated_session.current_stage)
        self.assertEqual(IMPLEMENTER_ROLE, updated_session.current_owner)
        self.assertTrue(
            any(item.id == target_item.id and item.status == WorkItemStatus.COMPLETED for item in work_items)
        )
        self.assertTrue(
            any(item.id == stale_item.id and item.status == WorkItemStatus.ASSIGNED for item in work_items)
        )

    def test_stale_role_output_mismatch_uses_payload_work_item_id_over_stale_assigned_item(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004SUBTASKSTALECHECK",
            workflow_profile="story_full",
        )
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        assert implementer_role is not None
        target_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="subtask_implementation",
            title="Subtask implementation for IOS-39995: Target subtask",
            owner_role_id=implementer_role.id,
            status=WorkItemStatus.ASSIGNED,
        )
        self.work_item_repository.create(
            session_id=session.id,
            work_type="subtask_implementation",
            title="Subtask implementation for IOS-39996: Stale subtask",
            owner_role_id=implementer_role.id,
            status=WorkItemStatus.ASSIGNED,
        )
        broken_session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="subtask_implementation_requested",
            current_owner=IMPLEMENTER_ROLE,
        )

        mismatch = self.coordinator._stale_role_output_mismatch(
            session=broken_session,
            role_name=IMPLEMENTER_ROLE,
            output_type="completed",
            output_payload={
                "work_item_id": target_item.id,
                "subtask_key": "IOS-39995",
                "summary": "subtask done",
            },
        )

        self.assertIsNone(mismatch)

    def test_subtask_completed_reuses_existing_assigned_next_item_after_snapshot_refresh(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004SUBTASKREUSE",
            workflow_profile="story_full",
            policy={"review_policy": "disabled"},
        )
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        assert implementer_role is not None
        active_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="subtask_implementation",
            title="Subtask implementation for IOS-39993: Completed subtask",
            owner_role_id=implementer_role.id,
            status=WorkItemStatus.ASSIGNED,
        )
        next_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="subtask_implementation",
            title="Subtask implementation for IOS-39994: Pending subtask",
            owner_role_id=implementer_role.id,
            status=WorkItemStatus.ASSIGNED,
        )
        active_session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="subtask_implementation_requested",
            current_owner=IMPLEMENTER_ROLE,
        )
        self.session_repository.update_status(session.id, SessionStatus.ACTIVE)
        self.write_statuses_file(
            "IOS-30004SUBTASKREUSE",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30004SUBTASKREUSE | Story | Parent story | In Progress |
| IOS-39993 | Sub-task | Completed subtask | Ready for test |
| IOS-39994 | Sub-task | Pending subtask | To Do |
""",
        )

        updated_session, followup_event = self.coordinator._handle_subtask_completed(
            active_session,
            self.event_repository.append(
                session_id=session.id,
                event_type="subtask_completed",
                producer_type="role_output",
                producer_id=IMPLEMENTER_ROLE,
                payload={
                    "work_item_id": active_item.id,
                    "subtask_key": "IOS-39993",
                    "summary": "completed",
                },
            ),
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        pending_ios_39994 = [
            item
            for item in work_items
            if item.work_type == "subtask_implementation"
            and "IOS-39994" in item.title
            and item.status != WorkItemStatus.COMPLETED
        ]

        self.assertEqual("subtask_implementation_requested", followup_event.event_type)
        self.assertEqual("subtask_implementation_requested", updated_session.current_stage)
        self.assertEqual(IMPLEMENTER_ROLE, updated_session.current_owner)
        self.assertEqual(1, len(pending_ios_39994))
        self.assertEqual(next_item.id, pending_ios_39994[0].id)
        self.assertEqual(WorkItemStatus.ASSIGNED, pending_ios_39994[0].status)

    def test_bug_full_verification_failed_routes_back_to_bug_fixer_with_fix_only_mode(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004BUG",
            workflow_profile="bug_full",
            policy={"test_policy": "enabled"},
        )
        self.coordinator.prepare_task_session("IOS-30004BUG")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="bug_analysis_completed",
            payload={"summary": "root cause found"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "bug fix done"},
        )

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_failed",
            payload={"failures": ["test"]},
        )
        bug_fixer_role = self.role_repository.get_by_name(session.id, BUG_FIXER_ROLE)
        sent_inputs = self.session_backend.get_sent_inputs(bug_fixer_role.runtime_handle)

        self.assertEqual("verification_correction_requested", updated_session.current_stage)
        self.assertEqual(BUG_FIXER_ROLE, updated_session.current_owner)
        self.assertEqual("verification_correction_requested", followup_event.event_type)
        self.assertIn("Mode: fix-only", sent_inputs[-1])
        self.assertIn("Apply verification corrections for IOS-30004BUG.", sent_inputs[-1])
        self.assertIn("fix the root cause cleanly and prevent regressions", sent_inputs[-1])
        self.assertNotIn('"issues_file_path"', sent_inputs[-1])
        self.assertNotIn('"bug_analysis_report_path"', sent_inputs[-1])

    def test_second_verification_dispatch_uses_continuation_prompt(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30004V2")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_failed",
            payload={"failures": ["test"]},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "corrections done"},
        )

        verification_role = self.role_repository.get_by_name(session.id, "verification-coordinator")
        sent_inputs = self.session_backend.get_sent_inputs(verification_role.runtime_handle)

        self.assertEqual(2, len(sent_inputs))
        self.assertIn("Read AGENTS.md/CLAUDE.md in the current directory once now", sent_inputs[0])
        self.assertIn(
            "Continue from your existing role context.",
            sent_inputs[-1],
        )
        self.assertNotIn("Read AGENTS.md/CLAUDE.md in the current directory once now", sent_inputs[-1])

    def test_verifier_can_block_non_converging_verification_cycle(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30004VBLOCK")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )

        updated_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name="verification-coordinator",
            output_type="blocked_verification_cycle",
            payload={
                "summary": "The same failing verification loop remains unresolved.",
                "details": "Two verification rounds produced the same correction guidance and the loop no longer converges.",
                "failures": ["test"],
                "check_outputs": {
                    "run-test.sh": "Tests still fail: presenter state mismatch",
                },
            },
        )
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual("verification_blocked", mapped_event.event_type)
        self.assertEqual("session_escalated_to_operator", followup_event.event_type)
        self.assertEqual("waiting_for_operator", updated_session.status.value)
        self.assertEqual("verification_requested", updated_session.current_stage)
        self.assertEqual("verification-coordinator", updated_session.current_owner)
        self.assertEqual("verification_cycle", str(followup_event.payload.get("reason") or ""))
        self.assertTrue(any(item.artifact_type == "final_verification_markdown" for item in artifacts))

    def test_resume_session_retries_verifier_after_blocked_verification_cycle(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30004VBLOCKRESUME")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )
        self.coordinator.handle_role_output(
            session_id=session.id,
            role_name="verification-coordinator",
            output_type="blocked_verification_cycle",
            payload={
                "summary": "The same failing verification loop remains unresolved.",
                "details": "The verifier asked for operator intervention.",
                "failures": ["test"],
                "check_outputs": {
                    "run-test.sh": "Tests still fail: presenter state mismatch",
                },
            },
        )

        resumed_session, resumed_event, dispatch_event = self.coordinator.resume_session(session.id)
        verifier_role = self.role_repository.get_by_name(session.id, "verification-coordinator")
        sent_inputs = self.session_backend.get_sent_inputs(verifier_role.runtime_handle)

        self.assertEqual("active", resumed_session.status.value)
        self.assertEqual("verification-coordinator", resumed_session.current_owner)
        self.assertEqual("session_resumed_by_operator", resumed_event.event_type)
        self.assertIsNotNone(dispatch_event)
        assert dispatch_event is not None
        self.assertEqual("role_input_dispatched", dispatch_event.event_type)
        self.assertIn("blocked_verification_cycle", sent_inputs[-1])

    def test_failed_verification_with_blocked_cycle_summary_stays_failed(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30004VBLOCKSUMMARY")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )

        updated_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name="verification-coordinator",
            output_type="failed",
            payload={
                "summary": "blocked_verification_cycle",
                "failures": ["The verification loop is no longer converging."],
            },
        )

        self.assertEqual("verification_failed", mapped_event.event_type)
        self.assertEqual("verification_correction_requested", followup_event.event_type)
        self.assertEqual("active", updated_session.status.value)
        self.assertEqual("verification_correction_requested", updated_session.current_stage)

    def test_verifier_passed_output_with_failures_is_rejected_without_explicit_result(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30004VPAYLOADFAIL")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )

        with self.assertRaisesRegex(
            IntakeError,
            "Verification output must include payload.result set to 'passed' or 'failed'",
        ):
            self.coordinator.handle_role_output(
                session_id=session.id,
                role_name="verification-coordinator",
                output_type="passed",
                payload={
                    "summary": "looks green",
                    "failures": ["run-test.sh failed"],
                },
            )

    def test_verifier_completed_output_with_failed_check_output_is_rejected_without_explicit_result(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30004VCHECKFAIL")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )

        with self.assertRaisesRegex(
            IntakeError,
            "Verification output must include payload.result set to 'passed' or 'failed'",
        ):
            self.coordinator.handle_role_output(
                session_id=session.id,
                role_name="verification-coordinator",
                output_type="completed",
                payload={
                    "summary": "verification finished",
                    "check_outputs": {
                        "run-test.sh": "Tests failed: presenter state mismatch",
                    },
                },
            )

    def test_verifier_completed_output_with_nested_failed_results_is_rejected_without_explicit_result(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30004VRESULTFAIL")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )

        with self.assertRaisesRegex(
            IntakeError,
            "Verification output must include payload.result set to 'passed' or 'failed'",
        ):
            self.coordinator.handle_role_output(
                session_id=session.id,
                role_name="verification-coordinator",
                output_type="completed",
                payload={
                    "results": {
                        "run_test": {
                            "status": "failed",
                            "errors": ["Compilation failed"],
                        },
                        "run_lint": {
                            "status": "passed",
                        },
                    },
                },
            )

    def test_verifier_completed_output_with_failed_verification_status_is_rejected_without_explicit_result(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30004VSTATUSFAIL")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )

        with self.assertRaisesRegex(
            IntakeError,
            "Verification output must include payload.result set to 'passed' or 'failed'",
        ):
            self.coordinator.handle_role_output(
                session_id=session.id,
                role_name="verification-coordinator",
                output_type="completed",
                payload={
                    "verification_status": "failed",
                    "commands": [
                        {"command": "run-test.sh", "status": "failed", "exit_code": 1},
                        {"command": "run-lint.sh", "status": "passed", "exit_code": 0},
                    ],
                },
            )

    def test_verifier_completed_output_with_failed_command_dict_materializes_failed_outcome_from_explicit_result(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30004VCMDDICTFAIL")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )

        updated_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name="verification-coordinator",
            output_type="completed",
            payload={
                "result": "failed",
                "commands": {
                    "run_test": {
                        "command": "bash scripts/run-test.sh IOS-30004VCMDDICTFAIL",
                        "status": "failed",
                        "exit_code": 1,
                        "phase": "build-for-testing",
                        "failure": "Compilation failed",
                    },
                    "run_lint": {
                        "command": "bash scripts/run-lint.sh IOS-30004VCMDDICTFAIL",
                        "status": "passed",
                        "exit_code": 0,
                    },
                    "run_build": {
                        "status": "not_run",
                        "reason": "per routed instructions",
                    },
                },
                "verification_report": "/tmp/final-verification.md",
                "code_modified": False,
            },
        )
        verification_outcome = (
            Path(self.temp_dir.name) / "IOS-30004VCMDDICTFAIL" / "spec" / "verification-outcome.json"
        )

        self.assertEqual("verification_failed", mapped_event.event_type)
        self.assertEqual("verification_correction_requested", followup_event.event_type)
        self.assertEqual("verification_correction_requested", updated_session.current_stage)
        self.assertEqual("implementer", updated_session.current_owner)
        self.assertTrue(verification_outcome.exists())
        outcome = json.loads(verification_outcome.read_text())
        self.assertEqual("failed", outcome["status"])
        self.assertEqual(3, len(outcome["commands"]))
        self.assertEqual("run_test", outcome["commands"][0]["name"])
        self.assertEqual("failed", outcome["commands"][0]["status"])

    def test_verifier_completed_output_with_failed_status_and_singular_failure_is_rejected_without_explicit_result(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30004VTOPFAIL")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )

        with self.assertRaisesRegex(
            IntakeError,
            "Verification output must include payload.result set to 'passed' or 'failed'",
        ):
            self.coordinator.handle_role_output(
                session_id=session.id,
                role_name="verification-coordinator",
                output_type="completed",
                payload={
                    "status": "failed",
                    "summary": "build-for-testing phase failed",
                    "failure": {
                        "phase": "build_for_testing",
                        "error": "invalid redeclaration of 'illCheck'",
                    },
                },
            )

    def test_verification_passed_completes_session(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30005")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={"summary": "all checks passed"},
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        events = self.event_repository.list_for_session(session.id)
        verification_report = Path(self.temp_dir.name) / "IOS-30005" / "spec" / "final-verification.md"
        verification_outcome = Path(self.temp_dir.name) / "IOS-30005" / "spec" / "verification-outcome.json"

        self.assertEqual("send_to_test_completed", updated_session.current_stage)
        self.assertIsNone(updated_session.current_owner)
        self.assertEqual("completed", updated_session.status.value)
        self.assertEqual("send_to_test_completed", followup_event.event_type)
        self.assertTrue(verification_report.exists())
        self.assertTrue(verification_outcome.exists())
        self.assertEqual("passed", json.loads(verification_outcome.read_text())["status"])
        self.assertIn("## Strategy", verification_report.read_text())
        self.assertIn("### Commands", verification_report.read_text())
        self.assertIn("PASS", verification_report.read_text())
        self.assertEqual(
            sorted(
                [
                    ("Initial implementation for IOS-30005", "completed"),
                    ("Verification for IOS-30005", "completed"),
                ]
            ),
            sorted((item.title, item.status.value) for item in work_items),
        )
        self.assertEqual(
            [
                "task_started",
                "task_prepared",
                "role_input_delivery_confirmed",
                "role_input_dispatched",
                "implementation_requested",
                "implementation_completed",
                "git_commit_completed",
                "role_input_delivery_confirmed",
                "role_input_dispatched",
                "verification_requested",
                "verification_passed",
                "task_completed",
                "mr_handoff_completed",
                "send_to_test_completed",
            ],
            [item.event_type for item in events],
        )

    def test_inconsistent_verification_passed_event_materializes_failed_outcome_and_routes_to_correction(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30005INCONSISTENT")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={
                "result": "failed",
                "summary": "build-for-testing phase failed",
                "failure": {
                    "phase": "build_for_testing",
                    "error": "invalid redeclaration of 'illCheck'",
                },
            },
        )
        verification_report = Path(self.temp_dir.name) / "IOS-30005INCONSISTENT" / "spec" / "final-verification.md"
        verification_outcome = Path(self.temp_dir.name) / "IOS-30005INCONSISTENT" / "spec" / "verification-outcome.json"

        self.assertEqual("verification_correction_requested", updated_session.current_stage)
        self.assertEqual("implementer", updated_session.current_owner)
        self.assertEqual("active", updated_session.status.value)
        self.assertEqual("verification_correction_requested", followup_event.event_type)
        self.assertTrue(verification_report.exists())
        self.assertTrue(verification_outcome.exists())
        self.assertEqual("failed", json.loads(verification_outcome.read_text())["status"])
        self.assertIn("FAIL", verification_report.read_text())

    def test_verification_passed_cleans_verification_tmp_after_completion(self) -> None:
        task_root = Path(self.temp_dir.name) / "IOS-30005TMPCLEAN"
        verification_root = task_root / "tmp" / "verification" / "ios"
        verification_root.mkdir(parents=True, exist_ok=True)
        (verification_root / "placeholder.txt").write_text("x")

        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30005TMPCLEAN")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={"summary": "all checks passed"},
        )

        self.assertEqual("completed", updated_session.status.value)
        self.assertEqual("send_to_test_completed", updated_session.current_stage)
        self.assertEqual("send_to_test_completed", followup_event.event_type)
        self.assertFalse((task_root / "tmp" / "verification").exists())

    def test_verification_passed_preserves_existing_final_verification_report(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30005EXISTING")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )
        verification_report = Path(self.temp_dir.name) / "IOS-30005EXISTING" / "spec" / "final-verification.md"
        verification_report.parent.mkdir(parents=True, exist_ok=True)
        verification_report.write_text(
            "# Final Verification: IOS-30005EXISTING\n\n"
            "## Result\nFAIL\n\n"
            "## Output: run-test.sh\n```text\nrich verifier output\n```\n"
        )

        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={"summary": "all checks passed"},
        )

        self.assertIn("rich verifier output", verification_report.read_text())

    def test_role_output_completed_moves_implementer_flow_forward(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30006")

        updated_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name="implementer",
            output_type="completed",
            payload={"summary": "done"},
        )
        events = self.event_repository.list_for_session(session.id)
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual("implementation_completed", mapped_event.event_type)
        self.assertEqual("verification_requested", followup_event.event_type)
        self.assertEqual("verification_requested", updated_session.current_stage)
        self.assertTrue(
            any(artifact.artifact_type == "role_output_json" for artifact in artifacts)
        )
        self.assertEqual(
            [
                "task_started",
                "task_prepared",
                "role_input_delivery_confirmed",
                "role_input_dispatched",
                "implementation_requested",
                "implementation_completed",
                "git_commit_completed",
                "role_input_delivery_confirmed",
                "role_input_dispatched",
                "verification_requested",
            ],
            [item.event_type for item in events],
        )

    def test_role_output_completed_moves_bug_analysis_forward(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30006BUG",
            workflow_profile="bug_full",
            policy={"test_policy": "enabled"},
        )
        self.coordinator.prepare_task_session("IOS-30006BUG")

        updated_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=BUG_FIXER_ROLE,
            output_type="completed",
            payload={"summary": "Root cause isolated"},
        )
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual("bug_analysis_completed", mapped_event.event_type)
        self.assertEqual("implementation_requested", followup_event.event_type)
        self.assertEqual("implementation_requested", updated_session.current_stage)
        self.assertEqual(BUG_FIXER_ROLE, updated_session.current_owner)
        self.assertEqual(
            [
                "task_started",
                "task_session_reused",
                "task_prepared",
                "role_input_delivery_confirmed",
                "role_input_dispatched",
                "bug_analysis_requested",
                "bug_analysis_completed",
                "role_input_delivery_confirmed",
                "role_input_dispatched",
                "implementation_requested",
            ],
            [item.event_type for item in events],
        )

    def test_role_output_completed_moves_story_flow_forward(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30006STORY",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30006STORY")
        proposal_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=PROPOSAL_CONTEXT_WORKER_ROLE,
            output_type="completed",
            payload={"summary": "Context prepared"},
        )

        self.assertEqual("proposal_context_completed", mapped_event.event_type)
        self.assertEqual("requirements_requested", followup_event.event_type)
        self.assertEqual("requirements_requested", proposal_session.current_stage)

        requirements_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=REQUIREMENTS_CLARIFIER_WORKER_ROLE,
            output_type="completed",
            payload={"summary": "Requirements prepared"},
        )

        self.assertEqual("requirements_completed", mapped_event.event_type)
        self.assertEqual("acceptance_criteria_requested", followup_event.event_type)
        self.assertEqual("acceptance_criteria_requested", requirements_session.current_stage)
        self.assertEqual("active", requirements_session.status.value)

        acceptance_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=ACCEPTANCE_CRITERIA_WORKER_ROLE,
            output_type="completed",
            payload={"summary": "Acceptance prepared"},
        )

        self.assertEqual("acceptance_criteria_completed", mapped_event.event_type)
        self.assertEqual("constraints_requested", followup_event.event_type)
        self.assertEqual("constraints_requested", acceptance_session.current_stage)
        self.assertEqual("active", acceptance_session.status.value)

        constraints_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=CONSTRAINTS_WORKER_ROLE,
            output_type="completed",
            payload={"summary": "Constraints prepared"},
        )

        self.assertEqual("constraints_completed", mapped_event.event_type)
        self.assertEqual("spec_verification_requested", followup_event.event_type)
        self.assertEqual("spec_verification_requested", constraints_session.current_stage)
        self.assertEqual("active", constraints_session.status.value)

        verifier_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=SPEC_VERIFIER_WORKER_ROLE,
            output_type="completed",
            payload={"summary": "Planning verified"},
        )

        self.assertEqual("spec_verification_completed", mapped_event.event_type)
        self.assertEqual("task_decomposition_requested", followup_event.event_type)
        self.assertEqual("task_decomposition_requested", verifier_session.current_stage)
        self.assertEqual("active", verifier_session.status.value)

        updated_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=TASK_DECOMPOSER_WORKER_ROLE,
            output_type="completed",
            payload=decomposition_payload("Decomposition prepared"),
        )
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual("task_decomposition_completed", mapped_event.event_type)
        self.assertIsNotNone(followup_event)
        event_types = [item.event_type for item in events]
        self.assertEqual("task_started", event_types[0])
        self.assertIn("proposal_context_completed", event_types)
        self.assertIn("requirements_completed", event_types)
        self.assertIn("acceptance_criteria_completed", event_types)
        self.assertIn("constraints_completed", event_types)
        self.assertIn("spec_verification_completed", event_types)
        self.assertIn("task_decomposition_requested", event_types)
        spec_root = Path(self.temp_dir.name) / "IOS-30006STORY" / "spec"
        self.assertTrue((spec_root / "proposal.md").is_file())
        self.assertTrue((spec_root / "requirements.md").is_file())
        self.assertTrue((spec_root / "acceptance_criteria.md").is_file())
        self.assertTrue((spec_root / "constraints.md").is_file())
        self.assertTrue((spec_root / "spec_verification.md").is_file())

    def test_story_planning_progression_reactivates_waiting_session_between_stages(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30006STORYWAIT",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30006STORYWAIT")

        self.session_repository.update_status(session.id, SessionStatus.WAITING_FOR_OPERATOR)
        proposal_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=PROPOSAL_CONTEXT_WORKER_ROLE,
            output_type="completed",
            payload={"summary": "Context prepared"},
        )
        self.assertEqual("proposal_context_completed", mapped_event.event_type)
        self.assertEqual("requirements_requested", followup_event.event_type)
        self.assertEqual("active", proposal_session.status.value)

        self.session_repository.update_status(session.id, SessionStatus.WAITING_FOR_OPERATOR)
        requirements_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=REQUIREMENTS_CLARIFIER_WORKER_ROLE,
            output_type="completed",
            payload={"summary": "Requirements prepared"},
        )
        self.assertEqual("requirements_completed", mapped_event.event_type)
        self.assertEqual("acceptance_criteria_requested", followup_event.event_type)
        self.assertEqual("active", requirements_session.status.value)

        self.session_repository.update_status(session.id, SessionStatus.WAITING_FOR_OPERATOR)
        acceptance_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=ACCEPTANCE_CRITERIA_WORKER_ROLE,
            output_type="completed",
            payload={"summary": "Acceptance prepared"},
        )
        self.assertEqual("acceptance_criteria_completed", mapped_event.event_type)
        self.assertEqual("constraints_requested", followup_event.event_type)
        self.assertEqual("active", acceptance_session.status.value)

        self.session_repository.update_status(session.id, SessionStatus.WAITING_FOR_OPERATOR)
        constraints_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=CONSTRAINTS_WORKER_ROLE,
            output_type="completed",
            payload={"summary": "Constraints prepared"},
        )
        self.assertEqual("constraints_completed", mapped_event.event_type)
        self.assertEqual("spec_verification_requested", followup_event.event_type)
        self.assertEqual("active", constraints_session.status.value)

        self.session_repository.update_status(session.id, SessionStatus.WAITING_FOR_OPERATOR)
        verifier_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=SPEC_VERIFIER_WORKER_ROLE,
            output_type="completed",
            payload={"summary": "Planning verified"},
        )
        self.assertEqual("spec_verification_completed", mapped_event.event_type)
        self.assertEqual("task_decomposition_requested", followup_event.event_type)
        self.assertEqual("active", verifier_session.status.value)

    def test_proposal_completion_preserves_existing_written_markdown(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30006PRESERVE",
            workflow_profile="story_full",
            policy={"requirements_clarification_mode": "autonomous"},
        )
        self.coordinator.prepare_task_session("IOS-30006PRESERVE")
        spec_root = Path(self.temp_dir.name) / "IOS-30006PRESERVE" / "spec"
        spec_root.mkdir(parents=True, exist_ok=True)
        proposal_path = spec_root / "proposal.md"
        rich_markdown = (
            "# Proposal\n\n"
            "## Problem\n\n"
            "Detailed grounded problem statement.\n\n"
            "## Proposed Approach\n\n"
            "Detailed implementation-shaping proposal.\n"
        )
        proposal_path.write_text(rich_markdown)

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={"summary": "compact summary only"},
        )

        self.assertEqual("requirements_requested", updated_session.current_stage)
        self.assertEqual("requirements_requested", followup_event.event_type)
        self.assertEqual(rich_markdown, proposal_path.read_text())

    def test_collect_role_output_records_runtime_output_artifact(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30007")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.session_backend.simulate_output(implementer_role.runtime_handle, "runtime line 1")
        self.session_backend.simulate_output(implementer_role.runtime_handle, "runtime line 2")

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual(session.id, updated_session.id)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual(2, chunk_count)
        self.assertTrue(any(artifact.artifact_type == "runtime_output" for artifact in artifacts))

    def test_poll_session_output_collects_chunks_for_multiple_roles(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30008")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        verification_role = self.role_repository.get_by_name(session.id, "verification-coordinator")
        self.session_backend.simulate_output(implementer_role.runtime_handle, "impl output")
        self.session_backend.simulate_output(verification_role.runtime_handle, "verify output")

        updated_session, event, role_count, chunk_count = self.coordinator.poll_session_output(
            session_id=session.id,
        )
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual(session.id, updated_session.id)
        self.assertIsNone(event)
        self.assertEqual(2, role_count)
        self.assertEqual(2, chunk_count)
        self.assertEqual(
            2,
            len([artifact for artifact in artifacts if artifact.artifact_type == "runtime_output"]),
        )

    def test_poll_session_output_consumes_result_json_from_role_workspace(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30008B")
        active_item = next(
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "implementation" and item.status.value == "assigned"
        )
        role_workspace = self.coordinator.role_workspace_manager.role_directory(  # type: ignore[union-attr]
            session.task_key,
            "implementer",
        )
        result_path = role_workspace / "RESULT.json"
        result_path.write_text(
            json.dumps(
                {
                    "output_type": "completed",
                    "payload": {"work_item_id": active_item.id, "summary": "done from file"},
                }
            )
        )

        updated_session, event, role_count, chunk_count = self.coordinator.poll_session_output(
            session_id=session.id,
        )
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual(session.id, updated_session.id)
        self.assertIsNone(event)
        self.assertEqual(2, role_count)
        self.assertEqual(1, chunk_count)
        self.assertEqual("verification_requested", updated_session.current_stage)
        self.assertFalse(result_path.exists())
        self.assertTrue(any(artifact.artifact_type == "role_result_json" for artifact in artifacts))

    def test_poll_session_output_consumes_result_json_with_raw_newline_in_string(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30008BRAW")
        active_item = next(
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "implementation" and item.status.value == "assigned"
        )
        role_workspace = self.coordinator.role_workspace_manager.role_directory(  # type: ignore[union-attr]
            session.task_key,
            "implementer",
        )
        result_path = role_workspace / "RESULT.json"
        result_path.write_text(
            '{\n'
            '  "output_type": "completed",\n'
            '  "payload": {\n'
            f'    "work_item_id": {active_item.id},\n'
            '    "summary": "done from file",\n'
            '    "notes": [\n'
            '      "Line one.\n'
            'Line two."\n'
            '    ]\n'
            '  }\n'
            '}\n'
        )

        updated_session, event, role_count, chunk_count = self.coordinator.poll_session_output(
            session_id=session.id,
        )
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual(session.id, updated_session.id)
        self.assertIsNone(event)
        self.assertEqual(2, role_count)
        self.assertEqual(1, chunk_count)
        self.assertEqual("verification_requested", updated_session.current_stage)
        self.assertFalse(result_path.exists())

    def test_poll_session_output_consumes_result_json_with_extra_trailing_brace(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30008BTAIL")
        active_item = next(
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "implementation" and item.status.value == "assigned"
        )
        role_workspace = self.coordinator.role_workspace_manager.role_directory(  # type: ignore[union-attr]
            session.task_key,
            "implementer",
        )
        result_path = role_workspace / "RESULT.json"
        result_path.write_text(
            '{"output_type":"completed","payload":'
            + json.dumps({"work_item_id": active_item.id, "summary": "done from file"})
            + "}}\n"
        )

        updated_session, event, role_count, chunk_count = self.coordinator.poll_session_output(
            session_id=session.id,
        )
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual(session.id, updated_session.id)
        self.assertIsNone(event)
        self.assertEqual(2, role_count)
        self.assertEqual(1, chunk_count)
        self.assertEqual("verification_requested", updated_session.current_stage)
        self.assertFalse(result_path.exists())
        self.assertTrue(any(artifact.artifact_type == "role_result_json" for artifact in artifacts))
        self.assertTrue(any(artifact.artifact_type == "role_result_json" for artifact in artifacts))

    def test_poll_session_output_consumes_task_root_result_json_for_active_role(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30008BROOT")
        active_item = next(
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "implementation" and item.status.value == "assigned"
        )
        task_root = Path(self.temp_dir.name) / session.task_key
        result_path = task_root / "RESULT.json"
        result_path.write_text(
            json.dumps(
                {
                    "output_type": "completed",
                    "payload": {
                        "work_item_id": active_item.id,
                        "summary": "done from task root",
                    },
                }
            )
        )

        updated_session, event, role_count, chunk_count = self.coordinator.poll_session_output(
            session_id=session.id,
        )
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual(session.id, updated_session.id)
        self.assertIsNone(event)
        self.assertEqual(2, role_count)
        self.assertEqual(1, chunk_count)
        self.assertEqual("verification_requested", updated_session.current_stage)
        self.assertEqual("verification-coordinator", updated_session.current_owner)
        self.assertFalse(result_path.exists())
        self.assertTrue(any(artifact.artifact_type == "role_result_json" for artifact in artifacts))

    def test_prepare_task_session_materializes_hydration_json_in_role_workspace(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30008C")
        role_workspace = self.coordinator.role_workspace_manager.role_directory(  # type: ignore[union-attr]
            session.task_key,
            "implementer",
        )
        hydration_path = role_workspace / "HYDRATION.json"

        self.assertTrue(hydration_path.is_file())
        hydration = json.loads(hydration_path.read_text())
        self.assertEqual("IOS-30008C", hydration["task_key"])
        self.assertEqual("implementation_requested", hydration["current_stage"])
        self.assertEqual("implementer", hydration["role_name"])
        self.assertNotIn("result_path", hydration)
        self.assertNotIn("result_writer_path", hydration)

    def test_runtime_state_summary_exposes_tmux_visibility_commands(self) -> None:
        tmux_backend = TmuxSessionBackend(mode="tmux", runtime_root=Path(self.temp_dir.name))
        coordinator = CoordinatorService(
            session_repository=self.session_repository,
            role_repository=self.role_repository,
            event_repository=self.event_repository,
            artifact_repository=self.artifact_repository,
            work_item_repository=self.work_item_repository,
            session_backend=tmux_backend,
            default_roles=DEFAULT_SESSION_ROLES,
            jira_adapter=FakeJiraAdapter(),
            snapshot_adapter=FakeSnapshotAdapter(Path(self.temp_dir.name)),
            gitlab_adapter=FakeGitLabAdapter(),
            artifacts_root=Path(self.temp_dir.name) / "artifacts-tmux-visibility",
            workdir_root=Path(self.temp_dir.name),
            event_bus=self.event_bus,
        )

        session, _, _ = coordinator.create_task_session(
            task_key=f"IOS-31000TMUX-{Path(self.temp_dir.name).name.upper()}",
            workflow_profile="oneshot",
            policy={
                "review_policy": "disabled",
                                "doc_harvest_policy": "disabled",
            },
        )

        summary = coordinator.get_runtime_state_summary(session.id)

        self.assertTrue(summary["available"])
        self.assertIn("tmux -S ", summary["tmux_attach_command"])
        self.assertTrue(str(summary["tmux_socket_path"]).endswith(".sock"))
        implementer = next(item for item in summary["roles"] if item["role_name"] == "implementer")
        self.assertEqual("live-idle", implementer["live_state"])
        self.assertFalse(implementer["is_current_owner"])
        self.assertIn("select-window", implementer["tmux_attach_command"])
        self.assertIn("capture-pane", implementer["tmux_capture_command"])
        verifier = next(item for item in summary["roles"] if item["role_name"] == "verification-coordinator")
        self.assertEqual("live-idle", verifier["live_state"])
        self.assertFalse(verifier["is_current_owner"])

        runtime_session = coordinator._runtime_session_handle_for_session(session)
        tmux_backend.stop_session(runtime_session)

    def test_runtime_state_summary_marks_dead_and_idle_roles(self) -> None:
        backend = AutoRecoveryRecordingBackend()
        self.session_backend = backend
        self.coordinator.session_backend = backend
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30004RUNTIMESTATE")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        verifier_role = self.role_repository.get_by_name(session.id, "verification-coordinator")
        assert implementer_role is not None
        assert verifier_role is not None
        assert implementer_role.runtime_handle is not None

        self.role_repository.update_runtime(
            verifier_role.id,
            runtime_backend=verifier_role.runtime_backend,
            runtime_handle="recording-IOS-30004RUNTIMESTATE:verification-coordinator:legacy",
            status=RoleStatus.RUNNING,
        )
        backend.role_alive["recording-IOS-30004RUNTIMESTATE:verification-coordinator:legacy"] = True
        backend.mark_dead(implementer_role.runtime_handle)

        summary = self.coordinator.get_runtime_state_summary(session.id)

        implementer = next(item for item in summary["roles"] if item["role_name"] == "implementer")
        verifier = next(item for item in summary["roles"] if item["role_name"] == "verification-coordinator")
        self.assertEqual("dead-stale", implementer["live_state"])
        self.assertTrue(implementer["is_current_owner"])
        self.assertEqual("live-idle", verifier["live_state"])
        self.assertFalse(verifier["is_current_owner"])

    def test_dispatch_records_transport_retry_event(self) -> None:
        backend = DispatchTraceRecordingBackend()
        self.session_backend = backend
        self.coordinator.session_backend = backend
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30004DISPATCHTRACE")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )

        events = self.event_repository.list_for_session(session.id)
        retry_event = [item for item in events if item.event_type == "role_input_delivery_retried"][-1]
        self.assertEqual("verification-coordinator", retry_event.payload["role_name"])
        self.assertEqual(1, retry_event.payload["retry_count"])
        self.assertEqual("retried", retry_event.payload["delivery_state"])

    def test_dispatch_records_pre_ready_buffer_as_stalled_delivery(self) -> None:
        backend = DispatchTraceRecordingBackend(delivery_state="buffered_pre_ready")
        self.session_backend = backend
        self.coordinator.session_backend = backend
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30004BUFFEREDDISPATCH")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )

        events = self.event_repository.list_for_session(session.id)
        stalled_event = [item for item in events if item.event_type == "role_input_delivery_stalled"][-1]
        dispatches = self.dispatch_repository.list_for_session(session.id)
        latest_dispatch = dispatches[-1]

        self.assertEqual("verification-coordinator", stalled_event.payload["role_name"])
        self.assertEqual("buffered_pre_ready", stalled_event.payload["delivery_state"])
        self.assertEqual("stalled", latest_dispatch.status.value)
        self.assertIn("not ready", latest_dispatch.error_text or "")

    def test_dispatch_records_transport_stall_event_on_send_failure(self) -> None:
        backend = DispatchTraceRecordingBackend()
        self.session_backend = backend
        self.coordinator.session_backend = backend
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30004DISPATCHSTALL")
        backend.fail_send = True

        with self.assertRaisesRegex(RuntimeError, "simulated send failure"):
            self.coordinator.handle_operator_event(
                session_id=session.id,
                event_type="implementation_completed",
                payload={"summary": "implementation done"},
            )

        events = self.event_repository.list_for_session(session.id)
        stalled_event = next(item for item in events if item.event_type == "role_input_delivery_stalled")
        self.assertEqual("verification-coordinator", stalled_event.payload["role_name"])
        self.assertIn("simulated send failure", stalled_event.payload["error"])
        self.assertIsNotNone(stalled_event.payload.get("dispatch_token"))

    def test_submit_result_returns_accepted_when_followup_dispatch_stalls_after_acceptance(self) -> None:
        backend = DispatchTraceRecordingBackend()
        self.session_backend = backend
        self.coordinator.session_backend = backend
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30004RESULTSTALL")
        work_item = next(
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "implementation"
        )
        backend.fail_send = True

        updated_session, event, mapped_event_type, followup_event_type, ignored = (
            self.coordinator.submit_role_result_document(
                document={
                    "output_type": "completed",
                    "payload": {
                        "work_item_id": work_item.id,
                        "summary": "implementation done",
                    },
                }
            )
        )
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual("implementation_completed", mapped_event_type)
        self.assertEqual("role_input_delivery_stalled", followup_event_type)
        self.assertFalse(ignored)
        self.assertEqual("verification_requested", updated_session.current_stage)
        self.assertTrue(any(item.event_type == "implementation_completed" for item in events))
        self.assertTrue(any(item.event_type == "role_input_delivery_stalled" for item in events))
        self.assertTrue(any(item.event_type == "role_result_followup_dispatch_failed" for item in events))

    def test_reconcile_session_dispatch_does_not_redispatch_stalled_token(self) -> None:
        backend = DispatchTraceRecordingBackend()
        self.session_backend = backend
        self.coordinator.session_backend = backend
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30004STALLTOKEN")
        backend.fail_send = True

        with self.assertRaisesRegex(RuntimeError, "simulated send failure"):
            self.coordinator.handle_operator_event(
                session_id=session.id,
                event_type="implementation_completed",
                payload={"summary": "implementation done"},
            )

        backend.fail_send = False
        verifier_role = self.role_repository.get_by_name(session.id, VERIFICATION_COORDINATOR_ROLE)
        self.assertIsNotNone(verifier_role)
        sent_before = list(self.session_backend.get_sent_inputs(verifier_role.runtime_handle))
        refreshed_session = self.session_repository.get_by_id(session.id)
        assert refreshed_session is not None

        reconciled = self.coordinator._reconcile_session_dispatch(refreshed_session)

        sent_after = self.session_backend.get_sent_inputs(verifier_role.runtime_handle)
        self.assertFalse(reconciled)
        self.assertEqual(sent_before, sent_after)

    def test_reconcile_session_dispatch_repairs_pre_ready_buffered_dispatch(self) -> None:
        backend = DispatchTraceRecordingBackend(delivery_state="buffered_pre_ready")
        self.session_backend = backend
        self.coordinator.session_backend = backend
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30004BUFFERREPAIR")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )
        verifier_role = self.role_repository.get_by_name(session.id, VERIFICATION_COORDINATOR_ROLE)
        self.assertIsNotNone(verifier_role)
        sent_before = list(self.session_backend.get_sent_inputs(verifier_role.runtime_handle))
        backend.delivery_state = "direct"
        refreshed_session = self.session_repository.get_by_id(session.id)
        assert refreshed_session is not None

        reconciled = self.coordinator._reconcile_session_dispatch(refreshed_session)

        dispatches = self.dispatch_repository.list_for_session(session.id)
        events = self.event_repository.list_for_session(session.id)
        sent_after = self.session_backend.get_sent_inputs(verifier_role.runtime_handle)

        self.assertTrue(reconciled)
        self.assertEqual("superseded", dispatches[-2].status.value)
        self.assertEqual("delivered", dispatches[-1].status.value)
        self.assertGreater(len(sent_after), len(sent_before))
        self.assertTrue(
            any(
                item.event_type == "role_input_dispatch_repair_requested"
                and item.payload.get("reason") == "launcher_dispatch_buffered_pre_ready"
                for item in events
            )
        )

    def test_reconcile_session_dispatch_waits_until_launcher_ready_for_pre_ready_buffer(self) -> None:
        backend = DispatchTraceRecordingBackend(delivery_state="buffered_pre_ready")
        backend.launcher_ready = False
        backend.launcher_role_ready = lambda role: backend.launcher_ready  # type: ignore[attr-defined]
        self.session_backend = backend
        self.coordinator.session_backend = backend
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30004BUFFERWAIT")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )
        verifier_role = self.role_repository.get_by_name(session.id, VERIFICATION_COORDINATOR_ROLE)
        self.assertIsNotNone(verifier_role)
        sent_before = list(self.session_backend.get_sent_inputs(verifier_role.runtime_handle))
        refreshed_session = self.session_repository.get_by_id(session.id)
        assert refreshed_session is not None

        reconciled = self.coordinator._reconcile_session_dispatch(refreshed_session)

        dispatches = self.dispatch_repository.list_for_session(session.id)
        sent_after = self.session_backend.get_sent_inputs(verifier_role.runtime_handle)

        self.assertFalse(reconciled)
        self.assertEqual("stalled", dispatches[-1].status.value)
        self.assertEqual(sent_before, sent_after)

    def test_poll_session_output_repairs_ready_pre_ready_buffered_dispatch(self) -> None:
        backend = DispatchTraceRecordingBackend(delivery_state="buffered_pre_ready")
        backend.launcher_role_ready = lambda role: True  # type: ignore[attr-defined]
        self.session_backend = backend
        self.coordinator.session_backend = backend
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30004BUFFERPOLL")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )
        verifier_role = self.role_repository.get_by_name(session.id, VERIFICATION_COORDINATOR_ROLE)
        self.assertIsNotNone(verifier_role)
        sent_before = list(self.session_backend.get_sent_inputs(verifier_role.runtime_handle))
        backend.delivery_state = "direct"

        _, event, _, chunk_count = self.coordinator.poll_session_output(session.id)

        dispatches = self.dispatch_repository.list_for_session(session.id)
        sent_after = self.session_backend.get_sent_inputs(verifier_role.runtime_handle)

        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual("session_dispatch_reconciled_from_poll", event.event_type)
        self.assertEqual(0, chunk_count)
        self.assertEqual("superseded", dispatches[-2].status.value)
        self.assertEqual("delivered", dispatches[-1].status.value)
        self.assertGreater(len(sent_after), len(sent_before))

    def test_reconcile_session_dispatch_repairs_delivered_launcher_dispatch_without_routed_work(
        self,
    ) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004MISSINGROUTED",
            workflow_profile="story_full",
            policy={"review_policy": "disabled"},
            role_config={
                "acceptance-criteria-worker": {
                    "runner": "claude",
                    "model": "sonnet",
                    "effort": "medium",
                }
            },
        )
        acceptance_role = self.role_repository.get_by_name(session.id, ACCEPTANCE_CRITERIA_WORKER_ROLE)
        assert acceptance_role is not None
        acceptance_role = self.role_repository.update_runtime(
            acceptance_role.id,
            runtime_backend="tmux",
            runtime_handle="sdd-IOS-30004MISSINGROUTED:acceptance-criteria-worker",
            status=RoleStatus.RUNNING,
        )
        work_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="acceptance_criteria",
            title=f"Acceptance criteria preparation for {session.task_key}",
            owner_role_id=acceptance_role.id,
            priority=101,
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="acceptance_criteria_requested",
            current_owner=ACCEPTANCE_CRITERIA_WORKER_ROLE,
        )
        self.dispatch_repository.create(
            session_id=session.id,
            role_id=acceptance_role.id,
            work_item_id=work_item.id,
            stage_name="acceptance_criteria_requested",
            dispatch_token="hv1-wi999",
            hydration_version=1,
            runtime_handle=acceptance_role.runtime_handle,
            status=DispatchStatus.DELIVERED,
        )
        workspace = self.coordinator.role_workspace_manager.ensure_role_workspace(  # type: ignore[union-attr]
            session.task_key,
            ACCEPTANCE_CRITERIA_WORKER_ROLE,
        )
        routed_path = workspace.directory / "ROUTED_WORK.md"
        if routed_path.exists():
            routed_path.unlink()

        reconciled = self.coordinator._reconcile_session_dispatch(session)

        dispatches = self.dispatch_repository.list_for_session(session.id)
        events = self.event_repository.list_for_session(session.id)
        sent_inputs = self.session_backend.get_sent_inputs(acceptance_role.runtime_handle)

        self.assertTrue(reconciled)
        self.assertEqual("superseded", dispatches[0].status.value)
        self.assertEqual("delivered", dispatches[-1].status.value)
        self.assertNotEqual("hv1-wi999", dispatches[-1].dispatch_token)
        self.assertTrue(sent_inputs)
        self.assertTrue(
            any(item.event_type == "role_input_dispatch_repair_requested" for item in events)
        )

    def test_collect_role_output_normalizes_structured_marker(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30009")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        active_item = next(
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "implementation" and item.status.value == "assigned"
        )
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            f'SDD_OUTPUT: {json.dumps({"output_type":"completed","payload":{"work_item_id":active_item.id,"summary":"done"}})}',
        )

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual("implementation_requested", updated_session.current_stage)
        self.assertTrue(any(item.event_type == "runtime_terminal_output_echo_ignored" for item in events))
        self.assertFalse(any(item.event_type == "implementation_completed" for item in events))

    def test_collect_role_output_normalizes_wrapped_structured_marker(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30009WRAP")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        active_item = next(
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "implementation" and item.status.value == "assigned"
        )
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            '\n'.join(
                [
                    f'• SDD_OUTPUT: {{"output_type":"completed","payload":{{"work_item_id":{active_item.id},"task_key":"IOS-ACCEPT-REAL-',
                    '  CODEX-TWO-ROUND-847B2H6Q","result":"Applied requested acceptance change",',
                    '  "changes":["repo/placeholder_change.txt"]}}',
                ]
            ),
        )

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual("implementation_requested", updated_session.current_stage)
        self.assertTrue(any(item.event_type == "runtime_terminal_output_echo_ignored" for item in events))
        self.assertFalse(any(item.event_type == "implementation_completed" for item in events))

    def test_collect_role_output_requests_missing_result_file_recreation_from_terminal_output(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30009RESULTRECREATE")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        active_item = next(
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "implementation" and item.status.value == "assigned"
        )
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            f'SDD_OUTPUT: {json.dumps({"output_type":"completed","payload":{"work_item_id":active_item.id,"summary":"done"}})}',
        )

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )
        events = self.event_repository.list_for_session(session.id)
        sent_inputs = self.session_backend.get_sent_inputs(implementer_role.runtime_handle)

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual("implementation_requested", updated_session.current_stage)
        self.assertTrue(any(item.event_type == "missing_result_file_recreation_requested" for item in events))
        self.assertTrue(sent_inputs)
        self.assertIn("Recreate RESULT.json exactly at", sent_inputs[-1])
        self.assertIn(f'"work_item_id": {active_item.id}', sent_inputs[-1])

    def test_collect_role_output_requests_missing_result_file_recreation_only_once(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30009RESULTRECREATEONCE")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        marker = 'SDD_OUTPUT: {"output_type":"completed","payload":{"work_item_id":123,"summary":"done"}}'
        self.session_backend.simulate_output(implementer_role.runtime_handle, marker)
        self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )
        sent_after_first = list(self.session_backend.get_sent_inputs(implementer_role.runtime_handle))

        self.session_backend.simulate_output(implementer_role.runtime_handle, marker)
        self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )
        sent_after_second = list(self.session_backend.get_sent_inputs(implementer_role.runtime_handle))

        self.assertEqual(len(sent_after_first), len(sent_after_second))

    def test_collect_role_output_does_not_request_missing_result_recreation_after_operator_reply(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30009RESULTRECREATECHAT",
            workflow_profile="story_full",
            policy={
                "requirements_clarification_mode": "ask-selectively",
            },
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="requirements_requested",
            current_owner=REQUIREMENTS_CLARIFIER_WORKER_ROLE,
        )
        session = self.session_repository.update_status(session.id, SessionStatus.WAITING_FOR_OPERATOR)
        role = self.role_repository.get_by_name(session.id, REQUIREMENTS_CLARIFIER_WORKER_ROLE)
        self.assertIsNotNone(role)
        self.work_item_repository.create(
            session_id=session.id,
            work_type="requirements",
            title="Requirements clarification for IOS-30009RESULTRECREATECHAT",
            owner_role_id=role.id,
            source_event_id=1,
            priority=10,
            status=WorkItemStatus.WAITING_FOR_OPERATOR,
        )
        self.coordinator._append_event(
            session_id=session.id,
            event_type="role_output_collected",
            producer_type="coordinator",
            payload={
                "role_name": REQUIREMENTS_CLARIFIER_WORKER_ROLE,
                "chunk_count": 1,
            },
        )
        self.coordinator.send_operator_runtime_input(
            session_id=session.id,
            text="Use option 1.",
        )
        sent_before_collect = list(self.session_backend.get_sent_inputs(role.runtime_handle))
        self.session_backend.simulate_output(
            role.runtime_handle,
            'SDD_OUTPUT: {"output_type":"failed","payload":{"work_item_id":123,"summary":"needs clarification"}}',
        )

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name=REQUIREMENTS_CLARIFIER_WORKER_ROLE,
        )
        sent_after_collect = self.session_backend.get_sent_inputs(role.runtime_handle)
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual("active", updated_session.status.value)
        self.assertEqual(sent_before_collect, sent_after_collect)
        self.assertFalse(
            any(item.event_type == "missing_result_file_recreation_requested" for item in events)
        )

    def test_reconcile_session_dispatch_skips_duplicate_redispatch_for_recent_dispatch(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30009REDISPATCH",
            workflow_profile="oneshot",
        )
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        assert implementer_role is not None
        work_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="implementation",
            title="Initial implementation for IOS-30009REDISPATCH",
            owner_role_id=implementer_role.id,
            status=WorkItemStatus.ASSIGNED,
        )
        active_session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="implementation_requested",
            current_owner=IMPLEMENTER_ROLE,
        )
        active_session = self.session_repository.update_status(session.id, SessionStatus.ACTIVE)

        self.coordinator._dispatch_role_work(
            session=active_session,
            role=implementer_role,
            work_item=work_item,
            stage_name="implementation_requested",
            instruction="Start implementation work for IOS-30009REDISPATCH.",
        )
        sent_before = list(self.session_backend.get_sent_inputs(implementer_role.runtime_handle))

        original_has_dispatch_event = self.coordinator._has_dispatch_event
        self.coordinator._has_dispatch_event = lambda *args, **kwargs: False  # type: ignore[method-assign]
        try:
            refreshed_session = self.session_repository.get_by_id(session.id)
            assert refreshed_session is not None
            reconciled = self.coordinator._reconcile_session_dispatch(refreshed_session)
        finally:
            self.coordinator._has_dispatch_event = original_has_dispatch_event  # type: ignore[method-assign]

        sent_after = self.session_backend.get_sent_inputs(implementer_role.runtime_handle)
        events = self.event_repository.list_for_session(session.id)

        self.assertFalse(reconciled)
        self.assertEqual(sent_before, sent_after)
        self.assertFalse(any(item.event_type == "session_dispatch_reconciled" for item in events))

    def test_reconcile_session_dispatch_skips_duplicate_redispatch_for_recent_dispatch_event(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30009REDISPATCHEVENT",
            workflow_profile="oneshot",
        )
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        assert implementer_role is not None
        work_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="implementation",
            title="Initial implementation for IOS-30009REDISPATCHEVENT",
            owner_role_id=implementer_role.id,
            status=WorkItemStatus.ASSIGNED,
        )
        active_session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="implementation_requested",
            current_owner=IMPLEMENTER_ROLE,
        )
        active_session = self.session_repository.update_status(session.id, SessionStatus.ACTIVE)

        self.coordinator._dispatch_role_work(
            session=active_session,
            role=implementer_role,
            work_item=work_item,
            stage_name="implementation_requested",
            instruction="Start implementation work for IOS-30009REDISPATCHEVENT.",
        )
        sent_before = list(self.session_backend.get_sent_inputs(implementer_role.runtime_handle))
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE roles SET updated_at = '2000-01-01 00:00:00' WHERE id = ?",
                (implementer_role.id,),
            )

        original_has_dispatch_event = self.coordinator._has_dispatch_event
        self.coordinator._has_dispatch_event = lambda *args, **kwargs: False  # type: ignore[method-assign]
        try:
            refreshed_session = self.session_repository.get_by_id(session.id)
            assert refreshed_session is not None
            reconciled = self.coordinator._reconcile_session_dispatch(refreshed_session)
        finally:
            self.coordinator._has_dispatch_event = original_has_dispatch_event  # type: ignore[method-assign]

        sent_after = self.session_backend.get_sent_inputs(implementer_role.runtime_handle)
        events = self.event_repository.list_for_session(session.id)

        self.assertFalse(reconciled)
        self.assertEqual(sent_before, sent_after)
        self.assertFalse(any(item.event_type == "session_dispatch_reconciled" for item in events))

    def test_dispatch_role_work_is_idempotent_for_active_same_target(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30009DISPATCHIDEMPOTENT",
            workflow_profile="oneshot",
        )
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        assert implementer_role is not None
        work_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="implementation",
            title="Initial implementation for IOS-30009DISPATCHIDEMPOTENT",
            owner_role_id=implementer_role.id,
            status=WorkItemStatus.ASSIGNED,
        )
        active_session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="implementation_requested",
            current_owner=IMPLEMENTER_ROLE,
        )
        active_session = self.session_repository.update_status(session.id, SessionStatus.ACTIVE)

        first_event = self.coordinator._dispatch_role_work(
            session=active_session,
            role=implementer_role,
            work_item=work_item,
            stage_name="implementation_requested",
            instruction="Start implementation work for IOS-30009DISPATCHIDEMPOTENT.",
        )
        sent_before = list(self.session_backend.get_sent_inputs(implementer_role.runtime_handle))

        second_event = self.coordinator._dispatch_role_work(
            session=active_session,
            role=implementer_role,
            work_item=work_item,
            stage_name="implementation_requested",
            instruction="Start implementation work for IOS-30009DISPATCHIDEMPOTENT.",
        )
        sent_after = self.session_backend.get_sent_inputs(implementer_role.runtime_handle)
        refreshed_role = self.role_repository.get_by_id(implementer_role.id)
        assert refreshed_role is not None
        dispatch_events = [
            event
            for event in self.event_repository.list_for_session(session.id)
            if event.event_type == "role_input_dispatched"
        ]

        self.assertEqual(first_event.id, second_event.id)
        self.assertEqual(sent_before, sent_after)
        self.assertEqual(1, len(dispatch_events))
        self.assertEqual(1, refreshed_role.last_hydration_version)

    def test_collect_role_output_preserves_spaces_in_wrapped_error_marker(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30009ERRWRAP")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            "\n".join(
                [
                    '• SDD_ERROR: {"summary":"Need one product decision before finalizing',
                    '  requirements","details":"The proposal leaves repeated enrollment behavior',
                    '  unresolved. Please confirm whether the new write-layer should suppress',
                    '  duplicate enrollment requests while the current cached entry is still valid,',
                    '  or always POST and let the backend handle',
                    '  duplicates.","needs_operator_input":true}',
                ]
            ),
        )

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )
        interactive = self.coordinator.get_interactive_state_summary(session.id)

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual("waiting_for_operator", updated_session.status.value)
        self.assertEqual(
            "The proposal leaves repeated enrollment behavior unresolved. "
            "Please confirm whether the new write-layer should suppress "
            "duplicate enrollment requests while the current cached entry is still valid, "
            "or always POST and let the backend handle duplicates.",
            interactive["details"],
        )

    def test_collect_role_output_escalates_malformed_error_marker(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30009ERRMALFORMED")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            '\n'.join(
                [
                    'SDD_ERROR: {"summary":"Verifier environment is broken",',
                    '  "details":"mise ERROR "tuist" could not exec process",',
                    '  "needs_operator_input":true}',
                ]
            ),
        )

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )
        events = self.event_repository.list_for_session(session.id)
        interactive = self.coordinator.get_interactive_state_summary(session.id)

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual("waiting_for_operator", updated_session.status.value)
        self.assertTrue(any(item.event_type == "role_runtime_error_reported" for item in events))
        self.assertTrue(any(item.event_type == "session_escalated_to_operator" for item in events))
        self.assertEqual("runtime emitted malformed SDD_ERROR marker", interactive["summary"])
        self.assertIn('"tuist"', interactive["details"])

    def test_collect_role_output_escalates_error_that_mentions_prior_work_item(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30009ERRMENTIONSOLDWI")
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        assert implementer_role is not None
        active_item = self.coordinator._find_active_work_item_for_role(session.id, implementer_role.id)
        assert active_item is not None
        prior_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="convention_review_correction",
            title=f"Prior convention review corrections for {session.task_key}",
            owner_role_id=implementer_role.id,
            status=WorkItemStatus.COMPLETED,
        )
        payload = {
            "summary": "Convention and requirements reviews conflict",
            "details": (
                f"The convention review work_item {prior_item.id} required removing the init side effect, "
                "but the current requirements review requires adding it back."
            ),
            "needs_operator_input": True,
        }
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            "SDD_ERROR: " + json.dumps(payload, sort_keys=True),
        )

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name=IMPLEMENTER_ROLE,
        )
        events = self.event_repository.list_for_session(session.id)
        interactive = self.coordinator.get_interactive_state_summary(session.id)

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual("waiting_for_operator", updated_session.status.value)
        self.assertEqual(WorkItemStatus.WAITING_FOR_OPERATOR, self.work_item_repository.get_by_id(active_item.id).status)
        self.assertTrue(any(item.event_type == "role_runtime_error_reported" for item in events))
        self.assertTrue(any(item.event_type == "session_escalated_to_operator" for item in events))
        self.assertFalse(any(item.event_type == "stale_role_output_ignored" for item in events))
        self.assertEqual(payload["summary"], interactive["summary"])

    def test_collect_role_output_ignores_replayed_error_after_accepted_result(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30009ERRREPLAY")
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        assert implementer_role is not None
        old_item = next(
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.owner_role_id == implementer_role.id and item.work_type == "implementation"
        )
        stale_payload = {
            "summary": "Documentation-review finding is based on stale code",
            "details": "The requested README change would document code that no longer exists.",
            "needs_operator_input": True,
        }
        self.coordinator._append_event(
            session_id=session.id,
            event_type="role_runtime_error_reported",
            producer_type="role",
            producer_id=IMPLEMENTER_ROLE,
            payload={
                "role_name": IMPLEMENTER_ROLE,
                "marker_type": "error",
                "current_stage": "documentation_review_correction_requested",
                **stale_payload,
            },
        )
        self.work_item_repository.update_status(old_item.id, WorkItemStatus.COMPLETED)
        self.coordinator._append_event(
            session_id=session.id,
            event_type="role_result_ingress_accepted",
            producer_type="coordinator",
            payload={
                "role_name": IMPLEMENTER_ROLE,
                "work_item_id": old_item.id,
                "current_stage": "documentation_review_correction_requested",
                "output_type": "completed",
            },
        )
        new_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="documentation_review_correction",
            title=f"Documentation review corrections for {session.task_key}",
            owner_role_id=implementer_role.id,
            status=WorkItemStatus.ASSIGNED,
        )
        self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="documentation_review_correction_requested",
            current_owner=IMPLEMENTER_ROLE,
        )
        self.session_repository.update_status(session.id, SessionStatus.ACTIVE)
        self.coordinator._append_event(
            session_id=session.id,
            event_type="role_input_dispatched",
            producer_type="coordinator",
            payload={
                "role_name": IMPLEMENTER_ROLE,
                "work_item_id": new_item.id,
                "stage_name": "documentation_review_correction_requested",
            },
        )
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            "SDD_ERROR: "
            + json.dumps(stale_payload, sort_keys=True),
        )

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name=IMPLEMENTER_ROLE,
        )
        events = self.event_repository.list_for_session(session.id)
        runtime_error_events = [item for item in events if item.event_type == "role_runtime_error_reported"]
        stale_events = [item for item in events if item.event_type == "stale_role_output_ignored"]

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual("active", updated_session.status.value)
        self.assertEqual(1, len(runtime_error_events))
        self.assertFalse(any(item.event_type == "session_escalated_to_operator" for item in events))
        self.assertTrue(stale_events)
        self.assertEqual(
            "replayed_runtime_error_after_accepted_result",
            stale_events[-1].payload.get("reason"),
        )
        self.assertEqual(new_item.id, stale_events[-1].payload.get("expected_work_item_id"))

    def test_collect_role_output_ignores_replayed_error_from_prior_dispatch(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30009ERRPRIOR")
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        assert implementer_role is not None
        old_item = self.coordinator._find_active_work_item_for_role(session.id, implementer_role.id)
        assert old_item is not None
        stale_payload = {
            "summary": "Convention finding pass-09 is a false positive",
            "details": "The operator already rejected this finding for the SDK overloads.",
            "needs_operator_input": True,
        }
        self.coordinator._append_event(
            session_id=session.id,
            event_type="role_runtime_error_reported",
            producer_type="role",
            producer_id=IMPLEMENTER_ROLE,
            payload={
                "role_name": IMPLEMENTER_ROLE,
                "marker_type": "error",
                "current_stage": "convention_review_correction_requested",
                **stale_payload,
            },
        )
        self.work_item_repository.update_status(old_item.id, WorkItemStatus.COMPLETED)
        new_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="requirements_review_correction",
            title=f"Requirements review corrections for {session.task_key}",
            owner_role_id=implementer_role.id,
            status=WorkItemStatus.ASSIGNED,
        )
        self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="requirements_review_correction_requested",
            current_owner=IMPLEMENTER_ROLE,
        )
        self.session_repository.update_status(session.id, SessionStatus.ACTIVE)
        self.coordinator._append_event(
            session_id=session.id,
            event_type="role_input_dispatched",
            producer_type="coordinator",
            payload={
                "role_name": IMPLEMENTER_ROLE,
                "work_item_id": new_item.id,
                "stage_name": "requirements_review_correction_requested",
            },
        )
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            "SDD_ERROR: " + json.dumps(stale_payload, sort_keys=True),
        )

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name=IMPLEMENTER_ROLE,
        )
        events = self.event_repository.list_for_session(session.id)
        stale_events = [item for item in events if item.event_type == "stale_role_output_ignored"]

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual(SessionStatus.ACTIVE, updated_session.status)
        self.assertEqual(IMPLEMENTER_ROLE, updated_session.current_owner)
        self.assertFalse(any(item.event_type == "session_escalated_to_operator" for item in events))
        self.assertTrue(stale_events)
        self.assertEqual(
            "replayed_runtime_error_from_prior_dispatch",
            stale_events[-1].payload.get("reason"),
        )
        self.assertEqual(new_item.id, stale_events[-1].payload.get("expected_work_item_id"))

    def test_collect_role_output_ignores_replayed_error_after_result_acceptance_without_active_item(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30009ERRAFTERRESULT")
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        assert implementer_role is not None
        active_item = self.coordinator._find_active_work_item_for_role(session.id, implementer_role.id)
        assert active_item is not None
        stale_payload = {
            "summary": "Convention finding pass-09 is a false positive",
            "details": "The operator already rejected this finding for the SDK overloads.",
            "needs_operator_input": True,
        }
        self.coordinator._append_event(
            session_id=session.id,
            event_type="role_runtime_error_reported",
            producer_type="role",
            producer_id=IMPLEMENTER_ROLE,
            payload={
                "role_name": IMPLEMENTER_ROLE,
                "marker_type": "error",
                "current_stage": "convention_review_correction_requested",
                **stale_payload,
            },
        )
        self.work_item_repository.update_status(active_item.id, WorkItemStatus.COMPLETED)
        self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="convention_review_requested",
            current_owner=CONVENTION_REVIEWER_ROLE,
        )
        self.session_repository.update_status(session.id, SessionStatus.ACTIVE)
        self.coordinator._append_event(
            session_id=session.id,
            event_type="role_result_ingress_accepted",
            producer_type="coordinator",
            payload={
                "role_name": IMPLEMENTER_ROLE,
                "work_item_id": active_item.id,
                "current_stage": "requirements_review_correction_requested",
                "output_type": "completed",
            },
        )
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            "SDD_ERROR: " + json.dumps(stale_payload, sort_keys=True),
        )

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name=IMPLEMENTER_ROLE,
        )
        events = self.event_repository.list_for_session(session.id)
        stale_events = [item for item in events if item.event_type == "stale_role_output_ignored"]

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual(SessionStatus.ACTIVE, updated_session.status)
        self.assertEqual(CONVENTION_REVIEWER_ROLE, updated_session.current_owner)
        self.assertFalse(any(item.event_type == "session_escalated_to_operator" for item in events))
        self.assertTrue(stale_events)
        self.assertEqual(
            "replayed_runtime_error_after_role_result_acceptance",
            stale_events[-1].payload.get("reason"),
        )
        self.assertEqual(active_item.id, stale_events[-1].payload.get("accepted_work_item_id"))

    def test_collect_role_output_ignores_replayed_error_after_operator_reply(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30009ERRREPLY")
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        assert implementer_role is not None
        active_item = self.coordinator._find_active_work_item_for_role(session.id, implementer_role.id)
        assert active_item is not None
        payload = {
            "summary": "Need one operator decision",
            "details": "Choose the replay ownership model before continuing.",
            "needs_operator_input": True,
        }
        marker = "SDD_ERROR: " + json.dumps(payload, sort_keys=True)
        self.session_backend.simulate_output(implementer_role.runtime_handle, marker)
        waiting_session, _, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name=IMPLEMENTER_ROLE,
        )
        self.assertEqual(1, chunk_count)
        self.assertEqual(SessionStatus.WAITING_FOR_OPERATOR, waiting_session.status)

        resumed_session, _ = self.coordinator.send_operator_runtime_input(
            session_id=session.id,
            text="Use the service-owned model and continue.",
        )
        self.assertEqual(SessionStatus.ACTIVE, resumed_session.status)

        self.session_backend.simulate_output(implementer_role.runtime_handle, marker)
        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name=IMPLEMENTER_ROLE,
        )
        events = self.event_repository.list_for_session(session.id)
        stale_events = [item for item in events if item.event_type == "stale_role_output_ignored"]
        escalation_events = [
            item
            for item in events
            if item.event_type == "session_escalated_to_operator"
        ]

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual(SessionStatus.ACTIVE, updated_session.status)
        self.assertEqual(IMPLEMENTER_ROLE, updated_session.current_owner)
        self.assertEqual(1, len(escalation_events))
        self.assertTrue(stale_events)
        self.assertEqual(
            "replayed_runtime_error_after_operator_reply",
            stale_events[-1].payload.get("reason"),
        )
        self.assertEqual(active_item.id, stale_events[-1].payload.get("expected_work_item_id"))

    def test_interactive_state_hides_replayed_error_from_prior_dispatch(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30009ERRPRIORUI")
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        assert implementer_role is not None
        old_item = self.coordinator._find_active_work_item_for_role(session.id, implementer_role.id)
        assert old_item is not None
        stale_payload = {
            "summary": "Convention finding pass-09 is a false positive",
            "details": "The operator already rejected this finding for the SDK overloads.",
            "needs_operator_input": True,
        }
        self.coordinator._append_event(
            session_id=session.id,
            event_type="role_runtime_error_reported",
            producer_type="role",
            producer_id=IMPLEMENTER_ROLE,
            payload={
                "role_name": IMPLEMENTER_ROLE,
                "marker_type": "error",
                "current_stage": "convention_review_correction_requested",
                **stale_payload,
            },
        )
        self.work_item_repository.update_status(old_item.id, WorkItemStatus.COMPLETED)
        new_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="requirements_review_correction",
            title=f"Requirements review corrections for {session.task_key}",
            owner_role_id=implementer_role.id,
            status=WorkItemStatus.WAITING_FOR_OPERATOR,
        )
        self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="requirements_review_correction_requested",
            current_owner=None,
        )
        self.session_repository.update_status(session.id, SessionStatus.WAITING_FOR_OPERATOR)
        self.coordinator._append_event(
            session_id=session.id,
            event_type="role_input_dispatched",
            producer_type="coordinator",
            payload={
                "role_name": IMPLEMENTER_ROLE,
                "work_item_id": new_item.id,
                "stage_name": "requirements_review_correction_requested",
            },
        )
        self.coordinator._append_event(
            session_id=session.id,
            event_type="session_escalated_to_operator",
            producer_type="coordinator",
            payload={
                "role_name": IMPLEMENTER_ROLE,
                "current_stage": "requirements_review_correction_requested",
                "reason": "runtime_error",
                **stale_payload,
            },
        )

        summary = self.coordinator.get_interactive_state_summary(session.id)

        self.assertFalse(summary["available"])
        self.assertFalse(summary["needs_operator_input"])

    def test_collect_role_output_ignores_stale_runtime_error_token_for_previous_work_item(
        self,
    ) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30009ERRTOKEN")
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        assert implementer_role is not None
        old_item = next(
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.owner_role_id == implementer_role.id and item.work_type == "implementation"
        )
        self.work_item_repository.update_status(old_item.id, WorkItemStatus.COMPLETED)
        new_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="documentation_review_correction",
            title=f"Documentation review corrections for {session.task_key}",
            owner_role_id=implementer_role.id,
            status=WorkItemStatus.ASSIGNED,
        )
        self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="documentation_review_correction_requested",
            current_owner=IMPLEMENTER_ROLE,
        )
        self.session_repository.update_status(session.id, SessionStatus.ACTIVE)
        payload = {
            "summary": "Result submission helper did not complete successfully",
            "details": "write-result.sh exited non-zero after interruption.",
            "needs_operator_input": True,
            "token": f"hv2-wi{old_item.id}",
        }
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            "SDD_ERROR: " + json.dumps(payload, sort_keys=True),
        )

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name=IMPLEMENTER_ROLE,
        )
        events = self.event_repository.list_for_session(session.id)
        stale_events = [item for item in events if item.event_type == "stale_role_output_ignored"]

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual("active", updated_session.status.value)
        self.assertEqual(IMPLEMENTER_ROLE, updated_session.current_owner)
        self.assertEqual(WorkItemStatus.ASSIGNED, self.work_item_repository.get_by_id(new_item.id).status)
        self.assertFalse(any(item.event_type == "role_runtime_error_reported" for item in events))
        self.assertFalse(any(item.event_type == "session_escalated_to_operator" for item in events))
        self.assertTrue(stale_events)
        self.assertEqual("address_mismatch", stale_events[-1].payload.get("reason"))
        self.assertEqual(new_item.id, stale_events[-1].payload.get("expected_work_item_id"))
        self.assertEqual(old_item.id, stale_events[-1].payload.get("payload_work_item_id"))

    def test_collect_role_output_ignores_incomplete_error_marker_live_capture(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30009ERRLIVEPARTIAL")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            "\n".join(
                [
                    'SDD_ERROR: {',
                    '  "summary": "operator decision needed",',
                    "",
                    "---------- implementer:IOS-30009ERRLIVEPARTIAL --",
                    "> ",
                    "[Opus 4.8] 33% | auto mode on (shift+tab to cycle)",
                ]
            ),
        )

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )
        events = self.event_repository.list_for_session(session.id)
        interactive = self.coordinator.get_interactive_state_summary(session.id)

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual("active", updated_session.status.value)
        self.assertFalse(any(item.event_type == "role_runtime_error_reported" for item in events))
        self.assertFalse(any(item.event_type == "session_escalated_to_operator" for item in events))
        self.assertFalse(interactive["available"])

    def test_collect_role_output_trims_live_capture_noise_after_error_json(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30009ERRLIVETAIL")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            "\n".join(
                [
                    'SDD_ERROR: {',
                    '  "summary": "operator decision needed",',
                    '  "details": "first line',
                    'second line",',
                    '  "needs_operator_input": true',
                    '}',
                    "",
                    "✻ Baked for 3m 21s",
                    "> previous operator reply",
                    "[Opus 4.8] 33% | auto mode on (shift+tab to cycle)",
                ]
            ),
        )

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )
        interactive = self.coordinator.get_interactive_state_summary(session.id)

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual("waiting_for_operator", updated_session.status.value)
        self.assertEqual("operator decision needed", interactive["summary"])
        self.assertEqual("first line second line", interactive["details"])

    def test_collect_role_output_escalates_malformed_error_before_live_capture_noise(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30009ERRMALFORMEDTAIL")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            "\n".join(
                [
                    'SDD_ERROR: {"summary": "Verification build is locked",',
                    '  "details": "xcodebuild failed: accessing build database',
                    '  ".../XCBuildData/build.db": database is locked",',
                    '  "needs_operator_input": true}',
                    "",
                    "✻ Crunched for 2m 6s",
                    "──────────────── implementer:IOS-30009ERRMALFORMEDTAIL ────────────────",
                    "❯ ",
                    "[Opus 4.8] 55% | auto mode on (shift+tab to cycle)",
                ]
            ),
        )

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )
        events = self.event_repository.list_for_session(session.id)
        interactive = self.coordinator.get_interactive_state_summary(session.id)

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual("waiting_for_operator", updated_session.status.value)
        self.assertTrue(any(item.event_type == "role_runtime_error_reported" for item in events))
        self.assertTrue(any(item.event_type == "session_escalated_to_operator" for item in events))
        self.assertEqual("runtime emitted malformed SDD_ERROR marker", interactive["summary"])
        self.assertIn("build.db", interactive["details"])
        self.assertNotIn("auto mode on", interactive["details"])

    def test_collect_role_output_consumes_result_json_from_role_workspace(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30009B")
        active_item = next(
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "implementation" and item.status.value == "assigned"
        )
        role_workspace = self.coordinator.role_workspace_manager.role_directory(  # type: ignore[union-attr]
            session.task_key,
            "implementer",
        )
        result_path = role_workspace / "RESULT.json"
        result_path.write_text(
            json.dumps(
                {
                    "output_type": "completed",
                    "payload": {"work_item_id": active_item.id, "summary": "done from file"},
                }
            )
        )

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )
        events = self.event_repository.list_for_session(session.id)
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual("verification_requested", updated_session.current_stage)
        self.assertFalse(result_path.exists())
        self.assertTrue(any(item.event_type == "implementation_completed" for item in events))
        self.assertTrue(any(item.artifact_type == "role_result_json" for item in artifacts))

    def test_collect_role_output_consumes_truncated_result_json_from_role_workspace(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30009BTRUNC")
        active_item = next(
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "implementation" and item.status.value == "assigned"
        )
        role_workspace = self.coordinator.role_workspace_manager.role_directory(  # type: ignore[union-attr]
            session.task_key,
            "implementer",
        )
        result_path = role_workspace / "RESULT.json"
        result_path.write_text(
            '{"output_type":"completed","payload":{"work_item_id":'
            + str(active_item.id)
            + ',"summary":"done from file","changes":["repo/placeholder_change.txt"]}',
            encoding="utf-8",
        )

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )
        events = self.event_repository.list_for_session(session.id)
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual("verification_requested", updated_session.current_stage)
        self.assertFalse(result_path.exists())
        self.assertTrue(any(item.event_type == "implementation_completed" for item in events))
        self.assertTrue(any(item.artifact_type == "role_result_json" for item in artifacts))

    def test_collect_role_output_ignores_stale_verifier_result_during_verification_correction(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30009C")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_failed",
            payload={"summary": "verification failed", "failures": ["lint"]},
        )
        verifier_workspace = self.coordinator.role_workspace_manager.role_directory(  # type: ignore[union-attr]
            session.task_key,
            "verification-coordinator",
        )
        result_path = verifier_workspace / "RESULT.json"
        result_path.write_text(
            json.dumps(
                {
                    "output_type": "completed",
                    "payload": {"summary": "late stale verifier result"},
                }
            )
        )

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="verification-coordinator",
        )
        events = self.event_repository.list_for_session(session.id)
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual("verification_correction_requested", updated_session.current_stage)
        self.assertEqual("implementer", updated_session.current_owner)
        self.assertFalse(result_path.exists())
        self.assertTrue(any(item.event_type == "stale_role_output_ignored" for item in events))
        self.assertFalse(any(item.event_type == "verification_passed" for item in events))
        self.assertTrue(any(item.artifact_type == "role_result_json" for item in artifacts))

    def test_collect_role_output_ignores_stale_subtask_implementer_result_when_next_subtask_is_unassigned(
        self,
    ) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30009ESUB",
            workflow_profile="story_full",
            policy={"review_policy": "disabled"},
        )
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        assert implementer_role is not None
        first_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="subtask_implementation",
            title="Subtask implementation for IOS-30090: First chunk",
            owner_role_id=implementer_role.id,
            priority=100,
        )
        self.work_item_repository.update_status(first_item.id, WorkItemStatus.COMPLETED)
        stale_session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="subtask_implementation_requested",
            current_owner=IMPLEMENTER_ROLE,
        )
        self.session_repository.update_status(stale_session.id, SessionStatus.ACTIVE)
        result_path = self.coordinator.role_workspace_manager.role_directory(  # type: ignore[union-attr]
            session.task_key,
            IMPLEMENTER_ROLE,
        ) / "RESULT.json"
        result_path.write_text(
            json.dumps(
                {
                    "output_type": "completed",
                    "payload": {"summary": "late stale subtask implementer result"},
                }
            )
        )

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name=IMPLEMENTER_ROLE,
        )
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual("subtask_implementation_requested", updated_session.current_stage)
        self.assertTrue(any(item.event_type == "stale_role_output_ignored" for item in events))

    def test_collect_role_output_ignores_stale_subtask_implementer_result_for_assigned_but_undispatched_next_subtask(
        self,
    ) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30009ESUB2",
            workflow_profile="story_full",
            policy={"review_policy": "disabled"},
        )
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        assert implementer_role is not None
        first_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="subtask_implementation",
            title="Subtask implementation for IOS-30092: First chunk",
            owner_role_id=implementer_role.id,
            priority=100,
        )
        second_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="subtask_implementation",
            title="Subtask implementation for IOS-30093: Second chunk",
            owner_role_id=None,
            priority=99,
            status=WorkItemStatus.UNASSIGNED,
        )
        self.work_item_repository.update_status(first_item.id, WorkItemStatus.COMPLETED)
        self.work_item_repository.update_assignment(
            second_item.id,
            owner_role_id=first_item.owner_role_id,
            status=WorkItemStatus.ASSIGNED,
        )
        stale_session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="subtask_implementation_requested",
            current_owner=IMPLEMENTER_ROLE,
        )
        self.session_repository.update_status(stale_session.id, SessionStatus.ACTIVE)
        result_path = self.coordinator.role_workspace_manager.role_directory(  # type: ignore[union-attr]
            session.task_key,
            IMPLEMENTER_ROLE,
        ) / "RESULT.json"
        result_path.write_text(
            json.dumps(
                {
                    "output_type": "completed",
                    "payload": {"summary": "late stale subtask implementer result"},
                }
            )
        )

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name=IMPLEMENTER_ROLE,
        )
        events = self.event_repository.list_for_session(session.id)
        refreshed_items = self.work_item_repository.list_for_session(session.id)
        refreshed_second_item = next(item for item in refreshed_items if item.id == second_item.id)

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual("subtask_implementation_requested", updated_session.current_stage)
        self.assertEqual("assigned", refreshed_second_item.status.value)
        self.assertFalse(any(item.event_type == "subtask_completed" for item in events))
        self.assertTrue(any(item.event_type == "stale_role_output_ignored" for item in events))

    def test_find_active_work_item_for_role_prefers_most_recent_assigned_item(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30009ERECENT",
            workflow_profile="story_full",
            policy={"review_policy": "disabled"},
        )
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        assert implementer_role is not None
        older = self.work_item_repository.create(
            session_id=session.id,
            work_type="subtask_implementation",
            title="Subtask implementation for IOS-30901: Older duplicate",
            owner_role_id=implementer_role.id,
            priority=100,
        )
        newer = self.work_item_repository.create(
            session_id=session.id,
            work_type="subtask_implementation",
            title="Subtask implementation for IOS-30902: Newer assignment",
            owner_role_id=implementer_role.id,
            priority=100,
        )

        active = self.coordinator._find_active_work_item_for_role(session.id, implementer_role.id)

        self.assertIsNotNone(active)
        self.assertEqual(newer.id, active.id)
        self.assertNotEqual(older.id, active.id)

    def test_collect_role_output_ignores_subtask_completion_with_mismatched_address(
        self,
    ) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30009ESUB3",
            workflow_profile="story_full",
            policy={"review_policy": "disabled"},
        )
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        assert implementer_role is not None
        active_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="subtask_implementation",
            title="Subtask implementation for IOS-30094: First chunk",
            owner_role_id=implementer_role.id,
            priority=100,
        )
        active_session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="subtask_implementation_requested",
            current_owner=IMPLEMENTER_ROLE,
        )
        self.session_repository.update_status(active_session.id, SessionStatus.ACTIVE)
        self.coordinator._append_event(
            session_id=session.id,
            event_type="role_input_dispatched",
            producer_type="coordinator",
            payload={
                "role_name": IMPLEMENTER_ROLE,
                "work_item_id": active_item.id,
                "stage_name": "subtask_implementation_requested",
                "hydration_version": 1,
                "prompt_mode": "live_continuation",
            },
        )
        result_path = self.coordinator.role_workspace_manager.role_directory(  # type: ignore[union-attr]
            session.task_key,
            IMPLEMENTER_ROLE,
        ) / "RESULT.json"
        result_path.write_text(
            json.dumps(
                {
                    "output_type": "completed",
                    "payload": {
                        "work_item_id": active_item.id + 1,
                        "subtask_key": "IOS-30095",
                        "summary": "mismatched addressed subtask result",
                    },
                }
            )
        )

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name=IMPLEMENTER_ROLE,
        )
        events = self.event_repository.list_for_session(session.id)
        refreshed_item = self.work_item_repository.get_by_id(active_item.id)

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual("subtask_implementation_requested", updated_session.current_stage)
        self.assertEqual("assigned", refreshed_item.status.value)
        self.assertFalse(any(item.event_type == "subtask_completed" for item in events))
        stale_events = [item for item in events if item.event_type == "stale_role_output_ignored"]
        self.assertTrue(stale_events)
        self.assertEqual("address_mismatch", stale_events[-1].payload["reason"])

    def test_collect_role_output_ignores_stale_subtask_runtime_error_with_previous_subtask_key(
        self,
    ) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30009ESUBERR",
            workflow_profile="story_full",
            policy={"review_policy": "disabled"},
        )
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        assert implementer_role is not None
        previous_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="subtask_implementation",
            title="Subtask implementation for IOS-30098: Previous chunk",
            owner_role_id=implementer_role.id,
            priority=100,
        )
        active_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="subtask_implementation",
            title="Subtask implementation for IOS-30099: Current chunk",
            owner_role_id=implementer_role.id,
            priority=99,
            status=WorkItemStatus.ASSIGNED,
        )
        self.work_item_repository.update_status(previous_item.id, WorkItemStatus.COMPLETED)
        active_session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="subtask_implementation_requested",
            current_owner=IMPLEMENTER_ROLE,
        )
        self.session_repository.update_status(active_session.id, SessionStatus.ACTIVE)
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            (
                "SDD_ERROR: "
                '{"summary":"IOS-30098 blocked on operator input",'
                '"details":"IOS-30009ESUBERR moved on, but IOS-30098 still has a stale blocker tail."}'
            ),
        )

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name=IMPLEMENTER_ROLE,
        )
        events = self.event_repository.list_for_session(session.id)
        refreshed_active = self.work_item_repository.get_by_id(active_item.id)

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual(SessionStatus.ACTIVE, updated_session.status)
        self.assertEqual("subtask_implementation_requested", updated_session.current_stage)
        self.assertEqual(IMPLEMENTER_ROLE, updated_session.current_owner)
        self.assertEqual(WorkItemStatus.ASSIGNED, refreshed_active.status)
        self.assertFalse(any(item.event_type == "role_runtime_error_reported" for item in events))
        self.assertFalse(any(item.event_type == "session_escalated_to_operator" for item in events))
        stale_events = [item for item in events if item.event_type == "stale_role_output_ignored"]
        self.assertTrue(stale_events)
        self.assertEqual("subtask_key_mismatch", stale_events[-1].payload["reason"])
        self.assertEqual("IOS-30099", stale_events[-1].payload["expected_subtask_key"])
        self.assertEqual(["IOS-30098"], stale_events[-1].payload["payload_subtask_keys"])

    def test_collect_role_output_accepts_subtask_completion_with_matching_address(
        self,
    ) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30009ESUB4",
            workflow_profile="story_full",
            policy={"review_policy": "disabled"},
        )
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        assert implementer_role is not None
        active_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="subtask_implementation",
            title="Subtask implementation for IOS-30096: First chunk",
            owner_role_id=implementer_role.id,
            priority=100,
        )
        next_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="subtask_implementation",
            title="Subtask implementation for IOS-30097: Second chunk",
            owner_role_id=None,
            priority=99,
            status=WorkItemStatus.UNASSIGNED,
        )
        active_session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="subtask_implementation_requested",
            current_owner=IMPLEMENTER_ROLE,
        )
        self.session_repository.update_status(active_session.id, SessionStatus.ACTIVE)
        self.coordinator._append_event(
            session_id=session.id,
            event_type="role_input_dispatched",
            producer_type="coordinator",
            payload={
                "role_name": IMPLEMENTER_ROLE,
                "work_item_id": active_item.id,
                "stage_name": "subtask_implementation_requested",
                "hydration_version": 1,
                "prompt_mode": "live_continuation",
            },
        )
        result_path = self.coordinator.role_workspace_manager.role_directory(  # type: ignore[union-attr]
            session.task_key,
            IMPLEMENTER_ROLE,
        ) / "RESULT.json"
        result_path.write_text(
            json.dumps(
                {
                    "output_type": "completed",
                    "payload": {
                        "work_item_id": active_item.id,
                        "subtask_key": "IOS-30096",
                        "summary": "matched addressed subtask result",
                    },
                }
            )
        )

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name=IMPLEMENTER_ROLE,
        )
        events = self.event_repository.list_for_session(session.id)
        refreshed_active = self.work_item_repository.get_by_id(active_item.id)
        refreshed_next = self.work_item_repository.get_by_id(next_item.id)

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual("subtask_implementation_requested", updated_session.current_stage)
        self.assertEqual("completed", refreshed_active.status.value)
        self.assertEqual("assigned", refreshed_next.status.value)
        self.assertTrue(any(item.event_type == "subtask_completed" for item in events))
        self.assertTrue(any(item.event_type == "subtask_transition_completed" for item in events))
        self.assertEqual(["IOS-30096"], self.jira_adapter.completed_subtasks)
        self.assertEqual([("IOS-30009ESUB4", "subtask IOS-30096")], self.gitlab_adapter.commit_requests)

    def test_collect_role_output_accepts_retry_subtask_completion_with_matching_address(
        self,
    ) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30009ESUBRETRY",
            workflow_profile="story_full",
            policy={"review_policy": "disabled"},
        )
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        assert implementer_role is not None
        active_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="subtask_implementation",
            title="Retry: Subtask implementation for IOS-30096R: First chunk",
            owner_role_id=implementer_role.id,
            priority=100,
        )
        active_session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="subtask_implementation_requested",
            current_owner=IMPLEMENTER_ROLE,
        )
        self.session_repository.update_status(active_session.id, SessionStatus.ACTIVE)
        self.coordinator._append_event(
            session_id=session.id,
            event_type="role_input_dispatched",
            producer_type="coordinator",
            payload={
                "role_name": IMPLEMENTER_ROLE,
                "work_item_id": active_item.id,
                "stage_name": "subtask_implementation_requested",
                "hydration_version": 1,
                "prompt_mode": "live_continuation",
            },
        )
        result_path = self.coordinator.role_workspace_manager.role_directory(  # type: ignore[union-attr]
            session.task_key,
            IMPLEMENTER_ROLE,
        ) / "RESULT.json"
        result_path.write_text(
            json.dumps(
                {
                    "output_type": "completed",
                    "payload": {
                        "work_item_id": active_item.id,
                        "subtask_key": "IOS-30096R",
                        "summary": "matched retry subtask result",
                    },
                }
            )
        )

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name=IMPLEMENTER_ROLE,
        )
        events = self.event_repository.list_for_session(session.id)
        refreshed_active = self.work_item_repository.get_by_id(active_item.id)

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual("verification_requested", updated_session.current_stage)
        self.assertEqual("completed", refreshed_active.status.value)
        self.assertTrue(any(item.event_type == "subtask_completed" for item in events))
        self.assertFalse(any(item.event_type == "stale_role_output_ignored" for item in events))
        self.assertEqual(["IOS-30096R"], self.jira_adapter.completed_subtasks)

    def test_poll_session_output_deduplicates_repeated_stale_implementer_runtime_marker(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30009G2",
            workflow_profile="oneshot",
            policy={
                "review_policy": "enabled",
                                "doc_harvest_policy": "disabled",
            },
        )
        self.coordinator.prepare_task_session("IOS-30009G2")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            'SDD_OUTPUT: {"output_type":"completed","payload":{"summary":"late stale implementer result"}}',
        )
        self.coordinator.poll_session_output(session_id=session.id)
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            'SDD_OUTPUT: {"output_type":"completed","payload":{"summary":"late stale implementer result"}}',
        )
        self.coordinator.poll_session_output(session_id=session.id)

        events = self.event_repository.list_for_session(session.id)
        stale_events = [item for item in events if item.event_type == "stale_role_output_ignored"]

        self.assertEqual(1, len(stale_events))

    def test_collect_role_output_records_progress_marker_without_stage_transition(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30010")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            'SDD_PROGRESS: {"status":"in_progress","message":"halfway there","progress":50}',
        )

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )
        events = self.event_repository.list_for_session(session.id)
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual("implementation_requested", updated_session.current_stage)
        self.assertFalse(any(item.event_type == "role_progress_reported" for item in events))
        self.assertFalse(any(item.event_type == "implementation_completed" for item in events))
        self.assertTrue(any(item.artifact_type == "runtime_progress_json" for item in artifacts))

    def test_collect_role_output_records_error_marker_without_stage_transition(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30014")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            'SDD_ERROR: {"summary":"tool failed","details":"command exited 1"}',
        )

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )
        events = self.event_repository.list_for_session(session.id)
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual("implementation_requested", updated_session.current_stage)
        self.assertEqual("waiting_for_operator", updated_session.status.value)
        self.assertIsNone(updated_session.current_owner)
        work_items = self.work_item_repository.list_for_session(session.id)
        self.assertEqual("waiting_for_operator", work_items[0].status.value)
        self.assertTrue(any(item.event_type == "role_runtime_error_reported" for item in events))
        self.assertTrue(any(item.event_type == "session_escalated_to_operator" for item in events))
        self.assertFalse(any(item.event_type == "implementation_completed" for item in events))
        self.assertTrue(any(item.artifact_type == "runtime_error_json" for item in artifacts))

    def test_collect_role_output_escalates_result_json_error_payload(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30014B")
        role_workspace = self.coordinator.role_workspace_manager.role_directory(  # type: ignore[union-attr]
            session.task_key,
            "implementer",
        )
        result_path = role_workspace / "RESULT.json"
        result_path.write_text(
            json.dumps(
                {
                    "output_type": "error",
                    "payload": {
                        "summary": "tool failed",
                        "details": "lint diagnostics missing",
                    },
                }
            )
        )

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )
        events = self.event_repository.list_for_session(session.id)
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual("implementation_requested", updated_session.current_stage)
        self.assertEqual("waiting_for_operator", updated_session.status.value)
        self.assertIsNone(updated_session.current_owner)
        self.assertFalse(result_path.exists())
        self.assertTrue(any(item.event_type == "role_runtime_error_reported" for item in events))
        self.assertTrue(any(item.event_type == "session_escalated_to_operator" for item in events))
        self.assertTrue(any(item.artifact_type == "role_result_json" for item in artifacts))
        self.assertTrue(any(item.artifact_type == "runtime_error_json" for item in artifacts))

    def test_collect_role_output_ignores_stale_error_from_non_owner_role_without_active_work(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30014C")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        verifier_role = self.role_repository.get_by_name(session.id, "verification-coordinator")
        active_item = next(
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "implementation" and item.status.value == "assigned"
        )
        self.work_item_repository.update_status(active_item.id, WorkItemStatus.COMPLETED)
        self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="verification_requested",
            current_owner="verification-coordinator",
        )
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            'SDD_ERROR: {"summary":"late error","details":"stale worker tail"}',
        )

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )
        events = self.event_repository.list_for_session(session.id)
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual("verification_requested", updated_session.current_stage)
        self.assertEqual("active", updated_session.status.value)
        self.assertEqual("verification-coordinator", updated_session.current_owner)
        self.assertFalse(any(item.event_type == "role_runtime_error_reported" for item in events))
        self.assertFalse(any(item.event_type == "session_escalated_to_operator" for item in events))
        self.assertTrue(any(item.event_type == "stale_role_output_ignored" for item in events))
        self.assertFalse(any(item.artifact_type == "runtime_error_json" for item in artifacts))

    def test_event_bus_receives_published_session_events(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30015")
        self.coordinator.handle_role_output(
            session_id=session.id,
            role_name="implementer",
            output_type="completed",
            payload={"summary": "done"},
        )

        recent = self.event_bus.recent_events(session_id=session.id)

        self.assertTrue(any(event.event_type == "implementation_completed" for event in recent))
        self.assertTrue(any(event.event_type == "verification_requested" for event in recent))

    def test_run_loop_once_polls_all_active_sessions(self) -> None:
        session_a, _, _, _ = self.coordinator.prepare_task_session("IOS-30011")
        session_b, _, _, _ = self.coordinator.prepare_task_session("IOS-30012")
        implementer_a = self.role_repository.get_by_name(session_a.id, "implementer")
        implementer_b = self.role_repository.get_by_name(session_b.id, "implementer")
        self.session_backend.simulate_output(implementer_a.runtime_handle, "a output")
        self.session_backend.simulate_output(implementer_b.runtime_handle, "b output")

        event, session_count, chunk_count = self.coordinator.run_loop_once()
        artifacts_a = self.artifact_repository.list_for_session(session_a.id)
        artifacts_b = self.artifact_repository.list_for_session(session_b.id)

        self.assertIsNone(event)
        self.assertEqual(2, session_count)
        self.assertEqual(2, chunk_count)
        self.assertTrue(any(artifact.artifact_type == "runtime_output" for artifact in artifacts_a))
        self.assertTrue(any(artifact.artifact_type == "runtime_output" for artifact in artifacts_b))

    def test_run_loop_once_reconciles_undispatched_work_item(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30013",
            workflow_profile="oneshot",
            policy=None,
        )
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        work_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="implementation",
            title="Recovered implementation for IOS-30013",
            owner_role_id=implementer_role.id,
            priority=100,
        )
        self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="implementation_requested",
            current_owner="implementer",
        )

        event, session_count, chunk_count = self.coordinator.run_loop_once()
        events = self.event_repository.list_for_session(session.id)
        refreshed_role = self.role_repository.get_by_name(session.id, "implementer")
        sent_inputs = self.session_backend.get_sent_inputs(implementer_role.runtime_handle)

        self.assertIsNone(event)
        self.assertEqual(1, session_count)
        self.assertEqual(0, chunk_count)
        self.assertEqual(1, refreshed_role.last_hydration_version)
        self.assertEqual(1, len(sent_inputs))
        self.assertIn("Start implementation work for IOS-30013.", sent_inputs[0])
        self.assertTrue(
            any(
                item.event_type == "role_input_dispatched"
                and item.payload.get("work_item_id") == work_item.id
                for item in events
            )
        )
        self.assertTrue(any(item.event_type == "session_dispatch_reconciled" for item in events))

    def test_run_loop_once_skips_session_escalated_to_operator(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30016")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            'SDD_ERROR: {"summary":"tool failed","details":"command exited 1"}',
        )

        updated_session, _, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )
        self.assertEqual("waiting_for_operator", updated_session.status.value)
        self.assertEqual(1, chunk_count)

        self.session_backend.simulate_output(implementer_role.runtime_handle, "should stay unread")
        event, session_count, loop_chunk_count = self.coordinator.run_loop_once()

        self.assertIsNone(event)
        self.assertEqual(0, session_count)
        self.assertEqual(0, loop_chunk_count)

    def test_pause_session_moves_active_session_to_paused(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30017")

        paused_session, event = self.coordinator.pause_session(session.id)
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual("paused", paused_session.status.value)
        self.assertEqual("implementer", paused_session.current_owner)
        self.assertEqual("session_paused_by_operator", event.event_type)
        self.assertTrue(any(item.event_type == "session_paused_by_operator" for item in events))

    def test_run_loop_once_skips_paused_session(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30018")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.coordinator.pause_session(session.id)
        self.session_backend.simulate_output(implementer_role.runtime_handle, "should stay unread")

        event, session_count, chunk_count = self.coordinator.run_loop_once()

        self.assertIsNone(event)
        self.assertEqual(0, session_count)
        self.assertEqual(0, chunk_count)

    def test_reopen_from_qa_reactivates_completed_session(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30021")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )
        completed_session, _ = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={"summary": "all green"},
        )

        updated_session, event, followup_event = self.coordinator.reopen_from_qa(
            session_id=completed_session.id,
            comment_text="QA: still broken on edge case",
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual("active", updated_session.status.value)
        self.assertEqual("qa_reopen_requested", updated_session.current_stage)
        self.assertEqual("implementer", updated_session.current_owner)
        self.assertEqual("qa_reopened", event.event_type)
        self.assertEqual("qa_reopen_requested", followup_event.event_type)
        self.assertTrue(
            any(item.title == "QA reopen follow-up for IOS-30021" for item in work_items)
        )
        self.assertTrue(
            any(item.work_type == "followup_implementation" for item in work_items)
        )
        self.assertTrue(any(item.event_type == "qa_reopened" for item in events))
        self.assertTrue(any(item.event_type == "qa_reopen_requested" for item in events))

    def test_story_reopen_from_qa_routes_into_subtask_graph_when_snapshot_has_unresolved_subtasks(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021QASUB",
            workflow_profile="story_full",
            policy=None,
        )
        self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="completed",
            current_owner=None,
        )
        self.session_repository.update_status(session.id, SessionStatus.COMPLETED)
        artifact_path = Path(self.temp_dir.name) / "artifacts" / "IOS-30021QASUB" / "planning" / "task_decomposition.md"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text("# Task decomposition\n")
        self.artifact_repository.create(
            session_id=session.id,
            stage_name="planning",
            artifact_type="task_decomposition_markdown",
            path=str(artifact_path),
            metadata={"task_key": "IOS-30021QASUB"},
        )
        self.write_statuses_file(
            "IOS-30021QASUB",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30021QASUB | Story | Parent story | Ready for test |
| IOS-30121 | Sub-task | Build data source | To Do |
| IOS-30122 | Sub-task | Cleanup edge case | Ready for test |
""",
        )

        updated_session, event, followup_event = self.coordinator.reopen_from_qa(
            session_id=session.id,
            comment_text="QA: still broken on edge case",
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual("qa_reopened", event.event_type)
        self.assertEqual("subtask_implementation_requested", followup_event.event_type)
        self.assertEqual("subtask_implementation_requested", updated_session.current_stage)
        self.assertEqual(IMPLEMENTER_ROLE, updated_session.current_owner)
        self.assertTrue(any(item.work_type == "subtask_implementation" for item in work_items))
        self.assertTrue(any(item.event_type == "subtask_snapshot_refreshed" for item in events))
        self.assertTrue(any(item.event_type == "subtask_graph_requested" for item in events))
        self.assertTrue(any(item.event_type == "subtask_implementation_requested" for item in events))

    def test_bug_full_qa_reopen_uses_bug_fixer_fix_only_followup(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021BUG",
            workflow_profile="bug_full",
            policy={"test_policy": "enabled"},
        )
        self.coordinator.prepare_task_session("IOS-30021BUG")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="bug_analysis_completed",
            payload={"summary": "root cause found"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={"summary": "all green"},
        )

        updated_session, event, followup_event = self.coordinator.reopen_from_qa(
            session_id=session.id,
            comment_text="QA: still broken on edge case",
        )
        bug_fixer_role = self.role_repository.get_by_name(session.id, BUG_FIXER_ROLE)
        sent_inputs = self.session_backend.get_sent_inputs(bug_fixer_role.runtime_handle)

        self.assertEqual("active", updated_session.status.value)
        self.assertEqual("qa_reopen_requested", updated_session.current_stage)
        self.assertEqual(BUG_FIXER_ROLE, updated_session.current_owner)
        self.assertEqual("qa_reopened", event.event_type)
        self.assertEqual("qa_reopen_requested", followup_event.event_type)
        self.assertIn("Mode: fix-only", sent_inputs[-1])
        self.assertIn("Apply QA reopen follow-up changes for IOS-30021BUG.", sent_inputs[-1])
        self.assertIn("highest-priority follow-up scope", sent_inputs[-1])
        role_workspace = self.coordinator.role_workspace_manager.role_directory(  # type: ignore[union-attr]
            "IOS-30021BUG",
            BUG_FIXER_ROLE,
        )
        hydration = json.loads((role_workspace / "HYDRATION.json").read_text())
        self.assertIn("followup_comments_path", hydration)
        self.assertNotIn("bug_analysis_report_path", hydration)

    def test_create_mr_handoff_marks_completed_session_as_handed_off(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30021A")
        self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="completed",
            current_owner=None,
        )
        completed_session = self.session_repository.update_status(session.id, SessionStatus.COMPLETED)
        self.write_passed_verification_outcome("IOS-30021A")

        updated_session, event, mr_url = self.coordinator.create_mr_handoff(
            session_id=completed_session.id
        )
        artifacts = self.artifact_repository.list_for_session(session.id)
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual("completed", updated_session.status.value)
        self.assertEqual("mr_handoff_completed", updated_session.current_stage)
        self.assertEqual("mr_handoff_completed", event.event_type)
        self.assertEqual(
            "https://gitlab.example.com/mobile/IOS-30021A/-/merge_requests/42",
            mr_url,
        )
        self.assertTrue(any(item.artifact_type == "mr_handoff_stdout" for item in artifacts))
        self.assertTrue(any(item.artifact_type == "mr_handoff_stderr" for item in artifacts))
        self.assertTrue(any(item.event_type == "mr_handoff_completed" for item in events))

    def test_create_mr_handoff_requires_completed_session(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30021B")

        with self.assertRaisesRegex(IntakeError, "must be completed before MR handoff"):
            self.coordinator.create_mr_handoff(session_id=session.id)

    def test_create_mr_handoff_failure_escalates_for_operator_retry(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30021B1")
        self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="completed",
            current_owner=None,
        )
        self.session_repository.update_status(session.id, SessionStatus.COMPLETED)
        self.write_passed_verification_outcome("IOS-30021B1")

        original_create_mr = self.gitlab_adapter.create_mr
        self.gitlab_adapter.create_mr = lambda task_key: CommandResult(
            command=["create_mr", task_key],
            returncode=1,
            stdout="",
            stderr="push failed\n",
        )
        failed_session, failed_event, mr_url = self.coordinator.create_mr_handoff(session_id=session.id)

        self.assertEqual("waiting_for_operator", failed_session.status.value)
        self.assertEqual("mr_handoff_failed", failed_session.current_stage)
        self.assertEqual("mr_handoff_failed", failed_event.event_type)
        self.assertIsNone(mr_url)

        self.gitlab_adapter.create_mr = original_create_mr
        retried_session, retried_event, retried_url = self.coordinator.create_mr_handoff(session_id=session.id)

        self.assertEqual("completed", retried_session.status.value)
        self.assertEqual("mr_handoff_completed", retried_session.current_stage)
        self.assertEqual("mr_handoff_completed", retried_event.event_type)
        self.assertEqual(
            "https://gitlab.example.com/mobile/IOS-30021B1/-/merge_requests/42",
            retried_url,
        )

    def test_send_to_test_handoff_marks_mr_handed_off_session_as_ready(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30021C")
        self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="mr_handoff_completed",
            current_owner=None,
        )
        self.session_repository.update_status(session.id, SessionStatus.COMPLETED)
        self.write_passed_verification_outcome("IOS-30021C")

        updated_session, event = self.coordinator.send_to_test_handoff(session_id=session.id)
        artifacts = self.artifact_repository.list_for_session(session.id)
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual("completed", updated_session.status.value)
        self.assertEqual("send_to_test_completed", updated_session.current_stage)
        self.assertEqual("send_to_test_completed", event.event_type)
        self.assertTrue(any(item.artifact_type == "send_to_test_stdout" for item in artifacts))
        self.assertTrue(any(item.artifact_type == "send_to_test_stderr" for item in artifacts))
        self.assertTrue(any(item.event_type == "send_to_test_completed" for item in events))

    def test_send_to_test_handoff_keeps_runtime_roles_alive_after_completion(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30021CKEEP")
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="mr_handoff_completed",
            current_owner=None,
        )
        self.session_repository.update_status(session.id, SessionStatus.COMPLETED)
        self.write_passed_verification_outcome("IOS-30021CKEEP")

        updated_session, event = self.coordinator.send_to_test_handoff(session_id=session.id)
        roles = self.role_repository.list_for_session(session.id)

        self.assertEqual("completed", updated_session.status.value)
        self.assertEqual("send_to_test_completed", updated_session.current_stage)
        self.assertEqual("send_to_test_completed", event.event_type)
        self.assertTrue(any(role.status.value == "running" for role in roles))
        self.assertTrue(any(role.runtime_handle for role in roles if role.status.value == "running"))

    def test_send_to_test_handoff_cleans_verification_tmp_after_completion(self) -> None:
        task_root = Path(self.temp_dir.name) / "IOS-30021CCLEAN"
        verification_root = task_root / "tmp" / "verification" / "ios"
        verification_root.mkdir(parents=True, exist_ok=True)
        (verification_root / "placeholder.txt").write_text("x")

        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30021CCLEAN")
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="mr_handoff_completed",
            current_owner=None,
        )
        self.session_repository.update_status(session.id, SessionStatus.COMPLETED)
        self.write_passed_verification_outcome("IOS-30021CCLEAN")

        updated_session, event = self.coordinator.send_to_test_handoff(session_id=session.id)

        self.assertEqual("completed", updated_session.status.value)
        self.assertEqual("send_to_test_completed", event.event_type)
        self.assertFalse((task_root / "tmp" / "verification").exists())

    def test_send_to_test_handoff_requires_mr_handoff_stage(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30021D")
        completed_session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="completed",
            current_owner=None,
        )
        self.session_repository.update_status(session.id, SessionStatus.COMPLETED)

        with self.assertRaisesRegex(IntakeError, "must complete MR handoff"):
            self.coordinator.send_to_test_handoff(session_id=completed_session.id)

    def test_create_mr_handoff_requires_passed_verification_report_when_verification_ran(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30021DELIVERYFAIL")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )
        verification_report = Path(self.temp_dir.name) / "IOS-30021DELIVERYFAIL" / "spec" / "final-verification.md"
        verification_report.parent.mkdir(parents=True, exist_ok=True)
        verification_report.write_text(
            "# Final Verification: IOS-30021DELIVERYFAIL\n\n"
            "## Result\nFAIL\n"
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="completed",
            current_owner=None,
        )
        self.session_repository.update_status(session.id, SessionStatus.COMPLETED)

        with self.assertRaisesRegex(IntakeError, "workflow verification did not pass"):
            self.coordinator.create_mr_handoff(session_id=session.id)

    def test_send_to_test_handoff_requires_passed_verification_report_when_verification_ran(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30021SENDFAIL")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )
        verification_report = Path(self.temp_dir.name) / "IOS-30021SENDFAIL" / "spec" / "final-verification.md"
        verification_report.parent.mkdir(parents=True, exist_ok=True)
        verification_report.write_text(
            "# Final Verification: IOS-30021SENDFAIL\n\n"
            "## Result\nFAIL\n"
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="mr_handoff_completed",
            current_owner=None,
        )
        self.session_repository.update_status(session.id, SessionStatus.COMPLETED)

        with self.assertRaisesRegex(IntakeError, "workflow verification did not pass"):
            self.coordinator.send_to_test_handoff(session_id=session.id)

    def test_delivery_gate_prefers_structured_verification_outcome_over_markdown(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30021OUTCOMEPASS")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )
        spec_root = Path(self.temp_dir.name) / "IOS-30021OUTCOMEPASS" / "spec"
        spec_root.mkdir(parents=True, exist_ok=True)
        (spec_root / "final-verification.md").write_text(
            "# Final Verification\n\n"
            "## Result\nFAIL\n"
        )
        (spec_root / "verification-outcome.json").write_text(
            json.dumps({"status": "passed", "task_key": "IOS-30021OUTCOMEPASS"}) + "\n"
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="completed",
            current_owner=None,
        )
        self.session_repository.update_status(session.id, SessionStatus.COMPLETED)

        completed_session, event, _ = self.coordinator.create_mr_handoff(session_id=session.id)

        self.assertEqual("completed", completed_session.status.value)
        self.assertEqual("mr_handoff_completed", event.event_type)

    def test_delivery_gate_blocks_when_structured_verification_outcome_failed_even_if_markdown_passes(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30021OUTCOMEFAIL")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )
        spec_root = Path(self.temp_dir.name) / "IOS-30021OUTCOMEFAIL" / "spec"
        spec_root.mkdir(parents=True, exist_ok=True)
        (spec_root / "final-verification.md").write_text(
            "# Final Verification\n\n"
            "## Result\nPASS\n"
        )
        (spec_root / "verification-outcome.json").write_text(
            json.dumps({"status": "failed", "task_key": "IOS-30021OUTCOMEFAIL"}) + "\n"
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="completed",
            current_owner=None,
        )
        self.session_repository.update_status(session.id, SessionStatus.COMPLETED)

        with self.assertRaisesRegex(IntakeError, "workflow verification did not pass"):
            self.coordinator.create_mr_handoff(session_id=session.id)

    def test_send_to_test_handoff_failure_escalates_for_operator_retry(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30021D1")
        self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="mr_handoff_completed",
            current_owner=None,
        )
        self.session_repository.update_status(session.id, SessionStatus.COMPLETED)
        self.write_passed_verification_outcome("IOS-30021D1")

        original_send_to_test = self.jira_adapter.send_to_test
        self.jira_adapter.send_to_test = lambda task_key: CommandResult(
            command=["send_to_test", task_key],
            returncode=1,
            stdout="",
            stderr="transition failed\n",
        )
        failed_session, failed_event = self.coordinator.send_to_test_handoff(session_id=session.id)

        self.assertEqual("waiting_for_operator", failed_session.status.value)
        self.assertEqual("send_to_test_failed", failed_session.current_stage)
        self.assertEqual("send_to_test_failed", failed_event.event_type)

        self.jira_adapter.send_to_test = original_send_to_test
        retried_session, retried_event = self.coordinator.send_to_test_handoff(session_id=session.id)

        self.assertEqual("completed", retried_session.status.value)
        self.assertEqual("send_to_test_completed", retried_session.current_stage)
        self.assertEqual("send_to_test_completed", retried_event.event_type)

    def test_verification_passed_routes_to_doc_harvest_when_policy_required(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021E",
            workflow_profile="oneshot",
            policy={"doc_harvest_policy": "required"},
        )
        self.coordinator.prepare_task_session("IOS-30021E")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={"summary": "all green"},
        )

        self.assertEqual("active", updated_session.status.value)
        self.assertEqual("doc_harvest_requested", updated_session.current_stage)
        self.assertEqual(DOC_HARVEST_ROLE, updated_session.current_owner)
        self.assertEqual("doc_harvest_requested", followup_event.event_type)

    def test_verification_passed_routes_to_doc_harvest_when_policy_enabled(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021EE",
            workflow_profile="oneshot",
            policy={"doc_harvest_policy": "enabled"},
        )
        self.coordinator.prepare_task_session("IOS-30021EE")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={"summary": "all green"},
        )

        self.assertEqual("active", updated_session.status.value)
        self.assertEqual("doc_harvest_requested", updated_session.current_stage)
        self.assertEqual(DOC_HARVEST_ROLE, updated_session.current_owner)
        self.assertEqual("doc_harvest_requested", followup_event.event_type)

    def test_active_runtime_output_ignores_standby_runtime_without_active_owner_or_stage_item(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021ACTIVEOUTPUT",
            workflow_profile="oneshot",
            policy={"review_policy": "disabled"},
        )
        self.coordinator.prepare_task_session("IOS-30021ACTIVEOUTPUT")

        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        verifier_role = self.role_repository.get_by_name(session.id, VERIFICATION_COORDINATOR_ROLE)
        assert implementer_role is not None
        assert verifier_role is not None
        assert implementer_role.runtime_handle is not None
        assert verifier_role.runtime_handle is not None

        self.session_backend.simulate_output(implementer_role.runtime_handle, "stale implementer output")
        self.session_backend.simulate_output(verifier_role.runtime_handle, "stale verifier output")

        self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="doc_harvest_requested",
            current_owner=DOC_HARVEST_ROLE,
        )

        summary = self.coordinator.get_active_runtime_output_summary(session.id)

        self.assertFalse(summary["available"])
        self.assertIsNone(summary["role_name"])
        self.assertEqual("", summary["content"])

    def test_active_runtime_output_records_stalled_runtime_poke(self) -> None:
        class StallPokeRecordingBackend(RecordingSessionBackend):
            def maybe_poke_stalled_role(self, role, *, snapshot=None):
                return {
                    "role_id": role.role_id,
                    "stalled_seconds": 181.0,
                    "threshold_seconds": 180.0,
                    "terminal_idle_signature_length": len(snapshot or ""),
                    "poke_text": ".",
                }

        backend = StallPokeRecordingBackend()
        self.session_backend = backend
        self.coordinator.session_backend = backend
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021STALLPOKE",
            workflow_profile="oneshot",
            policy={"review_policy": "disabled"},
        )
        self.coordinator.prepare_task_session("IOS-30021STALLPOKE")
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        assert implementer_role is not None
        assert implementer_role.runtime_handle is not None
        backend.simulate_output(implementer_role.runtime_handle, "stable console snapshot")

        summary = self.coordinator.get_active_runtime_output_summary(session.id)
        events = self.event_repository.list_for_session(session.id)
        poke_events = [event for event in events if event.event_type == "runtime_role_stall_poked"]

        self.assertTrue(summary["available"])
        self.assertEqual(1, len(poke_events))
        self.assertEqual(IMPLEMENTER_ROLE, poke_events[0].payload["role_name"])
        self.assertEqual(".", poke_events[0].payload["poke_text"])

    def test_active_runtime_output_does_not_poke_when_result_file_is_pending(self) -> None:
        class StallPokeRecordingBackend(RecordingSessionBackend):
            def maybe_poke_stalled_role(self, role, *, snapshot=None):
                return {
                    "role_id": role.role_id,
                    "stalled_seconds": 181.0,
                    "threshold_seconds": 180.0,
                    "terminal_idle_signature_length": len(snapshot or ""),
                    "poke_text": ".",
                }

        backend = StallPokeRecordingBackend()
        self.session_backend = backend
        self.coordinator.session_backend = backend
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021STALLRESULT",
            workflow_profile="oneshot",
            policy={"review_policy": "disabled"},
        )
        self.coordinator.prepare_task_session("IOS-30021STALLRESULT")
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        assert implementer_role is not None
        assert implementer_role.runtime_handle is not None
        backend.simulate_output(implementer_role.runtime_handle, "stable console snapshot")
        result_path = self.coordinator.role_workspace_manager.role_directory(  # type: ignore[union-attr]
            session.task_key,
            IMPLEMENTER_ROLE,
        ) / "RESULT.json"
        result_path.write_text('{"output_type":"completed","payload":{"work_item_id":1}}', encoding="utf-8")

        self.coordinator.get_active_runtime_output_summary(session.id)
        events = self.event_repository.list_for_session(session.id)

        self.assertFalse(any(event.event_type == "runtime_role_stall_poked" for event in events))

    def test_waiting_operator_output_does_not_poke_stalled_runtime(self) -> None:
        class StallPokeRecordingBackend(RecordingSessionBackend):
            def maybe_poke_stalled_role(self, role, *, snapshot=None):
                return {
                    "role_id": role.role_id,
                    "stalled_seconds": 181.0,
                    "threshold_seconds": 180.0,
                    "terminal_idle_signature_length": len(snapshot or ""),
                    "poke_text": ".",
                }

        backend = StallPokeRecordingBackend()
        self.session_backend = backend
        self.coordinator.session_backend = backend
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021WAITNOPOKE",
            workflow_profile="oneshot",
            policy={"review_policy": "disabled"},
        )
        self.coordinator.prepare_task_session("IOS-30021WAITNOPOKE")
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        assert implementer_role is not None
        assert implementer_role.id is not None
        assert implementer_role.runtime_handle is not None
        work_item = self.coordinator._find_active_work_item_for_role(session.id, implementer_role.id)
        assert work_item is not None
        self.work_item_repository.update_status(work_item.id, WorkItemStatus.WAITING_FOR_OPERATOR)
        self.session_repository.update_stage_and_owner(
            session.id,
            current_stage=session.current_stage,
            current_owner=None,
        )
        self.session_repository.update_status(session.id, SessionStatus.WAITING_FOR_OPERATOR)
        self.coordinator._append_event(
            session_id=session.id,
            event_type="session_escalated_to_operator",
            producer_type="coordinator",
            payload={
                "role_name": IMPLEMENTER_ROLE,
                "current_stage": session.current_stage,
                "summary": "Implementer needs a reply",
                "details": "Waiting for operator.",
                "needs_operator_input": True,
            },
        )
        backend.simulate_output(implementer_role.runtime_handle, "stable console snapshot")

        summary = self.coordinator.get_active_runtime_output_summary(session.id)
        events = self.event_repository.list_for_session(session.id)

        self.assertFalse(summary["available"])
        self.assertIsNone(summary["role_name"])
        self.assertEqual("", summary["content"])
        self.assertFalse(any(event.event_type == "runtime_role_stall_poked" for event in events))

    def test_collect_role_output_checks_active_owner_for_stalled_runtime(self) -> None:
        class StallPokeRecordingBackend(RecordingSessionBackend):
            def maybe_poke_stalled_role(self, role, *, snapshot=None):
                return {
                    "role_id": role.role_id,
                    "stalled_seconds": 181.0,
                    "threshold_seconds": 180.0,
                    "terminal_idle_signature_length": len(snapshot or ""),
                    "poke_text": ".",
                }

        backend = StallPokeRecordingBackend()
        self.session_backend = backend
        self.coordinator.session_backend = backend
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021COLLECTSTALL",
            workflow_profile="oneshot",
            policy={"review_policy": "disabled"},
        )
        self.coordinator.prepare_task_session("IOS-30021COLLECTSTALL")

        session, event, chunk_count = self.coordinator.collect_role_output(session.id, IMPLEMENTER_ROLE)
        events = self.event_repository.list_for_session(session.id)
        poke_events = [item for item in events if item.event_type == "runtime_role_stall_poked"]

        self.assertIsNone(event)
        self.assertEqual(0, chunk_count)
        self.assertEqual(1, len(poke_events))
        self.assertEqual(IMPLEMENTER_ROLE, poke_events[0].payload["role_name"])

    def test_complete_doc_harvest_marks_lane_completed(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021F",
            workflow_profile="oneshot",
            policy={"doc_harvest_policy": "enabled"},
        )
        self.coordinator.prepare_task_session("IOS-30021F")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={"summary": "all green"},
        )

        updated_session, event = self.coordinator.complete_doc_harvest(
            session_id=session.id,
            summary="Feature README updated with current behavior.",
        )
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual("active", updated_session.status.value)
        self.assertEqual("documentation_review_requested", updated_session.current_stage)
        self.assertEqual("doc_harvest_completed", event.event_type)
        self.assertEqual("active", event.payload.get("status"))
        self.assertTrue(any(item.artifact_type == "doc_harvest_summary" for item in artifacts))
        outcome_path = Path(self.temp_dir.name) / "IOS-30021F" / "spec" / "doc-harvest-outcome.json"
        self.assertTrue(outcome_path.exists())
        self.assertEqual("completed", json.loads(outcome_path.read_text())["status"])

    def test_complete_doc_harvest_refreshes_structured_diffs(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021FDIFF",
            workflow_profile="oneshot",
            policy={"doc_harvest_policy": "enabled"},
        )
        self.coordinator.prepare_task_session("IOS-30021FDIFF")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={"summary": "all green"},
        )

        with patch.object(
            self.coordinator,
            "_refresh_structured_diff_artifact",
            side_effect=lambda task_key, *, mode: f"/tmp/{task_key}-{mode}.md",
        ) as refresh_mock:
            self.coordinator.complete_doc_harvest(
                session_id=session.id,
                summary="Feature README updated with current behavior.",
            )

        self.assertEqual(
            [
                call("IOS-30021FDIFF", mode="source"),
                call("IOS-30021FDIFF", mode="docs"),
                call("IOS-30021FDIFF", mode="full"),
                call("IOS-30021FDIFF", mode="docs"),
                call("IOS-30021FDIFF", mode="full"),
            ],
            refresh_mock.call_args_list,
        )

    def test_complete_doc_harvest_is_rejected_when_policy_required(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021FR",
            workflow_profile="oneshot",
            policy={"doc_harvest_policy": "required"},
        )
        self.coordinator.prepare_task_session("IOS-30021FR")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={"summary": "all green"},
        )

        with self.assertRaisesRegex(
            IntakeError,
            "Manual doc harvest completion is only allowed when doc_harvest_policy is enabled",
        ):
            self.coordinator.complete_doc_harvest(
                session_id=session.id,
                summary="operator shortcut",
            )

    def test_doc_harvest_role_output_marks_lane_completed(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021FH",
            workflow_profile="oneshot",
            policy={"doc_harvest_policy": "required"},
        )
        self.coordinator.prepare_task_session("IOS-30021FH")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={"summary": "all green"},
        )

        updated_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=DOC_HARVEST_ROLE,
            output_type="completed",
            payload={"summary": "README enriched for the touched feature area."},
        )
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual("doc_harvest_completed", mapped_event.event_type)
        self.assertIsNotNone(followup_event)
        assert followup_event is not None
        self.assertEqual("documentation_review_requested", followup_event.event_type)
        self.assertEqual("active", updated_session.status.value)
        self.assertEqual("documentation_review_requested", updated_session.current_stage)
        self.assertTrue(any(item.artifact_type == "doc_harvest_summary" for item in artifacts))
        self.assertEqual(
            [
                ("IOS-30021FH", "implementation pass"),
                ("IOS-30021FH", "doc harvest"),
            ],
            self.gitlab_adapter.commit_requests,
        )
        doc_role = self.role_repository.get_by_name(session.id, DOC_HARVEST_ROLE)
        assert doc_role is not None
        self.assertEqual(RoleStatus.RUNNING, doc_role.status)

    def test_doc_harvest_completion_continues_delivery_after_commit(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021FHCOMMIT",
            workflow_profile="oneshot",
            policy={"doc_harvest_policy": "required"},
        )
        self.coordinator.prepare_task_session("IOS-30021FHCOMMIT")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={"summary": "all green"},
        )

        updated_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=DOC_HARVEST_ROLE,
            output_type="completed",
            payload={"summary": "README remains current."},
        )
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual("doc_harvest_completed", mapped_event.event_type)
        self.assertIsNotNone(followup_event)
        assert followup_event is not None
        self.assertEqual("documentation_review_requested", followup_event.event_type)
        self.assertEqual("active", updated_session.status.value)
        self.assertEqual("documentation_review_requested", updated_session.current_stage)
        self.assertTrue(any(item.event_type == "git_commit_completed" for item in events))
        self.assertFalse(any(item.event_type == "mr_handoff_completed" for item in events))

    def test_doc_harvest_completion_parks_when_delivery_gate_is_blocked(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021FHBLOCK",
            workflow_profile="oneshot",
            policy={"doc_harvest_policy": "required"},
        )
        self.coordinator.prepare_task_session("IOS-30021FHBLOCK")
        verification_report = Path(self.temp_dir.name) / "IOS-30021FHBLOCK" / "spec" / "final-verification.md"
        verification_report.parent.mkdir(parents=True, exist_ok=True)
        verification_report.write_text(
            "# Final Verification: IOS-30021FHBLOCK\n\n"
            "## Result\nFAIL\n"
        )
        self.event_repository.append(
            session_id=session.id,
            event_type="verification_requested",
            producer_type="coordinator",
            payload={"task_key": session.task_key},
        )
        doc_role = self.role_repository.get_by_name(session.id, DOC_HARVEST_ROLE)
        assert doc_role is not None
        doc_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="doc_harvest",
            title=f"Doc harvest for {session.task_key}",
            owner_role_id=doc_role.id,
            source_event_id=None,
            priority=112,
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="doc_harvest_requested",
            current_owner=DOC_HARVEST_ROLE,
        )
        self.session_repository.update_status(session.id, SessionStatus.ACTIVE)

        updated_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=DOC_HARVEST_ROLE,
            output_type="completed",
            payload={"summary": "README remains current.", "work_item_id": doc_item.id},
        )
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual("doc_harvest_completed", mapped_event.event_type)
        self.assertIsNotNone(followup_event)
        assert followup_event is not None
        self.assertEqual("documentation_review_requested", followup_event.event_type)
        self.assertEqual("active", updated_session.status.value)
        self.assertEqual("documentation_review_requested", updated_session.current_stage)
        self.assertTrue(any(item.event_type == "git_commit_completed" for item in events))
        self.assertFalse(any(item.event_type == "send_to_test_completed" for item in events))

    def test_verification_outcome_status_reads_structured_passed_json(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021VPASS1",
            workflow_profile="oneshot",
        )
        spec_root = Path(self.temp_dir.name) / "IOS-30021VPASS1" / "spec"
        spec_root.mkdir(parents=True, exist_ok=True)
        (spec_root / "verification-outcome.json").write_text(
            json.dumps({"status": "passed", "task_key": "IOS-30021VPASS1"}) + "\n"
        )

        self.assertEqual("passed", self.coordinator._verification_outcome_status(session))

    def test_verification_outcome_status_ignores_markdown_without_structured_json(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021VPASS2",
            workflow_profile="oneshot",
        )
        verification_report = Path(self.temp_dir.name) / "IOS-30021VPASS2" / "spec" / "final-verification.md"
        verification_report.parent.mkdir(parents=True, exist_ok=True)
        verification_report.write_text(
            "# Final Verification Report\n\n"
            "## Final status\n\n"
            "Deterministic verification **passed**. No code changes were made in this verification role.\n"
        )

        self.assertIsNone(self.coordinator._verification_outcome_status(session))

    def test_doc_harvest_skipped_not_needed_completes_session_when_policy_enabled(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021FHE",
            workflow_profile="oneshot",
            policy={"doc_harvest_policy": "enabled"},
        )
        self.coordinator.prepare_task_session("IOS-30021FHE")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={"summary": "all green"},
        )

        updated_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=DOC_HARVEST_ROLE,
            output_type="skipped_not_needed",
            payload={"summary": "No grounded README target was affected by this change."},
        )
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual("doc_harvest_completed", mapped_event.event_type)
        self.assertIsNotNone(followup_event)
        assert followup_event is not None
        self.assertEqual("documentation_review_requested", followup_event.event_type)
        self.assertEqual("active", updated_session.status.value)
        self.assertEqual("documentation_review_requested", updated_session.current_stage)
        self.assertTrue(any(item.artifact_type == "doc_harvest_summary" for item in artifacts))
        self.assertEqual(
            [
                ("IOS-30021FHE", "implementation pass"),
                ("IOS-30021FHE", "doc harvest"),
            ],
            self.gitlab_adapter.commit_requests,
        )

    def test_doc_harvest_skipped_not_needed_is_rejected_when_policy_required(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021FHR",
            workflow_profile="oneshot",
            policy={"doc_harvest_policy": "required"},
        )
        self.coordinator.prepare_task_session("IOS-30021FHR")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={"summary": "all green"},
        )

        with self.assertRaisesRegex(
            IntakeError,
            "Doc harvest cannot be skipped when doc_harvest_policy is required",
        ):
            self.coordinator.handle_role_output(
                session_id=session.id,
                role_name=DOC_HARVEST_ROLE,
                output_type="skipped_not_needed",
                payload={"summary": "No grounded README target was affected by this change."},
            )

    def test_documentation_review_passed_continues_delivery_after_doc_harvest(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021DOCREVIEWPASS",
            workflow_profile="oneshot",
            policy={"doc_harvest_policy": "required"},
        )
        self.coordinator.prepare_task_session("IOS-30021DOCREVIEWPASS")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={"summary": "all green"},
        )
        self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=DOC_HARVEST_ROLE,
            output_type="completed",
            payload={"summary": "README remains current."},
        )

        updated_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=DOCUMENTATION_REVIEWER_ROLE,
            output_type="passed",
            payload={"summary": "Documentation follows the guide."},
        )
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual("documentation_review_passed", mapped_event.event_type)
        self.assertIsNotNone(followup_event)
        assert followup_event is not None
        self.assertEqual("send_to_test_completed", followup_event.event_type)
        self.assertEqual("completed", updated_session.status.value)
        self.assertEqual("send_to_test_completed", updated_session.current_stage)
        self.assertTrue(any(item.artifact_type == "documentation_review_report_markdown" for item in artifacts))

    def test_documentation_review_failed_routes_docs_only_correction(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021DOCREVIEWFAIL",
            workflow_profile="oneshot",
            policy={"doc_harvest_policy": "required"},
        )
        self.coordinator.prepare_task_session("IOS-30021DOCREVIEWFAIL")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={"summary": "all green"},
        )
        self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=DOC_HARVEST_ROLE,
            output_type="completed",
            payload={"summary": "README updated."},
        )

        updated_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=DOCUMENTATION_REVIEWER_ROLE,
            output_type="failed",
            payload={
                "summary": "Production README contains Jira history.",
                "issues_markdown": "Remove IOS-12345 from README text.",
            },
        )
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual("documentation_review_issues_found", mapped_event.event_type)
        self.assertIsNotNone(followup_event)
        assert followup_event is not None
        self.assertEqual("documentation_review_correction_requested", followup_event.event_type)
        self.assertEqual("documentation_review_correction_requested", updated_session.current_stage)
        self.assertEqual(IMPLEMENTER_ROLE, updated_session.current_owner)
        self.assertTrue(any(item.artifact_type == "documentation_review_report_markdown" for item in artifacts))
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        assert implementer_role is not None
        sent_inputs = self.session_backend.get_sent_inputs(implementer_role.runtime_handle)
        self.assertIn("Edit only production documentation and comments", sent_inputs[-1])
        hydration = json.loads(
            (
                Path(self.temp_dir.name)
                / "IOS-30021DOCREVIEWFAIL"
                / "runtime"
                / "role-workspaces"
                / IMPLEMENTER_ROLE
                / "HYDRATION.json"
            ).read_text()
        )
        self.assertEqual("documentation_review", hydration["correction_source"])

    def test_documentation_review_failed_requires_actionable_findings(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021DOCREVIEWEMPTY",
            workflow_profile="oneshot",
            policy={"doc_harvest_policy": "required"},
        )
        self.coordinator.prepare_task_session("IOS-30021DOCREVIEWEMPTY")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={"summary": "all green"},
        )
        self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=DOC_HARVEST_ROLE,
            output_type="completed",
            payload={"summary": "README updated."},
        )

        with self.assertRaisesRegex(
            IntakeError,
            "Documentation review failed output must include payload.issues_markdown with actionable findings",
        ):
            self.coordinator.handle_role_output(
                session_id=session.id,
                role_name=DOCUMENTATION_REVIEWER_ROLE,
                output_type="failed",
                payload={"summary": "Documentation review found issues"},
            )

        work_items = self.work_item_repository.list_for_session(session.id)
        self.assertFalse(any(item.work_type == "documentation_review_correction" for item in work_items))

    def test_documentation_review_correction_returns_to_documentation_review(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021DOCREVIEWROUND",
            workflow_profile="oneshot",
            policy={"doc_harvest_policy": "required"},
        )
        self.coordinator.prepare_task_session("IOS-30021DOCREVIEWROUND")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={"summary": "all green"},
        )
        self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=DOC_HARVEST_ROLE,
            output_type="completed",
            payload={"summary": "README updated."},
        )
        self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=DOCUMENTATION_REVIEWER_ROLE,
            output_type="failed",
            payload={
                "summary": "Docs need cleanup.",
                "issues_markdown": "Remove implementation-only details from README.",
            },
        )

        updated_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=IMPLEMENTER_ROLE,
            output_type="completed",
            payload={"summary": "Docs cleanup applied."},
        )

        self.assertEqual("implementation_completed", mapped_event.event_type)
        self.assertIsNotNone(followup_event)
        assert followup_event is not None
        self.assertEqual("documentation_review_requested", followup_event.event_type)
        self.assertEqual("documentation_review_requested", updated_session.current_stage)

    def test_followup_implementation_completed_reenters_verification_loop(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30022")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )
        completed_session, _ = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={"summary": "all green"},
        )
        self.coordinator.reopen_from_qa(
            session_id=completed_session.id,
            comment_text="QA: still failing on edge case",
        )

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "qa fix done"},
        )

        self.assertEqual("verification_requested", updated_session.current_stage)
        self.assertEqual("verification-coordinator", updated_session.current_owner)
        self.assertEqual("verification_requested", followup_event.event_type)
        self.assertEqual(
            [
                ("IOS-30022", "implementation pass"),
                ("IOS-30022", "follow-up pass"),
            ],
            self.gitlab_adapter.commit_requests,
        )

    def test_resume_session_reactivates_escalated_work_item(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30019")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            'SDD_ERROR: {"summary":"tool failed","details":"command exited 1"}',
        )
        escalated_session, _, _ = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )

        resumed_session, resumed_event, dispatch_event = self.coordinator.resume_session(session.id)
        events = self.event_repository.list_for_session(session.id)
        sent_inputs = self.session_backend.get_sent_inputs(implementer_role.runtime_handle)
        work_items = self.work_item_repository.list_for_session(session.id)

        self.assertEqual("waiting_for_operator", escalated_session.status.value)
        self.assertEqual("active", resumed_session.status.value)
        self.assertEqual("implementer", resumed_session.current_owner)
        self.assertEqual("session_resumed_by_operator", resumed_event.event_type)
        self.assertEqual("role_input_dispatched", dispatch_event.event_type)
        self.assertEqual(1, len(work_items))
        self.assertEqual("assigned", work_items[0].status.value)
        self.assertEqual(2, len(sent_inputs))
        self.assertIn("Start implementation work for IOS-30019.", sent_inputs[-1])
        self.assertTrue(any(item.event_type == "session_resumed_by_operator" for item in events))

    def test_resume_session_reactivates_mcp_availability_blocker_without_redispatch(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30019MCP")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            'SDD_ERROR: {"summary":"required mcp access unavailable","details":"restore vpn","resume_strategy":"reactivate_only"}',
        )
        escalated_session, _, _ = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )

        resumed_session, resumed_event, followup_event = self.coordinator.resume_session(session.id)
        sent_inputs = self.session_backend.get_sent_inputs(implementer_role.runtime_handle)
        work_items = self.work_item_repository.list_for_session(session.id)

        self.assertEqual("waiting_for_operator", escalated_session.status.value)
        self.assertEqual("active", resumed_session.status.value)
        self.assertEqual("implementer", resumed_session.current_owner)
        self.assertEqual("session_resumed_by_operator", resumed_event.event_type)
        self.assertIsNone(followup_event)
        self.assertEqual(1, len(work_items))
        self.assertEqual("assigned", work_items[0].status.value)
        self.assertEqual(1, len(sent_inputs))

    def test_resume_session_requires_waiting_for_operator_status(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30020")

        with self.assertRaisesRegex(IntakeError, "not resumable"):
            self.coordinator.resume_session(session.id)

    def test_resume_session_reactivates_paused_session(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30021")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.coordinator.pause_session(session.id)

        resumed_session, resumed_event, dispatch_event = self.coordinator.resume_session(session.id)
        sent_inputs = self.session_backend.get_sent_inputs(implementer_role.runtime_handle)

        self.assertEqual("active", resumed_session.status.value)
        self.assertEqual("implementer", resumed_session.current_owner)
        self.assertEqual("session_resumed_by_operator", resumed_event.event_type)
        self.assertEqual("paused", resumed_event.payload["resume_reason"])
        self.assertEqual("role_input_dispatched", dispatch_event.event_type)
        self.assertEqual(2, len(sent_inputs))

    def test_resume_session_reactivates_paused_session_with_operator_pending_work(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30021PENDING")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        assert implementer_role is not None
        work_item = next(
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "implementation"
        )
        self.work_item_repository.update_status(work_item.id, WorkItemStatus.WAITING_FOR_OPERATOR)
        self.session_repository.update_stage_and_owner(
            session.id,
            current_stage=session.current_stage,
            current_owner=None,
        )
        self.session_repository.update_status(session.id, SessionStatus.PAUSED)

        resumed_session, resumed_event, dispatch_event = self.coordinator.resume_session(session.id)
        sent_inputs = self.session_backend.get_sent_inputs(implementer_role.runtime_handle)

        self.assertEqual("active", resumed_session.status.value)
        self.assertEqual("implementer", resumed_session.current_owner)
        self.assertEqual("session_resumed_by_operator", resumed_event.event_type)
        self.assertEqual("waiting_for_operator", resumed_event.payload["resume_reason"])
        self.assertEqual("role_input_dispatched", dispatch_event.event_type)
        self.assertEqual("assigned", self.work_item_repository.get_by_id(work_item.id).status.value)
        self.assertEqual(2, len(sent_inputs))

    def test_resume_session_from_subtask_creation_checkpoint_starts_implementation(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021EXEC",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30021EXEC")
        for event_type in (
            "proposal_context_completed",
            "requirements_completed",
            "acceptance_criteria_completed",
            "constraints_completed",
            "spec_verification_completed",
            "story_spec_completed",
        ):
            self.coordinator.handle_operator_event(
                session_id=session.id,
                event_type=event_type,
                payload={"summary": "prepared"},
            )
        active_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="task_decomposition_completed",
            payload=decomposition_payload("Decomposition prepared"),
        )
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        sent_inputs = self.session_backend.get_sent_inputs(implementer_role.runtime_handle)

        self.assertEqual("jira_subtasks_created", followup_event.event_type)
        self.assertEqual("subtask_creation_requested", active_session.current_stage)
        self.assertEqual("waiting_for_operator", active_session.status.value)
        self.assertEqual([], sent_inputs)

    def test_resume_session_from_subtask_creation_checkpoint_can_start_subtask_lane(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021SUBGRAPH",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30021SUBGRAPH")
        for event_type in (
            "proposal_context_completed",
            "requirements_completed",
            "acceptance_criteria_completed",
            "constraints_completed",
            "spec_verification_completed",
            "story_spec_completed",
        ):
            self.coordinator.handle_operator_event(
                session_id=session.id,
                event_type=event_type,
                payload={"summary": "prepared"},
            )
        self.write_statuses_file(
            "IOS-30021SUBGRAPH",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30021SUBGRAPH | Story | Parent story | In Progress |
| IOS-30121 | Sub-task | Build data source | To Do |
""",
        )
        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="task_decomposition_completed",
            payload=decomposition_payload("Decomposition prepared"),
        )
        self.assertEqual("subtask_implementation_requested", followup_event.event_type)
        self.assertEqual("subtask_implementation_requested", updated_session.current_stage)

    def test_retry_session_creates_new_work_item_for_escalated_session(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30022")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            'SDD_ERROR: {"summary":"tool failed","details":"command exited 1"}',
        )
        self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )

        retried_session, retried_event, dispatch_event = self.coordinator.retry_session(session.id)
        work_items = self.work_item_repository.list_for_session(session.id)
        sent_inputs = self.session_backend.get_sent_inputs(implementer_role.runtime_handle)

        self.assertEqual("active", retried_session.status.value)
        self.assertEqual("implementer", retried_session.current_owner)
        self.assertEqual("session_retried_by_operator", retried_event.event_type)
        self.assertEqual("role_input_dispatched", dispatch_event.event_type)
        self.assertEqual(2, len(work_items))
        self.assertEqual(
            ["assigned", "completed"],
            sorted(item.status.value for item in work_items),
        )
        self.assertTrue(
            any(
                item.title.startswith("Retry: ") and item.status.value == "assigned"
                for item in work_items
            )
        )

    def test_retry_session_retries_subtask_creation_checkpoint(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30022SUBTASK",
            workflow_profile="story_full",
            policy=None,
        )
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        assert implementer_role is not None
        plan_dir = Path(self.temp_dir.name) / "IOS-30022SUBTASK" / "plan"
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / "index.md").write_text(
            "# Execution Task List\n\n1. [Build data source](./01-build-data-source.md)\n",
            encoding="utf-8",
        )
        (plan_dir / "01-build-data-source.md").write_text(
            "# Build data source\n\n## What to implement\nCreate the feature data source.\n",
            encoding="utf-8",
        )
        self.work_item_repository.create(
            session_id=session.id,
            work_type="implementation",
            title=f"Initial implementation for {session.task_key}",
            owner_role_id=implementer_role.id,
            source_event_id=None,
            priority=100,
            status=WorkItemStatus.WAITING_FOR_OPERATOR,
        )
        self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="subtask_creation_requested",
            current_owner=None,
        )
        self.session_repository.update_status(session.id, SessionStatus.WAITING_FOR_OPERATOR)

        retried_session, retried_event, followup_event = self.coordinator.retry_session(session.id)

        self.assertEqual("session_retried_by_operator", retried_event.event_type)
        self.assertIn(followup_event.event_type, {"jira_subtasks_created", "subtask_implementation_requested"})
        self.assertIn(retried_session.current_stage, {"subtask_creation_requested", "subtask_implementation_requested"})

    def test_retry_session_picks_latest_operator_pending_item(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30022LATEST")
        verifier_role = self.role_repository.get_by_name(session.id, VERIFICATION_COORDINATOR_ROLE)
        assert verifier_role is not None
        older_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="verification",
            title=f"Verification for {session.task_key}",
            owner_role_id=verifier_role.id,
            source_event_id=None,
            priority=90,
            status=WorkItemStatus.WAITING_FOR_OPERATOR,
        )
        newer_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="verification",
            title=f"Retry: Verification for {session.task_key}",
            owner_role_id=verifier_role.id,
            source_event_id=None,
            priority=90,
            status=WorkItemStatus.WAITING_FOR_OPERATOR,
        )
        self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="verification_requested",
            current_owner=None,
        )
        self.session_repository.update_status(session.id, SessionStatus.WAITING_FOR_OPERATOR)

        retried_session, retried_event, dispatch_event = self.coordinator.retry_session(session.id)
        refreshed_items = {item.id: item for item in self.work_item_repository.list_for_session(session.id)}

        self.assertEqual("active", retried_session.status.value)
        self.assertEqual(newer_item.id, retried_event.payload.get("previous_work_item_id"))
        self.assertEqual("role_input_dispatched", dispatch_event.event_type)
        self.assertEqual(WorkItemStatus.COMPLETED, refreshed_items[older_item.id].status)
        self.assertEqual(WorkItemStatus.COMPLETED, refreshed_items[newer_item.id].status)

    def test_verification_passed_completes_retry_item_from_payload_work_item_id(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30022VERRETRY")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )
        verifier_role = self.role_repository.get_by_name(session.id, VERIFICATION_COORDINATOR_ROLE)
        assert verifier_role is not None
        original_item = next(
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "verification"
        )
        self.work_item_repository.update_status(original_item.id, WorkItemStatus.WAITING_FOR_OPERATOR)
        self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="verification_requested",
            current_owner=None,
        )
        self.session_repository.update_status(session.id, SessionStatus.WAITING_FOR_OPERATOR)

        retried_session, _retried_event, _dispatch_event = self.coordinator.retry_session(session.id)
        retry_item = next(
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "verification" and item.status == WorkItemStatus.ASSIGNED
        )

        updated_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=retried_session.id,
            role_name=VERIFICATION_COORDINATOR_ROLE,
            output_type="passed",
            payload={
                "result": "passed",
                "summary": "verification passed",
                "work_item_id": retry_item.id,
            },
        )
        refreshed_items = {item.id: item for item in self.work_item_repository.list_for_session(session.id)}

        self.assertEqual("verification_passed", mapped_event.event_type)
        self.assertNotEqual("verification_requested", updated_session.current_stage)
        self.assertEqual(WorkItemStatus.COMPLETED, refreshed_items[original_item.id].status)
        self.assertEqual(WorkItemStatus.COMPLETED, refreshed_items[retry_item.id].status)

    def test_redirect_session_reroutes_escalated_work_item_to_allowed_role(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30023")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        shadow_role = self.role_repository.create(
            session_id=session.id,
            role_name="implementer-shadow",
            runtime_backend="recording",
            runtime_handle="recording:implementer-shadow",
        )
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            'SDD_ERROR: {"summary":"tool failed","details":"command exited 1"}',
        )
        self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )
        ALLOWED_STAGE_ROLE_TARGETS["implementation_requested"].add("implementer-shadow")
        try:
            redirected_session, redirected_event, dispatch_event = self.coordinator.redirect_session(
                session_id=session.id,
                target_role_name="implementer-shadow",
            )
        finally:
            ALLOWED_STAGE_ROLE_TARGETS["implementation_requested"].remove("implementer-shadow")
        work_items = self.work_item_repository.list_for_session(session.id)
        refreshed_shadow_role = self.role_repository.get_by_name(session.id, "implementer-shadow")
        assert refreshed_shadow_role is not None
        shadow_inputs = self.session_backend.get_sent_inputs(refreshed_shadow_role.runtime_handle)

        self.assertEqual("active", redirected_session.status.value)
        self.assertEqual("implementer-shadow", redirected_session.current_owner)
        self.assertEqual("session_redirected_by_operator", redirected_event.event_type)
        self.assertEqual("role_input_dispatched", dispatch_event.event_type)
        self.assertEqual(2, len(work_items))
        self.assertTrue(
            any(
                item.title.startswith("Redirect to implementer-shadow:")
                and item.status.value == "assigned"
                for item in work_items
            )
        )
        self.assertTrue(
            any(
                item.owner_role_id == implementer_role.id and item.status.value == "waiting_for_operator"
                for item in work_items
            )
        )
        self.assertEqual(1, len(shadow_inputs))
        self.assertIn("Start implementation work for IOS-30023.", shadow_inputs[-1])

    def test_redirect_session_rejects_role_not_allowed_for_stage(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30024")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            'SDD_ERROR: {"summary":"tool failed","details":"command exited 1"}',
        )
        self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )

        with self.assertRaisesRegex(IntakeError, "not allowed for stage"):
            self.coordinator.redirect_session(
                session_id=session.id,
                target_role_name="verification-coordinator",
            )

    def test_redirect_session_requires_different_target_role(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30025")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            'SDD_ERROR: {"summary":"tool failed","details":"command exited 1"}',
        )
        self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )

        with self.assertRaisesRegex(IntakeError, "must differ"):
            self.coordinator.redirect_session(
                session_id=session.id,
                target_role_name="implementer",
            )

    def test_run_loop_once_auto_recovers_dead_owner_runtime(self) -> None:
        backend = AutoRecoveryRecordingBackend()
        self.session_backend = backend
        self.coordinator.session_backend = backend
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30004AUTORECOVER")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        assert implementer_role is not None
        dead_handle = implementer_role.runtime_handle
        assert dead_handle is not None
        backend.mark_dead(dead_handle)

        event, session_count, chunk_count = self.coordinator.run_loop_once()

        self.assertIsNone(event)
        self.assertEqual(1, session_count)
        self.assertEqual(0, chunk_count)
        refreshed_session = self.session_repository.get_by_id(session.id)
        refreshed_role = self.role_repository.get_by_name(session.id, "implementer")
        assert refreshed_session is not None
        assert refreshed_role is not None
        self.assertEqual("active", refreshed_session.status.value)
        self.assertEqual("implementer", refreshed_session.current_owner)
        self.assertNotEqual(dead_handle, refreshed_role.runtime_handle)
        events = self.event_repository.list_for_session(session.id)
        self.assertTrue(any(item.event_type == "runtime_role_auto_recovery_attempted" for item in events))
        self.assertTrue(any(item.event_type == "role_input_dispatched" for item in events))
        sent_inputs = backend.get_sent_inputs(refreshed_role.runtime_handle)
        self.assertEqual(1, len(sent_inputs))
        summary = self.coordinator.get_runtime_state_summary(session.id)
        self.assertIsNotNone(summary["last_auto_recovery"])
        self.assertEqual("implementer", summary["last_auto_recovery"]["role_name"])

    def test_run_loop_once_reconciles_stale_story_planning_owner_without_recovery(self) -> None:
        backend = AutoRecoveryRecordingBackend()
        self.session_backend = backend
        self.coordinator.session_backend = backend
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004PLANOWNER",
            workflow_profile="story_full",
            policy={"review_policy": "disabled"},
        )
        constraints_role = self.role_repository.get_by_name(session.id, CONSTRAINTS_WORKER_ROLE)
        spec_verifier_role = self.role_repository.get_by_name(session.id, SPEC_VERIFIER_WORKER_ROLE)
        assert constraints_role is not None
        assert spec_verifier_role is not None
        constraints_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="constraints",
            title=f"Constraints for {session.task_key}",
            owner_role_id=constraints_role.id,
            priority=100,
        )
        spec_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="spec_verification",
            title=f"Spec verification for {session.task_key}",
            owner_role_id=spec_verifier_role.id,
            priority=99,
        )
        self.work_item_repository.update_status(constraints_item.id, WorkItemStatus.COMPLETED)
        self.work_item_repository.update_status(spec_item.id, WorkItemStatus.ASSIGNED)
        self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="spec_verification_requested",
            current_owner=CONSTRAINTS_WORKER_ROLE,
        )
        dead_handle = constraints_role.runtime_handle
        assert dead_handle is not None
        backend.mark_dead(dead_handle)

        event, session_count, chunk_count = self.coordinator.run_loop_once()

        self.assertIsNone(event)
        self.assertEqual(1, session_count)
        self.assertEqual(0, chunk_count)
        refreshed_session = self.session_repository.get_by_id(session.id)
        refreshed_constraints_role = self.role_repository.get_by_name(session.id, CONSTRAINTS_WORKER_ROLE)
        assert refreshed_session is not None
        assert refreshed_constraints_role is not None
        self.assertEqual(SPEC_VERIFIER_WORKER_ROLE, refreshed_session.current_owner)
        self.assertEqual(RoleStatus.STOPPED, refreshed_constraints_role.status)
        events = self.event_repository.list_for_session(session.id)
        self.assertTrue(any(item.event_type == "session_owner_reconciled" for item in events))
        self.assertFalse(
            any(
                item.event_type == "runtime_role_auto_recovery_attempted"
                and item.payload.get("role_name") == CONSTRAINTS_WORKER_ROLE
                for item in events
            )
        )

    def test_run_loop_once_escalates_when_auto_recovery_fails(self) -> None:
        backend = AutoRecoveryRecordingBackend()
        self.session_backend = backend
        self.coordinator.session_backend = backend
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30004AUTORECOVERFAIL")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        assert implementer_role is not None
        dead_handle = implementer_role.runtime_handle
        assert dead_handle is not None
        backend.mark_dead(dead_handle)
        backend.fail_spawn_for.add((f"recording-IOS-30004AUTORECOVERFAIL", "implementer"))

        event, session_count, chunk_count = self.coordinator.run_loop_once()

        self.assertIsNone(event)
        self.assertEqual(1, session_count)
        self.assertEqual(0, chunk_count)
        refreshed_session = self.session_repository.get_by_id(session.id)
        refreshed_role = self.role_repository.get_by_name(session.id, "implementer")
        assert refreshed_session is not None
        assert refreshed_role is not None
        self.assertEqual("waiting_for_operator", refreshed_session.status.value)
        self.assertIsNone(refreshed_session.current_owner)
        self.assertEqual("failed", refreshed_role.status.value)
        work_items = self.work_item_repository.list_for_session(session.id)
        self.assertTrue(any(item.status.value == "waiting_for_operator" for item in work_items))
        events = self.event_repository.list_for_session(session.id)
        self.assertTrue(any(item.event_type == "runtime_role_auto_recovery_failed" for item in events))
        self.assertTrue(any(item.event_type == "session_escalated_to_operator" for item in events))


if __name__ == "__main__":
    unittest.main()
