"""Role names and coordinator-facing contracts."""

IMPLEMENTER_ROLE = "implementer"
TASK_COORDINATOR_ROLE = "task-coordinator"
VERIFICATION_COORDINATOR_ROLE = "verification-coordinator"
CODE_REVIEWER_ROLE = "code-reviewer"
STORY_SPEC_WORKER_ROLE = "story-spec-worker"
BUG_ANALYSIS_WORKER_ROLE = "bug-analysis-worker"

DEFAULT_SESSION_ROLES = [
    TASK_COORDINATOR_ROLE,
    IMPLEMENTER_ROLE,
    VERIFICATION_COORDINATOR_ROLE,
]

ALLOWED_STAGE_ROLE_TARGETS: dict[str, set[str]] = {
    "bug_analysis_requested": {
        BUG_ANALYSIS_WORKER_ROLE,
    },
    "story_spec_requested": {
        STORY_SPEC_WORKER_ROLE,
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
