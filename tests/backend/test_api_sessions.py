from pathlib import Path
import json
import tempfile
import time
import unittest
from unittest.mock import patch

try:
    from backend import session_policy as session_policy_module
    from backend.api.sse import SessionEventBus
    from backend.api.routes_sessions import (
        create_session,
        get_jira_subtasks,
        get_subtask_graph,
        get_subtask_progress,
        list_sessions,
        prepare_session,
        get_interactive_state,
        get_runtime_state,
    )
    from backend.api.routes_knowledge import list_knowledge
    from backend.api.schemas import CreateSessionRequest, PrepareSessionRequest
    from backend.api.routes_events import inject_event, list_events
    from backend.api.routes_work_items import list_work_items
    from backend.api.schemas import InjectEventRequest
    from backend.api.routes_roles import submit_role_output
    from backend.api.schemas import CollectRoleOutputRequest, RoleOutputRequest
    from backend.api.routes_artifacts import get_artifact, list_artifacts
    from backend.api.routes_roles import collect_role_output
    from backend.api.routes_operator import poll_session_output
    from backend.api.routes_operator import run_loop_once
    from backend.api.routes_operator import pause_session
    from backend.api.routes_operator import resume_session
    from backend.api.routes_operator import send_runtime_input
    from backend.api.routes_operator import retry_session
    from backend.api.routes_operator import reopen_from_qa
    from backend.api.routes_operator import redirect_session
    from backend.api.routes_operator import complete_doc_harvest
    from backend.api.routes_operator import skip_boy_scout
    from backend.api.routes_operator import complete_self_review
    from backend.api.routes_operator import create_mr
    from backend.api.routes_operator import create_knowledge, create_subtasks_from_plan
    from backend.api.routes_operator import cleanup_task
    from backend.api.routes_operator import get_bootstrap_guidance
    from backend.api.routes_operator import get_environment_doctor
    from backend.api.routes_operator import get_runtime_capabilities
    from backend.api.routes_operator import get_runtime_defaults
    from backend.api.routes_operator import refresh_subtask_state
    from backend.api.routes_operator import restart_runtime_role
    from backend.api.routes_operator import restart_runtime_session
    from backend.api.routes_operator import stop_runtime_role
    from backend.api.routes_operator import stop_runtime_session
    from backend.api.routes_operator import send_to_test
    from backend.api.routes_operator import start_subtask_graph
    from backend.api.routes_operator import ingest_mr_comments
    from backend.api.routes_operator import loop_status, start_loop, stop_loop
    from backend.api.routes_operator import update_runtime_defaults
    from backend.api.schemas import (
        CompleteDocHarvestRequest,
        CompleteSelfReviewRequest,
        CreateKnowledgeRequest,
        CleanupTaskRequest,
        CreateMrRequest,
        CreateSubtasksFromPlanRequest,
        SkipBoyScoutRequest,
        IngestMrCommentsRequest,
        PollSessionOutputRequest,
        PauseSessionRequest,
        RefreshSubtaskStateRequest,
        ReopenFromQaRequest,
        RedirectSessionRequest,
        ResumeSessionRequest,
        RestartRuntimeRoleRequest,
        RestartRuntimeSessionRequest,
        RetrySessionRequest,
        SendOperatorRuntimeInputRequest,
        SendToTestRequest,
        StopRuntimeRoleRequest,
        StopRuntimeSessionRequest,
        StartSubtaskGraphRequest,
        UpdateRuntimeDefaultsRequest,
    )
    from backend.coordinator.service import CoordinatorService
    from backend.coordinator.loop_runner import CoordinatorLoopRunner
    from backend.dependencies import AppDependencies
    from backend.roles.contracts import (
        ACCEPTANCE_CRITERIA_WORKER_ROLE,
        ALLOWED_STAGE_ROLE_TARGETS,
        BUG_FIXER_ROLE,
        CODE_REVIEWER_ROLE,
        CONSTRAINTS_WORKER_ROLE,
        DEFAULT_SESSION_ROLES,
        PROPOSAL_CONTEXT_WORKER_ROLE,
        REQUIREMENTS_CLARIFIER_WORKER_ROLE,
        SPEC_VERIFIER_WORKER_ROLE,
        TASK_DECOMPOSER_WORKER_ROLE,
    )
    from backend.roles.launcher import RoleLauncherManager
    from backend.roles.workspace import RoleWorkspaceManager
    from backend.session_backend.recording_backend import RecordingSessionBackend
    from backend.state.artifact_repository import ArtifactRepository
    from backend.state.db import Database
    from backend.state.event_repository import EventRepository
    from backend.state.role_repository import RoleRepository
    from backend.state.session_repository import SessionRepository
    from backend.state.work_item_repository import WorkItemRepository
    from backend.tools.command_runner import CommandResult

    FASTAPI_AVAILABLE = True
except ModuleNotFoundError:
    FASTAPI_AVAILABLE = False


class FakeJiraAdapter:
    def __init__(self) -> None:
        self.status_by_task: dict[str, str] = {}

    def resolve_parent(self, task_key: str) -> "CommandResult":
        return CommandResult(["resolve_parent", task_key], 0, f"{task_key}\n", "")

    def get_issue_type(self, task_key: str) -> "CommandResult":
        return CommandResult(["get_issue_type", task_key], 0, "Story\n", "")

    def get_issue_status(self, task_key: str) -> "CommandResult":
        status = self.status_by_task.get(task_key, "In Progress")
        return CommandResult(
            ["get_issue_status", task_key],
            0,
            json.dumps({"fields": {"status": {"name": status}}}),
            "",
        )

    def create_subtasks(self, task_key: str, plan_dir: Path) -> "CommandResult":
        return CommandResult(
            ["create_subtasks", task_key, str(plan_dir)],
            0,
            "Created subtasks:\n01    IOS-90001     Build data source\n",
            "",
        )

    def send_to_test(self, task_key: str) -> "CommandResult":
        return CommandResult(["send_to_test", task_key], 0, f"Done: {task_key} -> Ready for test\n", "")


class FakeSnapshotAdapter:
    def __init__(self, workdir_root: Path | None = None) -> None:
        self.workdir_root = workdir_root
        self.calls: list[str] = []
        self.statuses_by_task: dict[str, str] = {}

    def set_statuses_output(self, task_key: str, content: str) -> None:
        self.statuses_by_task[task_key] = content

    def run(self, task_key: str) -> "CommandResult":
        self.calls.append(task_key)
        if self.workdir_root is not None and task_key in self.statuses_by_task:
            task_dir = self.workdir_root / task_key
            task_dir.mkdir(parents=True, exist_ok=True)
            (task_dir / "statuses.md").write_text(self.statuses_by_task[task_key])
        return CommandResult(["snapshot", task_key], 0, "snapshot ok\n", "")


