"""Work item domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from backend.models.enums import WorkItemStatus


@dataclass(slots=True)
class WorkItem:
    id: int | None
    session_id: int
    work_type: str
    title: str
    status: WorkItemStatus
    owner_role_id: int | None = None
    source_event_id: int | None = None
    priority: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
