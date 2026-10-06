"""Event domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class Event:
    id: int | None
    session_id: int
    event_type: str
    producer_type: str
    producer_id: str | None
    payload: dict[str, Any]
    correlation_id: str | None = None
    created_at: datetime | None = None
