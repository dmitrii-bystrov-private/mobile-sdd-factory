from pathlib import Path
import tempfile
import unittest

try:
    from backend.api.routes_sessions import create_session, list_sessions
    from backend.api.schemas import CreateSessionRequest, PrepareSessionRequest
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
        coordinator = CoordinatorService(
            session_repository=session_repository,
            role_repository=role_repository,
            event_repository=event_repository,
            artifact_repository=artifact_repository,
            work_item_repository=work_item_repository,
            session_backend=TmuxSessionBackend(),
            default_roles=DEFAULT_SESSION_ROLES,
            jira_adapter=FakeJiraAdapter(),
            snapshot_adapter=FakeSnapshotAdapter(),
            artifacts_root=Path(self.temp_dir.name) / "artifacts",
        )
        self.dependencies = AppDependencies(
            config=None,
            database=self.database,
            session_repository=session_repository,
            role_repository=role_repository,
            event_repository=event_repository,
            artifact_repository=artifact_repository,
            work_item_repository=work_item_repository,
            session_backend=TmuxSessionBackend(),
            jira_adapter=FakeJiraAdapter(),
            snapshot_adapter=FakeSnapshotAdapter(),
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


if __name__ == "__main__":
    unittest.main()
