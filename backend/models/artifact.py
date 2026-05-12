"""Artifact domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class Artifact:
    id: int | None
    session_id: int
    role_id: int | None
    stage_name: str
    artifact_type: str
    path: str
    metadata: dict[str, Any]
    created_at: datetime | None = None
