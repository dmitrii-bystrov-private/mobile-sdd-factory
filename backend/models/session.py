"""Session domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from backend.models.enums import SessionStatus


@dataclass(slots=True)
class Session:
    id: int | None
    task_key: str
    status: SessionStatus
    current_stage: str
    current_owner: str | None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    ended_at: datetime | None = None
