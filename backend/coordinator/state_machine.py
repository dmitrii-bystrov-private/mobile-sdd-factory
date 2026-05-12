"""Session transition rules."""

from __future__ import annotations

from backend.models.enums import SessionStatus


ALLOWED_TRANSITIONS: dict[SessionStatus, set[SessionStatus]] = {
    SessionStatus.CREATED: {SessionStatus.ACTIVE, SessionStatus.CANCELLED, SessionStatus.FAILED},
    SessionStatus.ACTIVE: {
        SessionStatus.WAITING_FOR_OPERATOR,
        SessionStatus.PAUSED,
        SessionStatus.COMPLETED,
        SessionStatus.CANCELLED,
        SessionStatus.FAILED,
    },
    SessionStatus.WAITING_FOR_OPERATOR: {
        SessionStatus.ACTIVE,
        SessionStatus.CANCELLED,
        SessionStatus.FAILED,
    },
    SessionStatus.PAUSED: {SessionStatus.ACTIVE, SessionStatus.CANCELLED},
    SessionStatus.COMPLETED: set(),
    SessionStatus.CANCELLED: set(),
    SessionStatus.FAILED: set(),
}
