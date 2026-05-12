from pathlib import Path
import tempfile
import unittest

from backend.coordinator.service import CoordinatorService
from backend.roles.contracts import DEFAULT_SESSION_ROLES
from backend.session_backend.tmux_backend import TmuxSessionBackend
from backend.state.artifact_repository import ArtifactRepository
from backend.state.db import Database
from backend.state.event_repository import EventRepository
from backend.state.role_repository import RoleRepository
from backend.state.session_repository import SessionRepository
from backend.state.work_item_repository import WorkItemRepository
from backend.tools.command_runner import CommandResult


class FakeJiraAdapter:
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


class FakeSnapshotAdapter:
    def run(self, task_key: str) -> CommandResult:
        return CommandResult(
            command=["snapshot", task_key],
            returncode=0,
            stdout="snapshot ok\n",
            stderr="",
        )


class SessionCreationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "factory.sqlite3"
        self.database = Database(self.db_path)
        self.database.initialize()

        self.session_repository = SessionRepository(self.database)
        self.role_repository = RoleRepository(self.database)
        self.event_repository = EventRepository(self.database)
        self.artifact_repository = ArtifactRepository(self.database)
        self.work_item_repository = WorkItemRepository(self.database)
        self.coordinator = CoordinatorService(
            session_repository=self.session_repository,
            role_repository=self.role_repository,
            event_repository=self.event_repository,
            artifact_repository=self.artifact_repository,
            work_item_repository=self.work_item_repository,
            session_backend=TmuxSessionBackend(),
            default_roles=DEFAULT_SESSION_ROLES,
            jira_adapter=FakeJiraAdapter(),
            snapshot_adapter=FakeSnapshotAdapter(),
            artifacts_root=Path(self.temp_dir.name) / "artifacts",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_create_task_session_creates_roles_and_event(self) -> None:
        session, event, created = self.coordinator.create_task_session("IOS-30000")
        roles = self.role_repository.list_for_session(session.id)

        self.assertTrue(created)
        self.assertEqual("task_started", event.event_type)
        self.assertEqual("active", session.status.value)
        self.assertEqual(DEFAULT_SESSION_ROLES, [role.role_name for role in roles])

    def test_create_task_session_is_idempotent_for_existing_key(self) -> None:
        first_session, _, _ = self.coordinator.create_task_session("IOS-30001")
        second_session, event, created = self.coordinator.create_task_session("IOS-30001")
        roles = self.role_repository.list_for_session(first_session.id)

        self.assertFalse(created)
        self.assertEqual(first_session.id, second_session.id)
        self.assertEqual("task_session_reused", event.event_type)
        self.assertEqual(3, len(roles))

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
        self.assertEqual(3, len(artifacts))
        self.assertEqual(1, len(work_items))
        self.assertEqual("Initial implementation for IOS-30002", work_items[0].title)
        self.assertEqual("implementation_requested", refreshed_session.current_stage)
        self.assertEqual("implementer", refreshed_session.current_owner)
        self.assertEqual(
            ["task_started", "task_prepared", "implementation_requested"],
            [item.event_type for item in events],
        )


if __name__ == "__main__":
    unittest.main()
