"""Repository for retry and recovery checkpoints."""

from __future__ import annotations

import json

from backend.models.checkpoint import Checkpoint
from backend.state.db import Database
from backend.state.models import checkpoint_from_row


class CheckpointRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(
        self,
        session_id: int,
        checkpoint_type: str,
        label: str,
        metadata: dict,
    ) -> Checkpoint:
        with self.db.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO checkpoints (session_id, checkpoint_type, label, metadata_json)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, checkpoint_type, label, json.dumps(metadata)),
            )
            row = connection.execute(
                "SELECT * FROM checkpoints WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return checkpoint_from_row(row)
