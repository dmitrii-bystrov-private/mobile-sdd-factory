"""Session workflow policy normalization helpers."""

from __future__ import annotations

from dataclasses import dataclass

from backend.coordinator.intake import IntakeError

TRI_STATE_VALUES = {"disabled", "enabled", "required"}
REQUIREMENTS_CLARIFICATION_MODE_VALUES = {
    "ask-a-lot",
    "ask-selectively",
    "autonomous",
}
WORKFLOW_PROFILES = {"oneshot", "bug_full", "story_full"}

PROFILE_POLICY_FIELDS: dict[str, tuple[str, ...]] = {
    "oneshot": (
        "self_review_policy",
        "boy_scout_policy",
        "doc_harvest_policy",
    ),
    "bug_full": (
        "test_policy",
        "self_review_policy",
        "boy_scout_policy",
        "doc_harvest_policy",
    ),
    "story_full": (
        "self_review_policy",
        "boy_scout_policy",
        "doc_harvest_policy",
        "requirements_clarification_mode",
    ),
}

COMMON_DEFAULTS: dict[str, str] = {
    "self_review_policy": "enabled",
    "boy_scout_policy": "enabled",
    "doc_harvest_policy": "enabled",
}

FIELD_ALLOWED_VALUES: dict[str, set[str]] = {
    "test_policy": TRI_STATE_VALUES,
    "self_review_policy": TRI_STATE_VALUES,
    "boy_scout_policy": TRI_STATE_VALUES,
    "doc_harvest_policy": TRI_STATE_VALUES,
    "requirements_clarification_mode": REQUIREMENTS_CLARIFICATION_MODE_VALUES,
}

PROFILE_DEFAULTS: dict[str, dict[str, str]] = {
    "oneshot": {},
    "bug_full": {"test_policy": "enabled"},
    "story_full": {"requirements_clarification_mode": "ask-selectively"},
}


@dataclass(frozen=True, slots=True)
class SessionPolicyState:
    workflow_profile: str
    policy: dict[str, str]


def infer_workflow_profile(issue_type: str) -> str:
    normalized = issue_type.strip().lower()
    if normalized == "bug":
        return "bug_full"
    return "oneshot"


def normalize_session_policy(
    workflow_profile: str,
    policy: dict[str, str] | None,
) -> SessionPolicyState:
    if workflow_profile not in WORKFLOW_PROFILES:
        raise IntakeError(f"Unsupported workflow profile: {workflow_profile}")

    provided_policy = dict(policy or {})
    allowed_fields = set(PROFILE_POLICY_FIELDS[workflow_profile])
    unknown_fields = sorted(set(provided_policy) - allowed_fields)
    if unknown_fields:
        raise IntakeError(
            f"Policy fields are not allowed for {workflow_profile}: {', '.join(unknown_fields)}"
        )

    normalized = dict(COMMON_DEFAULTS)
    normalized.update(PROFILE_DEFAULTS[workflow_profile])
    normalized = {
        key: value
        for key, value in normalized.items()
        if key in allowed_fields
    }

    for field_name, value in provided_policy.items():
        allowed_values = FIELD_ALLOWED_VALUES.get(field_name)
        if allowed_values is None:
            raise IntakeError(f"Unsupported policy field: {field_name}")
        if value not in allowed_values:
            raise IntakeError(
                f"Unsupported policy value for {field_name}: {value}"
            )
        normalized[field_name] = value

    return SessionPolicyState(
        workflow_profile=workflow_profile,
        policy=normalized,
    )
