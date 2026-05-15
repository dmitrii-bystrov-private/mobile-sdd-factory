"""Role names and coordinator-facing contracts."""

IMPLEMENTER_ROLE = "implementer"
TASK_COORDINATOR_ROLE = "task-coordinator"
VERIFICATION_COORDINATOR_ROLE = "verification-coordinator"
CODE_REVIEWER_ROLE = "code-reviewer"

DEFAULT_SESSION_ROLES = [
    TASK_COORDINATOR_ROLE,
    IMPLEMENTER_ROLE,
    VERIFICATION_COORDINATOR_ROLE,
]

ALLOWED_STAGE_ROLE_TARGETS: dict[str, set[str]] = {
    "bug_analysis_requested": {
        IMPLEMENTER_ROLE,
    },
    "story_spec_requested": {
        IMPLEMENTER_ROLE,
    },
    "subtask_implementation_requested": {
        IMPLEMENTER_ROLE,
    },
    "implementation_requested": {
        IMPLEMENTER_ROLE,
    },
    "verification_requested": {
        VERIFICATION_COORDINATOR_ROLE,
    },
    "verification_correction_requested": {
        IMPLEMENTER_ROLE,
    },
    "self_review_requested": {
        CODE_REVIEWER_ROLE,
    },
    "self_review_correction_requested": {
        IMPLEMENTER_ROLE,
    },
}
