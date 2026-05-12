"""SSE helpers for live session updates."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import AsyncIterator

from backend.models.event import Event
from backend.state.event_repository import EventRepository


def event_stream_name() -> str:
    return "session_updates"


@dataclass(slots=True)
class StreamEvent:
    event_id: int | None
    session_id: int
    event_type: str
    payload: dict


class SessionEventBus:
    """In-memory publisher for live session updates."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[StreamEvent]] = []
        self._recent: list[StreamEvent] = []

    def publish(self, event: Event) -> None:
        stream_event = StreamEvent(
            event_id=event.id,
            session_id=event.session_id,
            event_type=event.event_type,
            payload=event.payload,
        )
        self._recent.append(stream_event)
        self._recent = self._recent[-200:]
        for queue in list(self._subscribers):
            queue.put_nowait(stream_event)

    def recent_events(self, session_id: int | None = None) -> list[StreamEvent]:
        if session_id is None:
            return list(self._recent)
        return [event for event in self._recent if event.session_id == session_id]

    def subscribe(self) -> asyncio.Queue[StreamEvent]:
        queue: asyncio.Queue[StreamEvent] = asyncio.Queue()
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[StreamEvent]) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)


async def sse_event_generator(
    event_repository: EventRepository,
    bus: SessionEventBus,
    session_id: int | None = None,
    since_event_id: int | None = None,
) -> AsyncIterator[str]:
    queue = bus.subscribe()
    try:
        if since_event_id is not None:
            replay_events = [
                _to_stream_event(event)
                for event in event_repository.list_after_id(
                    after_id=since_event_id,
                    session_id=session_id,
                )
            ]
        else:
            replay_events = bus.recent_events(session_id=session_id)
        for event in replay_events:
            yield _format_sse_event(event)
        while True:
            event = await queue.get()
            if since_event_id is not None and event.event_id is not None and event.event_id <= since_event_id:
                continue
            if session_id is not None and event.session_id != session_id:
                continue
            yield _format_sse_event(event)
    finally:
        bus.unsubscribe(queue)


def _format_sse_event(event: StreamEvent) -> str:
    body = (
        f"event: {event.event_type}\n"
        f"data: {json.dumps({'session_id': event.session_id, 'payload': event.payload})}\n\n"
    )
    if event.event_id is None:
        return body
    return f"id: {event.event_id}\n{body}"


def _to_stream_event(event: Event) -> StreamEvent:
    return StreamEvent(
        event_id=event.id,
        session_id=event.session_id,
        event_type=event.event_type,
        payload=event.payload,
    )
