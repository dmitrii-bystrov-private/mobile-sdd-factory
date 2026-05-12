from pathlib import Path
import tempfile
import unittest

try:
    from backend.api.sse import SessionEventBus
    from backend.api.routes_sessions import create_session, list_sessions
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
    from backend.api.schemas import PollSessionOutputRequest
    from backend.coordinator.service import CoordinatorService
    from backend.dependencies import AppDependencies
    from backend.roles.contracts import DEFAULT_SESSION_ROLES
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


class FakeSnapshotAdapter:
    def run(self, task_key: str) -> "CommandResult":
        return CommandResult(["snapshot", task_key], 0, "snapshot ok\n", "")


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
            artifacts_root=Path(self.temp_dir.name) / "artifacts",
            event_bus=event_bus,
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
            event_bus=event_bus,
            coordinator_service=coordinator,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_create_session_route_returns_created_session(self) -> None:
        response = create_session(
            CreateSessionRequest(task_key="IOS-40000"),
            dependencies=self.dependencies,
        )

        self.assertTrue(response.created)
        self.assertEqual("IOS-40000", response.session.task_key)
        self.assertEqual("task_started", response.event_type)

    def test_list_sessions_route_returns_created_session(self) -> None:
        create_session(
            CreateSessionRequest(task_key="IOS-40001"),
            dependencies=self.dependencies,
        )

        response = list_sessions(dependencies=self.dependencies)

        self.assertEqual(1, len(response.items))
        self.assertEqual("IOS-40001", response.items[0].task_key)

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
        self.assertEqual(3, response.role_count)
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
            PrepareSessionRequest(task_key="IOS-40010"),
            dependencies=self.dependencies,
        )
        prepare_b = __import__("backend.api.routes_sessions", fromlist=["prepare_session"]).prepare_session(
            PrepareSessionRequest(task_key="IOS-40011"),
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


if __name__ == "__main__":
    unittest.main()
