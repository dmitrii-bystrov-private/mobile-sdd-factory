"""Repository for session roles."""

from __future__ import annotations

from backend.models.enums import RoleStatus
from backend.models.role import Role
from backend.state.db import Database
from backend.state.models import role_from_row


class RoleRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(
        self,
        session_id: int,
        role_name: str,
        runtime_backend: str,
        runtime_handle: str | None = None,
        status: RoleStatus = RoleStatus.CREATED,
    ) -> Role:
        with self.db.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO roles (
                  session_id, role_name, status, runtime_backend, runtime_handle
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, role_name, status.value, runtime_backend, runtime_handle),
            )
            row = connection.execute(
                "SELECT * FROM roles WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return role_from_row(row)

    def list_for_session(self, session_id: int) -> list[Role]:
        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM roles WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
        return [role_from_row(row) for row in rows]

    def get_by_name(self, session_id: int, role_name: str) -> Role | None:
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT * FROM roles WHERE session_id = ? AND role_name = ?",
                (session_id, role_name),
            ).fetchone()
        if row is None:
            return None
        return role_from_row(row)

    def get_by_id(self, role_id: int) -> Role | None:
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT * FROM roles WHERE id = ?",
                (role_id,),
            ).fetchone()
        if row is None:
            return None
        return role_from_row(row)

    def increment_hydration_version(self, role_id: int) -> Role:
        with self.db.connect() as connection:
            connection.execute(
                """
                UPDATE roles
                SET last_hydration_version = last_hydration_version + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (role_id,),
            )
            row = connection.execute(
                "SELECT * FROM roles WHERE id = ?",
                (role_id,),
            ).fetchone()
        return role_from_row(row)
