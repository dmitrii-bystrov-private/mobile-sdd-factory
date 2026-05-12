"""Repository for session events."""

from __future__ import annotations

import json

from backend.models.event import Event
from backend.state.db import Database
from backend.state.models import event_from_row


class EventRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def append(
        self,
        session_id: int,
        event_type: str,
        producer_type: str,
        payload: dict,
        producer_id: str | None = None,
        correlation_id: str | None = None,
    ) -> Event:
        with self.db.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO events (
                  session_id, event_type, producer_type, producer_id, payload_json, correlation_id
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    event_type,
                    producer_type,
                    producer_id,
                    json.dumps(payload),
                    correlation_id,
                ),
            )
            row = connection.execute(
                "SELECT * FROM events WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return event_from_row(row)

    def list_for_session(self, session_id: int) -> list[Event]:
        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM events WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
        return [event_from_row(row) for row in rows]
