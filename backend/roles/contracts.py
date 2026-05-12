"""Role names and coordinator-facing contracts."""

IMPLEMENTER_ROLE = "implementer"
TASK_COORDINATOR_ROLE = "task-coordinator"
VERIFICATION_COORDINATOR_ROLE = "verification-coordinator"

DEFAULT_SESSION_ROLES = [
    TASK_COORDINATOR_ROLE,
    IMPLEMENTER_ROLE,
    VERIFICATION_COORDINATOR_ROLE,
]
