#!/usr/bin/env python3
"""Run a launcher-backed MR follow-up runtime acceptance through the route layer."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from backend.api.routes_events import list_events
from backend.api.routes_operator import ingest_mr_comments
from backend.api.routes_roles import submit_role_output
from backend.api.routes_sessions import create_session, prepare_session
from backend.api.schemas import (
    CreateSessionRequest,
    IngestMrCommentsRequest,
    PrepareSessionRequest,
    RoleOutputRequest,
)
from backend.roles.contracts import IMPLEMENTER_ROLE, VERIFICATION_COORDINATOR_ROLE
from run_roots import managed_run_root


def load_story_acceptance_module():
    module_path = Path(__file__).resolve().parent / "run-story-subtasks-acceptance.py"
    spec = spec_from_file_location("story_subtasks_acceptance", module_path)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def assert_role_launch_script(
    workdir_root: Path,
    task_key: str,
    role_name: str,
    expected_lifecycle: str,
) -> None:
    role_dir = workdir_root / task_key / "runtime" / "role-workspaces" / role_name
    agents_path = role_dir / "AGENTS.md"
    claude_path = role_dir / "CLAUDE.md"
    launch_script = role_dir / "launch-role.sh"

    assert role_dir.is_dir(), role_dir
    assert agents_path.is_file(), agents_path
    assert claude_path.is_symlink(), claude_path
    assert launch_script.is_file(), launch_script

    launch_text = launch_script.read_text()
    assert f"SDD_FACTORY_ROLE_NAME={role_name}" in launch_text
    assert f"SDD_FACTORY_ROLE_LIFECYCLE={expected_lifecycle}" in launch_text


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    story_acceptance = load_story_acceptance_module()
    with managed_run_root(repo_root, "sdd-factory-real-mr-followup-runtime-acceptance") as temp_root:
        deps = story_acceptance.build_acceptance_dependencies(repo_root=repo_root, temp_root=temp_root)

        task_key = "IOS-ACCEPT-REAL-MR-001"
        create_response = create_session(
            CreateSessionRequest(
                task_key=task_key,
                workflow_profile="oneshot",
                policy={
                    "self_review_policy": "disabled",
                    "boy_scout_policy": "disabled",
                    "doc_harvest_policy": "disabled",
                },
            ),
            dependencies=deps,
        )
        session_id = create_response.session.id

        assert_role_launch_script(temp_root / "workdir", task_key, IMPLEMENTER_ROLE, "persistent")
        assert_role_launch_script(
            temp_root / "workdir",
            task_key,
            VERIFICATION_COORDINATOR_ROLE,
            "persistent",
        )

        prepare_response = prepare_session(
            PrepareSessionRequest(task_key=task_key),
            dependencies=deps,
        )
        assert prepare_response.followup_event_type == "implementation_requested"

        implementation_role = deps.role_repository.get_by_name(session_id, IMPLEMENTER_ROLE)
        verification_role = deps.role_repository.get_by_name(session_id, VERIFICATION_COORDINATOR_ROLE)

        implementation_response = submit_role_output(
            RoleOutputRequest(
                session_id=session_id,
                role_name=IMPLEMENTER_ROLE,
                output_type="completed",
                payload={"summary": "Initial implementation done."},
            ),
            dependencies=deps,
        )
        assert implementation_response.followup_event_type == "verification_requested"

        verification_response = submit_role_output(
            RoleOutputRequest(
                session_id=session_id,
                role_name=VERIFICATION_COORDINATOR_ROLE,
                output_type="passed",
                payload={"summary": "Initial verification passed."},
            ),
            dependencies=deps,
        )
        assert verification_response.followup_event_type == "task_completed"
        assert verification_response.session.status == "completed"

        mr_followup_response = ingest_mr_comments(
            IngestMrCommentsRequest(
                session_id=session_id,
                platform="ios",
                mr_id="2942",
            ),
            dependencies=deps,
        )
        assert mr_followup_response.ingested
        assert mr_followup_response.event_type == "mr_comments_received"
        assert mr_followup_response.followup_event_type == "mr_followup_requested"
        assert mr_followup_response.session.current_stage == "mr_followup_requested"
        assert mr_followup_response.session.current_owner == IMPLEMENTER_ROLE
        assert mr_followup_response.session.status == "active"

        implementer_inputs = deps.session_backend.get_sent_inputs(implementation_role.runtime_handle)
        assert len(implementer_inputs) == 2
        assert "Continue from your existing implementer role context" in implementer_inputs[-1]
        assert "Apply MR follow-up changes for IOS-ACCEPT-REAL-MR-001." in implementer_inputs[-1]
        assert '"work_item_type": "followup_implementation"' in implementer_inputs[-1]

        followup_response = submit_role_output(
            RoleOutputRequest(
                session_id=session_id,
                role_name=IMPLEMENTER_ROLE,
                output_type="completed",
                payload={"summary": "MR follow-up changes implemented."},
            ),
            dependencies=deps,
        )
        assert followup_response.followup_event_type == "verification_requested"
        assert followup_response.session.current_stage == "verification_requested"
        assert followup_response.session.current_owner == VERIFICATION_COORDINATOR_ROLE

        verifier_inputs = deps.session_backend.get_sent_inputs(verification_role.runtime_handle)
        assert len(verifier_inputs) == 2
        assert "Continue from your existing verification-coordinator role context" in verifier_inputs[-1]

        final_verification_response = submit_role_output(
            RoleOutputRequest(
                session_id=session_id,
                role_name=VERIFICATION_COORDINATOR_ROLE,
                output_type="passed",
                payload={"summary": "Verification passed after MR follow-up."},
            ),
            dependencies=deps,
        )
        assert final_verification_response.followup_event_type == "task_completed"
        assert final_verification_response.session.status == "completed"

        events_response = list_events(session_id=session_id, dependencies=deps)
        event_types = [item.event_type for item in events_response.items]
        assert "mr_comments_received" in event_types
        assert "mr_followup_requested" in event_types
        assert event_types.count("verification_requested") == 2
        assert event_types.count("verification_passed") == 2
        assert event_types.count("task_completed") == 2

        print(f"Real MR follow-up runtime acceptance passed for session {session_id}.")


if __name__ == "__main__":
    main()
