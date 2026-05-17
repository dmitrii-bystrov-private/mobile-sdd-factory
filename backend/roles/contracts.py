"""Role names and coordinator-facing contracts."""

IMPLEMENTER_ROLE = "implementer"
BUG_FIXER_ROLE = "bug-fixer"
TASK_COORDINATOR_ROLE = "task-coordinator"
VERIFICATION_COORDINATOR_ROLE = "verification-coordinator"
CODE_REVIEWER_ROLE = "code-reviewer"
CODE_SCOUT_ROLE = "code-scout"
PROPOSAL_CONTEXT_WORKER_ROLE = "proposal-context-worker"
REQUIREMENTS_CLARIFIER_WORKER_ROLE = "requirements-clarifier-worker"
ACCEPTANCE_CRITERIA_WORKER_ROLE = "acceptance-criteria-worker"
CONSTRAINTS_WORKER_ROLE = "constraints-worker"
SPEC_VERIFIER_WORKER_ROLE = "spec-verifier-worker"
STORY_SPEC_WORKER_ROLE = "story-spec-worker"
TASK_DECOMPOSER_WORKER_ROLE = "task-decomposer-worker"

DEFAULT_SESSION_ROLES = [
    TASK_COORDINATOR_ROLE,
    IMPLEMENTER_ROLE,
    VERIFICATION_COORDINATOR_ROLE,
]

ALLOWED_STAGE_ROLE_TARGETS: dict[str, set[str]] = {
    "bug_analysis_requested": {
        BUG_FIXER_ROLE,
    },
    "story_spec_requested": {
        STORY_SPEC_WORKER_ROLE,
    },
    "proposal_context_requested": {
        PROPOSAL_CONTEXT_WORKER_ROLE,
    },
    "requirements_requested": {
        REQUIREMENTS_CLARIFIER_WORKER_ROLE,
    },
    "acceptance_criteria_requested": {
        ACCEPTANCE_CRITERIA_WORKER_ROLE,
    },
    "constraints_requested": {
        CONSTRAINTS_WORKER_ROLE,
    },
    "spec_verification_requested": {
        SPEC_VERIFIER_WORKER_ROLE,
    },
    "task_decomposition_requested": {
        TASK_DECOMPOSER_WORKER_ROLE,
    },
    "subtask_implementation_requested": {
        IMPLEMENTER_ROLE,
    },
    "implementation_requested": {
        IMPLEMENTER_ROLE,
        BUG_FIXER_ROLE,
    },
    "verification_requested": {
        VERIFICATION_COORDINATOR_ROLE,
    },
    "verification_correction_requested": {
        IMPLEMENTER_ROLE,
        BUG_FIXER_ROLE,
    },
    "self_review_requested": {
        CODE_REVIEWER_ROLE,
    },
    "boy_scout_requested": {
        CODE_SCOUT_ROLE,
    },
    "self_review_correction_requested": {
        IMPLEMENTER_ROLE,
        BUG_FIXER_ROLE,
    },
}
