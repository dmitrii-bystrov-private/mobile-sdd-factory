from pathlib import Path
import tempfile
import unittest

from backend.models.enums import SessionStatus
from backend.state.db import Database
from backend.state.event_repository import EventRepository
from backend.state.role_repository import RoleRepository
from backend.state.session_repository import SessionRepository
from backend.state.work_item_repository import WorkItemRepository


class RepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "factory.sqlite3"
        self.database = Database(self.db_path)
        self.database.initialize()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_session_repository_create_and_lookup(self) -> None:
        repository = SessionRepository(self.database)

        created = repository.create(task_key="IOS-20000", current_stage="intake")
        loaded = repository.get_by_task_key("IOS-20000")

        self.assertIsNotNone(created.id)
        self.assertIsNotNone(loaded)
        self.assertEqual("IOS-20000", loaded.task_key)
        self.assertEqual(SessionStatus.CREATED, loaded.status)

    def test_role_repository_lists_roles_for_session(self) -> None:
        session_repository = SessionRepository(self.database)
        role_repository = RoleRepository(self.database)
        session = session_repository.create(task_key="IOS-20001", current_stage="intake")

        role_repository.create(session.id, "implementer", "tmux", "tmux:implementer")
        role_repository.create(
            session.id, "verification-coordinator", "tmux", "tmux:verification"
        )

        roles = role_repository.list_for_session(session.id)

        self.assertEqual(["implementer", "verification-coordinator"], [role.role_name for role in roles])

    def test_event_repository_lists_session_events_in_order(self) -> None:
        session_repository = SessionRepository(self.database)
        event_repository = EventRepository(self.database)
        session = session_repository.create(task_key="IOS-20002", current_stage="intake")

        event_repository.append(session.id, "task_started", "coordinator", {"task_key": "IOS-20002"})
        event_repository.append(
            session.id,
            "verification_requested",
            "coordinator",
            {"task_key": "IOS-20002"},
        )

        events = event_repository.list_for_session(session.id)

        self.assertEqual(["task_started", "verification_requested"], [event.event_type for event in events])

    def test_work_item_repository_lists_items_in_priority_order(self) -> None:
        session_repository = SessionRepository(self.database)
        work_item_repository = WorkItemRepository(self.database)
        session = session_repository.create(task_key="IOS-20003", current_stage="intake")

        work_item_repository.create(session.id, "implementation", "low", priority=1)
        work_item_repository.create(session.id, "implementation", "high", priority=10)

        items = work_item_repository.list_for_session(session.id)

        self.assertEqual(["high", "low"], [item.title for item in items])


if __name__ == "__main__":
    unittest.main()
