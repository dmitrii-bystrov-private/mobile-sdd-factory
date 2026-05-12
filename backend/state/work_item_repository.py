"""Repository for session work items."""

from __future__ import annotations

from backend.models.enums import WorkItemStatus
from backend.models.work_item import WorkItem
from backend.state.db import Database
from backend.state.models import work_item_from_row


class WorkItemRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(
        self,
        session_id: int,
        work_type: str,
        title: str,
        owner_role_id: int | None = None,
        source_event_id: int | None = None,
        priority: int = 0,
        status: WorkItemStatus | None = None,
    ) -> WorkItem:
        persisted_status = status or (
            WorkItemStatus.ASSIGNED if owner_role_id is not None else WorkItemStatus.UNASSIGNED
        )
        with self.db.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO work_items (
                  session_id, work_type, title, status, owner_role_id, source_event_id, priority
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    work_type,
                    title,
                    persisted_status.value,
                    owner_role_id,
                    source_event_id,
                    priority,
                ),
            )
            row = connection.execute(
                "SELECT * FROM work_items WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return work_item_from_row(row)

    def list_for_session(self, session_id: int) -> list[WorkItem]:
        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM work_items WHERE session_id = ? ORDER BY priority DESC, id ASC",
                (session_id,),
            ).fetchall()
        return [work_item_from_row(row) for row in rows]
