"""SSE helpers for live session updates."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import AsyncIterator

from backend.models.event import Event


def event_stream_name() -> str:
    return "session_updates"


@dataclass(slots=True)
class StreamEvent:
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
    bus: SessionEventBus,
    session_id: int | None = None,
) -> AsyncIterator[str]:
    queue = bus.subscribe()
    try:
        for event in bus.recent_events(session_id=session_id):
            yield _format_sse_event(event)
        while True:
            event = await queue.get()
            if session_id is not None and event.session_id != session_id:
                continue
            yield _format_sse_event(event)
    finally:
        bus.unsubscribe(queue)


def _format_sse_event(event: StreamEvent) -> str:
    return (
        f"event: {event.event_type}\n"
        f"data: {json.dumps({'session_id': event.session_id, 'payload': event.payload})}\n\n"
    )
