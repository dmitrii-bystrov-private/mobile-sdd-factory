#!/usr/bin/env python3
"""Run a broad bug-shaped runtime acceptance through the operator route layer."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from backend.api.routes_events import inject_event, list_events
from backend.api.routes_operator import reopen_from_qa
from backend.api.routes_roles import submit_role_output
from backend.api.routes_sessions import create_session
from backend.api.schemas import (
    CreateSessionRequest,
    InjectEventRequest,
    ReopenFromQaRequest,
    RoleOutputRequest,
)
from backend.roles.contracts import BUG_FIXER_ROLE, VERIFICATION_COORDINATOR_ROLE
from backend.tools.command_runner import CommandResult
from runtime_config import acceptance_role_config
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
    with managed_run_root(repo_root, "sdd-factory-real-bug-runtime-acceptance") as temp_root:
        deps = story_acceptance.build_acceptance_dependencies(repo_root=repo_root, temp_root=temp_root)

        deps.jira_adapter.get_issue_type = lambda task_key: CommandResult(  # type: ignore[method-assign]
            command=["fake_get_issue_type", task_key],
            returncode=0,
            stdout="Bug\n",
            stderr="",
        )
        deps.coordinator_service.jira_adapter = deps.jira_adapter

        task_key = "IOS-ACCEPT-REAL-BUG-001"
        create_response = create_session(
            CreateSessionRequest(
                task_key=task_key,
                workflow_profile="bug_full",
                prepare=True,
                policy={
                    "test_policy": "required",
                    "self_review_policy": "disabled",
                    "boy_scout_policy": "disabled",
                    "doc_harvest_policy": "disabled",
                },
                role_config=acceptance_role_config(
                    [BUG_FIXER_ROLE, VERIFICATION_COORDINATOR_ROLE]
                ),
            ),
            dependencies=deps,
        )
        session_id = create_response.session.id

        assert_role_launch_script(temp_root / "workdir", task_key, BUG_FIXER_ROLE, "persistent")
        assert_role_launch_script(
            temp_root / "workdir",
            task_key,
            VERIFICATION_COORDINATOR_ROLE,
            "persistent",
        )
        assert create_response.followup_event_type == "bug_analysis_requested"
        assert create_response.session.current_stage == "bug_analysis_requested"
        assert create_response.session.current_owner == BUG_FIXER_ROLE

        analysis_response = submit_role_output(
            RoleOutputRequest(
                session_id=session_id,
                role_name=BUG_FIXER_ROLE,
                output_type="completed",
                payload={
                    "summary": "Root cause isolated in coordinator resume path.",
                    "test_strategy": "Add regression around repeated resume after parked work.",
                },
            ),
            dependencies=deps,
        )
        assert analysis_response.followup_event_type == "implementation_requested"
        assert analysis_response.session.current_stage == "implementation_requested"
        assert analysis_response.session.current_owner == BUG_FIXER_ROLE

        implementation_response = submit_role_output(
            RoleOutputRequest(
                session_id=session_id,
                role_name=BUG_FIXER_ROLE,
                output_type="completed",
                payload={"summary": "Bug fix implemented with regression test."},
            ),
            dependencies=deps,
        )
        assert implementation_response.followup_event_type == "verification_requested"
        assert implementation_response.session.current_stage == "verification_requested"
        assert implementation_response.session.current_owner == VERIFICATION_COORDINATOR_ROLE

        verification_response = submit_role_output(
            RoleOutputRequest(
                session_id=session_id,
                role_name=VERIFICATION_COORDINATOR_ROLE,
                output_type="passed",
                payload={"summary": "Verification passed for bug fix."},
            ),
            dependencies=deps,
        )
        assert verification_response.followup_event_type == "send_to_test_completed"
        assert verification_response.session.status == "completed"
        assert verification_response.session.current_stage == "send_to_test_completed"

        qa_reopen_response = reopen_from_qa(
            ReopenFromQaRequest(
                session_id=session_id,
                comment_text="QA: edge case still fails after reopen.",
            ),
            dependencies=deps,
        )
        assert qa_reopen_response.reopened
        assert qa_reopen_response.event_type == "qa_reopened"
        assert qa_reopen_response.followup_event_type == "qa_reopen_requested"
        assert qa_reopen_response.session.current_stage == "qa_reopen_requested"
        assert qa_reopen_response.session.current_owner == BUG_FIXER_ROLE

        followup_response = submit_role_output(
            RoleOutputRequest(
                session_id=session_id,
                role_name=BUG_FIXER_ROLE,
                output_type="completed",
                payload={"summary": "QA follow-up fix implemented."},
            ),
            dependencies=deps,
        )
        assert followup_response.followup_event_type == "verification_requested"
        assert followup_response.session.current_stage == "verification_requested"

        final_verification_response = submit_role_output(
            RoleOutputRequest(
                session_id=session_id,
                role_name=VERIFICATION_COORDINATOR_ROLE,
                output_type="passed",
                payload={"summary": "Final verification passed."},
            ),
            dependencies=deps,
        )
        assert final_verification_response.followup_event_type == "send_to_test_completed"
        assert final_verification_response.session.status == "completed"

        events_response = list_events(session_id=session_id, dependencies=deps)
        event_types = [item.event_type for item in events_response.items]
        assert "bug_analysis_requested" in event_types
        assert "bug_analysis_completed" in event_types
        assert "implementation_requested" in event_types
        assert "verification_requested" in event_types
        assert "qa_reopened" in event_types
        assert "qa_reopen_requested" in event_types
        assert event_types.count("verification_passed") == 2
        assert "mr_handoff_completed" in event_types
        assert "send_to_test_completed" in event_types

        print(f"Real bug runtime acceptance passed for session {session_id}.")


if __name__ == "__main__":
    main()