class FakeGitLabAdapter:
    def create_mr(self, task_key: str) -> "CommandResult":
        return CommandResult(
            ["create_mr", task_key],
            0,
            (
                f"Pushing branch for {task_key}\n"
                f"https://gitlab.example.com/mobile/{task_key}/-/merge_requests/42\n"
            ),
            "",
        )

    def fetch_mr_comments(self, platform: str, mr_id: str) -> "CommandResult":
        return CommandResult(
            ["fetch_mr_comments", platform, mr_id],
            0,
            (
                f"# Unresolved MR discussions: !{mr_id} (1 total)\n\n"
                "## Discussion 1 — file.swift:10\n\n"
                "**Reviewer:** Please fix this\n\n"
                "---\n"
            ),
            "",
        )


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed in the local environment")
class SessionApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self._original_boy_scout_default = session_policy_module.COMMON_DEFAULTS["boy_scout_policy"]
        session_policy_module.COMMON_DEFAULTS["boy_scout_policy"] = "disabled"
        self.db_path = Path(self.temp_dir.name) / "factory.sqlite3"
        self.database = Database(self.db_path)
        self.database.initialize()

        session_repository = SessionRepository(self.database)
        role_repository = RoleRepository(self.database)
        event_repository = EventRepository(self.database)
        artifact_repository = ArtifactRepository(self.database)
        work_item_repository = WorkItemRepository(self.database)
        session_backend = RecordingSessionBackend()
        event_bus = SessionEventBus()
        self.snapshot_adapter = FakeSnapshotAdapter(Path(self.temp_dir.name))
        self.jira_adapter = FakeJiraAdapter()
        coordinator = CoordinatorService(
            session_repository=session_repository,
            role_repository=role_repository,
            event_repository=event_repository,
            artifact_repository=artifact_repository,
            work_item_repository=work_item_repository,
            session_backend=session_backend,
            default_roles=DEFAULT_SESSION_ROLES,
            jira_adapter=self.jira_adapter,
            snapshot_adapter=self.snapshot_adapter,
            gitlab_adapter=FakeGitLabAdapter(),
            artifacts_root=Path(self.temp_dir.name) / "artifacts",
            workdir_root=Path(self.temp_dir.name),
            event_bus=event_bus,
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
        loop_runner = CoordinatorLoopRunner(
            callback=coordinator.run_loop_once,
            interval_seconds=0.01,
        )
        self.dependencies = AppDependencies(
            config=None,
            database=self.database,
            session_repository=session_repository,
            role_repository=role_repository,
            event_repository=event_repository,
            artifact_repository=artifact_repository,
            work_item_repository=work_item_repository,
            session_backend=session_backend,
            jira_adapter=self.jira_adapter,
            snapshot_adapter=self.snapshot_adapter,
            gitlab_adapter=FakeGitLabAdapter(),
            event_bus=event_bus,
            loop_runner=loop_runner,
            coordinator_service=coordinator,
        )

    def tearDown(self) -> None:
        session_policy_module.COMMON_DEFAULTS["boy_scout_policy"] = self._original_boy_scout_default
        self.temp_dir.cleanup()

    def write_statuses_file(self, task_key: str, content: str) -> None:
        task_dir = Path(self.temp_dir.name) / task_key
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "statuses.md").write_text(content)

    def test_create_session_route_returns_created_session(self) -> None:
        response = create_session(
            CreateSessionRequest(
                task_key="IOS-40000",
                workflow_profile="bug_full",
                policy={"test_policy": "required"},
            ),
            dependencies=self.dependencies,
        )

        self.assertTrue(response.created)
        self.assertEqual("IOS-40000", response.session.task_key)
        self.assertEqual("bug_full", response.session.workflow_profile)
        self.assertEqual("required", response.session.policy["test_policy"])
        self.assertEqual("task_started", response.event_type)

    def test_cleanup_task_route_soft_keeps_session_and_removes_runtime_residue(self) -> None:
        create_response = create_session(
            CreateSessionRequest(task_key="IOS-40100", workflow_profile="oneshot"),
            dependencies=self.dependencies,
        )
        self.jira_adapter.status_by_task["IOS-40100"] = "In Progress"
        runtime_dir = Path(self.temp_dir.name) / "IOS-40100" / "runtime"
        tmp_dir = Path(self.temp_dir.name) / "IOS-40100" / "tmp"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)

        response = cleanup_task(
            CleanupTaskRequest(session_id=create_response.session.id, cleanup_mode="soft"),
            dependencies=self.dependencies,
        )

        self.assertTrue(response.cleaned)
        self.assertFalse(response.deleted_session)
        self.assertEqual("soft", response.cleanup_mode)
        self.assertFalse(runtime_dir.exists())
        self.assertFalse(tmp_dir.exists())
        sessions = list_sessions(dependencies=self.dependencies)
        self.assertEqual(["IOS-40100"], [item.task_key for item in sessions.items])

    def test_cleanup_task_route_full_requires_closed_status_unless_forced(self) -> None:
        create_response = create_session(
            CreateSessionRequest(task_key="IOS-40101", workflow_profile="oneshot"),
            dependencies=self.dependencies,
        )
        self.jira_adapter.status_by_task["IOS-40101"] = "In Progress"

        with self.assertRaises(Exception):
            cleanup_task(
                CleanupTaskRequest(session_id=create_response.session.id, cleanup_mode="full"),
                dependencies=self.dependencies,
            )

    def test_create_session_route_creates_role_workspaces(self) -> None:
        response = create_session(
            CreateSessionRequest(task_key="IOS-40000W", workflow_profile="oneshot"),
            dependencies=self.dependencies,
        )

        self.assertTrue(response.created)
        for role_name in DEFAULT_SESSION_ROLES + [CODE_REVIEWER_ROLE]:
            role_dir = Path(self.temp_dir.name) / "IOS-40000W" / "runtime" / "role-workspaces" / role_name
            self.assertTrue(role_dir.is_dir())
            self.assertTrue((role_dir / "AGENTS.md").is_file())
            self.assertTrue((role_dir / "CLAUDE.md").is_symlink())

    def test_create_session_route_creates_role_launch_scripts(self) -> None:
        response = create_session(
            CreateSessionRequest(task_key="IOS-40000L", workflow_profile="oneshot"),
            dependencies=self.dependencies,
        )

        self.assertTrue(response.created)
        implementer_role = self.dependencies.role_repository.get_by_name(
            response.session.id,
            "implementer",
        )
        launch_script = (
            Path(self.temp_dir.name)
            / "IOS-40000L"
            / "runtime"
            / "role-workspaces"
            / "implementer"
            / "launch-role.sh"
        )
        self.assertTrue(launch_script.is_file())
        self.assertEqual(
            [str(launch_script)],
            self.dependencies.session_backend.get_spawn_command(implementer_role.runtime_handle),
        )

    def test_runtime_defaults_routes_roundtrip_project_local_settings(self) -> None:
        response = get_runtime_defaults(dependencies=self.dependencies)

        self.assertIsNone(response.default_runner)
        self.assertIn("implementer", response.known_roles)
        self.assertTrue(response.source_path.endswith(".sdd-factory/settings.local.json"))

        updated = update_runtime_defaults(
            UpdateRuntimeDefaultsRequest(
                default_runner="codex",
                role_defaults={
                    "implementer": {
                        "runner": "claude",
                        "model": "sonnet",
                        "effort": "high",
                    }
                },
            ),
            dependencies=self.dependencies,
        )

        self.assertEqual("codex", updated.default_runner)
        self.assertEqual("claude", updated.role_defaults["implementer"].runner)
        self.assertEqual("sonnet", updated.role_defaults["implementer"].model)
        self.assertEqual("high", updated.role_defaults["implementer"].effort)
        self.assertTrue(Path(updated.source_path).is_file())

    def test_list_sessions_route_returns_created_session(self) -> None:
        create_session(
            CreateSessionRequest(task_key="IOS-40001", workflow_profile="oneshot"),
            dependencies=self.dependencies,
        )

        response = list_sessions(dependencies=self.dependencies)

        self.assertEqual(1, len(response.items))
        self.assertEqual("IOS-40001", response.items[0].task_key)

    def test_get_subtask_graph_route_returns_snapshot_summary(self) -> None:
        response = create_session(
            CreateSessionRequest(task_key="IOS-40001G", workflow_profile="story_full"),
            dependencies=self.dependencies,
        )
        self.write_statuses_file(
            "IOS-40001G",
            "\n".join(
                [
                    "| Key | Type | Title | Status |",
                    "| --- | --- | --- | --- |",
                    "| IOS-40001G | Story | Parent story | In Progress |",
                    "| IOS-40002 | Sub-task | Wire API | In Progress |",
                    "| IOS-40003 | Sub-task | Add tests | Ready for test |",
                ]
            ),
        )

        summary = get_subtask_graph(response.session.id, dependencies=self.dependencies)

        self.assertTrue(summary.available)
        self.assertEqual(2, summary.total_count)
        self.assertEqual(1, summary.completed_count)
        self.assertEqual(1, summary.unresolved_count)
        self.assertEqual(["IOS-40002", "IOS-40003"], [row.key for row in summary.rows])

    def test_get_subtask_progress_route_returns_queue_state(self) -> None:
        create_response = create_session(
            CreateSessionRequest(task_key="IOS-40001P", workflow_profile="story_full"),
            dependencies=self.dependencies,
        )
        prepare_session(
            PrepareSessionRequest(task_key="IOS-40001P"),
            dependencies=self.dependencies,
        )
        for event_type, summary in [
            ("proposal_context_completed", "Proposal ready"),
            ("requirements_completed", "Requirements ready"),
            ("acceptance_criteria_completed", "Acceptance ready"),
            ("constraints_completed", "Constraints ready"),
            ("spec_verification_completed", "Spec verified"),
            ("story_spec_completed", "Story spec complete"),
            ("task_decomposition_completed", "Decomposition complete"),
        ]:
            inject_event(
                InjectEventRequest(
                    session_id=create_response.session.id,
                    event_type=event_type,
                    payload={"summary": summary},
                ),
                dependencies=self.dependencies,
            )
        self.write_statuses_file(
            "IOS-40001P",
            "\n".join(
                [
                    "| Key | Type | Title | Status |",
                    "| --- | --- | --- | --- |",
                    "| IOS-40001P | Story | Parent story | In Progress |",
                    "| IOS-40120 | Sub-task | Wire API | In Progress |",
                    "| IOS-40121 | Sub-task | Add tests | To Do |",
                ]
            ),
        )
        start_subtask_graph(
            StartSubtaskGraphRequest(session_id=create_response.session.id),
            dependencies=self.dependencies,
        )

        summary = get_subtask_progress(create_response.session.id, dependencies=self.dependencies)

        self.assertTrue(summary.available)
        self.assertEqual("IOS-40120", summary.current_subtask_key)
        self.assertEqual("Wire API", summary.current_subtask_title)
        self.assertEqual(2, summary.total_count)
        self.assertEqual(0, summary.completed_count)
        self.assertEqual(2, summary.remaining_count)
        self.assertEqual(["assigned", "unassigned"], [item.status for item in summary.items])

    def test_get_jira_subtasks_route_returns_created_subtasks_summary(self) -> None:
        create_response = create_session(
            CreateSessionRequest(task_key="IOS-40005JS", workflow_profile="story_full"),
            dependencies=self.dependencies,
        )
        prepare_response = prepare_session(
            PrepareSessionRequest(task_key="IOS-40005JS"),
            dependencies=self.dependencies,
        )
        for event_type in (
            "proposal_context_completed",
            "requirements_completed",
            "acceptance_criteria_completed",
            "constraints_completed",
            "spec_verification_completed",
            "story_spec_completed",
        ):
            inject_event(
                InjectEventRequest(
                    session_id=create_response.session.id,
                    event_type=event_type,
                    payload={"summary": "prepared"},
                ),
                dependencies=self.dependencies,
            )
        inject_event(
            InjectEventRequest(
                session_id=create_response.session.id,
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
            ),
            dependencies=self.dependencies,
        )
        self.write_statuses_file(
            "IOS-40005JS",
            "\n".join(
                [
                    "| Key | Type | Title | Status |",
                    "| --- | --- | --- | --- |",
                    "| IOS-40005JS | Story | Parent story | In Progress |",
                    "| IOS-90001 | Sub-task | Build data source | To Do |",
                    "| IOS-90002 | Sub-task | Wire presentation layer | Ready for test |",
                ]
            ),
        )
        create_subtasks_from_plan(
            CreateSubtasksFromPlanRequest(session_id=create_response.session.id),
            dependencies=self.dependencies,
        )

        summary = get_jira_subtasks(create_response.session.id, dependencies=self.dependencies)

        self.assertTrue(summary.available)
        self.assertEqual(1, summary.total_count)
        self.assertEqual(["IOS-90001"], [item.key for item in summary.items])

    def test_refresh_subtask_state_route_auto_starts_subtask_lane(self) -> None:
        create_response = create_session(
            CreateSessionRequest(task_key="IOS-40005REFRESH", workflow_profile="story_full"),
            dependencies=self.dependencies,
        )
        prepare_session(
            PrepareSessionRequest(task_key="IOS-40005REFRESH"),
            dependencies=self.dependencies,
        )
        for event_type in (
            "proposal_context_completed",
            "requirements_completed",
            "acceptance_criteria_completed",
            "constraints_completed",
            "spec_verification_completed",
            "story_spec_completed",
        ):
            inject_event(
                InjectEventRequest(
                    session_id=create_response.session.id,
                    event_type=event_type,
                    payload={"summary": "prepared"},
                ),
                dependencies=self.dependencies,
            )
        inject_event(
            InjectEventRequest(
                session_id=create_response.session.id,
                event_type="task_decomposition_completed",
                payload={"summary": "Decomposition prepared"},
            ),
            dependencies=self.dependencies,
        )
        self.write_statuses_file(
            "IOS-40005REFRESH",
            "\n".join(
                [
                    "| Key | Type | Title | Status |",
                    "| --- | --- | --- | --- |",
                    "| IOS-40005REFRESH | Story | Parent story | In Progress |",
                    "| IOS-40130 | Sub-task | Build data source | To Do |",
                    "| IOS-40131 | Sub-task | Wire presentation | To Do |",
                ]
            ),
        )

        response = refresh_subtask_state(
            RefreshSubtaskStateRequest(session_id=create_response.session.id),
            dependencies=self.dependencies,
        )

        self.assertTrue(response.refreshed)
        self.assertEqual("subtask_state_refreshed_by_operator", response.event_type)
        self.assertEqual("subtask_implementation_requested", response.followup_event_type)
        self.assertEqual("subtask_implementation_requested", response.session.current_stage)

    def test_create_session_route_rejects_irrelevant_policy_for_profile(self) -> None:
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as context:
            create_session(
                CreateSessionRequest(
                    task_key="IOS-40001A",
                    workflow_profile="oneshot",
                    policy={"test_policy": "required"},
                ),
                dependencies=self.dependencies,
            )

        self.assertEqual(400, context.exception.status_code)

    def test_prepare_session_route_returns_intake_details(self) -> None:
        from backend.api.routes_sessions import prepare_session

        response = prepare_session(
            PrepareSessionRequest(task_key="IOS-40002"),
            dependencies=self.dependencies,
        )

        self.assertTrue(response.created)
        self.assertEqual("task_prepared", response.event_type)
        self.assertEqual("IOS-40002", response.resolved_task_key)
        self.assertEqual("Story", response.issue_type)
        self.assertEqual(0, response.snapshot_exit_code)
        self.assertEqual("implementation_requested", response.followup_event_type)

    def test_prepare_session_route_reuses_existing_policy_aware_session(self) -> None:
        from backend.api.routes_sessions import prepare_session

        create_response = create_session(
            CreateSessionRequest(
                task_key="IOS-40002A",
                workflow_profile="oneshot",
                policy={"self_review_policy": "required"},
            ),
            dependencies=self.dependencies,
        )

        response = prepare_session(
            PrepareSessionRequest(task_key="IOS-40002A"),
            dependencies=self.dependencies,
        )

        self.assertFalse(response.created)
        self.assertEqual(create_response.session.id, response.session.id)
        self.assertEqual("oneshot", response.session.workflow_profile)
        self.assertEqual("required", response.session.policy["self_review_policy"])

    def test_prepare_session_route_uses_bug_analysis_for_bug_full(self) -> None:
        from backend.api.routes_sessions import prepare_session

        create_response = create_session(
            CreateSessionRequest(
                task_key="IOS-40002BUG",
                workflow_profile="bug_full",
                policy={"test_policy": "required"},
            ),
            dependencies=self.dependencies,
        )

        response = prepare_session(
            PrepareSessionRequest(task_key="IOS-40002BUG"),
            dependencies=self.dependencies,
        )

        self.assertFalse(response.created)
        self.assertEqual(create_response.session.id, response.session.id)
        self.assertEqual("bug_full", response.session.workflow_profile)
        self.assertEqual("bug_analysis_requested", response.followup_event_type)
        self.assertEqual("bug_analysis_requested", response.session.current_stage)
        self.assertEqual(BUG_FIXER_ROLE, response.session.current_owner)

    def test_event_and_work_item_routes_reflect_verification_handoff(self) -> None:
        prepare_response = __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40003"),
            dependencies=self.dependencies,
        )

        inject_response = inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="implementation_completed",
                payload={"summary": "done"},
            ),
            dependencies=self.dependencies,
        )
        events_response = list_events(
            session_id=prepare_response.session.id,
            dependencies=self.dependencies,
        )
        work_items_response = list_work_items(
            session_id=prepare_response.session.id,
            dependencies=self.dependencies,
        )

        self.assertEqual("verification_requested", inject_response.followup_event_type)
        self.assertEqual("verification_requested", inject_response.session.current_stage)
        self.assertEqual(7, len(events_response.items))
        self.assertEqual(2, len(work_items_response.items))

    def test_bug_analysis_completed_event_returns_implementation_handoff(self) -> None:
        prepare_response = create_session(
            CreateSessionRequest(
                task_key="IOS-40003BUG",
                workflow_profile="bug_full",
                policy={"test_policy": "enabled"},
            ),
            dependencies=self.dependencies,
        )
        __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40003BUG"),
            dependencies=self.dependencies,
        )

        response = inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="bug_analysis_completed",
                payload={"summary": "Need to restore coordinator state"},
            ),
            dependencies=self.dependencies,
        )
        work_items_response = list_work_items(
            session_id=prepare_response.session.id,
            dependencies=self.dependencies,
        )

        self.assertEqual("implementation_requested", response.followup_event_type)
        self.assertEqual("implementation_requested", response.session.current_stage)
        self.assertEqual(BUG_FIXER_ROLE, response.session.current_owner)
        self.assertEqual(2, len(work_items_response.items))

    def test_prepare_session_route_uses_proposal_context_for_story_full(self) -> None:
        from backend.api.routes_sessions import prepare_session

        create_response = create_session(
            CreateSessionRequest(
                task_key="IOS-40002STORY",
                workflow_profile="story_full",
            ),
            dependencies=self.dependencies,
        )

        response = prepare_session(
            PrepareSessionRequest(task_key="IOS-40002STORY"),
            dependencies=self.dependencies,
        )

        self.assertFalse(response.created)
        self.assertEqual(create_response.session.id, response.session.id)
        self.assertEqual("story_full", response.session.workflow_profile)
        self.assertEqual("proposal_context_requested", response.followup_event_type)
        self.assertEqual("proposal_context_requested", response.session.current_stage)

    def test_create_session_route_accepts_story_clarification_mode(self) -> None:
        response = create_session(
            CreateSessionRequest(
                task_key="IOS-40002CLARIFY",
                workflow_profile="story_full",
                policy={"requirements_clarification_mode": "ask-a-lot"},
            ),
            dependencies=self.dependencies,
        )

        self.assertEqual("ask-a-lot", response.session.policy["requirements_clarification_mode"])

    def test_proposal_context_completed_event_returns_story_spec_handoff(self) -> None:
        prepare_response = create_session(
            CreateSessionRequest(
                task_key="IOS-40003PCTX",
                workflow_profile="story_full",
            ),
            dependencies=self.dependencies,
        )
        __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40003PCTX"),
            dependencies=self.dependencies,
        )

        response = inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="proposal_context_completed",
                payload={"summary": "Context prepared"},
            ),
            dependencies=self.dependencies,
        )

        self.assertEqual("requirements_requested", response.followup_event_type)
        self.assertEqual("requirements_requested", response.session.current_stage)

    def test_requirements_completed_event_returns_acceptance_criteria_handoff(self) -> None:
        prepare_response = create_session(
            CreateSessionRequest(
                task_key="IOS-40003REQ",
                workflow_profile="story_full",
            ),
            dependencies=self.dependencies,
        )
        __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40003REQ"),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="proposal_context_completed",
                payload={"summary": "Context prepared"},
            ),
            dependencies=self.dependencies,
        )

        response = inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="requirements_completed",
                payload={"summary": "Requirements prepared"},
            ),
            dependencies=self.dependencies,
        )

        self.assertEqual("acceptance_criteria_requested", response.followup_event_type)
        self.assertEqual("acceptance_criteria_requested", response.session.current_stage)

    def test_acceptance_criteria_completed_event_returns_constraints_handoff(self) -> None:
        prepare_response = create_session(
            CreateSessionRequest(
                task_key="IOS-40003ACC",
                workflow_profile="story_full",
            ),
            dependencies=self.dependencies,
        )
        __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40003ACC"),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="proposal_context_completed",
                payload={"summary": "Context prepared"},
            ),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="requirements_completed",
                payload={"summary": "Requirements prepared"},
            ),
            dependencies=self.dependencies,
        )

        response = inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="acceptance_criteria_completed",
                payload={"summary": "Acceptance prepared"},
            ),
            dependencies=self.dependencies,
        )

        self.assertEqual("constraints_requested", response.followup_event_type)
        self.assertEqual("constraints_requested", response.session.current_stage)

    def test_constraints_completed_event_returns_spec_verification_handoff(self) -> None:
        prepare_response = create_session(
            CreateSessionRequest(
                task_key="IOS-40003CONSTR",
                workflow_profile="story_full",
            ),
            dependencies=self.dependencies,
        )
        __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40003CONSTR"),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="proposal_context_completed",
                payload={"summary": "Context prepared"},
            ),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="requirements_completed",
                payload={"summary": "Requirements prepared"},
            ),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="acceptance_criteria_completed",
                payload={"summary": "Acceptance prepared"},
            ),
            dependencies=self.dependencies,
        )

        response = inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="constraints_completed",
                payload={"summary": "Constraints prepared"},
            ),
            dependencies=self.dependencies,
        )

        self.assertEqual("spec_verification_requested", response.followup_event_type)
        self.assertEqual("spec_verification_requested", response.session.current_stage)

    def test_spec_verification_completed_event_returns_story_spec_handoff(self) -> None:
        prepare_response = create_session(
            CreateSessionRequest(
                task_key="IOS-40003VERIFY",
                workflow_profile="story_full",
            ),
            dependencies=self.dependencies,
        )
        __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40003VERIFY"),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="proposal_context_completed",
                payload={"summary": "Context prepared"},
            ),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="requirements_completed",
                payload={"summary": "Requirements prepared"},
            ),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="acceptance_criteria_completed",
                payload={"summary": "Acceptance prepared"},
            ),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="constraints_completed",
                payload={"summary": "Constraints prepared"},
            ),
            dependencies=self.dependencies,
        )

        response = inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="spec_verification_completed",
                payload={"summary": "Planning verified"},
            ),
            dependencies=self.dependencies,
        )

        self.assertEqual("story_spec_requested", response.followup_event_type)
        self.assertEqual("story_spec_requested", response.session.current_stage)

    def test_story_spec_completed_event_returns_task_decomposition_handoff(self) -> None:
        prepare_response = create_session(
            CreateSessionRequest(
                task_key="IOS-40003STORY",
                workflow_profile="story_full",
            ),
            dependencies=self.dependencies,
        )
        __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40003STORY"),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="proposal_context_completed",
                payload={"summary": "Context prepared"},
            ),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="requirements_completed",
                payload={"summary": "Requirements prepared"},
            ),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="acceptance_criteria_completed",
                payload={"summary": "Acceptance prepared"},
            ),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="constraints_completed",
                payload={"summary": "Constraints prepared"},
            ),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="spec_verification_completed",
                payload={"summary": "Planning verified"},
            ),
            dependencies=self.dependencies,
        )

        response = inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="story_spec_completed",
                payload={"summary": "Define screen structure first"},
            ),
            dependencies=self.dependencies,
        )
        work_items_response = list_work_items(
            session_id=prepare_response.session.id,
            dependencies=self.dependencies,
        )

        self.assertEqual("task_decomposition_requested", response.followup_event_type)
        self.assertEqual("task_decomposition_requested", response.session.current_stage)
        self.assertEqual(7, len(work_items_response.items))

    def test_task_decomposition_completed_event_returns_implementation_handoff(self) -> None:
        prepare_response = create_session(
            CreateSessionRequest(
                task_key="IOS-40003DECOMP",
                workflow_profile="story_full",
            ),
            dependencies=self.dependencies,
        )
        __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40003DECOMP"),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="proposal_context_completed",
                payload={"summary": "Context prepared"},
            ),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="requirements_completed",
                payload={"summary": "Requirements prepared"},
            ),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="acceptance_criteria_completed",
                payload={"summary": "Acceptance prepared"},
            ),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="constraints_completed",
                payload={"summary": "Constraints prepared"},
            ),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="spec_verification_completed",
                payload={"summary": "Planning verified"},
            ),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="story_spec_completed",
                payload={"summary": "Define screen structure first"},
            ),
            dependencies=self.dependencies,
        )
        self.write_statuses_file(
            "IOS-40003DECOMP",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-40003DECOMP | Story | Parent story | In Progress |
| IOS-40030 | Sub-task | Already done one | Ready for test |
| IOS-40031 | Sub-task | Already done two | Released |
""",
        )

        response = inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="task_decomposition_completed",
                payload={"summary": "Split into execution chunks"},
            ),
            dependencies=self.dependencies,
        )

        self.assertEqual("implementation_requested", response.followup_event_type)
        self.assertEqual("implementation_requested", response.session.current_stage)

    def test_start_subtask_graph_route_converts_story_session(self) -> None:
        from backend.api.routes_sessions import prepare_session

        create_response = create_session(
            CreateSessionRequest(
                task_key="IOS-40003SUBTASK",
                workflow_profile="story_full",
            ),
            dependencies=self.dependencies,
        )
        prepare_session(
            PrepareSessionRequest(task_key="IOS-40003SUBTASK"),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=create_response.session.id,
                event_type="proposal_context_completed",
                payload={"summary": "Context prepared"},
            ),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=create_response.session.id,
                event_type="requirements_completed",
                payload={"summary": "Requirements prepared"},
            ),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=create_response.session.id,
                event_type="acceptance_criteria_completed",
                payload={"summary": "Acceptance prepared"},
            ),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=create_response.session.id,
                event_type="constraints_completed",
                payload={"summary": "Constraints prepared"},
            ),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=create_response.session.id,
                event_type="spec_verification_completed",
                payload={"summary": "Planning verified"},
            ),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=create_response.session.id,
                event_type="story_spec_completed",
                payload={"summary": "Split work into subtasks"},
            ),
            dependencies=self.dependencies,
        )
        self.write_statuses_file(
            "IOS-40003SUBTASK",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-40003SUBTASK | Story | Parent story | In Progress |
| IOS-40103 | Sub-task | Already done one | Ready for test |
| IOS-40104 | Sub-task | Already done two | Released |
""",
        )
        inject_event(
            InjectEventRequest(
                session_id=create_response.session.id,
                event_type="task_decomposition_completed",
                payload={"summary": "Execution chunks prepared"},
            ),
            dependencies=self.dependencies,
        )
        self.write_statuses_file(
            "IOS-40003SUBTASK",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-40003SUBTASK | Story | Parent story | In Progress |
| IOS-40100 | Sub-task | Build repository | To Do |
| IOS-40101 | Sub-task | Connect presenter | In Progress |
| IOS-40102 | Sub-task | Final QA polish | Ready for test |
""",
        )

        response = start_subtask_graph(
            StartSubtaskGraphRequest(session_id=create_response.session.id),
            dependencies=self.dependencies,
        )
        work_items_response = list_work_items(
            session_id=create_response.session.id,
            dependencies=self.dependencies,
        )

        self.assertTrue(response.started)
        self.assertEqual("subtask_graph_requested", response.event_type)
        self.assertEqual("subtask_implementation_requested", response.followup_event_type)
        self.assertEqual("subtask_implementation_requested", response.session.current_stage)
        self.assertEqual(9, len(work_items_response.items))

    def test_subtask_completed_event_keeps_story_session_in_subtask_lane(self) -> None:
        from backend.api.routes_sessions import prepare_session

        create_response = create_session(
            CreateSessionRequest(
                task_key="IOS-40004SUBTASK",
                workflow_profile="story_full",
                policy={"self_review_policy": "disabled"},
            ),
            dependencies=self.dependencies,
        )
        prepare_session(
            PrepareSessionRequest(task_key="IOS-40004SUBTASK"),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=create_response.session.id,
                event_type="proposal_context_completed",
                payload={"summary": "Context prepared"},
            ),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=create_response.session.id,
                event_type="requirements_completed",
                payload={"summary": "Requirements prepared"},
            ),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=create_response.session.id,
                event_type="acceptance_criteria_completed",
                payload={"summary": "Acceptance prepared"},
            ),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=create_response.session.id,
                event_type="constraints_completed",
                payload={"summary": "Constraints prepared"},
            ),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=create_response.session.id,
                event_type="spec_verification_completed",
                payload={"summary": "Planning verified"},
            ),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=create_response.session.id,
                event_type="story_spec_completed",
                payload={"summary": "Split work into subtasks"},
            ),
            dependencies=self.dependencies,
        )
        self.write_statuses_file(
            "IOS-40004SUBTASK",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-40004SUBTASK | Story | Parent story | In Progress |
| IOS-40112 | Sub-task | Already done one | Ready for test |
| IOS-40113 | Sub-task | Already done two | Released |
""",
        )
        inject_event(
            InjectEventRequest(
                session_id=create_response.session.id,
                event_type="task_decomposition_completed",
                payload={"summary": "Execution chunks prepared"},
            ),
            dependencies=self.dependencies,
        )
        self.write_statuses_file(
            "IOS-40004SUBTASK",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-40004SUBTASK | Story | Parent story | In Progress |
| IOS-40110 | Sub-task | Build data source | To Do |
| IOS-40111 | Sub-task | Wire screen state | To Do |
""",
        )
        start_subtask_graph(
            StartSubtaskGraphRequest(session_id=create_response.session.id),
            dependencies=self.dependencies,
        )

        first_response = inject_event(
            InjectEventRequest(
                session_id=create_response.session.id,
                event_type="subtask_completed",
                payload={"summary": "First subtask done"},
            ),
            dependencies=self.dependencies,
        )
        second_response = inject_event(
            InjectEventRequest(
                session_id=create_response.session.id,
                event_type="subtask_completed",
                payload={"summary": "Second subtask done"},
            ),
            dependencies=self.dependencies,
        )

        self.assertEqual("subtask_implementation_requested", first_response.followup_event_type)
        self.assertEqual("subtask_implementation_requested", first_response.session.current_stage)
        self.assertEqual("verification_requested", second_response.followup_event_type)
        self.assertEqual("verification_requested", second_response.session.current_stage)

    def test_create_knowledge_route_writes_repo_visible_file(self) -> None:
        from backend.api.routes_sessions import prepare_session

        prepare_response = prepare_session(
            PrepareSessionRequest(task_key="IOS-40005KNOW"),
            dependencies=self.dependencies,
        )
        response = create_knowledge(
            CreateKnowledgeRequest(
                session_id=prepare_response.session.id,
                title="Reuse existing navigation assembly",
                guidance="Prefer the existing assembly instead of adding a new navigation helper.",
                scope="navigation",
            ),
            dependencies=self.dependencies,
        )

        knowledge_files = list(
            (Path(self.temp_dir.name) / "IOS-40005KNOW" / "repo" / "knowledge").rglob("*.md")
        )
        self.assertTrue(response.created)
        self.assertEqual("knowledge_created", response.event_type)
        self.assertTrue(any("Reuse existing navigation assembly" in path.read_text() for path in knowledge_files))

    def test_create_subtasks_from_plan_route_records_batch_run(self) -> None:
        from backend.api.routes_sessions import create_session, prepare_session

        create_response = create_session(
            CreateSessionRequest(
                task_key="IOS-40005SUBBATCH",
                workflow_profile="story_full",
            ),
            dependencies=self.dependencies,
        )
        prepare_session(
            PrepareSessionRequest(task_key="IOS-40005SUBBATCH"),
            dependencies=self.dependencies,
        )
        plan_dir = Path(self.temp_dir.name) / "IOS-40005SUBBATCH" / "plan"
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / "index.md").write_text(
            "# Execution Task List\n\n| # | Task | Depends on | Status |\n|---|------|------------|--------|\n| 01 | [Build data source](./01-build-data-source.md) | — | ☐ |\n"
        )
        (plan_dir / "01-build-data-source.md").write_text(
            "# Build data source\n\n## What to implement\nCreate the feature data source.\n"
        )

        response = create_subtasks_from_plan(
            CreateSubtasksFromPlanRequest(session_id=create_response.session.id),
            dependencies=self.dependencies,
        )
        artifacts_response = list_artifacts(
            session_id=create_response.session.id,
            dependencies=self.dependencies,
        )

        self.assertTrue(response.created)
        self.assertEqual("jira_subtasks_created", response.event_type)
        self.assertTrue(any(item.artifact_type == "jira_subtasks_stdout" for item in artifacts_response.items))
        self.assertTrue(any(item.artifact_type == "jira_subtasks_summary" for item in artifacts_response.items))
        self.assertTrue(any(item.artifact_type == "subtasks_snapshot_stdout" for item in artifacts_response.items))

    def test_create_subtasks_from_plan_route_can_auto_start_subtask_lane(self) -> None:
        from backend.api.routes_sessions import create_session, prepare_session

        create_response = create_session(
            CreateSessionRequest(
                task_key="IOS-40005SUBAUTO",
                workflow_profile="story_full",
                policy={"self_review_policy": "disabled"},
            ),
            dependencies=self.dependencies,
        )
        prepare_session(
            PrepareSessionRequest(task_key="IOS-40005SUBAUTO"),
            dependencies=self.dependencies,
        )
        for event_type in (
            "proposal_context_completed",
            "requirements_completed",
            "acceptance_criteria_completed",
            "constraints_completed",
            "spec_verification_completed",
            "story_spec_completed",
        ):
            inject_event(
                InjectEventRequest(
                    session_id=create_response.session.id,
                    event_type=event_type,
                    payload={"summary": "prepared"},
                ),
                dependencies=self.dependencies,
            )
        inject_event(
            InjectEventRequest(
                session_id=create_response.session.id,
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
            ),
            dependencies=self.dependencies,
        )
        self.write_statuses_file(
            "IOS-40005SUBAUTO",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-40005SUBAUTO | Story | Parent story | In Progress |
| IOS-40120 | Sub-task | Build data source | To Do |
| IOS-40121 | Sub-task | Finish docs | Ready for test |
""",
        )

        response = create_subtasks_from_plan(
            CreateSubtasksFromPlanRequest(session_id=create_response.session.id),
            dependencies=self.dependencies,
        )

        self.assertTrue(response.created)
        self.assertEqual("jira_subtasks_created", response.event_type)
        self.assertEqual("subtask_implementation_requested", response.followup_event_type)
        self.assertEqual("subtask_implementation_requested", response.session.current_stage)

    def test_list_knowledge_route_returns_repo_visible_items(self) -> None:
        from backend.api.routes_sessions import prepare_session

        prepare_response = prepare_session(
            PrepareSessionRequest(task_key="IOS-40008KNOW"),
            dependencies=self.dependencies,
        )
        create_knowledge(
            CreateKnowledgeRequest(
                session_id=prepare_response.session.id,
                title="Presenter cache owns the state",
                guidance="Treat presenter cache as the durable source of truth in this feature area.",
                scope="card-details",
            ),
            dependencies=self.dependencies,
        )

        response = list_knowledge(dependencies=self.dependencies)

        self.assertTrue(any(item.title == "Presenter cache owns the state" for item in response.items))

    def test_verification_failed_event_returns_correction_handoff(self) -> None:
        prepare_response = __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40004"),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="implementation_completed",
                payload={"summary": "done"},
            ),
            dependencies=self.dependencies,
        )

        response = inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="verification_failed",
                payload={"failures": ["tests failed"]},
            ),
            dependencies=self.dependencies,
        )
        work_items_response = list_work_items(
            session_id=prepare_response.session.id,
            dependencies=self.dependencies,
        )

        self.assertEqual("verification_correction_requested", response.followup_event_type)
        self.assertEqual("verification_correction_requested", response.session.current_stage)
        self.assertEqual("implementer", response.session.current_owner)
        self.assertEqual(3, len(work_items_response.items))

    def test_verification_passed_event_completes_session(self) -> None:
        prepare_response = __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40005"),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="implementation_completed",
                payload={"summary": "done"},
            ),
            dependencies=self.dependencies,
        )

        response = inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="verification_passed",
                payload={"summary": "all green"},
            ),
            dependencies=self.dependencies,
        )
        events_response = list_events(
            session_id=prepare_response.session.id,
            dependencies=self.dependencies,
        )

        self.assertEqual("task_completed", response.followup_event_type)
        self.assertEqual("completed", response.session.current_stage)
        self.assertEqual("completed", response.session.status)
        self.assertEqual(9, len(events_response.items))

    def test_role_output_route_maps_to_domain_event(self) -> None:
        prepare_response = __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40006"),
            dependencies=self.dependencies,
        )

        response = submit_role_output(
            RoleOutputRequest(
                session_id=prepare_response.session.id,
                role_name="implementer",
                output_type="completed",
                payload={"summary": "done"},
            ),
            dependencies=self.dependencies,
        )
        events_response = list_events(
            session_id=prepare_response.session.id,
            dependencies=self.dependencies,
        )

        self.assertEqual("implementation_completed", response.mapped_event_type)
        self.assertEqual("verification_requested", response.followup_event_type)
        self.assertEqual("verification_requested", response.session.current_stage)
        self.assertEqual(7, len(events_response.items))

    def test_artifact_detail_route_returns_content_and_metadata(self) -> None:
        prepare_response = __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40007"),
            dependencies=self.dependencies,
        )
        submit_role_output(
            RoleOutputRequest(
                session_id=prepare_response.session.id,
                role_name="implementer",
                output_type="completed",
                payload={"summary": "done"},
            ),
            dependencies=self.dependencies,
        )

        artifacts_response = list_artifacts(
            session_id=prepare_response.session.id,
            dependencies=self.dependencies,
        )
        output_artifact = next(
            artifact for artifact in artifacts_response.items if artifact.artifact_type == "role_output_json"
        )
        detail = get_artifact(
            artifact_id=output_artifact.id,
            dependencies=self.dependencies,
        )

        self.assertEqual("role_output_json", detail.artifact_type)
        self.assertEqual("implementer", detail.metadata["role_name"])
        self.assertIn('"summary": "done"', detail.content)

    def test_collect_role_output_route_returns_chunk_count(self) -> None:
        prepare_response = __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40008"),
            dependencies=self.dependencies,
        )
        implementer_role = self.dependencies.role_repository.get_by_name(
            prepare_response.session.id,
            "implementer",
        )
        self.dependencies.session_backend.simulate_output(implementer_role.runtime_handle, "line 1")
        self.dependencies.session_backend.simulate_output(implementer_role.runtime_handle, "line 2")

        response = collect_role_output(
            CollectRoleOutputRequest(
                session_id=prepare_response.session.id,
                role_name="implementer",
            ),
            dependencies=self.dependencies,
        )

        self.assertTrue(response.collected)
        self.assertEqual(2, response.chunk_count)
        self.assertEqual("role_output_collected", response.event_type)

    def test_collect_role_output_route_normalizes_marker(self) -> None:
        prepare_response = __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40008"),
            dependencies=self.dependencies,
        )
        implementer_role = self.dependencies.role_repository.get_by_name(
            prepare_response.session.id,
            "implementer",
        )
        self.dependencies.session_backend.simulate_output(
            implementer_role.runtime_handle,
            'SDD_OUTPUT: {"output_type":"completed","payload":{"summary":"done"}}',
        )

        response = collect_role_output(
            CollectRoleOutputRequest(
                session_id=prepare_response.session.id,
                role_name="implementer",
            ),
            dependencies=self.dependencies,
        )
        events_response = list_events(
            session_id=prepare_response.session.id,
            dependencies=self.dependencies,
        )

        self.assertTrue(response.collected)
        self.assertEqual(1, response.chunk_count)
        self.assertEqual("role_output_collected", response.event_type)
        self.assertTrue(any(item.event_type == "implementation_completed" for item in events_response.items))
        self.assertTrue(any(item.event_type == "verification_requested" for item in events_response.items))

    def test_collect_role_output_route_consumes_result_json(self) -> None:
        prepare_response = __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40008B"),
            dependencies=self.dependencies,
        )
        role_workspace = self.dependencies.coordinator_service.role_workspace_manager.role_directory(  # type: ignore[union-attr]
            "IOS-40008B",
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

        response = collect_role_output(
            CollectRoleOutputRequest(
                session_id=prepare_response.session.id,
                role_name="implementer",
            ),
            dependencies=self.dependencies,
        )
        self.assertTrue(response.collected)
        self.assertEqual(1, response.chunk_count)
        self.assertEqual("role_output_collected", response.event_type)
        self.assertEqual("verification_requested", response.session.current_stage)
        self.assertFalse(result_path.exists())

    def test_poll_session_output_route_collects_all_role_chunks(self) -> None:
        prepare_response = __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40008"),
            dependencies=self.dependencies,
        )
        implementer_role = self.dependencies.role_repository.get_by_name(
            prepare_response.session.id,
            "implementer",
        )
        verification_role = self.dependencies.role_repository.get_by_name(
            prepare_response.session.id,
            "verification-coordinator",
        )
        self.dependencies.session_backend.simulate_output(implementer_role.runtime_handle, "impl line")
        self.dependencies.session_backend.simulate_output(verification_role.runtime_handle, "verif line")

        response = poll_session_output(
            PollSessionOutputRequest(session_id=prepare_response.session.id),
            dependencies=self.dependencies,
        )
        artifacts_response = list_artifacts(
            session_id=prepare_response.session.id,
            dependencies=self.dependencies,
        )

        self.assertTrue(response.polled)
        self.assertEqual(4, response.role_count)
        self.assertEqual(2, response.chunk_count)
        self.assertEqual("session_output_polled", response.event_type)
        runtime_outputs = [a for a in artifacts_response.items if a.artifact_type == "runtime_output"]
        self.assertEqual(2, len(runtime_outputs))

    def test_poll_session_output_route_consumes_result_json(self) -> None:
        prepare_response = __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40008C"),
            dependencies=self.dependencies,
        )
        role_workspace = self.dependencies.coordinator_service.role_workspace_manager.role_directory(  # type: ignore[union-attr]
            "IOS-40008C",
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

        response = poll_session_output(
            PollSessionOutputRequest(session_id=prepare_response.session.id),
            dependencies=self.dependencies,
        )

        self.assertTrue(response.polled)
        self.assertEqual(4, response.role_count)
        self.assertEqual(1, response.chunk_count)
        self.assertEqual("session_output_polled", response.event_type)
        self.assertEqual("verification_requested", response.session.current_stage)
        self.assertFalse(result_path.exists())

    def test_event_bus_recent_events_reflect_api_actions(self) -> None:
        prepare_response = __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40009"),
            dependencies=self.dependencies,
        )
        submit_role_output(
            RoleOutputRequest(
                session_id=prepare_response.session.id,
                role_name="implementer",
                output_type="completed",
                payload={"summary": "done"},
            ),
            dependencies=self.dependencies,
        )

        recent = self.dependencies.event_bus.recent_events(session_id=prepare_response.session.id)

        self.assertTrue(any(event.event_type == "implementation_completed" for event in recent))
        self.assertTrue(any(event.event_type == "verification_requested" for event in recent))

    def test_run_loop_once_route_polls_active_sessions(self) -> None:
        prepare_a = __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40011"),
            dependencies=self.dependencies,
        )
        prepare_b = __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40012"),
            dependencies=self.dependencies,
        )
        implementer_a = self.dependencies.role_repository.get_by_name(prepare_a.session.id, "implementer")
        implementer_b = self.dependencies.role_repository.get_by_name(prepare_b.session.id, "implementer")
        self.dependencies.session_backend.simulate_output(implementer_a.runtime_handle, "a line")
        self.dependencies.session_backend.simulate_output(implementer_b.runtime_handle, "b line")

        response = run_loop_once(dependencies=self.dependencies)

        self.assertTrue(response.ran)
        self.assertEqual(2, response.session_count)
        self.assertEqual(2, response.chunk_count)
        self.assertEqual("coordinator_loop_ran", response.event_type)

    def test_loop_runner_routes_control_background_loop(self) -> None:
        start_response = start_loop(dependencies=self.dependencies)
        self.assertTrue(start_response.changed)
        self.assertTrue(start_response.status.running)

        time.sleep(0.03)

        status_response = loop_status(dependencies=self.dependencies)
        self.assertTrue(status_response.running)
        self.assertGreaterEqual(status_response.tick_count, 1)

        stop_response = stop_loop(dependencies=self.dependencies)
        self.assertTrue(stop_response.changed)
        self.assertFalse(stop_response.status.running)

    def test_resume_session_route_reactivates_escalated_session(self) -> None:
        prepare_response = __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40013"),
            dependencies=self.dependencies,
        )
        implementer_role = self.dependencies.role_repository.get_by_name(
            prepare_response.session.id,
            "implementer",
        )
        self.dependencies.session_backend.simulate_output(
            implementer_role.runtime_handle,
            'SDD_ERROR: {"summary":"tool failed","details":"command exited 1"}',
        )
        collect_role_output(
            CollectRoleOutputRequest(
                session_id=prepare_response.session.id,
                role_name="implementer",
            ),
            dependencies=self.dependencies,
        )

        response = resume_session(
            ResumeSessionRequest(session_id=prepare_response.session.id),
            dependencies=self.dependencies,
        )

        self.assertTrue(response.resumed)
        self.assertEqual("session_resumed_by_operator", response.event_type)
        self.assertEqual("role_input_dispatched", response.followup_event_type)
        self.assertEqual("active", response.session.status)
        self.assertEqual("implementer", response.session.current_owner)

    def test_resume_session_route_reactivates_mcp_blocker_without_redispatch(self) -> None:
        prepare_response = __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40013MCP"),
            dependencies=self.dependencies,
        )
        implementer_role = self.dependencies.role_repository.get_by_name(
            prepare_response.session.id,
            "implementer",
        )
        self.dependencies.session_backend.simulate_output(
            implementer_role.runtime_handle,
            'SDD_ERROR: {"summary":"required mcp access unavailable","details":"restore vpn","resume_strategy":"reactivate_only"}',
        )
        collect_role_output(
            CollectRoleOutputRequest(
                session_id=prepare_response.session.id,
                role_name="implementer",
            ),
            dependencies=self.dependencies,
        )

        response = resume_session(
            ResumeSessionRequest(session_id=prepare_response.session.id),
            dependencies=self.dependencies,
        )

        self.assertTrue(response.resumed)
        self.assertEqual("session_resumed_by_operator", response.event_type)
        self.assertIsNone(response.followup_event_type)
        self.assertEqual("active", response.session.status)
        self.assertEqual("implementer", response.session.current_owner)

    def test_send_runtime_input_route_continues_waiting_session(self) -> None:
        prepare_response = __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40013A"),
            dependencies=self.dependencies,
        )
        implementer_role = self.dependencies.role_repository.get_by_name(
            prepare_response.session.id,
            "implementer",
        )
        self.dependencies.session_backend.simulate_output(
            implementer_role.runtime_handle,
            'SDD_ERROR: {"summary":"tool failed","details":"command exited 1"}',
        )
        collect_role_output(
            CollectRoleOutputRequest(
                session_id=prepare_response.session.id,
                role_name="implementer",
            ),
            dependencies=self.dependencies,
        )

        response = send_runtime_input(
            SendOperatorRuntimeInputRequest(
                session_id=prepare_response.session.id,
                text="1",
            ),
            dependencies=self.dependencies,
        )

        self.assertTrue(response.sent)
        self.assertEqual("operator_runtime_input_sent", response.event_type)
        self.assertEqual("active", response.session.status)
        self.assertEqual("implementer", response.session.current_owner)
        self.assertEqual(
            ["1"],
            self.dependencies.session_backend.get_sent_inputs(implementer_role.runtime_handle)[-1:],
        )

    def test_get_interactive_state_route_returns_runtime_blocker_summary(self) -> None:
        prepare_response = __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40013B"),
            dependencies=self.dependencies,
        )
        implementer_role = self.dependencies.role_repository.get_by_name(
            prepare_response.session.id,
            "implementer",
        )
        self.dependencies.session_backend.simulate_output(
            implementer_role.runtime_handle,
            'SDD_ERROR: {"summary":"interactive selection required","details":"operator choice needed"}',
        )
        collect_role_output(
            CollectRoleOutputRequest(
                session_id=prepare_response.session.id,
                role_name="implementer",
            ),
            dependencies=self.dependencies,
        )

        response = get_interactive_state(
            prepare_response.session.id,
            dependencies=self.dependencies,
        )

        self.assertTrue(response.available)
        self.assertEqual("implementer", response.role_name)
        self.assertEqual("interactive selection required", response.summary)
        self.assertEqual("operator choice needed", response.details)
        self.assertEqual("session_escalated_to_operator", response.source_event_type)
        self.assertTrue(response.needs_operator_input)

    def test_get_interactive_state_route_clears_after_operator_runtime_input(self) -> None:
        prepare_response = __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40013C"),
            dependencies=self.dependencies,
        )
        implementer_role = self.dependencies.role_repository.get_by_name(
            prepare_response.session.id,
            "implementer",
        )
        self.dependencies.session_backend.simulate_output(
            implementer_role.runtime_handle,
            'SDD_ERROR: {"summary":"interactive selection required","details":"operator choice needed"}',
        )
        collect_role_output(
            CollectRoleOutputRequest(
                session_id=prepare_response.session.id,
                role_name="implementer",
            ),
            dependencies=self.dependencies,
        )
        send_runtime_input(
            SendOperatorRuntimeInputRequest(
                session_id=prepare_response.session.id,
                text="1",
            ),
            dependencies=self.dependencies,
        )

        response = get_interactive_state(
            prepare_response.session.id,
            dependencies=self.dependencies,
        )

        self.assertFalse(response.available)
        self.assertFalse(response.needs_operator_input)

    def test_requirements_clarifier_runtime_input_can_continue_story_flow(self) -> None:
        create_response = create_session(
            CreateSessionRequest(
                task_key="IOS-40013REQINT",
                workflow_profile="story_full",
                policy={"boy_scout_policy": "disabled"},
            ),
            dependencies=self.dependencies,
        )
        prepare_session(
            PrepareSessionRequest(task_key="IOS-40013REQINT"),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=create_response.session.id,
                event_type="proposal_context_completed",
                payload={"summary": "proposal ready"},
            ),
            dependencies=self.dependencies,
        )
        clarifier_role = self.dependencies.role_repository.get_by_name(
            create_response.session.id,
            REQUIREMENTS_CLARIFIER_WORKER_ROLE,
        )
        self.dependencies.session_backend.simulate_output(
            clarifier_role.runtime_handle,
            'SDD_ERROR: {"summary":"clarification required","details":"Need product decision about fallback behavior."}',
        )
        collect_role_output(
            CollectRoleOutputRequest(
                session_id=create_response.session.id,
                role_name=REQUIREMENTS_CLARIFIER_WORKER_ROLE,
            ),
            dependencies=self.dependencies,
        )

        send_runtime_input(
            SendOperatorRuntimeInputRequest(
                session_id=create_response.session.id,
                text="Use the existing fallback behavior and document it explicitly.",
            ),
            dependencies=self.dependencies,
        )
        self.dependencies.session_backend.simulate_output(
            clarifier_role.runtime_handle,
            'SDD_OUTPUT: {"output_type":"completed","payload":{"summary":"Requirements clarified","assumptions":"Fallback stays unchanged."}}',
        )

        response = collect_role_output(
            CollectRoleOutputRequest(
                session_id=create_response.session.id,
                role_name=REQUIREMENTS_CLARIFIER_WORKER_ROLE,
            ),
            dependencies=self.dependencies,
        )
        events_response = list_events(create_response.session.id, dependencies=self.dependencies)

        self.assertEqual("acceptance_criteria_requested", response.session.current_stage)
        self.assertTrue(any(item.event_type == "requirements_completed" for item in events_response.items))

    def test_skip_boy_scout_route_moves_session_to_verification(self) -> None:
        create_response = create_session(
            CreateSessionRequest(
                task_key="IOS-40013BSKIP",
                workflow_profile="oneshot",
                policy={"boy_scout_policy": "enabled"},
            ),
            dependencies=self.dependencies,
        )
        prepare_session(
            PrepareSessionRequest(task_key="IOS-40013BSKIP"),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=create_response.session.id,
                event_type="implementation_completed",
                payload={"summary": "done"},
            ),
            dependencies=self.dependencies,
        )
        scout_role = self.dependencies.role_repository.get_by_name(
            create_response.session.id,
            "code-scout",
        )
        spec_dir = Path(self.temp_dir.name) / "IOS-40013BSKIP" / "spec"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "findings.md").write_text("SCOUT_RESULT: findings_found\n\n## Finding 1: Extract helper\n")
        self.dependencies.session_backend.simulate_output(
            scout_role.runtime_handle,
            'SDD_OUTPUT: {"output_type":"completed","payload":{"result":"findings_found","summary":"Found one improvement opportunity."}}',
        )
        collect_role_output(
            CollectRoleOutputRequest(
                session_id=create_response.session.id,
                role_name="code-scout",
            ),
            dependencies=self.dependencies,
        )

        response = skip_boy_scout(
            SkipBoyScoutRequest(
                session_id=create_response.session.id,
                reason="Track the refactor separately.",
            ),
            dependencies=self.dependencies,
        )

        self.assertTrue(response.skipped)
        self.assertEqual("boy_scout_skipped_by_operator", response.event_type)
        self.assertEqual("verification_requested", response.followup_event_type)
        self.assertEqual("verification_requested", response.session.current_stage)

    def test_get_environment_doctor_route_returns_report(self) -> None:
        fake_report = {
            "overall_status": "warn",
            "repo_root": self.temp_dir.name,
            "required_ok": 2,
            "required_total": 3,
            "optional_warnings": 1,
            "checks": [
                {
                    "id": "env.SDD_WORKDIR",
                    "category": "environment",
                    "label": "Task workdir root",
                    "required": True,
                    "status": "ok",
                    "details": "ok",
                    "value": self.temp_dir.name,
                    "source": "process env",
                    "hint": None,
                }
            ],
        }

        with patch("backend.api.routes_operator.build_report", return_value=fake_report):
            response = get_environment_doctor(dependencies=self.dependencies)

        self.assertEqual("warn", response.overall_status)
        self.assertEqual(2, response.required_ok)
        self.assertEqual(3, response.required_total)
        self.assertEqual(1, len(response.checks))
        self.assertEqual("env.SDD_WORKDIR", response.checks[0].id)

    def test_get_bootstrap_guidance_route_returns_guidance(self) -> None:
        fake_report = {
            "overall_status": "warn",
            "repo_root": self.temp_dir.name,
            "required_ok": 2,
            "required_total": 3,
            "optional_warnings": 1,
            "checks": [
                {
                    "id": "env.SDD_WORKDIR",
                    "category": "environment",
                    "label": "Task workdir root",
                    "required": True,
                    "status": "missing",
                    "details": "SDD_WORKDIR is not set.",
                    "value": None,
                    "source": None,
                    "hint": "Set SDD_WORKDIR.",
                }
            ],
        }

        with patch("backend.api.routes_operator.build_report", return_value=fake_report):
            response = get_bootstrap_guidance(dependencies=self.dependencies)

        self.assertEqual("warn", response.overall_status)
        self.assertEqual(1, response.required_action_count)
        self.assertEqual("Resolve required setup issues first.", response.next_step)
        self.assertEqual("env.SDD_WORKDIR", response.required_actions[0].id)

    def test_get_runtime_capabilities_route_returns_capability_surface(self) -> None:
        fake_capabilities = {
            "available_runners": ["claude", "codex"],
            "default_runner": "claude",
            "runners": [
                {
                    "runner": "claude",
                    "available": True,
                    "source": "local cli probe + curated alias catalog",
                    "path": "/usr/bin/claude",
                    "supports_custom_model": True,
                    "models": [
                        {
                            "id": "sonnet",
                            "label": "Sonnet",
                            "supported_efforts": ["low", "medium", "high", "xhigh", "max"],
                            "default_effort": "medium",
                            "visibility": "list",
                            "supported_in_api": True,
                            "source": "anthropic alias catalog",
                        }
                    ],
                }
            ],
            "legacy_role_defaults": [
                {
                    "role_name": "implementer",
                    "model": "sonnet",
                    "effort": "medium",
                    "mcp_servers": ["ios-rag", "android-rag", "frontend-rag"],
                    "source": ".claude/agents/implementer.md",
                }
            ],
        }

        with patch("backend.api.routes_operator.build_runtime_capabilities", return_value=fake_capabilities):
            response = get_runtime_capabilities(dependencies=self.dependencies)

        self.assertEqual(["claude", "codex"], response.available_runners)
        self.assertEqual("claude", response.default_runner)
        self.assertEqual("claude", response.runners[0].runner)
        self.assertEqual("sonnet", response.runners[0].models[0].id)
        self.assertEqual("implementer", response.legacy_role_defaults[0].role_name)

    def test_get_runtime_state_route_returns_runtime_handles(self) -> None:
        prepare_response = __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40013R"),
            dependencies=self.dependencies,
        )

        response = get_runtime_state(
            prepare_response.session.id,
            dependencies=self.dependencies,
        )

        self.assertTrue(response.available)
        self.assertTrue(response.runtime_session_id)
        self.assertGreaterEqual(len(response.roles), 1)
        self.assertTrue(any(role.role_name == "implementer" for role in response.roles))

    def test_get_runtime_state_route_returns_last_auto_recovery(self) -> None:
        from tests.backend.test_session_creation import AutoRecoveryRecordingBackend

        backend = AutoRecoveryRecordingBackend()
        self.dependencies.session_backend = backend
        self.dependencies.coordinator_service.session_backend = backend
        prepare_response = __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40013RA"),
            dependencies=self.dependencies,
        )
        session_id = prepare_response.session.id
        implementer_role = self.dependencies.role_repository.get_by_name(session_id, "implementer")
        assert implementer_role is not None
        assert implementer_role.runtime_handle is not None
        backend.mark_dead(implementer_role.runtime_handle)
        self.dependencies.coordinator_service.run_loop_once()

        response = get_runtime_state(
            session_id,
            dependencies=self.dependencies,
        )

        self.assertIsNotNone(response.last_auto_recovery)
        assert response.last_auto_recovery is not None
        self.assertEqual("implementer", response.last_auto_recovery.role_name)

    def test_stop_runtime_role_route_stops_role_and_pauses_session(self) -> None:
        prepare_response = __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40013S"),
            dependencies=self.dependencies,
        )

        response = stop_runtime_role(
            StopRuntimeRoleRequest(
                session_id=prepare_response.session.id,
                role_name="implementer",
            ),
            dependencies=self.dependencies,
        )

        self.assertTrue(response.stopped)
        self.assertEqual("runtime_role_stopped_by_operator", response.event_type)
        self.assertEqual("paused", response.session.status)

    def test_stop_runtime_session_route_stops_all_roles_and_pauses_session(self) -> None:
        prepare_response = __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40013T"),
            dependencies=self.dependencies,
        )

        response = stop_runtime_session(
            StopRuntimeSessionRequest(session_id=prepare_response.session.id),
            dependencies=self.dependencies,
        )

        self.assertTrue(response.stopped)
        self.assertEqual("runtime_session_stopped_by_operator", response.event_type)
        self.assertEqual("paused", response.session.status)

    def test_restart_runtime_role_route_restarts_owner_and_redispatches_work(self) -> None:
        prepare_response = __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40013U"),
            dependencies=self.dependencies,
        )
        stopped = stop_runtime_role(
            StopRuntimeRoleRequest(
                session_id=prepare_response.session.id,
                role_name="implementer",
            ),
            dependencies=self.dependencies,
        )

        response = restart_runtime_role(
            RestartRuntimeRoleRequest(
                session_id=prepare_response.session.id,
                role_name="implementer",
            ),
            dependencies=self.dependencies,
        )

        self.assertTrue(stopped.stopped)
        self.assertTrue(response.restarted)
        self.assertEqual("runtime_role_restarted_by_operator", response.event_type)
        self.assertEqual("role_input_dispatched", response.followup_event_type)
        self.assertEqual("active", response.session.status)

    def test_restart_runtime_session_route_restarts_roles_and_redispatches_owner(self) -> None:
        prepare_response = __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40013V"),
            dependencies=self.dependencies,
        )
        stopped = stop_runtime_session(
            StopRuntimeSessionRequest(session_id=prepare_response.session.id),
            dependencies=self.dependencies,
        )

        response = restart_runtime_session(
            RestartRuntimeSessionRequest(session_id=prepare_response.session.id),
            dependencies=self.dependencies,
        )

        self.assertTrue(stopped.stopped)
        self.assertTrue(response.restarted)
        self.assertEqual("runtime_session_restarted_by_operator", response.event_type)
        self.assertEqual("role_input_dispatched", response.followup_event_type)
        self.assertEqual("active", response.session.status)

    def test_pause_session_route_pauses_active_session(self) -> None:
        prepare_response = __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40014"),
            dependencies=self.dependencies,
        )

        response = pause_session(
            PauseSessionRequest(session_id=prepare_response.session.id),
            dependencies=self.dependencies,
        )

        self.assertTrue(response.paused)
        self.assertEqual("session_paused_by_operator", response.event_type)
        self.assertEqual("paused", response.session.status)
        self.assertEqual("implementer", response.session.current_owner)

    def test_ingest_mr_comments_route_reopens_completed_session(self) -> None:
        prepare_response = __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40014A"),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="implementation_completed",
                payload={"summary": "done"},
            ),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="verification_passed",
                payload={"summary": "all green"},
            ),
            dependencies=self.dependencies,
        )

        response = ingest_mr_comments(
            IngestMrCommentsRequest(
                session_id=prepare_response.session.id,
                platform="ios",
                mr_id="2942",
            ),
            dependencies=self.dependencies,
        )

        self.assertTrue(response.ingested)
        self.assertEqual("mr_comments_received", response.event_type)
        self.assertEqual("mr_followup_requested", response.followup_event_type)
        self.assertEqual("active", response.session.status)
        self.assertEqual("mr_followup_requested", response.session.current_stage)
        self.assertEqual(1, response.discussion_count)

    def test_create_mr_route_marks_completed_session_as_handed_off(self) -> None:
        prepare_response = __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40014MR"),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="implementation_completed",
                payload={"summary": "done"},
            ),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="verification_passed",
                payload={"summary": "all green"},
            ),
            dependencies=self.dependencies,
        )

        response = create_mr(
            CreateMrRequest(session_id=prepare_response.session.id),
            dependencies=self.dependencies,
        )
        artifacts_response = list_artifacts(
            session_id=prepare_response.session.id,
            dependencies=self.dependencies,
        )

        self.assertTrue(response.handed_off)
        self.assertEqual("mr_handoff_completed", response.event_type)
        self.assertEqual("mr_handoff_completed", response.session.current_stage)
        self.assertEqual("completed", response.session.status)
        self.assertEqual(
            "https://gitlab.example.com/mobile/IOS-40014MR/-/merge_requests/42",
            response.mr_url,
        )
        self.assertTrue(any(item.artifact_type == "mr_handoff_stdout" for item in artifacts_response.items))

    def test_send_to_test_route_marks_mr_handed_off_session_as_ready(self) -> None:
        prepare_response = __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40014ST"),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="implementation_completed",
                payload={"summary": "done"},
            ),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="verification_passed",
                payload={"summary": "all green"},
            ),
            dependencies=self.dependencies,
        )
        create_mr(
            CreateMrRequest(session_id=prepare_response.session.id),
            dependencies=self.dependencies,
        )

        response = send_to_test(
            SendToTestRequest(session_id=prepare_response.session.id),
            dependencies=self.dependencies,
        )
        artifacts_response = list_artifacts(
            session_id=prepare_response.session.id,
            dependencies=self.dependencies,
        )

        self.assertTrue(response.handed_off)
        self.assertEqual("send_to_test_completed", response.event_type)
        self.assertEqual("send_to_test_completed", response.session.current_stage)
        self.assertEqual("completed", response.session.status)
        self.assertTrue(any(item.artifact_type == "send_to_test_stdout" for item in artifacts_response.items))

    def test_verification_passed_routes_to_doc_harvest_when_policy_required(self) -> None:
        create_response = create_session(
            CreateSessionRequest(
                task_key="IOS-40014DH",
                workflow_profile="oneshot",
                policy={"doc_harvest_policy": "required"},
            ),
            dependencies=self.dependencies,
        )
        __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40014DH"),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=create_response.session.id,
                event_type="implementation_completed",
                payload={"summary": "done"},
            ),
            dependencies=self.dependencies,
        )

        response = inject_event(
            InjectEventRequest(
                session_id=create_response.session.id,
                event_type="verification_passed",
                payload={"summary": "all green"},
            ),
            dependencies=self.dependencies,
        )

        self.assertEqual("doc_harvest_requested", response.followup_event_type)
        self.assertEqual("doc_harvest_requested", response.session.current_stage)
        self.assertEqual("active", response.session.status)

    def test_implementation_completed_routes_to_self_review_when_policy_required(self) -> None:
        create_response = create_session(
            CreateSessionRequest(
                task_key="IOS-40014SR",
                workflow_profile="oneshot",
                policy={"self_review_policy": "required"},
            ),
            dependencies=self.dependencies,
        )
        __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40014SR"),
            dependencies=self.dependencies,
        )

        response = inject_event(
            InjectEventRequest(
                session_id=create_response.session.id,
                event_type="implementation_completed",
                payload={"summary": "done"},
            ),
            dependencies=self.dependencies,
        )

        self.assertEqual("self_review_requested", response.followup_event_type)
        self.assertEqual("self_review_requested", response.session.current_stage)
        self.assertEqual("active", response.session.status)

    def test_complete_self_review_route_passed_marks_verification_requested(self) -> None:
        create_response = create_session(
            CreateSessionRequest(
                task_key="IOS-40014SR2",
                workflow_profile="oneshot",
                policy={"self_review_policy": "required"},
            ),
            dependencies=self.dependencies,
        )
        __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40014SR2"),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=create_response.session.id,
                event_type="implementation_completed",
                payload={"summary": "done"},
            ),
            dependencies=self.dependencies,
        )

        response = complete_self_review(
            CompleteSelfReviewRequest(
                session_id=create_response.session.id,
                outcome="passed",
                summary="Reviewed implementation and found no blocking issues.",
            ),
            dependencies=self.dependencies,
        )
        artifacts_response = list_artifacts(
            session_id=create_response.session.id,
            dependencies=self.dependencies,
        )

        self.assertTrue(response.completed)
        self.assertEqual("self_review_passed", response.event_type)
        self.assertEqual("verification_requested", response.followup_event_type)
        self.assertEqual("verification_requested", response.session.current_stage)
        self.assertTrue(any(item.artifact_type == "self_review_summary" for item in artifacts_response.items))

    def test_complete_self_review_route_with_issues_marks_correction_requested(self) -> None:
        create_response = create_session(
            CreateSessionRequest(
                task_key="IOS-40014SR3",
                workflow_profile="oneshot",
                policy={"self_review_policy": "required"},
            ),
            dependencies=self.dependencies,
        )
        __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40014SR3"),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=create_response.session.id,
                event_type="implementation_completed",
                payload={"summary": "done"},
            ),
            dependencies=self.dependencies,
        )

        response = complete_self_review(
            CompleteSelfReviewRequest(
                session_id=create_response.session.id,
                outcome="issues_found",
                summary="Found two naming issues and one missing guard branch.",
            ),
            dependencies=self.dependencies,
        )

        self.assertTrue(response.completed)
        self.assertEqual("self_review_issues_found", response.event_type)
        self.assertEqual("self_review_correction_requested", response.followup_event_type)
        self.assertEqual("self_review_correction_requested", response.session.current_stage)
        self.assertEqual("implementer", response.session.current_owner)

    def test_complete_doc_harvest_route_marks_lane_completed(self) -> None:
        create_response = create_session(
            CreateSessionRequest(
                task_key="IOS-40014DH2",
                workflow_profile="oneshot",
                policy={"doc_harvest_policy": "required"},
            ),
            dependencies=self.dependencies,
        )
        __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40014DH2"),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=create_response.session.id,
                event_type="implementation_completed",
                payload={"summary": "done"},
            ),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=create_response.session.id,
                event_type="verification_passed",
                payload={"summary": "all green"},
            ),
            dependencies=self.dependencies,
        )

        response = complete_doc_harvest(
            CompleteDocHarvestRequest(
                session_id=create_response.session.id,
                summary="Feature README updated with current behavior.",
            ),
            dependencies=self.dependencies,
        )
        artifacts_response = list_artifacts(
            session_id=create_response.session.id,
            dependencies=self.dependencies,
        )

        self.assertTrue(response.completed)
        self.assertEqual("doc_harvest_completed", response.event_type)
        self.assertEqual("doc_harvest_completed", response.session.current_stage)
        self.assertEqual("completed", response.session.status)
        self.assertTrue(any(item.artifact_type == "doc_harvest_summary" for item in artifacts_response.items))

    def test_reopen_from_qa_route_reactivates_completed_session(self) -> None:
        prepare_response = __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40014B"),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="implementation_completed",
                payload={"summary": "done"},
            ),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="verification_passed",
                payload={"summary": "all green"},
            ),
            dependencies=self.dependencies,
        )

        response = reopen_from_qa(
            ReopenFromQaRequest(
                session_id=prepare_response.session.id,
                comment_text="QA: still failing on edge case",
            ),
            dependencies=self.dependencies,
        )

        self.assertTrue(response.reopened)
        self.assertEqual("qa_reopened", response.event_type)
        self.assertEqual("qa_reopen_requested", response.followup_event_type)
        self.assertEqual("active", response.session.status)
        self.assertEqual("qa_reopen_requested", response.session.current_stage)

    def test_followup_completion_after_qa_reopen_returns_to_verification(self) -> None:
        prepare_response = __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40014C"),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="implementation_completed",
                payload={"summary": "done"},
            ),
            dependencies=self.dependencies,
        )
        inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="verification_passed",
                payload={"summary": "all green"},
            ),
            dependencies=self.dependencies,
        )
        reopen_from_qa(
            ReopenFromQaRequest(
                session_id=prepare_response.session.id,
                comment_text="QA: still failing on edge case",
            ),
            dependencies=self.dependencies,
        )

        response = inject_event(
            InjectEventRequest(
                session_id=prepare_response.session.id,
                event_type="implementation_completed",
                payload={"summary": "qa fix done"},
            ),
            dependencies=self.dependencies,
        )

        self.assertEqual("verification_requested", response.followup_event_type)
        self.assertEqual("verification_requested", response.session.current_stage)

    def test_retry_session_route_creates_new_retry_work_item(self) -> None:
        prepare_response = __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40015"),
            dependencies=self.dependencies,
        )
        implementer_role = self.dependencies.role_repository.get_by_name(
            prepare_response.session.id,
            "implementer",
        )
        self.dependencies.session_backend.simulate_output(
            implementer_role.runtime_handle,
            'SDD_ERROR: {"summary":"tool failed","details":"command exited 1"}',
        )
        collect_role_output(
            CollectRoleOutputRequest(
                session_id=prepare_response.session.id,
                role_name="implementer",
            ),
            dependencies=self.dependencies,
        )

        response = retry_session(
            RetrySessionRequest(session_id=prepare_response.session.id),
            dependencies=self.dependencies,
        )
        work_items_response = list_work_items(
            session_id=prepare_response.session.id,
            dependencies=self.dependencies,
        )

        self.assertTrue(response.retried)
        self.assertEqual("session_retried_by_operator", response.event_type)
        self.assertEqual("role_input_dispatched", response.followup_event_type)
        self.assertEqual("active", response.session.status)
        self.assertEqual("implementer", response.session.current_owner)
        self.assertEqual(2, len(work_items_response.items))
        self.assertTrue(any(item.title.startswith("Retry: ") for item in work_items_response.items))

    def test_redirect_session_route_reroutes_escalated_work_to_allowed_target_role(self) -> None:
        prepare_response = __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40016"),
            dependencies=self.dependencies,
        )
        implementer_role = self.dependencies.role_repository.get_by_name(
            prepare_response.session.id,
            "implementer",
        )
        self.dependencies.role_repository.create(
            session_id=prepare_response.session.id,
            role_name="implementer-shadow",
            runtime_backend="recording",
            runtime_handle="recording:implementer-shadow",
        )
        self.dependencies.session_backend.simulate_output(
            implementer_role.runtime_handle,
            'SDD_ERROR: {"summary":"tool failed","details":"command exited 1"}',
        )
        collect_role_output(
            CollectRoleOutputRequest(
                session_id=prepare_response.session.id,
                role_name="implementer",
            ),
            dependencies=self.dependencies,
        )
        ALLOWED_STAGE_ROLE_TARGETS["implementation_requested"].add("implementer-shadow")
        try:
            response = redirect_session(
                RedirectSessionRequest(
                    session_id=prepare_response.session.id,
                    target_role_name="implementer-shadow",
                ),
                dependencies=self.dependencies,
            )
        finally:
            ALLOWED_STAGE_ROLE_TARGETS["implementation_requested"].remove("implementer-shadow")
        work_items_response = list_work_items(
            session_id=prepare_response.session.id,
            dependencies=self.dependencies,
        )

        self.assertTrue(response.redirected)
        self.assertEqual("session_redirected_by_operator", response.event_type)
        self.assertEqual("role_input_dispatched", response.followup_event_type)
        self.assertEqual("active", response.session.status)
        self.assertEqual("implementer-shadow", response.session.current_owner)
        self.assertEqual(2, len(work_items_response.items))
        self.assertTrue(
            any(
                item.title.startswith("Redirect to implementer-shadow:")
                for item in work_items_response.items
            )
        )


if __name__ == "__main__":
    unittest.main()
