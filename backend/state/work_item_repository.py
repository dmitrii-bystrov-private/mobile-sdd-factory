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

    def get_by_id(self, work_item_id: int) -> WorkItem | None:
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT * FROM work_items WHERE id = ?",
                (work_item_id,),
            ).fetchone()
        if row is None:
            return None
        return work_item_from_row(row)

    def update_status(self, work_item_id: int, status: WorkItemStatus) -> WorkItem:
        with self.db.connect() as connection:
            connection.execute(
                """
                UPDATE work_items
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status.value, work_item_id),
            )
            row = connection.execute(
                "SELECT * FROM work_items WHERE id = ?",
                (work_item_id,),
            ).fetchone()
        return work_item_from_row(row)

    def update_title(self, work_item_id: int, title: str) -> WorkItem:
        with self.db.connect() as connection:
            connection.execute(
                """
                UPDATE work_items
                SET title = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (title, work_item_id),
            )
            row = connection.execute(
                "SELECT * FROM work_items WHERE id = ?",
                (work_item_id,),
            ).fetchone()
        return work_item_from_row(row)

    def update_assignment(
        self,
        work_item_id: int,
        owner_role_id: int | None,
        status: WorkItemStatus,
    ) -> WorkItem:
        with self.db.connect() as connection:
            connection.execute(
                """
                UPDATE work_items
                SET owner_role_id = ?, status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (owner_role_id, status.value, work_item_id),
            )
            row = connection.execute(
                "SELECT * FROM work_items WHERE id = ?",
                (work_item_id,),
            ).fetchone()
        return work_item_from_row(row)

    def update_shape(
        self,
        work_item_id: int,
        *,
        work_type: str,
        title: str,
        owner_role_id: int | None,
        status: WorkItemStatus,
    ) -> WorkItem:
        with self.db.connect() as connection:
            connection.execute(
                """
                UPDATE work_items
                SET work_type = ?, title = ?, owner_role_id = ?, status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (work_type, title, owner_role_id, status.value, work_item_id),
            )
            row = connection.execute(
                "SELECT * FROM work_items WHERE id = ?",
                (work_item_id,),
            ).fetchone()
        return work_item_from_row(row)
