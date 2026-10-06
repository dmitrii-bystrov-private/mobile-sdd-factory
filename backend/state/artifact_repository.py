"""Repository for stage artifacts."""

from __future__ import annotations

import json

from backend.models.artifact import Artifact
from backend.state.db import Database
from backend.state.models import artifact_from_row


DEFAULT_UI_EXCLUDED_ARTIFACT_TYPES = {
    "runtime_output",
    "runtime_progress_json",
}


class ArtifactRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(
        self,
        session_id: int,
        stage_name: str,
        artifact_type: str,
        path: str,
        metadata: dict,
        role_id: int | None = None,
    ) -> Artifact:
        with self.db.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO artifacts (session_id, role_id, stage_name, artifact_type, path, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, role_id, stage_name, artifact_type, path, json.dumps(metadata)),
            )
            row = connection.execute(
                "SELECT * FROM artifacts WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return artifact_from_row(row)

    def list_for_session(self, session_id: int) -> list[Artifact]:
        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM artifacts WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
        return [artifact_from_row(row) for row in rows]

    def list_for_session_excluding(
        self,
        session_id: int,
        excluded_artifact_types: set[str],
    ) -> list[Artifact]:
        if not excluded_artifact_types:
            return self.list_for_session(session_id)
        placeholders = ",".join("?" for _ in excluded_artifact_types)
        with self.db.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT *
                FROM artifacts
                WHERE session_id = ?
                  AND artifact_type NOT IN ({placeholders})
                ORDER BY id ASC
                """,
                (session_id, *sorted(excluded_artifact_types)),
            ).fetchall()
        return [artifact_from_row(row) for row in rows]

    def get_by_id(self, artifact_id: int) -> Artifact | None:
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT * FROM artifacts WHERE id = ?",
                (artifact_id,),
            ).fetchone()
        if row is None:
            return None
        return artifact_from_row(row)
