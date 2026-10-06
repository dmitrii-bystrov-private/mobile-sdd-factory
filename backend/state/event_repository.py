"""Repository for session events."""

from __future__ import annotations

import json

from backend.models.event import Event
from backend.state.db import Database
from backend.state.models import event_from_row


DEFAULT_UI_EXCLUDED_EVENT_TYPES = {
    "coordinator_loop_ran",
    "runtime_terminal_output_echo_ignored",
    "session_output_polled",
}


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

    def list_for_session_excluding(
        self,
        session_id: int,
        excluded_event_types: set[str],
    ) -> list[Event]:
        if not excluded_event_types:
            return self.list_for_session(session_id)
        placeholders = ",".join("?" for _ in excluded_event_types)
        with self.db.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT *
                FROM events
                WHERE session_id = ?
                  AND event_type NOT IN ({placeholders})
                ORDER BY id ASC
                """,
                (session_id, *sorted(excluded_event_types)),
            ).fetchall()
        return [event_from_row(row) for row in rows]

    def latest_for_session_by_type(
        self,
        session_id: int,
        event_types: set[str],
    ) -> Event | None:
        if not event_types:
            return None
        placeholders = ",".join("?" for _ in event_types)
        with self.db.connect() as connection:
            row = connection.execute(
                f"""
                SELECT *
                FROM events
                WHERE session_id = ?
                  AND event_type IN ({placeholders})
                ORDER BY id DESC
                LIMIT 1
                """,
                (session_id, *sorted(event_types)),
            ).fetchone()
        if row is None:
            return None
        return event_from_row(row)

    def latest_for_session_by_type_and_payload(
        self,
        *,
        session_id: int,
        event_type: str,
        payload_matches: dict[str, object],
    ) -> Event | None:
        predicates = ["session_id = ?", "event_type = ?"]
        params: list[object] = [session_id, event_type]
        for key in sorted(payload_matches):
            predicates.append(f"json_extract(payload_json, '$.{key}') = ?")
            params.append(payload_matches[key])
        with self.db.connect() as connection:
            row = connection.execute(
                f"""
                SELECT *
                FROM events
                WHERE {" AND ".join(predicates)}
                ORDER BY id DESC
                LIMIT 1
                """,
                tuple(params),
            ).fetchone()
        if row is None:
            return None
        return event_from_row(row)

    def list_after_id(
        self,
        after_id: int,
        session_id: int | None = None,
    ) -> list[Event]:
        query = "SELECT * FROM events WHERE id > ?"
        params: list[int] = [after_id]
        if session_id is not None:
            query += " AND session_id = ?"
            params.append(session_id)
        query += " ORDER BY id ASC"
        with self.db.connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return [event_from_row(row) for row in rows]
