#!/usr/bin/env python3
"""Run launcher-backed operator recovery acceptance through the route layer."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from backend.api.routes_events import list_events
from backend.api.routes_operator import poll_session_output, resume_session, retry_session
from backend.api.routes_sessions import create_session, prepare_session
from backend.api.routes_work_items import list_work_items
from backend.api.schemas import (
    CreateSessionRequest,
    PollSessionOutputRequest,
    PrepareSessionRequest,
    ResumeSessionRequest,
    RetrySessionRequest,
)
from backend.roles.contracts import IMPLEMENTER_ROLE
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
    with managed_run_root(repo_root, "sdd-factory-escalation-resume-acceptance") as temp_root:
        deps = story_acceptance.build_acceptance_dependencies(repo_root=repo_root, temp_root=temp_root)

        session_specs = [
            ("IOS-ACCEPT-RECOVERY-RESUME-001", "resume"),
            ("IOS-ACCEPT-RECOVERY-RETRY-001", "retry"),
        ]

        for task_key, recovery_mode in session_specs:
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

            prepare_response = prepare_session(
                PrepareSessionRequest(task_key=task_key),
                dependencies=deps,
            )
            assert prepare_response.followup_event_type == "implementation_requested"

            implementer_role = deps.role_repository.get_by_name(session_id, IMPLEMENTER_ROLE)
            deps.session_backend.simulate_output(
                implementer_role.runtime_handle,
                'SDD_ERROR: {"summary":"tool failed","details":"command exited 1"}',
            )

            poll_response = poll_session_output(
                PollSessionOutputRequest(session_id=session_id),
                dependencies=deps,
            )
            assert poll_response.polled
            assert poll_response.chunk_count == 1
            assert poll_response.session.status == "waiting_for_operator"
            assert poll_response.session.current_owner is None

            if recovery_mode == "resume":
                recovery_response = resume_session(
                    ResumeSessionRequest(session_id=session_id),
                    dependencies=deps,
                )
                assert recovery_response.resumed
                assert recovery_response.event_type == "session_resumed_by_operator"
            else:
                recovery_response = retry_session(
                    RetrySessionRequest(session_id=session_id),
                    dependencies=deps,
                )
                assert recovery_response.retried
                assert recovery_response.event_type == "session_retried_by_operator"

            assert recovery_response.followup_event_type == "role_input_dispatched"
            assert recovery_response.session.status == "active"
            assert recovery_response.session.current_owner == IMPLEMENTER_ROLE

            events_response = list_events(session_id=session_id, dependencies=deps)
            event_types = [item.event_type for item in events_response.items]
            assert "role_runtime_error_reported" in event_types
            assert "session_escalated_to_operator" in event_types
            if recovery_mode == "resume":
                assert "session_resumed_by_operator" in event_types
            else:
                assert "session_retried_by_operator" in event_types

            work_items_response = list_work_items(session_id=session_id, dependencies=deps)
            if recovery_mode == "resume":
                assert len(work_items_response.items) == 1
            else:
                assert len(work_items_response.items) == 2
                assert any(item.title.startswith("Retry: ") for item in work_items_response.items)

        print("Escalation and resume operator acceptance passed.")


if __name__ == "__main__":
    main()
