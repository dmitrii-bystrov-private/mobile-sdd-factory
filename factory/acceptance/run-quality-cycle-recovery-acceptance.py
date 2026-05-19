#!/usr/bin/env python3
"""Run operator recovery acceptance for blocked review and verification cycles."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from backend.api.routes_events import list_events
from backend.api.routes_operator import resume_session
from backend.api.routes_roles import submit_role_output
from backend.api.routes_sessions import create_session, prepare_session
from backend.api.routes_work_items import list_work_items
from backend.api.schemas import (
    CreateSessionRequest,
    PrepareSessionRequest,
    ResumeSessionRequest,
    RoleOutputRequest,
)
from backend.roles.contracts import CODE_REVIEWER_ROLE, VERIFICATION_COORDINATOR_ROLE
from run_roots import managed_run_root


def load_acceptance_module():
    module_path = Path(__file__).resolve().parent / "run-happy-path-acceptance.py"
    spec = spec_from_file_location("happy_path_acceptance", module_path)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    acceptance = load_acceptance_module()

    with managed_run_root(repo_root, "sdd-factory-quality-cycle-recovery") as temp_root:
        deps = acceptance.build_acceptance_dependencies(repo_root=repo_root, temp_root=temp_root)

        # Reviewer-blocked self-review cycle.
        review_session = create_session(
            CreateSessionRequest(
                task_key="IOS-ACCEPT-REVIEW-CYCLE-001",
                workflow_profile="oneshot",
                policy={
                    "self_review_policy": "required",
                    "boy_scout_policy": "disabled",
                    "doc_harvest_policy": "disabled",
                },
            ),
            dependencies=deps,
        ).session
        prepare_session(
            PrepareSessionRequest(task_key=review_session.task_key),
            dependencies=deps,
        )
        submit_role_output(
            RoleOutputRequest(
                session_id=review_session.id,
                role_name="implementer",
                output_type="completed",
                payload={"summary": "implementation done"},
            ),
            dependencies=deps,
        )
        blocked_review = submit_role_output(
            RoleOutputRequest(
                session_id=review_session.id,
                role_name=CODE_REVIEWER_ROLE,
                output_type="blocked_review_cycle",
                payload={
                    "summary": "Repeated review findings remain unresolved.",
                    "details": "The same review loop no longer converges.",
                    "issues": [
                        {
                            "severity": "error",
                            "file": "FeatureViewModel.swift",
                            "problem": "Reducer violation is still present.",
                            "required_change": "Route the mutation through the reducer.",
                        }
                    ],
                },
            ),
            dependencies=deps,
        )
        assert blocked_review.followup_event_type == "session_escalated_to_operator"
        assert blocked_review.session.status == "waiting_for_operator"
        assert blocked_review.session.current_stage == "self_review_requested"
        assert blocked_review.session.current_owner == CODE_REVIEWER_ROLE
        review_work_items = list_work_items(session_id=review_session.id, dependencies=deps).items
        assert any(item.status == "waiting_for_operator" for item in review_work_items)

        resumed_review = resume_session(
            ResumeSessionRequest(session_id=review_session.id),
            dependencies=deps,
        )
        assert resumed_review.followup_event_type == "role_input_dispatched"
        assert resumed_review.session.status == "active"
        assert resumed_review.session.current_owner == CODE_REVIEWER_ROLE

        reviewer_role = deps.role_repository.get_by_name(review_session.id, CODE_REVIEWER_ROLE)
        reviewer_inputs = deps.session_backend.get_sent_inputs(reviewer_role.runtime_handle)
        assert "blocked_review_cycle" in reviewer_inputs[-1]

        review_events = [item.event_type for item in list_events(session_id=review_session.id, dependencies=deps).items]
        assert "self_review_blocked" in review_events
        assert "session_resumed_by_operator" in review_events

        # Verifier-blocked verification cycle.
        verification_session = create_session(
            CreateSessionRequest(
                task_key="IOS-ACCEPT-VERIFY-CYCLE-001",
                workflow_profile="oneshot",
                policy={
                    "self_review_policy": "disabled",
                    "boy_scout_policy": "disabled",
                    "doc_harvest_policy": "disabled",
                },
            ),
            dependencies=deps,
        ).session
        prepare_session(
            PrepareSessionRequest(task_key=verification_session.task_key),
            dependencies=deps,
        )
        submit_role_output(
            RoleOutputRequest(
                session_id=verification_session.id,
                role_name="implementer",
                output_type="completed",
                payload={"summary": "implementation done"},
            ),
            dependencies=deps,
        )
        blocked_verification = submit_role_output(
            RoleOutputRequest(
                session_id=verification_session.id,
                role_name=VERIFICATION_COORDINATOR_ROLE,
                output_type="blocked_verification_cycle",
                payload={
                    "summary": "Repeated verification failures remain unresolved.",
                    "details": "The same verification loop no longer converges.",
                    "failures": ["test"],
                    "check_outputs": {
                        "run-test.sh": "Tests still fail: presenter state mismatch",
                    },
                },
            ),
            dependencies=deps,
        )
        assert blocked_verification.followup_event_type == "session_escalated_to_operator"
        assert blocked_verification.session.status == "waiting_for_operator"
        assert blocked_verification.session.current_stage == "verification_requested"
        assert blocked_verification.session.current_owner == VERIFICATION_COORDINATOR_ROLE
        verification_work_items = list_work_items(
            session_id=verification_session.id,
            dependencies=deps,
        ).items
        assert any(item.status == "waiting_for_operator" for item in verification_work_items)

        resumed_verification = resume_session(
            ResumeSessionRequest(session_id=verification_session.id),
            dependencies=deps,
        )
        assert resumed_verification.followup_event_type == "role_input_dispatched"
        assert resumed_verification.session.status == "active"
        assert resumed_verification.session.current_owner == VERIFICATION_COORDINATOR_ROLE

        verifier_role = deps.role_repository.get_by_name(
            verification_session.id,
            VERIFICATION_COORDINATOR_ROLE,
        )
        verifier_inputs = deps.session_backend.get_sent_inputs(verifier_role.runtime_handle)
        assert "blocked_verification_cycle" in verifier_inputs[-1]

        verification_events = [
            item.event_type
            for item in list_events(session_id=verification_session.id, dependencies=deps).items
        ]
        assert "verification_blocked" in verification_events
        assert "session_resumed_by_operator" in verification_events

        print("Quality cycle recovery operator acceptance passed.")


if __name__ == "__main__":
    main()
