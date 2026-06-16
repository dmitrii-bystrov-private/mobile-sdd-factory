"""Role names and coordinator-facing contracts."""

IMPLEMENTER_ROLE = "implementer"
BUG_FIXER_ROLE = "bug-fixer"
VERIFICATION_COORDINATOR_ROLE = "verification-coordinator"
CODE_REVIEWER_ROLE = "code-reviewer"
CODE_SCOUT_ROLE = "code-scout"
CONVENTION_REVIEWER_ROLE = "convention-reviewer"
REQUIREMENTS_REVIEWER_ROLE = "requirements-reviewer"
DOC_HARVEST_ROLE = "doc-harvest-worker"
DOCUMENTATION_REVIEWER_ROLE = "documentation-reviewer"
PROPOSAL_CONTEXT_WORKER_ROLE = "proposal-context-worker"
REQUIREMENTS_CLARIFIER_WORKER_ROLE = "requirements-clarifier-worker"
ACCEPTANCE_CRITERIA_WORKER_ROLE = "acceptance-criteria-worker"
CONSTRAINTS_WORKER_ROLE = "constraints-worker"
SPEC_VERIFIER_WORKER_ROLE = "spec-verifier-worker"
TASK_DECOMPOSER_WORKER_ROLE = "task-decomposer-worker"

RETIRED_ROLE_NAMES = {
    "mr-comments-analyst-worker",
}

DEFAULT_SESSION_ROLES = [
    IMPLEMENTER_ROLE,
    VERIFICATION_COORDINATOR_ROLE,
]

PERSISTENT_SESSION_ROLES = [
    IMPLEMENTER_ROLE,
    VERIFICATION_COORDINATOR_ROLE,
    CONVENTION_REVIEWER_ROLE,
    REQUIREMENTS_REVIEWER_ROLE,
    CODE_REVIEWER_ROLE,
    CODE_SCOUT_ROLE,
    DOC_HARVEST_ROLE,
    DOCUMENTATION_REVIEWER_ROLE,
    BUG_FIXER_ROLE,
]

ALLOWED_STAGE_ROLE_TARGETS: dict[str, set[str]] = {
    "bug_analysis_requested": {
        BUG_FIXER_ROLE,
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
    "convention_review_requested": {
        CONVENTION_REVIEWER_ROLE,
    },
    "requirements_review_requested": {
        REQUIREMENTS_REVIEWER_ROLE,
    },
    "boy_scout_requested": {
        CODE_SCOUT_ROLE,
    },
    "boy_scout_correction_requested": {
        IMPLEMENTER_ROLE,
        BUG_FIXER_ROLE,
    },
    "doc_harvest_requested": {
        DOC_HARVEST_ROLE,
    },
    "documentation_review_requested": {
        DOCUMENTATION_REVIEWER_ROLE,
    },
    "documentation_review_correction_requested": {
        IMPLEMENTER_ROLE,
        BUG_FIXER_ROLE,
    },
    "self_review_correction_requested": {
        IMPLEMENTER_ROLE,
        BUG_FIXER_ROLE,
    },
    "convention_review_correction_requested": {
        IMPLEMENTER_ROLE,
        BUG_FIXER_ROLE,
    },
    "requirements_review_correction_requested": {
        IMPLEMENTER_ROLE,
        BUG_FIXER_ROLE,
    },
}
