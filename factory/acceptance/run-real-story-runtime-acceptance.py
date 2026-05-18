#!/usr/bin/env python3
"""Run a broad story-shaped runtime acceptance through the operator route layer."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from backend.api.routes_events import inject_event, list_events
from backend.api.routes_operator import create_subtasks_from_plan, resume_session
from backend.api.routes_roles import submit_role_output
from backend.api.routes_sessions import create_session, prepare_session
from backend.api.schemas import (
    CreateSessionRequest,
    CreateSubtasksFromPlanRequest,
    InjectEventRequest,
    PrepareSessionRequest,
    ResumeSessionRequest,
    RoleOutputRequest,
)
from backend.roles.contracts import (
    ACCEPTANCE_CRITERIA_WORKER_ROLE,
    CODE_REVIEWER_ROLE,
    CONSTRAINTS_WORKER_ROLE,
    IMPLEMENTER_ROLE,
    PROPOSAL_CONTEXT_WORKER_ROLE,
    REQUIREMENTS_CLARIFIER_WORKER_ROLE,
    SPEC_VERIFIER_WORKER_ROLE,
    STORY_SPEC_WORKER_ROLE,
    TASK_DECOMPOSER_WORKER_ROLE,
    VERIFICATION_COORDINATOR_ROLE,
)
from backend.tools.command_runner import CommandResult
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
    with managed_run_root(repo_root, "sdd-factory-real-story-runtime-acceptance") as temp_root:
        deps = story_acceptance.build_acceptance_dependencies(repo_root=repo_root, temp_root=temp_root)

        task_key = "IOS-ACCEPT-REAL-STORY-001"
        create_response = create_session(
            CreateSessionRequest(
                task_key=task_key,
                workflow_profile="story_full",
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
        assert_role_launch_script(temp_root / "workdir", task_key, VERIFICATION_COORDINATOR_ROLE, "persistent")

        prepare_response = prepare_session(
            PrepareSessionRequest(task_key=task_key),
            dependencies=deps,
        )
        assert prepare_response.followup_event_type == "proposal_context_requested"

        statuses_path = temp_root / "workdir" / task_key / "statuses.md"
        statuses_path.write_text(
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-ACCEPT-REAL-STORY-001 | Story | Parent story | In Progress |
"""
        )

        planning_steps = [
            ("proposal_context_completed", PROPOSAL_CONTEXT_WORKER_ROLE, "Proposal ready"),
            ("requirements_completed", REQUIREMENTS_CLARIFIER_WORKER_ROLE, "Requirements ready"),
            ("acceptance_criteria_completed", ACCEPTANCE_CRITERIA_WORKER_ROLE, "Acceptance ready"),
            ("constraints_completed", CONSTRAINTS_WORKER_ROLE, "Constraints ready"),
            ("spec_verification_completed", SPEC_VERIFIER_WORKER_ROLE, "Spec verified"),
            ("story_spec_completed", STORY_SPEC_WORKER_ROLE, "Story spec ready"),
        ]
        for event_type, role_name, summary in planning_steps:
            assert_role_launch_script(temp_root / "workdir", task_key, role_name, "one-shot")
            inject_event(
                InjectEventRequest(
                    session_id=session_id,
                    event_type=event_type,
                    payload={"summary": summary},
                ),
                dependencies=deps,
            )

        assert_role_launch_script(temp_root / "workdir", task_key, TASK_DECOMPOSER_WORKER_ROLE, "one-shot")
        inject_event(
            InjectEventRequest(
                session_id=session_id,
                event_type="task_decomposition_completed",
                payload={
                    "summary": "Decomposition prepared",
                    "task_breakdown": "Build data source, then wire presentation layer.",
                    "plan_index_markdown": (
                        "# Execution Task List\n\n"
                        "| # | Task | Depends on | Status |\n"
                        "|---|------|------------|--------|\n"
                        "| 01 | [Build data source](./01-build-data-source.md) | — | ☐ |\n"
                        "| 02 | [Wire presentation layer](./02-wire-presentation-layer.md) | 01 | ☐ |\n"
                    ),
                    "plan_task_files": [
                        {
                            "filename": "01-build-data-source.md",
                            "content": "# Build data source\n\n## What to implement\nCreate the feature data source.\n",
                        },
                        {
                            "filename": "02-wire-presentation-layer.md",
                            "content": "# Wire presentation layer\n\n## What to implement\nConnect state to UI.\n",
                        },
                    ],
                },
            ),
            dependencies=deps,
        )

        statuses_path.write_text(
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-ACCEPT-REAL-STORY-001 | Story | Parent story | In Progress |
| IOS-91001 | Sub-task | Build data source | To Do |
| IOS-91002 | Sub-task | Wire presentation layer | To Do |
"""
        )

        create_subtasks_response = create_subtasks_from_plan(
            CreateSubtasksFromPlanRequest(session_id=session_id),
            dependencies=deps,
        )
        assert create_subtasks_response.created
        assert create_subtasks_response.followup_event_type is None
        assert create_subtasks_response.session.current_stage == "subtask_creation_requested"

        resume_response = resume_session(
            ResumeSessionRequest(session_id=session_id),
            dependencies=deps,
        )
        assert resume_response.event_type == "session_resumed_by_operator"
        assert resume_response.followup_event_type == "subtask_implementation_requested"
        assert resume_response.session.current_stage == "subtask_implementation_requested"

        snapshot_adapter = deps.snapshot_adapter
        original_run = snapshot_adapter.run

        def run_with_terminal_subtasks(task_key_for_refresh: str) -> CommandResult:
            statuses_path.write_text(
                """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-ACCEPT-REAL-STORY-001 | Story | Parent story | In Progress |
| IOS-91001 | Sub-task | Build data source | Ready for test |
| IOS-91002 | Sub-task | Wire presentation layer | Released |
"""
            )
            return original_run(task_key_for_refresh)

        snapshot_adapter.run = run_with_terminal_subtasks  # type: ignore[method-assign]
        deps.coordinator_service.snapshot_adapter = snapshot_adapter

        subtask_response = inject_event(
            InjectEventRequest(
                session_id=session_id,
                event_type="subtask_completed",
                payload={"summary": "Subtask implementation done"},
            ),
            dependencies=deps,
        )
        assert subtask_response.followup_event_type == "verification_requested"
        assert subtask_response.session.current_stage == "verification_requested"

        verification_response = submit_role_output(
            RoleOutputRequest(
                session_id=session_id,
                role_name=VERIFICATION_COORDINATOR_ROLE,
                output_type="passed",
                payload={"summary": "verification passed"},
            ),
            dependencies=deps,
        )
        assert verification_response.followup_event_type == "send_to_test_completed"
        assert verification_response.session.status == "completed"
        assert verification_response.session.current_stage == "send_to_test_completed"

        events_response = list_events(session_id=session_id, dependencies=deps)
        event_types = [item.event_type for item in events_response.items]
        assert "proposal_context_requested" in event_types
        assert "task_decomposition_requested" in event_types
        assert "jira_subtasks_created" in event_types
        assert "subtask_graph_requested" in event_types
        assert "subtask_snapshot_refreshed" in event_types
        assert "verification_passed" in event_types
        assert "mr_handoff_completed" in event_types
        assert "send_to_test_completed" in event_types

        print(f"Real story runtime acceptance passed for session {session_id}.")


if __name__ == "__main__":
    main()
