from pathlib import Path
import tempfile
import unittest

from backend.models.enums import SessionStatus
from backend.state.db import Database
from backend.state.event_repository import EventRepository
from backend.state.memory_item_repository import MemoryItemRepository
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

        created = repository.create(
            task_key="IOS-20000",
            current_stage="intake",
            workflow_profile="bug_full",
            policy={
                "test_policy": "enabled",
                "self_review_policy": "enabled",
                "boy_scout_policy": "enabled",
                "doc_harvest_policy": "enabled",
            },
        )
        loaded = repository.get_by_task_key("IOS-20000")

        self.assertIsNotNone(created.id)
        self.assertIsNotNone(loaded)
        self.assertEqual("IOS-20000", loaded.task_key)
        self.assertEqual(SessionStatus.CREATED, loaded.status)
        self.assertEqual("bug_full", loaded.workflow_profile)
        self.assertEqual("enabled", loaded.policy["test_policy"])

    def test_role_repository_lists_roles_for_session(self) -> None:
        session_repository = SessionRepository(self.database)
        role_repository = RoleRepository(self.database)
        session = session_repository.create(
            task_key="IOS-20001",
            current_stage="intake",
            workflow_profile="oneshot",
            policy={
                "self_review_policy": "enabled",
                "boy_scout_policy": "enabled",
                "doc_harvest_policy": "enabled",
            },
        )

        role_repository.create(session.id, "implementer", "tmux", "tmux:implementer")
        role_repository.create(
            session.id, "verification-coordinator", "tmux", "tmux:verification"
        )

        roles = role_repository.list_for_session(session.id)

        self.assertEqual(["implementer", "verification-coordinator"], [role.role_name for role in roles])

    def test_event_repository_lists_session_events_in_order(self) -> None:
        session_repository = SessionRepository(self.database)
        event_repository = EventRepository(self.database)
        session = session_repository.create(
            task_key="IOS-20002",
            current_stage="intake",
            workflow_profile="oneshot",
            policy={
                "self_review_policy": "enabled",
                "boy_scout_policy": "enabled",
                "doc_harvest_policy": "enabled",
            },
        )

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
        session = session_repository.create(
            task_key="IOS-20003",
            current_stage="intake",
            workflow_profile="oneshot",
            policy={
                "self_review_policy": "enabled",
                "boy_scout_policy": "enabled",
                "doc_harvest_policy": "enabled",
            },
        )

        work_item_repository.create(session.id, "implementation", "low", priority=1)
        work_item_repository.create(session.id, "implementation", "high", priority=10)

        items = work_item_repository.list_for_session(session.id)

        self.assertEqual(["high", "low"], [item.title for item in items])

    def test_memory_item_repository_creates_and_matches_items(self) -> None:
        session_repository = SessionRepository(self.database)
        repository = MemoryItemRepository(self.database)
        session = session_repository.create(
            task_key="IOS-20004",
            current_stage="intake",
            workflow_profile="oneshot",
            policy={
                "self_review_policy": "enabled",
                "boy_scout_policy": "enabled",
                "doc_harvest_policy": "enabled",
            },
        )

        created = repository.create(
            item_type="verification_failure_lesson",
            status="active",
            platform="ios",
            workflow_profile="oneshot",
            source_session_id=session.id,
            source_event_id=None,
            summary="Missing guard branch before verification.",
            metadata={"source_stage": "verification_requested"},
        )
        matched = repository.list_matching(
            item_type="verification_failure_lesson",
            platform="ios",
            workflow_profile="oneshot",
        )
        updated = repository.increment_use_count(created.id)

        self.assertIsNotNone(created.id)
        self.assertEqual(1, len(matched))
        self.assertEqual("Missing guard branch before verification.", matched[0].summary)
        self.assertEqual(1, updated.use_count)


if __name__ == "__main__":
    unittest.main()
