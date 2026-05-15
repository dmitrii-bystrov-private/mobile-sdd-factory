from pathlib import Path
import tempfile
import time
import unittest

try:
    from backend.api.sse import SessionEventBus
    from backend.api.routes_sessions import create_session, list_sessions
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
    from backend.api.routes_operator import retry_session
    from backend.api.routes_operator import reopen_from_qa
    from backend.api.routes_operator import redirect_session
    from backend.api.routes_operator import complete_doc_harvest
    from backend.api.routes_operator import complete_self_review
    from backend.api.routes_operator import create_mr
    from backend.api.routes_operator import create_knowledge
    from backend.api.routes_operator import send_to_test
    from backend.api.routes_operator import start_subtask_graph
    from backend.api.routes_operator import ingest_mr_comments
    from backend.api.routes_operator import loop_status, start_loop, stop_loop
    from backend.api.schemas import (
        CompleteDocHarvestRequest,
        CompleteSelfReviewRequest,
        CreateKnowledgeRequest,
        CreateMrRequest,
        IngestMrCommentsRequest,
        PollSessionOutputRequest,
        PauseSessionRequest,
        ReopenFromQaRequest,
        RedirectSessionRequest,
        ResumeSessionRequest,
        RetrySessionRequest,
        SendToTestRequest,
        StartSubtaskGraphRequest,
    )
    from backend.coordinator.service import CoordinatorService
    from backend.coordinator.loop_runner import CoordinatorLoopRunner
    from backend.dependencies import AppDependencies
    from backend.roles.contracts import (
        ALLOWED_STAGE_ROLE_TARGETS,
        BUG_FIXER_ROLE,
        CODE_REVIEWER_ROLE,
        DEFAULT_SESSION_ROLES,
        PROPOSAL_CONTEXT_WORKER_ROLE,
        REQUIREMENTS_CLARIFIER_WORKER_ROLE,
    )
    from backend.roles.launcher import RoleLauncherManager
    from backend.roles.workspace import RoleWorkspaceManager
    from backend.session_backend.tmux_backend import TmuxSessionBackend
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
    def resolve_parent(self, task_key: str) -> "CommandResult":
        return CommandResult(["resolve_parent", task_key], 0, f"{task_key}\n", "")

    def get_issue_type(self, task_key: str) -> "CommandResult":
        return CommandResult(["get_issue_type", task_key], 0, "Story\n", "")

    def send_to_test(self, task_key: str) -> "CommandResult":
        return CommandResult(["send_to_test", task_key], 0, f"Done: {task_key} -> Ready for test\n", "")


class FakeSnapshotAdapter:
    def run(self, task_key: str) -> "CommandResult":
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
        self.db_path = Path(self.temp_dir.name) / "factory.sqlite3"
        self.database = Database(self.db_path)
        self.database.initialize()

        session_repository = SessionRepository(self.database)
        role_repository = RoleRepository(self.database)
        event_repository = EventRepository(self.database)
        artifact_repository = ArtifactRepository(self.database)
        work_item_repository = WorkItemRepository(self.database)
        session_backend = TmuxSessionBackend()
        event_bus = SessionEventBus()
        coordinator = CoordinatorService(
            session_repository=session_repository,
            role_repository=role_repository,
            event_repository=event_repository,
            artifact_repository=artifact_repository,
            work_item_repository=work_item_repository,
            session_backend=session_backend,
            default_roles=DEFAULT_SESSION_ROLES,
            jira_adapter=FakeJiraAdapter(),
            snapshot_adapter=FakeSnapshotAdapter(),
            gitlab_adapter=FakeGitLabAdapter(),
            artifacts_root=Path(self.temp_dir.name) / "artifacts",
            workdir_root=Path(self.temp_dir.name),
            knowledge_root=Path(self.temp_dir.name) / "knowledge",
            event_bus=event_bus,
            role_workspace_manager=RoleWorkspaceManager(
                runtime_root=Path(self.temp_dir.name) / "runtime",
                repo_root=Path(self.temp_dir.name) / "repo-root",
                workdir_root=Path(self.temp_dir.name),
            ),
            role_launcher_manager=RoleLauncherManager(
                repo_root=Path(self.temp_dir.name) / "repo-root",
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
            jira_adapter=FakeJiraAdapter(),
            snapshot_adapter=FakeSnapshotAdapter(),
            gitlab_adapter=FakeGitLabAdapter(),
            event_bus=event_bus,
            loop_runner=loop_runner,
            coordinator_service=coordinator,
        )

    def tearDown(self) -> None:
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

    def test_create_session_route_creates_role_workspaces(self) -> None:
        response = create_session(
            CreateSessionRequest(task_key="IOS-40000W", workflow_profile="oneshot"),
            dependencies=self.dependencies,
        )

        self.assertTrue(response.created)
        for role_name in DEFAULT_SESSION_ROLES + [CODE_REVIEWER_ROLE]:
            role_dir = Path(self.temp_dir.name) / "runtime" / "role-workspaces" / "IOS-40000W" / role_name
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
            / "runtime"
            / "role-workspaces"
            / "IOS-40000L"
            / "implementer"
            / "launch-role.sh"
        )
        self.assertTrue(launch_script.is_file())
        self.assertEqual(
            [str(launch_script)],
            self.dependencies.session_backend.get_spawn_command(implementer_role.runtime_handle),
        )

    def test_list_sessions_route_returns_created_session(self) -> None:
        create_session(
            CreateSessionRequest(task_key="IOS-40001", workflow_profile="oneshot"),
            dependencies=self.dependencies,
        )

        response = list_sessions(dependencies=self.dependencies)

        self.assertEqual(1, len(response.items))
        self.assertEqual("IOS-40001", response.items[0].task_key)
        self.assertEqual("oneshot", response.items[0].workflow_profile)

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

    def test_requirements_completed_event_returns_story_spec_handoff(self) -> None:
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

        self.assertEqual("story_spec_requested", response.followup_event_type)
        self.assertEqual("story_spec_requested", response.session.current_stage)

    def test_story_spec_completed_event_returns_implementation_handoff(self) -> None:
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

        self.assertEqual("implementation_requested", response.followup_event_type)
        self.assertEqual("implementation_requested", response.session.current_stage)
        self.assertEqual(4, len(work_items_response.items))

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
        self.assertEqual(5, len(work_items_response.items))

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

        knowledge_files = list((Path(self.temp_dir.name) / "knowledge").rglob("*.md"))
        self.assertTrue(response.created)
        self.assertEqual("knowledge_created", response.event_type)
        self.assertTrue(any("Reuse existing navigation assembly" in path.read_text() for path in knowledge_files))

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
