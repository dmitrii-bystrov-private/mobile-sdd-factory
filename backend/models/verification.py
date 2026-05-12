"""Verification domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from backend.models.enums import VerificationStatus


@dataclass(slots=True)
class VerificationRun:
    id: int | None
    session_id: int
    attempt_number: int
    status: VerificationStatus
    command_profile: str
    artifact_group_id: str | None = None
    created_at: datetime | None = None
