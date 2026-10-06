"""Repository for persisted dispatch-token lifecycle state."""

from __future__ import annotations

from backend.models.dispatch import Dispatch
from backend.models.enums import DispatchStatus
from backend.state.db import Database
from backend.state.models import dispatch_from_row


_ACTIVE_DISPATCH_STATUSES = (
    DispatchStatus.DISPATCHING.value,
    DispatchStatus.DELIVERED.value,
    DispatchStatus.STALLED.value,
)


class DispatchRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(
        self,
        *,
        session_id: int,
        role_id: int,
        work_item_id: int,
        stage_name: str,
        dispatch_token: str,
        hydration_version: int,
        runtime_handle: str | None,
        status: DispatchStatus = DispatchStatus.DISPATCHING,
        error_text: str | None = None,
    ) -> Dispatch:
        with self.db.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO dispatches (
                  session_id,
                  role_id,
                  work_item_id,
                  stage_name,
                  dispatch_token,
                  hydration_version,
                  runtime_handle,
                  status,
                  error_text
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    role_id,
                    work_item_id,
                    stage_name,
                    dispatch_token,
                    hydration_version,
                    runtime_handle,
                    status.value,
                    error_text,
                ),
            )
            row = connection.execute(
                "SELECT * FROM dispatches WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return dispatch_from_row(row)

    def get_by_token(self, dispatch_token: str) -> Dispatch | None:
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT * FROM dispatches WHERE dispatch_token = ?",
                (dispatch_token,),
            ).fetchone()
        if row is None:
            return None
        return dispatch_from_row(row)

    def list_for_session(self, session_id: int) -> list[Dispatch]:
        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM dispatches WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
        return [dispatch_from_row(row) for row in rows]

    def get_latest_active_for_target(
        self,
        *,
        session_id: int,
        role_id: int,
        work_item_id: int,
        stage_name: str,
    ) -> Dispatch | None:
        with self.db.connect() as connection:
            row = connection.execute(
                f"""
                SELECT *
                FROM dispatches
                WHERE session_id = ?
                  AND role_id = ?
                  AND work_item_id = ?
                  AND stage_name = ?
                  AND status IN ({",".join("?" for _ in _ACTIVE_DISPATCH_STATUSES)})
                ORDER BY id DESC
                LIMIT 1
                """,
                (session_id, role_id, work_item_id, stage_name, *_ACTIVE_DISPATCH_STATUSES),
            ).fetchone()
        if row is None:
            return None
        return dispatch_from_row(row)

    def update_status(
        self,
        dispatch_token: str,
        *,
        status: DispatchStatus,
        error_text: str | None = None,
    ) -> Dispatch | None:
        with self.db.connect() as connection:
            connection.execute(
                """
                UPDATE dispatches
                SET status = ?, error_text = ?, updated_at = CURRENT_TIMESTAMP
                WHERE dispatch_token = ?
                """,
                (status.value, error_text, dispatch_token),
            )
            row = connection.execute(
                "SELECT * FROM dispatches WHERE dispatch_token = ?",
                (dispatch_token,),
            ).fetchone()
        if row is None:
            return None
        return dispatch_from_row(row)

    def supersede_active_for_target(
        self,
        *,
        session_id: int,
        role_id: int,
        work_item_id: int,
        stage_name: str,
    ) -> None:
        with self.db.connect() as connection:
            connection.execute(
                f"""
                UPDATE dispatches
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE session_id = ?
                  AND role_id = ?
                  AND work_item_id = ?
                  AND stage_name = ?
                  AND status IN ({",".join("?" for _ in _ACTIVE_DISPATCH_STATUSES)})
                """,
                (
                    DispatchStatus.SUPERSEDED.value,
                    session_id,
                    role_id,
                    work_item_id,
                    stage_name,
                    *_ACTIVE_DISPATCH_STATUSES,
                ),
            )

    def mark_terminal_for_work_item(
        self,
        *,
        session_id: int,
        role_id: int,
        work_item_id: int,
    ) -> None:
        with self.db.connect() as connection:
            connection.execute(
                f"""
                UPDATE dispatches
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE session_id = ?
                  AND role_id = ?
                  AND work_item_id = ?
                  AND status IN ({",".join("?" for _ in _ACTIVE_DISPATCH_STATUSES)})
                """,
                (
                    DispatchStatus.TERMINAL.value,
                    session_id,
                    role_id,
                    work_item_id,
                    *_ACTIVE_DISPATCH_STATUSES,
                ),
            )
