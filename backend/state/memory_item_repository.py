"""Repository for reusable cross-session memory items."""

from __future__ import annotations

import json

from backend.models.memory_item import MemoryItem
from backend.state.db import Database
from backend.state.models import memory_item_from_row


class MemoryItemRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(
        self,
        item_type: str,
        status: str,
        platform: str,
        workflow_profile: str,
        source_session_id: int,
        summary: str,
        metadata: dict,
        source_event_id: int | None = None,
    ) -> MemoryItem:
        with self.db.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO memory_items (
                  item_type,
                  status,
                  platform,
                  workflow_profile,
                  source_session_id,
                  source_event_id,
                  summary,
                  metadata_json,
                  use_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    item_type,
                    status,
                    platform,
                    workflow_profile,
                    source_session_id,
                    source_event_id,
                    summary,
                    json.dumps(metadata, sort_keys=True),
                ),
            )
            row = connection.execute(
                "SELECT * FROM memory_items WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return memory_item_from_row(row)

    def list_matching(
        self,
        item_type: str,
        platform: str,
        workflow_profile: str,
        status: str = "active",
    ) -> list[MemoryItem]:
        with self.db.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM memory_items
                WHERE item_type = ? AND status = ? AND platform = ? AND workflow_profile = ?
                ORDER BY created_at DESC, id DESC
                """,
                (item_type, status, platform, workflow_profile),
            ).fetchall()
        return [memory_item_from_row(row) for row in rows]

    def increment_use_count(self, memory_item_id: int) -> MemoryItem:
        with self.db.connect() as connection:
            connection.execute(
                """
                UPDATE memory_items
                SET use_count = use_count + 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (memory_item_id,),
            )
            row = connection.execute(
                "SELECT * FROM memory_items WHERE id = ?",
                (memory_item_id,),
            ).fetchone()
        return memory_item_from_row(row)
