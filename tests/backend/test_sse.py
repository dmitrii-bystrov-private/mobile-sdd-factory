import asyncio
from pathlib import Path
import tempfile
import unittest

from backend.api.sse import SessionEventBus, sse_event_generator
from backend.models.event import Event
from backend.state.db import Database
from backend.state.event_repository import EventRepository
from backend.state.session_repository import SessionRepository


class SseReplayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name) / "factory.sqlite3")
        self.database.initialize()
        self.event_repository = EventRepository(self.database)
        self.session_repository = SessionRepository(self.database)
        self.event_bus = SessionEventBus()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    async def test_generator_replays_events_from_repository_after_cursor(self) -> None:
        session = self.session_repository.create(
            task_key="IOS-50101",
            current_stage="intake",
            workflow_profile="oneshot",
            policy={
                "self_review_policy": "enabled",
                "boy_scout_policy": "enabled",
                "doc_harvest_policy": "enabled",
            },
        )
        first = self.event_repository.append(
            session_id=session.id,
            event_type="task_started",
            producer_type="coordinator",
            payload={"step": 1},
        )
        second = self.event_repository.append(
            session_id=session.id,
            event_type="implementation_requested",
            producer_type="coordinator",
            payload={"step": 2},
        )

        generator = sse_event_generator(
            self.event_repository,
            self.event_bus,
            session_id=session.id,
            since_event_id=first.id,
        )

        chunk = await anext(generator)
        await generator.aclose()

        self.assertIn(f"id: {second.id}", chunk)
        self.assertIn("event: implementation_requested", chunk)
        self.assertIn(f'"session_id": {session.id}', chunk)
        self.assertIn('"step": 2', chunk)

    async def test_generator_filters_replay_by_session(self) -> None:
        session_a = self.session_repository.create(
            task_key="IOS-50201",
            current_stage="intake",
            workflow_profile="oneshot",
            policy={
                "self_review_policy": "enabled",
                "boy_scout_policy": "enabled",
                "doc_harvest_policy": "enabled",
            },
        )
        session_b = self.session_repository.create(
            task_key="IOS-50202",
            current_stage="intake",
            workflow_profile="oneshot",
            policy={
                "self_review_policy": "enabled",
                "boy_scout_policy": "enabled",
                "doc_harvest_policy": "enabled",
            },
        )
        anchor = self.event_repository.append(
            session_id=session_a.id,
            event_type="task_started",
            producer_type="coordinator",
            payload={"step": 1},
        )
        self.event_repository.append(
            session_id=session_b.id,
            event_type="task_started",
            producer_type="coordinator",
            payload={"step": 2},
        )
        target = self.event_repository.append(
            session_id=session_a.id,
            event_type="verification_requested",
            producer_type="coordinator",
            payload={"step": 3},
        )

        generator = sse_event_generator(
            self.event_repository,
            self.event_bus,
            session_id=session_a.id,
            since_event_id=anchor.id,
        )

        chunk = await anext(generator)
        await generator.aclose()

        self.assertIn(f"id: {target.id}", chunk)
        self.assertIn("event: verification_requested", chunk)
        self.assertNotIn(f'"session_id": {session_b.id}', chunk)

    async def test_generator_delivers_live_event_after_replay(self) -> None:
        session = self.session_repository.create(
            task_key="IOS-50301",
            current_stage="intake",
            workflow_profile="oneshot",
            policy={
                "self_review_policy": "enabled",
                "boy_scout_policy": "enabled",
                "doc_harvest_policy": "enabled",
            },
        )
        anchor = self.event_repository.append(
            session_id=session.id,
            event_type="task_started",
            producer_type="coordinator",
            payload={"step": 1},
        )

        generator = sse_event_generator(
            self.event_repository,
            self.event_bus,
            session_id=session.id,
            since_event_id=anchor.id,
        )

        task = asyncio.create_task(anext(generator))
        await asyncio.sleep(0)
        live_event = Event(
            id=anchor.id + 1,
            session_id=session.id,
            event_type="role_output_collected",
            producer_type="coordinator",
            producer_id=None,
            payload={"step": 2},
        )
        self.event_bus.publish(live_event)
        chunk = await asyncio.wait_for(task, timeout=1)
        await generator.aclose()

        self.assertIn(f"id: {live_event.id}", chunk)
        self.assertIn("event: role_output_collected", chunk)
        self.assertIn('"step": 2', chunk)
