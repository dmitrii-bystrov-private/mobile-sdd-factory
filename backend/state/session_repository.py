"""Repository for task sessions."""

from __future__ import annotations

import json

from backend.models.enums import SessionStatus
from backend.models.session import Session
from backend.state.db import Database
from backend.state.models import session_from_row


class SessionRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(
        self,
        task_key: str,
        current_stage: str,
        workflow_profile: str,
        policy: dict[str, str],
        role_config: dict[str, dict[str, str]] | None = None,
    ) -> Session:
        with self.db.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO sessions (task_key, status, current_stage, workflow_profile, policy_json, role_config_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    task_key,
                    SessionStatus.CREATED.value,
                    current_stage,
                    workflow_profile,
                    json.dumps(policy, sort_keys=True),
                    json.dumps(role_config or {}, sort_keys=True),
                ),
            )
            row = connection.execute(
                "SELECT * FROM sessions WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return session_from_row(row)

    def get_by_task_key(self, task_key: str) -> Session | None:
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE task_key = ?",
                (task_key,),
            ).fetchone()
        if row is None:
            return None
        return session_from_row(row)

    def get_by_id(self, session_id: int) -> Session | None:
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return session_from_row(row)

    def list_all(self) -> list[Session]:
        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM sessions ORDER BY created_at DESC, id DESC"
            ).fetchall()
        return [session_from_row(row) for row in rows]

    def list_by_status(self, status: SessionStatus) -> list[Session]:
        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM sessions WHERE status = ? ORDER BY created_at DESC, id DESC",
                (status.value,),
            ).fetchall()
        return [session_from_row(row) for row in rows]

    def update_status(self, session_id: int, status: SessionStatus) -> Session:
        with self.db.connect() as connection:
            connection.execute(
                """
                UPDATE sessions
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status.value, session_id),
            )
            row = connection.execute(
                "SELECT * FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        return session_from_row(row)

    def update_stage_and_owner(
        self,
        session_id: int,
        current_stage: str,
        current_owner: str | None,
    ) -> Session:
        with self.db.connect() as connection:
            connection.execute(
                """
                UPDATE sessions
                SET current_stage = ?, current_owner = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (current_stage, current_owner, session_id),
            )
            row = connection.execute(
                "SELECT * FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        return session_from_row(row)

    def update_policy(
        self,
        session_id: int,
        workflow_profile: str,
        policy: dict[str, str],
        role_config: dict[str, dict[str, str]] | None = None,
    ) -> Session:
        with self.db.connect() as connection:
            connection.execute(
                """
                UPDATE sessions
                SET workflow_profile = ?, policy_json = ?, role_config_json = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    workflow_profile,
                    json.dumps(policy, sort_keys=True),
                    json.dumps(role_config or {}, sort_keys=True),
                    session_id,
                ),
            )
            row = connection.execute(
                "SELECT * FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        return session_from_row(row)
