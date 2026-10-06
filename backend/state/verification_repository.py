"""Repository for verification runs."""

from __future__ import annotations

from backend.models.enums import VerificationStatus
from backend.models.verification import VerificationRun
from backend.state.db import Database
from backend.state.models import verification_run_from_row


class VerificationRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(self, session_id: int, attempt_number: int, command_profile: str) -> VerificationRun:
        with self.db.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO verification_runs (session_id, attempt_number, status, command_profile)
                VALUES (?, ?, ?, ?)
                """,
                (
                    session_id,
                    attempt_number,
                    VerificationStatus.REQUESTED.value,
                    command_profile,
                ),
            )
            row = connection.execute(
                "SELECT * FROM verification_runs WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return verification_run_from_row(row)
