"""Memory item domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class MemoryItem:
    id: int | None
    item_type: str
    status: str
    platform: str
    workflow_profile: str
    source_session_id: int
    source_event_id: int | None
    summary: str
    metadata: dict[str, Any]
    use_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
