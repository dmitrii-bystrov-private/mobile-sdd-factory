from pathlib import Path
import json
import tempfile
import time
import unittest
from unittest.mock import patch

from backend.api.sse import SessionEventBus
from backend import session_policy as session_policy_module
from backend.coordinator.intake import IntakeError
from backend.coordinator.service import CoordinatorService
from backend.models.enums import SessionStatus
from backend.roles.contracts import (
    ALLOWED_STAGE_ROLE_TARGETS,
    BUG_FIXER_ROLE,
    CODE_REVIEWER_ROLE,
    CODE_SCOUT_ROLE,
    DOC_HARVEST_ROLE,
    DEFAULT_SESSION_ROLES,
    ACCEPTANCE_CRITERIA_WORKER_ROLE,
    CONSTRAINTS_WORKER_ROLE,
    IMPLEMENTER_ROLE,
    MR_COMMENTS_ANALYST_ROLE,
    PROPOSAL_CONTEXT_WORKER_ROLE,
    REQUIREMENTS_CLARIFIER_WORKER_ROLE,
    SPEC_VERIFIER_WORKER_ROLE,
    TASK_DECOMPOSER_WORKER_ROLE,
    STORY_SPEC_WORKER_ROLE,
)
from backend.roles.launcher import RoleLauncherManager
from backend.role_runtime_config import normalize_role_runtime_config
from backend.roles.workspace import RoleWorkspaceManager
from backend.session_backend.recording_backend import RecordingSessionBackend
from backend.session_backend.tmux_backend import TmuxSessionBackend
from backend.session_backend.runtime_models import RuntimeRoleHandle, RuntimeSessionHandle
from backend.state.artifact_repository import ArtifactRepository
from backend.state.db import Database
from backend.state.event_repository import EventRepository
from backend.state.role_repository import RoleRepository
from backend.state.session_repository import SessionRepository
from backend.state.work_item_repository import WorkItemRepository
from backend.tools.command_runner import CommandResult


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

    def set_statuses_output(self, task_key: str, content: str) -> None:
        self.statuses_by_task[task_key] = content

    def run(self, task_key: str) -> CommandResult:
        self.calls.append(task_key)
        if self.workdir_root is not None and task_key in self.statuses_by_task:
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

    def fetch_mr_comments(self, platform: str, mr_id: str) -> CommandResult:
        return CommandResult(
            command=["fetch_mr_comments", platform, mr_id],
            returncode=0,
            stdout=(
                f"# Unresolved MR discussions: !{mr_id} (2 total)\n\n"
                "## Discussion 1 — file_a.swift:10\n\n"
                "**Reviewer:** First comment\n\n"
                "---\n\n"
                "## Discussion 2 — file_b.swift:20\n\n"
                "**Reviewer:** Second comment\n\n"
                "---\n"
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


class SessionCreationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self._original_boy_scout_default = session_policy_module.COMMON_DEFAULTS["boy_scout_policy"]
        self._original_self_review_default = session_policy_module.COMMON_DEFAULTS["self_review_policy"]
        self._original_doc_harvest_default = session_policy_module.COMMON_DEFAULTS["doc_harvest_policy"]
        session_policy_module.COMMON_DEFAULTS["boy_scout_policy"] = "disabled"
        session_policy_module.COMMON_DEFAULTS["self_review_policy"] = "disabled"
        session_policy_module.COMMON_DEFAULTS["doc_harvest_policy"] = "disabled"
        self.db_path = Path(self.temp_dir.name) / "factory.sqlite3"
        self.database = Database(self.db_path)
        self.database.initialize()

        self.session_repository = SessionRepository(self.database)
        self.role_repository = RoleRepository(self.database)
        self.event_repository = EventRepository(self.database)
        self.artifact_repository = ArtifactRepository(self.database)
        self.work_item_repository = WorkItemRepository(self.database)
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
        )

    def tearDown(self) -> None:
        session_policy_module.COMMON_DEFAULTS["boy_scout_policy"] = self._original_boy_scout_default
        session_policy_module.COMMON_DEFAULTS["self_review_policy"] = self._original_self_review_default
        session_policy_module.COMMON_DEFAULTS["doc_harvest_policy"] = self._original_doc_harvest_default
        self.temp_dir.cleanup()

    def write_statuses_file(self, task_key: str, content: str) -> None:
        task_dir = Path(self.temp_dir.name) / task_key
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "statuses.md").write_text(content)

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
                "self_review_policy": "disabled",
                "boy_scout_policy": "disabled",
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
                                "runner": "codex",
                                "model": "gpt-5.5",
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
                "runner": "codex",
                "model": "gpt-5.5",
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
                        "mcp_servers": ["notion", "ios-rag", "android-rag", "frontend-rag"],
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
                "self_review_policy": "enabled",
                "boy_scout_policy": "enabled",
                "doc_harvest_policy": "enabled",
                "requirements_clarification_mode": "ask-selectively",
            },
            role_config={
                "proposal-context-worker": {
                    "runner": "codex",
                    "model": "gpt-5.5",
                    "effort": "medium",
                },
                "requirements-clarifier-worker": {
                    "runner": "claude",
                    "model": "sonnet",
                    "effort": "medium",
                },
                "code-scout": {
                    "runner": "codex",
                    "model": "gpt-5.5",
                    "effort": "high",
                },
                "doc-harvest-worker": {
                    "runner": "claude",
                    "model": "sonnet",
                    "effort": "medium",
                },
                "mr-comments-analyst-worker": {
                    "runner": "codex",
                    "model": "gpt-5.5",
                    "effort": "medium",
                },
            },
        )

        self.assertEqual(
            {
                "runner": "codex",
                "model": "gpt-5.5",
                "effort": "medium",
            },
            session.role_config["proposal-context-worker"],
        )
        self.assertEqual(
            {
                "runner": "codex",
                "model": "gpt-5.5",
                "effort": "high",
            },
            session.role_config["code-scout"],
        )
        self.assertEqual(
            {
                "runner": "claude",
                "model": "sonnet",
                "effort": "medium",
            },
            session.role_config["doc-harvest-worker"],
        )
        self.assertIn("mr-comments-analyst-worker", session.role_config)

    def test_send_operator_runtime_input_reactivates_waiting_session_without_new_handoff(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30002",
            workflow_profile="oneshot",
            policy={
                "self_review_policy": "disabled",
                "boy_scout_policy": "disabled",
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

    def test_get_interactive_state_summary_uses_latest_runtime_error(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003",
            workflow_profile="oneshot",
            policy={
                "self_review_policy": "disabled",
                "boy_scout_policy": "disabled",
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
                "self_review_policy": "disabled",
                "boy_scout_policy": "disabled",
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

    def test_get_interactive_state_summary_runtime_error_does_not_require_operator_input(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004RUNTIME",
            workflow_profile="oneshot",
            policy={
                "self_review_policy": "disabled",
                "boy_scout_policy": "disabled",
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
                "self_review_policy": "disabled",
                "boy_scout_policy": "disabled",
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
            policy={"self_review_policy": "required"},
        )

        self.assertIsNotNone(session.id)
        for role_name in DEFAULT_SESSION_ROLES + [CODE_REVIEWER_ROLE]:
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
        self.assertIn("Treat final test+lint verification as deferred to the coordinator.", implementer_agents)
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
            / CODE_REVIEWER_ROLE
            / "AGENTS.md"
        ).read_text()
        self.assertIn("Project conventions:", reviewer_agents)
        self.assertIn("Read previous review reports first when they are provided", reviewer_agents)
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
        self.assertIn("If an `Issues file:` path is routed, treat it as the primary narrow-scope input", bug_fixer_agents)
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

    def test_claude_launcher_generates_role_scoped_mcp_files(self) -> None:
        repo_root = Path(self.temp_dir.name) / "repo-root-mcp"
        (repo_root / ".claude" / "agents").mkdir(parents=True, exist_ok=True)
        (repo_root / ".claude" / "settings.local.json").write_text(
            json.dumps(
                {
                    "env": {"DOC_HARVEST_ENABLED": "true"},
                    "permissions": {
                        "allow": [
                            "Bash(git status)",
                            "mcp__ios-rag__search",
                            "mcp__frontend-rag__read_file",
                            "mcp__notion__search",
                        ]
                    },
                    "enabledMcpjsonServers": [
                        "ios-rag",
                        "frontend-rag",
                        "notion",
                    ],
                }
            )
        )
        (repo_root / ".mcp.json").write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "ios-rag": {"type": "http", "url": "https://example.com/ios"},
                        "frontend-rag": {"type": "http", "url": "https://example.com/frontend"},
                        "notion": {"type": "http", "url": "https://example.com/notion"},
                    }
                }
            )
        )
        (repo_root / ".claude" / "agents" / "implementer.md").write_text(
            "\n".join(
                [
                    "---",
                    "name: implementer",
                    "model: sonnet",
                    "effort: medium",
                    "mcpServers:",
                    "  - ios-rag",
                    "  - frontend-rag",
                    "---",
                    "",
                ]
            )
        )
        (repo_root / ".claude" / "agents" / "code-reviewer.md").write_text(
            "\n".join(
                [
                    "---",
                    "name: code-reviewer",
                    "model: sonnet",
                    "effort: medium",
                    "mcpServers: []",
                    "---",
                    "",
                ]
            )
        )
        (repo_root / ".claude" / "agents" / "proposal-collector.md").write_text(
            "\n".join(
                [
                    "---",
                    "name: proposal-collector",
                    "model: sonnet",
                    "effort: medium",
                    "mcpServers:",
                    "  - notion",
                    "---",
                    "",
                ]
            )
        )
        (repo_root / ".claude" / "agents" / "context-collector.md").write_text(
            "\n".join(
                [
                    "---",
                    "name: context-collector",
                    "model: sonnet",
                    "effort: high",
                    "mcpServers:",
                    "  - ios-rag",
                    "  - frontend-rag",
                    "---",
                    "",
                ]
            )
        )

        workspace_manager = RoleWorkspaceManager(
            runtime_root=Path(self.temp_dir.name),
            repo_root=repo_root,
            workdir_root=Path(self.temp_dir.name),
        )
        launcher_manager = RoleLauncherManager(
            repo_root=repo_root,
            workdir_root=Path(self.temp_dir.name),
        )
        implementer_workspace = workspace_manager.ensure_role_workspace("IOS-30000MCP", "implementer")
        launcher_manager.ensure_launch_plan(
            task_key="IOS-30000MCP",
            workspace=implementer_workspace,
            role_config={"runner": "claude", "model": "sonnet", "effort": "medium"},
        )

        implementer_settings = json.loads(
            (implementer_workspace.directory / "claude.settings.role.json").read_text()
        )
        self.assertEqual(
            ["ios-rag", "android-rag", "frontend-rag"],
            implementer_settings["enabledMcpjsonServers"],
        )
        self.assertEqual(
            [
                "Bash(git status)",
                "mcp__ios-rag__search",
                "mcp__frontend-rag__read_file",
            ],
            implementer_settings["permissions"]["allow"],
        )
        implementer_mcp = json.loads(
            (implementer_workspace.directory / "claude.mcp.role.json").read_text()
        )
        self.assertEqual(
            {"ios-rag", "frontend-rag"},
            set(implementer_mcp["mcpServers"].keys()),
        )
        implementer_script = (implementer_workspace.directory / "launch-role.sh").read_text()
        self.assertIn("SDD_FACTORY_CLAUDE_SETTINGS=", implementer_script)
        self.assertIn("SDD_FACTORY_CLAUDE_MCP_CONFIG=", implementer_script)

        reviewer_workspace = workspace_manager.ensure_role_workspace("IOS-30000MCP", "code-reviewer")
        launcher_manager.ensure_launch_plan(
            task_key="IOS-30000MCP",
            workspace=reviewer_workspace,
            role_config={"runner": "claude", "model": "sonnet", "effort": "medium"},
        )
        reviewer_settings = json.loads(
            (reviewer_workspace.directory / "claude.settings.role.json").read_text()
        )
        self.assertEqual([], reviewer_settings["enabledMcpjsonServers"])
        reviewer_mcp = json.loads(
            (reviewer_workspace.directory / "claude.mcp.role.json").read_text()
        )
        self.assertEqual({}, reviewer_mcp["mcpServers"])

        proposal_context_workspace = workspace_manager.ensure_role_workspace(
            "IOS-30000MCP",
            PROPOSAL_CONTEXT_WORKER_ROLE,
        )
        launcher_manager.ensure_launch_plan(
            task_key="IOS-30000MCP",
            workspace=proposal_context_workspace,
            role_config={"runner": "claude", "model": "sonnet", "effort": "medium"},
        )
        proposal_context_settings = json.loads(
            (proposal_context_workspace.directory / "claude.settings.role.json").read_text()
        )
        self.assertEqual(
            {"ios-rag", "android-rag", "frontend-rag", "notion"},
            set(proposal_context_settings["enabledMcpjsonServers"]),
        )
        proposal_context_mcp = json.loads(
            (proposal_context_workspace.directory / "claude.mcp.role.json").read_text()
        )
        self.assertEqual(
            {"ios-rag", "frontend-rag", "notion"},
            set(proposal_context_mcp["mcpServers"].keys()),
        )

    def test_real_launcher_backed_runtime_keeps_persistent_role_context_across_rounds(self) -> None:
        runtime_root = Path(self.temp_dir.name)
        repo_root = Path(self.temp_dir.name) / "repo-root-real-launcher"
        session_backend = RecordingSessionBackend()
        coordinator = CoordinatorService(
            session_repository=self.session_repository,
            role_repository=self.role_repository,
            event_repository=self.event_repository,
            artifact_repository=self.artifact_repository,
            work_item_repository=self.work_item_repository,
            session_backend=session_backend,
            default_roles=DEFAULT_SESSION_ROLES,
            jira_adapter=FakeJiraAdapter(),
            snapshot_adapter=FakeSnapshotAdapter(),
            gitlab_adapter=FakeGitLabAdapter(),
            artifacts_root=Path(self.temp_dir.name) / "artifacts-real-launcher",
            workdir_root=Path(self.temp_dir.name),
            event_bus=self.event_bus,
            role_workspace_manager=RoleWorkspaceManager(
                runtime_root=runtime_root,
                repo_root=repo_root,
                workdir_root=Path(self.temp_dir.name),
            ),
            role_launcher_manager=RoleLauncherManager(
                repo_root=repo_root,
                workdir_root=Path(self.temp_dir.name),
            ),
        )

        session, _, _ = coordinator.create_task_session(
            "IOS-30000E2E",
            workflow_profile="oneshot",
            policy={
                "self_review_policy": "required",
                "boy_scout_policy": "disabled",
                "doc_harvest_policy": "enabled",
            },
        )
        prepared_session, _, _, _ = coordinator.prepare_task_session("IOS-30000E2E")

        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        reviewer_role = self.role_repository.get_by_name(session.id, CODE_REVIEWER_ROLE)
        verifier_role = self.role_repository.get_by_name(session.id, "verification-coordinator")

        for role in (implementer_role, reviewer_role, verifier_role):
            spawn_command = session_backend.get_spawn_command(role.runtime_handle)
            self.assertEqual(1, len(spawn_command))
            launch_script_text = Path(spawn_command[0]).read_text()
            self.assertIn("/factory/scripts/run-role-agent.sh", launch_script_text)

        coordinator.handle_operator_event(
            session_id=prepared_session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )
        coordinator.handle_role_output(
            session_id=prepared_session.id,
            role_name=CODE_REVIEWER_ROLE,
            output_type="passed",
            payload={"summary": "clean review"},
        )
        coordinator.handle_role_output(
            session_id=prepared_session.id,
            role_name="verification-coordinator",
            output_type="failed",
            payload={"summary": "verification failed", "failures": ["lint"]},
        )
        coordinator.handle_operator_event(
            session_id=prepared_session.id,
            event_type="implementation_completed",
            payload={"summary": "verification correction done"},
        )

        implementer_inputs = session_backend.get_sent_inputs(implementer_role.runtime_handle)
        reviewer_inputs = session_backend.get_sent_inputs(reviewer_role.runtime_handle)
        verifier_inputs = session_backend.get_sent_inputs(verifier_role.runtime_handle)

        self.assertEqual(2, len(implementer_inputs))
        self.assertIn("Read AGENTS.md/CLAUDE.md in the current directory now.", implementer_inputs[0])
        self.assertIn(
            "Continue from your existing implementer role context in this persistent task session.",
            implementer_inputs[1],
        )

        self.assertEqual(1, len(reviewer_inputs))
        self.assertIn("Role-specific rules:", reviewer_inputs[0])
        self.assertIn("review_scope", reviewer_inputs[0])

        self.assertEqual(2, len(verifier_inputs))
        self.assertIn("Read AGENTS.md/CLAUDE.md in the current directory now.", verifier_inputs[0])
        self.assertIn(
            "Continue from your existing verification-coordinator role context in this persistent task session.",
            verifier_inputs[1],
        )

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
        self.assertEqual(3, len(roles))

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
                policy={"self_review_policy": "required"},
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
        self.assertIn("Read AGENTS.md/CLAUDE.md in the current directory now.", sent_inputs[0])
        self.assertIn("Role-specific rules:", sent_inputs[0])
        self.assertIn("Use RAG tools first for code exploration", sent_inputs[0])
        self.assertIn("Final test+lint gate remains deferred to the coordinator.", sent_inputs[0])

    def test_prepare_task_session_reuses_existing_policy_aware_session(self) -> None:
        session, _, created = self.coordinator.create_task_session(
            "IOS-30002A",
            workflow_profile="oneshot",
            policy={
                "self_review_policy": "required",
                "boy_scout_policy": "disabled",
                "doc_harvest_policy": "enabled",
            },
        )

        prepared_session, event, prepared_created, details = self.coordinator.prepare_task_session("IOS-30002A")

        self.assertTrue(created)
        self.assertFalse(prepared_created)
        self.assertEqual(session.id, prepared_session.id)
        self.assertEqual("oneshot", prepared_session.workflow_profile)
        self.assertEqual("required", prepared_session.policy["self_review_policy"])
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
                "role_input_dispatched",
                "bug_analysis_requested",
            ],
            [item.event_type for item in events],
        )
        self.assertEqual(1, len(sent_inputs))
        self.assertIn("Mode: analysis-only", sent_inputs[0])
        self.assertIn("Analyze bug IOS-30002BUG before implementation.", sent_inputs[0])
        self.assertIn("Test policy for this session: required.", sent_inputs[0])
        self.assertIn("Role-specific rules:", sent_inputs[0])
        self.assertIn("In `analysis-only` mode, read task description/comments first", sent_inputs[0])
        self.assertIn('"bug_analysis_report_path"', sent_inputs[0])
        self.assertIn('"bug_mode": "analysis-only"', sent_inputs[0])
        self.assertIn('"primary_bug_inputs": "description.md + comments.md"', sent_inputs[0])

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
                "role_input_dispatched",
                "implementation_requested",
                "implementation_completed",
                "git_commit_completed",
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
        self.assertIn("Read AGENTS.md/CLAUDE.md in the current directory now.", sent_inputs[0])
        self.assertIn("Role-specific rules:", sent_inputs[0])
        self.assertIn("Use `run-test.sh` and `run-lint.sh`; do not run `run-build.sh` here.", sent_inputs[0])
        self.assertIn("verification_report_path", sent_inputs[0])

    def test_implementation_completed_routes_to_reviewer_when_self_review_required(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003R",
            workflow_profile="oneshot",
            policy={
                "self_review_policy": "required",
                "boy_scout_policy": "disabled",
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
            if item.work_type == "self_review"
        ]
        reviewer_role = self.role_repository.get_by_name(session.id, CODE_REVIEWER_ROLE)
        sent_inputs = self.session_backend.get_sent_inputs(reviewer_role.runtime_handle)

        self.assertEqual("self_review_requested", updated_session.current_stage)
        self.assertEqual(CODE_REVIEWER_ROLE, updated_session.current_owner)
        self.assertEqual("self_review_requested", followup_event.event_type)
        self.assertEqual(1, len(review_items))
        self.assertEqual(1, len(sent_inputs))
        self.assertIn("Review the current task changes for IOS-30003R.", sent_inputs[0])
        self.assertIn("Role-specific rules:", sent_inputs[0])
        self.assertIn("Start from the current diff and review only the touched changes.", sent_inputs[0])
        self.assertIn("review_scope", sent_inputs[0])

    def test_reviewer_output_passed_routes_self_review_to_verification(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003RP",
            workflow_profile="oneshot",
            policy={
                "self_review_policy": "required",
                "boy_scout_policy": "disabled",
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
            role_name=CODE_REVIEWER_ROLE,
            output_type="passed",
            payload={"summary": "clean review"},
        )
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual("self_review_passed", mapped_event.event_type)
        self.assertEqual("verification_requested", followup_event.event_type)
        self.assertEqual("verification_requested", updated_session.current_stage)
        self.assertEqual("verification-coordinator", updated_session.current_owner)
        self.assertTrue(any(item.artifact_type == "self_review_report_markdown" for item in artifacts))

    def test_reviewer_output_failed_routes_self_review_to_correction(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003RF",
            workflow_profile="oneshot",
            policy={
                "self_review_policy": "required",
                "boy_scout_policy": "disabled",
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
            role_name=CODE_REVIEWER_ROLE,
            output_type="failed",
            payload={"summary": "issues remain"},
        )
        artifacts = self.artifact_repository.list_for_session(session.id)
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        sent_inputs = self.session_backend.get_sent_inputs(implementer_role.runtime_handle)

        self.assertEqual("self_review_issues_found", mapped_event.event_type)
        self.assertEqual("self_review_correction_requested", followup_event.event_type)
        self.assertEqual("self_review_correction_requested", updated_session.current_stage)
        self.assertEqual("implementer", updated_session.current_owner)
        self.assertTrue(any(item.artifact_type == "self_review_report_markdown" for item in artifacts))
        self.assertIn('"issues_file_path"', sent_inputs[-1])
        self.assertIn("pass-01.md", sent_inputs[-1])

    def test_reviewer_can_block_non_converging_self_review_cycle(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003RBLOCK",
            workflow_profile="oneshot",
            policy={
                "self_review_policy": "required",
                "boy_scout_policy": "disabled",
                "doc_harvest_policy": "disabled",
            },
        )
        prepared_session, _, _, _ = self.coordinator.prepare_task_session("IOS-30003RBLOCK")
        self.coordinator.handle_operator_event(
            session_id=prepared_session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )

        updated_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=prepared_session.id,
            role_name=CODE_REVIEWER_ROLE,
            output_type="blocked_review_cycle",
            payload={
                "summary": "Repeated reducer violation remains unresolved.",
                "details": "Two review passes raised the same reducer issue and the loop no longer converges.",
                "issues": [
                    {
                        "severity": "error",
                        "file": "Sources/Feature/FeatureViewModel.swift",
                        "convention": "Feature template",
                        "problem": "State mutation still bypasses the reducer.",
                        "required_change": "Route the mutation through the reducer path.",
                    }
                ],
            },
        )
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual("self_review_blocked", mapped_event.event_type)
        self.assertEqual("session_escalated_to_operator", followup_event.event_type)
        self.assertEqual("waiting_for_operator", updated_session.status.value)
        self.assertEqual("self_review_requested", updated_session.current_stage)
        self.assertEqual(CODE_REVIEWER_ROLE, updated_session.current_owner)
        self.assertEqual("self_review_cycle", str(followup_event.payload.get("reason") or ""))
        self.assertTrue(any(item.artifact_type == "self_review_report_markdown" for item in artifacts))

    def test_resume_session_retries_reviewer_after_blocked_self_review_cycle(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003RBLOCKRESUME",
            workflow_profile="oneshot",
            policy={
                "self_review_policy": "required",
                "boy_scout_policy": "disabled",
                "doc_harvest_policy": "disabled",
            },
        )
        prepared_session, _, _, _ = self.coordinator.prepare_task_session("IOS-30003RBLOCKRESUME")
        self.coordinator.handle_operator_event(
            session_id=prepared_session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )
        self.coordinator.handle_role_output(
            session_id=prepared_session.id,
            role_name=CODE_REVIEWER_ROLE,
            output_type="blocked_review_cycle",
            payload={
                "summary": "Repeated reducer violation remains unresolved.",
                "details": "The review loop no longer converges.",
                "issues": [
                    {
                        "severity": "error",
                        "file": "Sources/Feature/FeatureViewModel.swift",
                        "convention": "Feature template",
                        "problem": "State mutation still bypasses the reducer.",
                        "required_change": "Route the mutation through the reducer path.",
                    }
                ],
            },
        )

        resumed_session, resumed_event, dispatch_event = self.coordinator.resume_session(session.id)
        reviewer_role = self.role_repository.get_by_name(session.id, CODE_REVIEWER_ROLE)
        sent_inputs = self.session_backend.get_sent_inputs(reviewer_role.runtime_handle)

        self.assertEqual("active", resumed_session.status.value)
        self.assertEqual(CODE_REVIEWER_ROLE, resumed_session.current_owner)
        self.assertEqual("session_resumed_by_operator", resumed_event.event_type)
        self.assertIsNotNone(dispatch_event)
        assert dispatch_event is not None
        self.assertEqual("role_input_dispatched", dispatch_event.event_type)
        self.assertIn("blocked_review_cycle", sent_inputs[-1])

    def test_second_self_review_dispatch_includes_previous_review_report_paths(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003R2",
            workflow_profile="oneshot",
            policy={
                "self_review_policy": "required",
                "boy_scout_policy": "enabled",
                "doc_harvest_policy": "enabled",
            },
        )
        prepared_session, _, _, _ = self.coordinator.prepare_task_session("IOS-30003R2")
        self.coordinator.handle_operator_event(
            session_id=prepared_session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )
        _, review_event, _ = self.coordinator.handle_role_output(
            session_id=prepared_session.id,
            role_name=CODE_REVIEWER_ROLE,
            output_type="failed",
            payload={"summary": "issues remain"},
        )

        refreshed = self.coordinator._get_session_or_raise(session.id)
        self.coordinator._enqueue_self_review(session=refreshed, source_event=review_event)

        reviewer_role = self.role_repository.get_by_name(session.id, CODE_REVIEWER_ROLE)
        sent_inputs = self.session_backend.get_sent_inputs(reviewer_role.runtime_handle)
        self.assertEqual(2, len(sent_inputs))
        self.assertIn(
            "Previous review reports (read first and do not re-flag the same issues):",
            sent_inputs[-1],
        )
        self.assertIn("previous_review_report_paths", sent_inputs[-1])
        self.assertIn("review_report_path", sent_inputs[-1])

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
                "role_input_dispatched",
                "bug_analysis_requested",
                "bug_analysis_completed",
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
        self.assertIn("Continue from your existing bug-fixer role context", bug_fixer_inputs[-1])
        self.assertIn('"bug_analysis_report_path"', bug_fixer_inputs[-1])
        self.assertIn('"bug_mode": "fix-only"', bug_fixer_inputs[-1])
        self.assertIn("In `fix-only` mode, read the saved `spec/bug-analysis.md` first", bug_fixer_inputs[-1])

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
                "role_input_dispatched",
                "proposal_context_requested",
            ],
            [item.event_type for item in events],
        )
        self.assertEqual(1, len(sent_inputs))
        self.assertIn("Produce the proposal and context package for story IOS-30002STORY before requirements and final story spec.", sent_inputs[0])
        self.assertIn("Read `description.md` and `comments.md`", sent_inputs[0])
        self.assertIn("comments take precedence over description when they conflict", sent_inputs[0])
        self.assertIn("use Notion MCP for `notion.so` links", sent_inputs[0])
        self.assertIn("treat non-Notion external links as operator-provided context references", sent_inputs[0])
        self.assertIn("Role-specific rules:", sent_inputs[0])
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
        self.assertIn("bounded one-shot worker", proposal_agents)
        self.assertIn("comments.md` as the fresher source", proposal_agents)
        self.assertIn("Notion MCP for `notion.so` content", proposal_agents)
        self.assertIn("non-Notion external links as operator-provided context references", proposal_agents)
        self.assertIn("SDD_FACTORY_ROLE_LIFECYCLE=one-shot", launch_script_text)
        self.assertIn("lifecycle=%s", launch_script_text)

    def test_proposal_context_link_warning_emits_event_and_artifact_for_non_notion_links(self) -> None:
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
        self.assertEqual(1, events[-1].payload["link_count"])
        warning_artifact = next(
            artifact for artifact in artifacts if artifact.artifact_type == "proposal_external_links_warning"
        )
        warning_text = Path(warning_artifact.path).read_text()
        self.assertIn("https://example.com/spec", warning_text)
        self.assertNotIn("notion.so/page", warning_text)

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
        self.assertTrue(hydration["feature_overview_path"].endswith("spec/context/feature-overview.md"))
        self.assertTrue(hydration["proposal_path"].endswith("spec/proposal.md"))

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
        self.assertEqual("acceptance_criteria_requested", followup_event.event_type)
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

    def test_spec_verification_completed_moves_story_session_to_story_spec(self) -> None:
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
        spec_role = self.role_repository.get_by_name(session.id, STORY_SPEC_WORKER_ROLE)
        sent_inputs = self.session_backend.get_sent_inputs(spec_role.runtime_handle)

        self.assertEqual("story_spec_requested", updated_session.current_stage)
        self.assertEqual(STORY_SPEC_WORKER_ROLE, updated_session.current_owner)
        self.assertEqual("story_spec_requested", followup_event.event_type)
        self.assertEqual(
            [
                ("acceptance_criteria", "completed"),
                ("constraints", "completed"),
                ("proposal_context", "completed"),
                ("requirements", "completed"),
                ("spec_verification", "completed"),
                ("story_spec", "assigned"),
            ],
            sorted((item.work_type, item.status.value) for item in work_items),
        )
        self.assertEqual(1, len(sent_inputs))
        self.assertIn("Prepare the final implementation-shaping story spec for IOS-30003VERIFY before coding.", sent_inputs[0])
        self.assertIn("durable implementation guide", sent_inputs[0])
        self.assertIn("Planning verification summary: Planning package is coherent", sent_inputs[0])
        self.assertIn("Verified focus: navigation + state ownership", sent_inputs[0])

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

        self.assertEqual("spec_verification_blocked", mapped_event.event_type)
        self.assertEqual("session_escalated_to_operator", followup_event.event_type)
        self.assertEqual("waiting_for_operator", updated_session.status.value)
        self.assertEqual("spec_verification_requested", updated_session.current_stage)
        self.assertEqual(SPEC_VERIFIER_WORKER_ROLE, updated_session.current_owner)
        self.assertTrue(bool(followup_event.payload.get("needs_operator_input")))
        self.assertTrue(any(item.work_type == "spec_verification" and item.status.value == "waiting_for_operator" for item in work_items))

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
        self.assertEqual("spec_verification_blockers", summary["source_reason"])
        self.assertEqual(SPEC_VERIFIER_WORKER_ROLE, summary["role_name"])
        self.assertTrue(summary["needs_operator_input"])

    def test_story_spec_completed_moves_session_to_task_decomposition(self) -> None:
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
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="spec_verification_completed",
            payload={"summary": "Planning verified"},
        )

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="story_spec_completed",
            payload={
                "summary": "Need a new screen plus navigation wiring",
                "constraints": "Reuse existing assembly pattern and analytics hooks",
            },
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        events = self.event_repository.list_for_session(session.id)
        decomposer_role = self.role_repository.get_by_name(session.id, TASK_DECOMPOSER_WORKER_ROLE)
        sent_inputs = self.session_backend.get_sent_inputs(decomposer_role.runtime_handle)
        spec_role = self.role_repository.get_by_name(session.id, STORY_SPEC_WORKER_ROLE)

        self.assertEqual("task_decomposition_requested", updated_session.current_stage)
        self.assertEqual(TASK_DECOMPOSER_WORKER_ROLE, updated_session.current_owner)
        self.assertEqual("task_decomposition_requested", followup_event.event_type)
        self.assertEqual("stopped", spec_role.status.value)
        self.assertEqual(
            [
                ("acceptance_criteria", "completed"),
                ("constraints", "completed"),
                ("proposal_context", "completed"),
                ("requirements", "completed"),
                ("spec_verification", "completed"),
                ("story_spec", "completed"),
                ("task_decomposition", "assigned"),
            ],
            sorted((item.work_type, item.status.value) for item in work_items),
        )
        self.assertEqual(
            [
                "task_started",
                "task_session_reused",
                "task_prepared",
                "role_input_dispatched",
                "proposal_context_requested",
                "proposal_context_completed",
                "role_input_dispatched",
                "requirements_requested",
                "requirements_completed",
                "role_input_dispatched",
                "acceptance_criteria_requested",
                "acceptance_criteria_completed",
                "role_input_dispatched",
                "constraints_requested",
                "constraints_completed",
                "role_input_dispatched",
                "spec_verification_requested",
                "spec_verification_completed",
                "role_input_dispatched",
                "story_spec_requested",
                "story_spec_completed",
                "role_input_dispatched",
                "task_decomposition_requested",
            ],
            [item.event_type for item in events],
        )
        self.assertEqual(1, len(sent_inputs))
        self.assertIn("Prepare task decomposition for story IOS-30003STORY before implementation starts.", sent_inputs[0])
        self.assertIn("Always produce a durable `plan/index.md` plus self-contained `plan/NN-*.md` task package", sent_inputs[0])
        self.assertIn("Story spec summary: Need a new screen plus navigation wiring", sent_inputs[0])

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

        self.assertEqual("implementation_requested", updated_session.current_stage)
        self.assertEqual("implementer", updated_session.current_owner)
        self.assertEqual("active", updated_session.status.value)
        self.assertEqual("implementation_requested", followup_event.event_type)
        self.assertEqual("stopped", decomposer_role.status.value)
        self.assertEqual(
            [
                ("acceptance_criteria", "completed"),
                ("constraints", "completed"),
                ("implementation", "assigned"),
                ("proposal_context", "completed"),
                ("requirements", "completed"),
                ("spec_verification", "completed"),
                ("story_spec", "completed"),
                ("task_decomposition", "completed"),
            ],
            sorted((item.work_type, item.status.value) for item in work_items),
        )
        self.assertEqual(
            [
                "task_started",
                "task_session_reused",
                "task_prepared",
                "role_input_dispatched",
                "proposal_context_requested",
                "proposal_context_completed",
                "role_input_dispatched",
                "requirements_requested",
                "requirements_completed",
                "role_input_dispatched",
                "acceptance_criteria_requested",
                "acceptance_criteria_completed",
                "role_input_dispatched",
                "constraints_requested",
                "constraints_completed",
                "role_input_dispatched",
                "spec_verification_requested",
                "spec_verification_completed",
                "role_input_dispatched",
                "story_spec_requested",
                "story_spec_completed",
                "role_input_dispatched",
                "task_decomposition_requested",
                "task_decomposition_completed",
                "role_input_dispatched",
                "implementation_requested",
                "jira_subtasks_created",
            ],
            [item.event_type for item in events],
        )
        self.assertTrue(implementer_inputs)

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

        self.assertEqual("implementation_requested", followup_event.event_type)
        self.assertEqual("implementation_requested", updated_session.current_stage)
        self.assertEqual("active", updated_session.status.value)
        self.assertTrue((plan_dir / "index.md").is_file())
        self.assertTrue((plan_dir / "01-build-data-source.md").is_file())
        self.assertTrue(
            any(artifact.artifact_type == "task_decomposition_plan_index" for artifact in artifacts)
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

        with self.assertRaisesRegex(IntakeError, "plan_index_markdown"):
            self.coordinator.handle_operator_event(
                session_id=session.id,
                event_type="task_decomposition_completed",
                payload={"summary": "Decomposition prepared"},
            )

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
        (plan_dir / "01-build-data-source.md").write_text(
            "# Build data source\n\n## What to implement\nCreate the feature data source.\n"
        )

        updated_session, event, followup_event = self.coordinator.create_subtasks_from_plan(session.id)
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual(session.id, updated_session.id)
        self.assertEqual("jira_subtasks_created", event.event_type)
        self.assertEqual(["IOS-90001"], event.payload["created_subtask_keys"])
        self.assertIsNone(followup_event)
        self.assertTrue(any(item.artifact_type == "jira_subtasks_stdout" for item in artifacts))
        self.assertTrue(any(item.artifact_type == "jira_subtasks_stderr" for item in artifacts))
        self.assertTrue(any(item.artifact_type == "jira_subtasks_summary" for item in artifacts))
        self.assertTrue(any(item.artifact_type == "subtasks_snapshot_stdout" for item in artifacts))
        self.assertTrue(any(item.artifact_type == "subtasks_snapshot_stderr" for item in artifacts))
        self.assertEqual(0, event.payload["snapshot_refresh_exit_code"])

    def test_create_subtasks_from_plan_auto_starts_subtask_graph_from_active_implementation(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003SUBAUTO",
            workflow_profile="story_full",
            policy={"self_review_policy": "disabled"},
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
                    ("story_spec", "completed"),
                    ("task_decomposition", "completed"),
                    ("subtask_implementation", "assigned"),
                    ("subtask_implementation", "unassigned"),
                ]
            ),
            sorted((item.work_type, item.status.value) for item in work_items),
        )
        self.assertIn("Implement subtask IOS-30010", sent_inputs[-1])
        self.assertIn("Use the routed execution plan artifact as the primary execution plan input.", sent_inputs[-1])
        self.assertIn("decomposition_artifact_path", sent_inputs[-1])

    def test_subtask_completion_assigns_next_subtask_before_verification(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004SUBTASK",
            workflow_profile="story_full",
            policy={"self_review_policy": "disabled"},
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
        self.assertEqual(
            ["assigned", "completed", "completed", "completed", "completed", "completed", "completed", "completed", "completed"],
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

    def test_subtask_completion_refreshes_snapshot_and_rewrites_graph(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004SUBREFRESH",
            workflow_profile="story_full",
            policy={"self_review_policy": "disabled"},
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

    def test_subtask_completion_uses_refreshed_snapshot_as_remaining_source_of_truth(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004SUBTRUTH",
            workflow_profile="story_full",
            policy={"self_review_policy": "disabled"},
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

    def test_refresh_snapshot_reopens_completed_story_into_subtask_execution(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004REOPEN",
            workflow_profile="story_full",
            policy={"self_review_policy": "disabled"},
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

    def test_refresh_subtask_state_reconciles_remaining_queue_during_active_subtask_execution(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004REFRESHQUEUE",
            workflow_profile="story_full",
            policy={"self_review_policy": "disabled"},
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
                "role_input_dispatched",
                "implementation_requested",
                "implementation_completed",
                "git_commit_completed",
                "role_input_dispatched",
                "verification_requested",
                "verification_failed",
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
        self.assertIn("Continue from your existing implementer role context", sent_inputs[-1])
        self.assertIn("If the routed work is a narrow correction pass", sent_inputs[-1])
        self.assertNotIn("Read AGENTS.md/CLAUDE.md in the current directory now.", sent_inputs[-1])
        self.assertTrue(verification_report.exists())
        self.assertIn("## Result", verification_report.read_text())
        self.assertIn("FAIL", verification_report.read_text())
        self.assertIn("## Output: run-test.sh", verification_report.read_text())
        self.assertIn("presenter state mismatch", verification_report.read_text())

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
        self.assertIn("narrow bug-fix correction pass", sent_inputs[-1])
        self.assertIn('"issues_file_path"', sent_inputs[-1])
        self.assertIn('"bug_analysis_report_path"', sent_inputs[-1])

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
        self.assertIn("Read AGENTS.md/CLAUDE.md in the current directory now.", sent_inputs[0])
        self.assertIn(
            "Continue from your existing verification-coordinator role context",
            sent_inputs[-1],
        )
        self.assertNotIn("Read AGENTS.md/CLAUDE.md in the current directory now.", sent_inputs[-1])

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

    def test_verification_correction_reenters_verification_without_reopening_optional_quality_lanes(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004V2QUAL",
            workflow_profile="oneshot",
            policy={
                "self_review_policy": "enabled",
                "boy_scout_policy": "enabled",
                "doc_harvest_policy": "disabled",
            },
        )
        self.coordinator.prepare_task_session("IOS-30004V2QUAL")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )
        self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=CODE_REVIEWER_ROLE,
            output_type="passed",
            payload={"summary": "review clean"},
        )
        self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=CODE_SCOUT_ROLE,
            output_type="completed",
            payload={"result": "clean", "summary": "no improvements"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_failed",
            payload={"failures": ["test"]},
        )

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "verification corrections done"},
        )

        verification_role = self.role_repository.get_by_name(session.id, "verification-coordinator")
        reviewer_role = self.role_repository.get_by_name(session.id, CODE_REVIEWER_ROLE)
        reviewer_inputs = self.session_backend.get_sent_inputs(reviewer_role.runtime_handle)
        verification_inputs = self.session_backend.get_sent_inputs(verification_role.runtime_handle)

        self.assertEqual("verification_requested", updated_session.current_stage)
        self.assertEqual("verification-coordinator", updated_session.current_owner)
        self.assertEqual("verification_requested", followup_event.event_type)
        self.assertEqual(2, len(verification_inputs))
        self.assertEqual(1, len(reviewer_inputs))

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

        self.assertEqual("send_to_test_completed", updated_session.current_stage)
        self.assertIsNone(updated_session.current_owner)
        self.assertEqual("completed", updated_session.status.value)
        self.assertEqual("send_to_test_completed", followup_event.event_type)
        self.assertTrue(verification_report.exists())
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
                "role_input_dispatched",
                "implementation_requested",
                "implementation_completed",
                "git_commit_completed",
                "role_input_dispatched",
                "verification_requested",
                "verification_passed",
                "task_completed",
                "mr_handoff_completed",
                "send_to_test_completed",
            ],
            [item.event_type for item in events],
        )

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
                "role_input_dispatched",
                "implementation_requested",
                "implementation_completed",
                "git_commit_completed",
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
                "role_input_dispatched",
                "bug_analysis_requested",
                "bug_analysis_completed",
                "role_input_dispatched",
                "implementation_requested",
            ],
            [item.event_type for item in events],
        )

    def test_role_output_completed_moves_story_spec_forward(self) -> None:
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

        acceptance_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=ACCEPTANCE_CRITERIA_WORKER_ROLE,
            output_type="completed",
            payload={"summary": "Acceptance prepared"},
        )

        self.assertEqual("acceptance_criteria_completed", mapped_event.event_type)
        self.assertEqual("constraints_requested", followup_event.event_type)
        self.assertEqual("constraints_requested", acceptance_session.current_stage)

        constraints_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=CONSTRAINTS_WORKER_ROLE,
            output_type="completed",
            payload={"summary": "Constraints prepared"},
        )

        self.assertEqual("constraints_completed", mapped_event.event_type)
        self.assertEqual("spec_verification_requested", followup_event.event_type)
        self.assertEqual("spec_verification_requested", constraints_session.current_stage)

        verifier_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=SPEC_VERIFIER_WORKER_ROLE,
            output_type="completed",
            payload={"summary": "Planning verified"},
        )

        self.assertEqual("spec_verification_completed", mapped_event.event_type)
        self.assertEqual("story_spec_requested", followup_event.event_type)
        self.assertEqual("story_spec_requested", verifier_session.current_stage)

        decomposition_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=STORY_SPEC_WORKER_ROLE,
            output_type="completed",
            payload={"summary": "Scope clarified"},
        )

        self.assertEqual("story_spec_completed", mapped_event.event_type)
        self.assertEqual("task_decomposition_requested", followup_event.event_type)
        self.assertEqual("task_decomposition_requested", decomposition_session.current_stage)

        updated_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=TASK_DECOMPOSER_WORKER_ROLE,
            output_type="completed",
            payload=decomposition_payload("Decomposition prepared"),
        )
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual("task_decomposition_completed", mapped_event.event_type)
        self.assertEqual("implementation_requested", followup_event.event_type)
        self.assertEqual("implementation_requested", updated_session.current_stage)
        self.assertEqual("active", updated_session.status.value)
        self.assertEqual(
            [
                "task_started",
                "task_session_reused",
                "task_prepared",
                "role_input_dispatched",
                "proposal_context_requested",
                "proposal_context_completed",
                "role_input_dispatched",
                "requirements_requested",
                "requirements_completed",
                "role_input_dispatched",
                "acceptance_criteria_requested",
                "acceptance_criteria_completed",
                "role_input_dispatched",
                "constraints_requested",
                "constraints_completed",
                "role_input_dispatched",
                "spec_verification_requested",
                "spec_verification_completed",
                "role_input_dispatched",
                "story_spec_requested",
                "story_spec_completed",
                "role_input_dispatched",
                "task_decomposition_requested",
                "task_decomposition_completed",
                "role_input_dispatched",
                "implementation_requested",
                "jira_subtasks_created",
            ],
            [item.event_type for item in events],
        )
        spec_root = Path(self.temp_dir.name) / "IOS-30006STORY" / "spec"
        self.assertTrue((spec_root / "proposal.md").is_file())
        self.assertTrue((spec_root / "requirements.md").is_file())
        self.assertTrue((spec_root / "acceptance_criteria.md").is_file())
        self.assertTrue((spec_root / "constraints.md").is_file())
        self.assertTrue((spec_root / "spec_verification.md").is_file())
        self.assertTrue((spec_root / "story_spec.md").is_file())

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
        self.assertEqual("session_output_polled", event.event_type)
        self.assertEqual(3, role_count)
        self.assertEqual(2, chunk_count)
        self.assertEqual(
            2,
            len([artifact for artifact in artifacts if artifact.artifact_type == "runtime_output"]),
        )

    def test_poll_session_output_consumes_result_json_from_role_workspace(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30008B")
        role_workspace = self.coordinator.role_workspace_manager.role_directory(  # type: ignore[union-attr]
            session.task_key,
            "implementer",
        )
        result_path = role_workspace / "RESULT.json"
        result_path.write_text(
            json.dumps(
                {
                    "output_type": "completed",
                    "payload": {"summary": "done from file"},
                }
            )
        )

        updated_session, event, role_count, chunk_count = self.coordinator.poll_session_output(
            session_id=session.id,
        )
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual(session.id, updated_session.id)
        self.assertEqual("session_output_polled", event.event_type)
        self.assertEqual(3, role_count)
        self.assertEqual(1, chunk_count)
        self.assertEqual("verification_requested", updated_session.current_stage)
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
                "self_review_policy": "disabled",
                "boy_scout_policy": "disabled",
                "doc_harvest_policy": "disabled",
            },
        )

        summary = coordinator.get_runtime_state_summary(session.id)

        self.assertTrue(summary["available"])
        self.assertIn("tmux -S ", summary["tmux_attach_command"])
        self.assertTrue(str(summary["tmux_socket_path"]).endswith(".sock"))
        implementer = next(item for item in summary["roles"] if item["role_name"] == "implementer")
        self.assertIn("select-window", implementer["tmux_attach_command"])
        self.assertIn("capture-pane", implementer["tmux_capture_command"])

        runtime_session = coordinator._runtime_session_handle_for_session(session)
        tmux_backend.stop_session(runtime_session)

    def test_collect_role_output_normalizes_structured_marker(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30009")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            'SDD_OUTPUT: {"output_type":"completed","payload":{"summary":"done"}}',
        )

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual("verification_requested", updated_session.current_stage)
        self.assertTrue(any(item.event_type == "implementation_completed" for item in events))
        self.assertTrue(any(item.event_type == "verification_requested" for item in events))

    def test_collect_role_output_normalizes_wrapped_structured_marker(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30009WRAP")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            '\n'.join(
                [
                    '• SDD_OUTPUT: {"output_type":"completed","payload":{"task_key":"IOS-ACCEPT-REAL-',
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
        self.assertEqual("verification_requested", updated_session.current_stage)
        self.assertTrue(any(item.event_type == "implementation_completed" for item in events))
        self.assertTrue(any(item.event_type == "verification_requested" for item in events))

    def test_collect_role_output_consumes_result_json_from_role_workspace(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30009B")
        role_workspace = self.coordinator.role_workspace_manager.role_directory(  # type: ignore[union-attr]
            session.task_key,
            "implementer",
        )
        result_path = role_workspace / "RESULT.json"
        result_path.write_text(
            json.dumps(
                {
                    "output_type": "completed",
                    "payload": {"summary": "done from file"},
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

    def test_collect_role_output_ignores_stale_reviewer_result_during_self_review_correction(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30009D",
            workflow_profile="oneshot",
            policy={
                "self_review_policy": "enabled",
                "boy_scout_policy": "disabled",
                "doc_harvest_policy": "disabled",
            },
        )
        self.coordinator.prepare_task_session("IOS-30009D")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )
        self.coordinator.handle_role_output(
            session_id=session.id,
            role_name="code-reviewer",
            output_type="failed",
            payload={"summary": "review issues", "issues": ["narrow fix needed"]},
        )
        reviewer_workspace = self.coordinator.role_workspace_manager.role_directory(  # type: ignore[union-attr]
            session.task_key,
            "code-reviewer",
        )
        result_path = reviewer_workspace / "RESULT.json"
        result_path.write_text(
            json.dumps(
                {
                    "output_type": "completed",
                    "payload": {"summary": "late stale reviewer result"},
                }
            )
        )

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="code-reviewer",
        )
        events = self.event_repository.list_for_session(session.id)
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual("self_review_correction_requested", updated_session.current_stage)
        self.assertEqual("implementer", updated_session.current_owner)
        self.assertFalse(result_path.exists())
        self.assertTrue(any(item.event_type == "stale_role_output_ignored" for item in events))
        self.assertFalse(any(item.event_type == "self_review_passed" for item in events))
        self.assertTrue(any(item.artifact_type == "role_result_json" for item in artifacts))

    def test_collect_role_output_ignores_stale_reviewer_result_after_handoff_to_verification_correction(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30009F",
            workflow_profile="oneshot",
            policy={
                "self_review_policy": "enabled",
                "boy_scout_policy": "disabled",
                "doc_harvest_policy": "disabled",
            },
        )
        self.coordinator.prepare_task_session("IOS-30009F")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )
        self.coordinator.handle_role_output(
            session_id=session.id,
            role_name="code-reviewer",
            output_type="passed",
            payload={"summary": "review clean"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_failed",
            payload={"summary": "verification failed", "failures": ["lint"]},
        )
        reviewer_workspace = self.coordinator.role_workspace_manager.role_directory(  # type: ignore[union-attr]
            session.task_key,
            "code-reviewer",
        )
        result_path = reviewer_workspace / "RESULT.json"
        result_path.write_text(
            json.dumps(
                {
                    "output_type": "completed",
                    "payload": {"summary": "late stale reviewer result after verification handoff"},
                }
            )
        )

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="code-reviewer",
        )
        events = self.event_repository.list_for_session(session.id)
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual("verification_correction_requested", updated_session.current_stage)
        self.assertEqual("implementer", updated_session.current_owner)
        self.assertFalse(result_path.exists())
        self.assertTrue(any(item.event_type == "stale_role_output_ignored" for item in events))
        self.assertEqual(1, sum(1 for item in events if item.event_type == "self_review_passed"))
        self.assertTrue(any(item.artifact_type == "role_result_json" for item in artifacts))

    def test_collect_role_output_ignores_stale_implementer_result_after_handoff_to_reviewer(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30009E",
            workflow_profile="oneshot",
            policy={
                "self_review_policy": "enabled",
                "boy_scout_policy": "disabled",
                "doc_harvest_policy": "disabled",
            },
        )
        self.coordinator.prepare_task_session("IOS-30009E")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )
        implementer_workspace = self.coordinator.role_workspace_manager.role_directory(  # type: ignore[union-attr]
            session.task_key,
            "implementer",
        )
        result_path = implementer_workspace / "RESULT.json"
        result_path.write_text(
            json.dumps(
                {
                    "output_type": "completed",
                    "payload": {"summary": "late stale implementer result"},
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
        self.assertEqual("self_review_requested", updated_session.current_stage)
        self.assertEqual("code-reviewer", updated_session.current_owner)
        self.assertFalse(result_path.exists())
        self.assertTrue(any(item.event_type == "stale_role_output_ignored" for item in events))
        self.assertEqual(1, sum(1 for item in events if item.event_type == "implementation_completed"))
        self.assertTrue(any(item.artifact_type == "role_result_json" for item in artifacts))

    def test_poll_session_output_ignores_stale_implementer_runtime_marker_after_handoff_to_reviewer(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30009G",
            workflow_profile="oneshot",
            policy={
                "self_review_policy": "enabled",
                "boy_scout_policy": "disabled",
                "doc_harvest_policy": "disabled",
            },
        )
        self.coordinator.prepare_task_session("IOS-30009G")
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

        updated_session, event, role_count, chunk_count = self.coordinator.poll_session_output(
            session_id=session.id,
        )
        events = self.event_repository.list_for_session(session.id)
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual("session_output_polled", event.event_type)
        self.assertEqual(4, role_count)
        self.assertEqual(1, chunk_count)
        self.assertEqual("self_review_requested", updated_session.current_stage)
        self.assertEqual("code-reviewer", updated_session.current_owner)
        self.assertTrue(any(item.event_type == "stale_role_output_ignored" for item in events))
        self.assertEqual(1, sum(1 for item in events if item.event_type == "implementation_completed"))
        self.assertTrue(any(item.artifact_type == "runtime_output" for item in artifacts))

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
        self.assertTrue(any(item.event_type == "role_progress_reported" for item in events))
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

        self.assertEqual("coordinator_loop_ran", event.event_type)
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

        self.assertEqual("coordinator_loop_ran", event.event_type)
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

    def test_ingest_mr_comments_reopens_completed_session_with_followup_work(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30020")
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

        updated_session, event, followup_event, discussion_count = self.coordinator.ingest_mr_comments(
            session_id=completed_session.id,
            platform="ios",
            mr_id="2942",
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual("active", updated_session.status.value)
        self.assertEqual("mr_comments_analysis_requested", updated_session.current_stage)
        self.assertEqual(MR_COMMENTS_ANALYST_ROLE, updated_session.current_owner)
        self.assertEqual("mr_comments_received", event.event_type)
        self.assertEqual("mr_comments_analysis_requested", followup_event.event_type)
        self.assertEqual(2, discussion_count)
        self.assertTrue(
            any(item.title == "MR comment analysis for IOS-30020 from !2942" for item in work_items)
        )
        self.assertTrue(
            any(item.work_type == "mr_comments_analysis" for item in work_items)
        )
        self.assertTrue(any(item.event_type == "mr_comments_received" for item in events))
        self.assertTrue(any(item.event_type == "mr_comments_analysis_requested" for item in events))

    def test_mr_comments_analysis_completion_routes_to_subtask_graph_when_snapshot_contains_followup_subtasks(
        self,
    ) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30020A")
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
        self.coordinator.ingest_mr_comments(
            session_id=completed_session.id,
            platform="ios",
            mr_id="2943",
        )
        plan_dir = Path(self.temp_dir.name) / "IOS-30020A" / "plan"
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / "index.md").write_text(
            "# Execution Task List\n\n| # | Task | Depends on | Status |\n|---|------|------------|--------|\n| 01 | [Address MR feedback](./01-address-mr-feedback.md) | — | ☐ |\n"
        )
        (plan_dir / "01-address-mr-feedback.md").write_text(
            "# Address MR feedback\n\n## What to implement\nApply the grouped MR follow-up changes.\n"
        )
        self.write_statuses_file(
            "IOS-30020A",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30020A | Story | Parent story | Ready for test |
| IOS-90001 | Sub-task | Address MR feedback | To Do |
| IOS-90002 | Sub-task | Cleanup review leftovers | To Do |
""",
        )

        updated_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=MR_COMMENTS_ANALYST_ROLE,
            output_type="completed",
            payload={"summary": "Grouped two review themes into actionable follow-up plan."},
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        events = self.event_repository.list_for_session(session.id)
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual("mr_comments_analysis_completed", mapped_event.event_type)
        self.assertEqual("subtask_implementation_requested", followup_event.event_type)
        self.assertEqual("subtask_implementation_requested", updated_session.current_stage)
        self.assertEqual("implementer", updated_session.current_owner)
        self.assertTrue(any(item.work_type == "mr_comments_analysis" for item in work_items))
        self.assertTrue(any(item.work_type == "subtask_implementation" for item in work_items))
        self.assertTrue(any(item.event_type == "mr_comments_analysis_completed" for item in events))
        self.assertTrue(any(item.event_type == "jira_subtasks_created" for item in events))
        self.assertTrue(any(item.event_type == "subtask_graph_requested" for item in events))
        self.assertTrue(any(item.event_type == "subtask_implementation_requested" for item in events))
        self.assertTrue(any(item.artifact_type == "jira_subtasks_summary" for item in artifacts))
        self.assertTrue(any(item.artifact_type == "mr_followup_plan_markdown" for item in artifacts))

    def test_mr_comments_analysis_completion_falls_back_to_direct_followup_without_resolved_snapshot_subtasks(
        self,
    ) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30020B")
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
        self.coordinator.ingest_mr_comments(
            session_id=completed_session.id,
            platform="ios",
            mr_id="2944",
        )
        plan_dir = Path(self.temp_dir.name) / "IOS-30020B" / "plan"
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / "index.md").write_text(
            "# Execution Task List\n\n| # | Task | Depends on | Status |\n|---|------|------------|--------|\n| 01 | [Address MR feedback](./01-address-mr-feedback.md) | — | ☐ |\n"
        )
        (plan_dir / "01-address-mr-feedback.md").write_text(
            "# Address MR feedback\n\n## What to implement\nApply the grouped MR follow-up changes.\n"
        )

        updated_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=MR_COMMENTS_ANALYST_ROLE,
            output_type="completed",
            payload={"summary": "Grouped two review themes into actionable follow-up plan."},
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual("mr_comments_analysis_completed", mapped_event.event_type)
        self.assertEqual("mr_followup_requested", followup_event.event_type)
        self.assertEqual("mr_followup_requested", updated_session.current_stage)
        self.assertTrue(any(item.work_type == "followup_implementation" for item in work_items))
        self.assertTrue(any(item.event_type == "mr_followup_requested" for item in events))

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
        self.assertIn('"followup_comments_path"', sent_inputs[-1])
        self.assertIn('"bug_analysis_report_path"', sent_inputs[-1])

    def test_create_mr_handoff_marks_completed_session_as_handed_off(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30021A")
        self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="completed",
            current_owner=None,
        )
        completed_session = self.session_repository.update_status(session.id, SessionStatus.COMPLETED)

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

        updated_session, event = self.coordinator.send_to_test_handoff(session_id=session.id)
        artifacts = self.artifact_repository.list_for_session(session.id)
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual("completed", updated_session.status.value)
        self.assertEqual("send_to_test_completed", updated_session.current_stage)
        self.assertEqual("send_to_test_completed", event.event_type)
        self.assertTrue(any(item.artifact_type == "send_to_test_stdout" for item in artifacts))
        self.assertTrue(any(item.artifact_type == "send_to_test_stderr" for item in artifacts))
        self.assertTrue(any(item.event_type == "send_to_test_completed" for item in events))

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

    def test_send_to_test_handoff_failure_escalates_for_operator_retry(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30021D1")
        self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="mr_handoff_completed",
            current_owner=None,
        )
        self.session_repository.update_status(session.id, SessionStatus.COMPLETED)

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

    def test_implementation_completed_routes_to_self_review_when_policy_required(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021SR1",
            workflow_profile="oneshot",
            policy={"self_review_policy": "required"},
        )
        self.coordinator.prepare_task_session("IOS-30021SR1")

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )

        self.assertEqual("active", updated_session.status.value)
        self.assertEqual("self_review_requested", updated_session.current_stage)
        self.assertEqual("code-reviewer", updated_session.current_owner)
        self.assertEqual("self_review_requested", followup_event.event_type)

    def test_implementation_completed_routes_to_self_review_when_policy_enabled(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021SR1E",
            workflow_profile="oneshot",
            policy={"self_review_policy": "enabled"},
        )
        self.coordinator.prepare_task_session("IOS-30021SR1E")

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )

        self.assertEqual("active", updated_session.status.value)
        self.assertEqual("self_review_requested", updated_session.current_stage)
        self.assertEqual("code-reviewer", updated_session.current_owner)
        self.assertEqual("self_review_requested", followup_event.event_type)

    def test_complete_self_review_passed_routes_to_verification(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021SR2",
            workflow_profile="oneshot",
            policy={"self_review_policy": "enabled"},
        )
        self.coordinator.prepare_task_session("IOS-30021SR2")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )

        updated_session, event, followup_event = self.coordinator.complete_self_review(
            session_id=session.id,
            outcome="passed",
            summary="Reviewed implementation and found no blocking issues.",
        )
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual("self_review_passed", event.event_type)
        self.assertEqual("verification_requested", followup_event.event_type)
        self.assertEqual("verification_requested", updated_session.current_stage)
        self.assertEqual("verification-coordinator", updated_session.current_owner)
        self.assertTrue(any(item.artifact_type == "self_review_summary" for item in artifacts))
        self.assertTrue(any(item.artifact_type == "self_review_report_markdown" for item in artifacts))

    def test_self_review_skipped_not_needed_routes_to_verification_when_policy_enabled(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021SR2E",
            workflow_profile="oneshot",
            policy={"self_review_policy": "enabled"},
        )
        self.coordinator.prepare_task_session("IOS-30021SR2E")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )

        updated_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=CODE_REVIEWER_ROLE,
            output_type="skipped_not_needed",
            payload={"summary": "The diff is too small to justify a meaningful self-review pass."},
        )

        self.assertEqual("self_review_passed", mapped_event.event_type)
        self.assertIsNotNone(followup_event)
        assert followup_event is not None
        self.assertEqual("verification_requested", followup_event.event_type)
        self.assertEqual("verification_requested", updated_session.current_stage)
        self.assertEqual("verification-coordinator", updated_session.current_owner)

    def test_self_review_skipped_not_needed_is_rejected_when_policy_required(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021SR2R",
            workflow_profile="oneshot",
            policy={"self_review_policy": "required"},
        )
        self.coordinator.prepare_task_session("IOS-30021SR2R")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )

        with self.assertRaisesRegex(
            IntakeError,
            "Self review cannot be skipped when self_review_policy is required",
        ):
            self.coordinator.handle_role_output(
                session_id=session.id,
                role_name=CODE_REVIEWER_ROLE,
                output_type="skipped_not_needed",
                payload={"summary": "The diff is too small to justify a meaningful self-review pass."},
            )

    def test_implementation_completed_routes_to_boy_scout_when_policy_enabled(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021BS1",
            workflow_profile="oneshot",
            policy={"boy_scout_policy": "enabled", "self_review_policy": "disabled"},
        )
        self.coordinator.prepare_task_session("IOS-30021BS1")

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )
        work_items = self.work_item_repository.list_for_session(session.id)

        self.assertEqual("active", updated_session.status.value)
        self.assertEqual("boy_scout_requested", updated_session.current_stage)
        self.assertEqual(CODE_SCOUT_ROLE, updated_session.current_owner)
        self.assertEqual("boy_scout_requested", followup_event.event_type)
        self.assertTrue(any(item.work_type == "boy_scout" for item in work_items))

    def test_boy_scout_skipped_not_needed_routes_to_verification_when_policy_enabled(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021BS1E",
            workflow_profile="oneshot",
            policy={"boy_scout_policy": "enabled", "self_review_policy": "disabled"},
        )
        self.coordinator.prepare_task_session("IOS-30021BS1E")

        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )

        updated_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=CODE_SCOUT_ROLE,
            output_type="skipped_not_needed",
            payload={"summary": "The change is too small to justify a meaningful Boy Scout pass."},
        )

        self.assertEqual("boy_scout_completed", mapped_event.event_type)
        self.assertIsNotNone(followup_event)
        assert followup_event is not None
        self.assertEqual("verification_requested", followup_event.event_type)
        self.assertEqual("verification_requested", updated_session.current_stage)
        self.assertEqual("verification-coordinator", updated_session.current_owner)

    def test_boy_scout_skipped_not_needed_is_rejected_when_policy_required(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021BS1R",
            workflow_profile="oneshot",
            policy={"boy_scout_policy": "required", "self_review_policy": "disabled"},
        )
        self.coordinator.prepare_task_session("IOS-30021BS1R")

        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )

        with self.assertRaisesRegex(
            IntakeError,
            "Boy Scout cannot be skipped when boy_scout_policy is required",
        ):
            self.coordinator.handle_role_output(
                session_id=session.id,
                role_name=CODE_SCOUT_ROLE,
                output_type="skipped_not_needed",
                payload={"summary": "The change is too small to justify a meaningful Boy Scout pass."},
            )

    def test_boy_scout_findings_for_new_code_route_directly_to_implementer(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021BSAUTO",
            workflow_profile="oneshot",
            policy={"boy_scout_policy": "enabled", "self_review_policy": "disabled"},
        )
        self.coordinator.prepare_task_session("IOS-30021BSAUTO")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )

        spec_dir = Path(self.temp_dir.name) / "IOS-30021BSAUTO" / "spec"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "diff.md").write_text(
            "# Diff Artifact: IOS-30021BSAUTO\n\n"
            "## Changed Files\n\n"
            "| Status | Path |\n|---|---|\n"
            "| added | `FeatureBuilder.swift` |\n"
            "| added | `FeatureMapper.swift` |\n\n"
        )
        (spec_dir / "findings.md").write_text(
            "SCOUT_RESULT: findings_found\n\n"
            "## Finding 1: Extract helper\n\n"
            "**Files**: `FeatureBuilder.swift`, `FeatureMapper.swift`\n"
            "**Principle**: DRY\n"
            "**Problem**: Duplicate mapping logic exists.\n"
            "**Suggestion**: Extract a shared helper.\n"
        )

        updated_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=CODE_SCOUT_ROLE,
            output_type="completed",
            payload={"result": "findings_found", "summary": "Found one improvement opportunity."},
        )
        artifacts = self.artifact_repository.list_for_session(session.id)
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        sent_inputs = self.session_backend.get_sent_inputs(implementer_role.runtime_handle)

        self.assertEqual("boy_scout_completed", mapped_event.event_type)
        self.assertIsNotNone(followup_event)
        assert followup_event is not None
        self.assertEqual("boy_scout_correction_requested", followup_event.event_type)
        self.assertEqual("boy_scout_correction_requested", updated_session.current_stage)
        self.assertEqual(IMPLEMENTER_ROLE, updated_session.current_owner)
        self.assertTrue(any(item.artifact_type == "boy_scout_actionable_markdown" for item in artifacts))
        self.assertIn('"issues_file_path"', sent_inputs[-1])
        self.assertIn("boy-scout-actionable.md", sent_inputs[-1])

    def test_boy_scout_findings_can_be_skipped_into_verification(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021BS2",
            workflow_profile="oneshot",
            policy={"boy_scout_policy": "enabled", "self_review_policy": "disabled"},
        )
        self.coordinator.prepare_task_session("IOS-30021BS2")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )

        spec_dir = Path(self.temp_dir.name) / "IOS-30021BS2" / "spec"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "findings.md").write_text("SCOUT_RESULT: findings_found\n\n## Finding 1: Extract helper\n")

        updated_session, _, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=CODE_SCOUT_ROLE,
            output_type="completed",
            payload={
                "result": "findings_found",
                "summary": "Found one maintainability improvement opportunity.",
            },
        )

        self.assertEqual("waiting_for_operator", updated_session.status.value)
        self.assertEqual("boy_scout_requested", updated_session.current_stage)
        self.assertEqual("session_escalated_to_operator", followup_event.event_type)

        updated_session, event, verification_event = self.coordinator.skip_boy_scout(
            session_id=session.id,
            reason="Track the refactor separately; continue to final verification.",
        )
        artifacts = self.artifact_repository.list_for_session(session.id)
        deferred_path = Path(self.temp_dir.name) / "IOS-30021BS2" / "spec" / "scout-deferred.md"

        self.assertEqual("boy_scout_skipped_by_operator", event.event_type)
        self.assertEqual("verification_requested", verification_event.event_type)
        self.assertEqual("verification_requested", updated_session.current_stage)
        self.assertEqual("verification-coordinator", updated_session.current_owner)
        self.assertTrue(any(item.artifact_type == "boy_scout_findings" for item in artifacts))
        self.assertTrue(any(item.artifact_type == "boy_scout_deferred_markdown" for item in artifacts))
        self.assertTrue(deferred_path.is_file())
        self.assertIn("Extract helper", deferred_path.read_text())

    def test_resolve_boy_scout_findings_creates_tech_debt_and_routes_remaining_findings(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021BSMIX",
            workflow_profile="oneshot",
            policy={"boy_scout_policy": "enabled", "self_review_policy": "disabled"},
        )
        self.coordinator.prepare_task_session("IOS-30021BSMIX")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )

        spec_dir = Path(self.temp_dir.name) / "IOS-30021BSMIX" / "spec"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "diff.md").write_text(
            "# Diff Artifact: IOS-30021BSMIX\n\n"
            "## Changed Files\n\n"
            "| Status | Path |\n|---|---|\n"
            "| added | `NewBuilder.swift` |\n"
            "| modified | `LegacyPresenter.swift` |\n\n"
        )
        (spec_dir / "findings.md").write_text(
            "SCOUT_RESULT: findings_found\n\n"
            "## Finding 1: Extract builder helper\n\n"
            "**Files**: `NewBuilder.swift`\n"
            "**Principle**: DRY\n"
            "**Problem**: Duplicate helper logic exists.\n"
            "**Suggestion**: Extract a shared helper.\n\n"
            "---\n\n"
            "## Finding 2: Split legacy presenter\n\n"
            "**Files**: `LegacyPresenter.swift`\n"
            "**Principle**: SRP\n"
            "**Problem**: Presenter does too much.\n"
            "**Suggestion**: Split responsibilities.\n"
        )

        updated_session, _, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=CODE_SCOUT_ROLE,
            output_type="completed",
            payload={"result": "findings_found", "summary": "Found two improvement opportunities."},
        )
        self.assertEqual("waiting_for_operator", updated_session.status.value)
        self.assertEqual("session_escalated_to_operator", followup_event.event_type)

        updated_session, event, correction_event = self.coordinator.resolve_boy_scout_findings(
            session_id=session.id,
            resolution="create_tech_debt",
        )
        artifacts = self.artifact_repository.list_for_session(session.id)
        deferred_path = Path(self.temp_dir.name) / "IOS-30021BSMIX" / "spec" / "scout-deferred.md"
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        sent_inputs = self.session_backend.get_sent_inputs(implementer_role.runtime_handle)

        self.assertEqual("boy_scout_tech_debt_created", event.event_type)
        self.assertEqual("boy_scout_correction_requested", correction_event.event_type)
        self.assertEqual("boy_scout_correction_requested", updated_session.current_stage)
        self.assertEqual(IMPLEMENTER_ROLE, updated_session.current_owner)
        self.assertTrue(any(item.artifact_type == "boy_scout_actionable_markdown" for item in artifacts))
        self.assertTrue(any(item.artifact_type == "boy_scout_deferred_markdown" for item in artifacts))
        self.assertTrue(deferred_path.is_file())
        self.assertIn("Split legacy presenter", deferred_path.read_text())
        self.assertIn('"issues_file_path"', sent_inputs[-1])
        actionable_path = spec_dir / "boy-scout-actionable.md"
        self.assertTrue(actionable_path.is_file())
        actionable_text = actionable_path.read_text()
        self.assertIn("Extract builder helper", actionable_text)
        self.assertNotIn("Split legacy presenter", actionable_text)

    def test_get_interactive_state_summary_exposes_boy_scout_reason(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021BSREASON",
            workflow_profile="oneshot",
            policy={"boy_scout_policy": "enabled", "self_review_policy": "disabled"},
        )
        self.coordinator.prepare_task_session("IOS-30021BSREASON")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )

        spec_dir = Path(self.temp_dir.name) / "IOS-30021BSREASON" / "spec"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "findings.md").write_text("SCOUT_RESULT: findings_found\n\n## Finding 1: Extract helper\n")
        self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=CODE_SCOUT_ROLE,
            output_type="completed",
            payload={"result": "findings_found", "summary": "Found one improvement opportunity."},
        )

        summary = self.coordinator.get_interactive_state_summary(session.id)

        self.assertTrue(summary["available"])
        self.assertEqual("boy_scout_findings", summary["source_reason"])
        self.assertEqual("boy_scout_requested", summary["current_stage"])
        self.assertFalse(summary["needs_operator_input"])

    def test_boy_scout_manual_skip_is_rejected_when_policy_required(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021BS2R",
            workflow_profile="oneshot",
            policy={"boy_scout_policy": "required", "self_review_policy": "disabled"},
        )
        self.coordinator.prepare_task_session("IOS-30021BS2R")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )

        spec_dir = Path(self.temp_dir.name) / "IOS-30021BS2R" / "spec"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "findings.md").write_text("SCOUT_RESULT: findings_found\n\n## Finding 1: Extract helper\n")
        self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=CODE_SCOUT_ROLE,
            output_type="completed",
            payload={
                "result": "findings_found",
                "summary": "Found one maintainability improvement opportunity.",
            },
        )

        with self.assertRaisesRegex(
            IntakeError,
            "Manual Boy Scout skip is only allowed when boy_scout_policy is enabled",
        ):
            self.coordinator.skip_boy_scout(
                session_id=session.id,
                reason="operator shortcut",
            )

    def test_complete_self_review_with_issues_routes_to_implementer_correction(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021SR3",
            workflow_profile="oneshot",
            policy={"self_review_policy": "enabled"},
        )
        self.coordinator.prepare_task_session("IOS-30021SR3")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )

        updated_session, event, followup_event = self.coordinator.complete_self_review(
            session_id=session.id,
            outcome="issues_found",
            summary="Found two naming issues and one missing guard branch.",
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        artifacts = self.artifact_repository.list_for_session(session.id)
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        sent_inputs = self.session_backend.get_sent_inputs(implementer_role.runtime_handle)

        self.assertEqual("self_review_issues_found", event.event_type)
        self.assertEqual("self_review_correction_requested", followup_event.event_type)
        self.assertEqual("self_review_correction_requested", updated_session.current_stage)
        self.assertEqual("implementer", updated_session.current_owner)
        self.assertTrue(any(item.work_type == "self_review_correction" for item in work_items))
        self.assertTrue(any(item.artifact_type == "self_review_report_markdown" for item in artifacts))
        self.assertIn('"issues_file_path"', sent_inputs[-1])
        self.assertIn("pass-01.md", sent_inputs[-1])

    def test_complete_self_review_is_rejected_when_policy_required(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021SR3R",
            workflow_profile="oneshot",
            policy={"self_review_policy": "required"},
        )
        self.coordinator.prepare_task_session("IOS-30021SR3R")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )

        with self.assertRaisesRegex(
            IntakeError,
            "Manual self review completion is only allowed when self_review_policy is enabled",
        ):
            self.coordinator.complete_self_review(
                session_id=session.id,
                outcome="passed",
                summary="operator shortcut",
            )

    def test_self_review_correction_completed_reenters_self_review_loop(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021SR4",
            workflow_profile="oneshot",
            policy={"self_review_policy": "enabled"},
        )
        self.coordinator.prepare_task_session("IOS-30021SR4")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )
        self.coordinator.complete_self_review(
            session_id=session.id,
            outcome="issues_found",
            summary="Found two naming issues and one missing guard branch.",
        )

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "self review fixes done"},
        )
        reviewer_role = self.role_repository.get_by_name(session.id, CODE_REVIEWER_ROLE)
        sent_inputs = self.session_backend.get_sent_inputs(reviewer_role.runtime_handle)

        self.assertEqual("self_review_requested", updated_session.current_stage)
        self.assertEqual(CODE_REVIEWER_ROLE, updated_session.current_owner)
        self.assertEqual("self_review_requested", followup_event.event_type)
        self.assertIn("previous_review_report_paths", sent_inputs[-1])
        self.assertIn("pass-01.md", sent_inputs[-1])
        self.assertIn("pass-02.md", sent_inputs[-1])

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

        self.assertEqual("completed", updated_session.status.value)
        self.assertEqual("doc_harvest_completed", updated_session.current_stage)
        self.assertEqual("doc_harvest_completed", event.event_type)
        self.assertTrue(any(item.artifact_type == "doc_harvest_summary" for item in artifacts))

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
        self.assertEqual("send_to_test_completed", followup_event.event_type)
        self.assertEqual("completed", updated_session.status.value)
        self.assertEqual("send_to_test_completed", updated_session.current_stage)
        self.assertTrue(any(item.artifact_type == "doc_harvest_summary" for item in artifacts))
        self.assertEqual(
            [
                ("IOS-30021FH", "implementation pass"),
                ("IOS-30021FH", "doc harvest"),
            ],
            self.gitlab_adapter.commit_requests,
        )

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
        self.assertEqual("send_to_test_completed", followup_event.event_type)
        self.assertEqual("completed", updated_session.status.value)
        self.assertEqual("send_to_test_completed", updated_session.current_stage)
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

        self.assertEqual("implementation_requested", followup_event.event_type)
        self.assertEqual("implementation_requested", active_session.current_stage)
        self.assertEqual("active", active_session.status.value)
        self.assertIn("Start implementation work for IOS-30021EXEC.", sent_inputs[-1])

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
            ["assigned", "waiting_for_operator"],
            sorted(item.status.value for item in work_items),
        )
        self.assertTrue(
            any(
                item.title.startswith("Retry: ") and item.status.value == "assigned"
                for item in work_items
            )
        )
        self.assertEqual(2, len(sent_inputs))
        self.assertIn("Start implementation work for IOS-30022.", sent_inputs[-1])

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
        shadow_inputs = self.session_backend.get_sent_inputs(shadow_role.runtime_handle)

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

        self.assertEqual("coordinator_loop_ran", event.event_type)
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

        self.assertEqual("coordinator_loop_ran", event.event_type)
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
