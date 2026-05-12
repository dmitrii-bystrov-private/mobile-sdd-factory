"""Checkpoint domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class Checkpoint:
    id: int | None
    session_id: int
    checkpoint_type: str
    label: str
    metadata: dict[str, Any]
    created_at: datetime | None = None
