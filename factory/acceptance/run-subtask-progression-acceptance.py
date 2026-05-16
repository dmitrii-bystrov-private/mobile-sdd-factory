#!/usr/bin/env python3
"""Run subtask progression acceptance through the operator route layer."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import tempfile

from backend.api.routes_events import inject_event
from backend.api.routes_sessions import create_session, get_subtask_graph, get_subtask_progress, prepare_session
from backend.api.schemas import CreateSessionRequest, InjectEventRequest, PrepareSessionRequest
from backend.tools.command_runner import CommandResult


def load_story_acceptance_module():
    module_path = Path(__file__).resolve().parent / "run-story-subtasks-acceptance.py"
    spec = spec_from_file_location("story_subtasks_acceptance", module_path)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    story_acceptance = load_story_acceptance_module()
    with tempfile.TemporaryDirectory(prefix="sdd-factory-subtask-progression-acceptance.") as temp_dir:
        temp_root = Path(temp_dir)
        deps = story_acceptance.build_acceptance_dependencies(repo_root=repo_root, temp_root=temp_root)

        create_response = create_session(
            CreateSessionRequest(
                task_key="IOS-ACCEPT-SUBTASK-001",
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
        prepare_session(
            PrepareSessionRequest(task_key="IOS-ACCEPT-SUBTASK-001"),
            dependencies=deps,
        )

        statuses_path = temp_root / "workdir" / "IOS-ACCEPT-SUBTASK-001" / "statuses.md"
        statuses_path.write_text(
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-ACCEPT-SUBTASK-001 | Story | Parent story | In Progress |
| IOS-52001 | Sub-task | Build data source | To Do |
| IOS-52002 | Sub-task | Wire presentation | To Do |
"""
        )

        for event_type in (
            "proposal_context_completed",
            "requirements_completed",
            "acceptance_criteria_completed",
            "constraints_completed",
            "spec_verification_completed",
            "story_spec_completed",
        ):
            inject_event(
                InjectEventRequest(
                    session_id=session_id,
                    event_type=event_type,
                    payload={"summary": "prepared"},
                ),
                dependencies=deps,
            )

        decomposition_response = inject_event(
            InjectEventRequest(
                session_id=session_id,
                event_type="task_decomposition_completed",
                payload={"summary": "Decomposition prepared"},
            ),
            dependencies=deps,
        )
        assert decomposition_response.followup_event_type == "subtask_implementation_requested"
        assert decomposition_response.session.current_stage == "subtask_implementation_requested"

        snapshot_adapter = deps.snapshot_adapter
        original_run = snapshot_adapter.run

        def run_with_progression(task_key: str) -> CommandResult:
            statuses_path.write_text(
                """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-ACCEPT-SUBTASK-001 | Story | Parent story | In Progress |
| IOS-52001 | Sub-task | Build data source | Ready for test |
| IOS-52002 | Sub-task | Wire presentation | To Do |
"""
            )
            return original_run(task_key)

        snapshot_adapter.run = run_with_progression  # type: ignore[method-assign]
        deps.coordinator_service.snapshot_adapter = snapshot_adapter

        subtask_response = inject_event(
            InjectEventRequest(
                session_id=session_id,
                event_type="subtask_completed",
                payload={"summary": "First unresolved subtask done"},
            ),
            dependencies=deps,
        )
        assert subtask_response.followup_event_type == "subtask_implementation_requested"
        assert subtask_response.session.current_stage == "subtask_implementation_requested"

        graph_summary = get_subtask_graph(session_id, dependencies=deps)
        assert graph_summary.available
        assert graph_summary.completed_count == 1
        assert graph_summary.unresolved_count == 1
        assert [row.status for row in graph_summary.rows] == ["Ready for test", "To Do"]

        progress_summary = get_subtask_progress(session_id, dependencies=deps)
        assert progress_summary.available
        assert progress_summary.current_subtask_key == "IOS-52002"
        assert progress_summary.completed_count == 1
        assert progress_summary.remaining_count == 1
        assert [item.status for item in progress_summary.items] == ["completed", "assigned"]

        print(f"Subtask progression acceptance passed for session {session_id}.")


if __name__ == "__main__":
    main()
