#!/usr/bin/env python3
"""Run story-subtask acceptance through the operator route layer without binding a port."""

from __future__ import annotations

from pathlib import Path

from backend.api.routes_events import inject_event, list_events
from backend.api.routes_operator import create_subtasks_from_plan
from backend.api.routes_operator import resume_session
from backend.api.routes_roles import submit_role_output
from backend.api.routes_sessions import create_session, prepare_session
from backend.api.schemas import (
    CreateSubtasksFromPlanRequest,
    CreateSessionRequest,
    InjectEventRequest,
    PrepareSessionRequest,
    ResumeSessionRequest,
    RoleOutputRequest,
)
from backend.api.sse import SessionEventBus
from backend.coordinator.loop_runner import CoordinatorLoopRunner
from backend.coordinator.service import CoordinatorService
from backend.dependencies import AppDependencies
from backend.roles.contracts import DEFAULT_SESSION_ROLES
from backend.roles.launcher import RoleLauncherManager
from backend.roles.workspace import RoleWorkspaceManager
from backend.session_backend.recording_backend import RecordingSessionBackend
from backend.state.artifact_repository import ArtifactRepository
from backend.state.db import Database
from backend.state.event_repository import EventRepository
from backend.state.role_repository import RoleRepository
from backend.state.session_repository import SessionRepository
from backend.state.work_item_repository import WorkItemRepository
from backend.tools.fake_adapters import FakeGitLabAdapter, FakeJiraAdapter, FakeSnapshotAdapter
from run_roots import managed_run_root


def build_acceptance_dependencies(repo_root: Path, temp_root: Path) -> AppDependencies:
    database = Database(temp_root / "acceptance.sqlite3")
    database.initialize()

    session_repository = SessionRepository(database)
    role_repository = RoleRepository(database)
    event_repository = EventRepository(database)
    artifact_repository = ArtifactRepository(database)
    work_item_repository = WorkItemRepository(database)
    session_backend = RecordingSessionBackend()
    jira_adapter = FakeJiraAdapter(repo_root)
    snapshot_adapter = FakeSnapshotAdapter(repo_root, temp_root / "workdir")
    gitlab_adapter = FakeGitLabAdapter(repo_root)
    event_bus = SessionEventBus()
    coordinator_service = CoordinatorService(
        session_repository=session_repository,
        role_repository=role_repository,
        event_repository=event_repository,
        artifact_repository=artifact_repository,
        work_item_repository=work_item_repository,
        session_backend=session_backend,
        default_roles=DEFAULT_SESSION_ROLES,
        jira_adapter=jira_adapter,
        snapshot_adapter=snapshot_adapter,
        gitlab_adapter=gitlab_adapter,
        artifacts_root=temp_root / "workdir" / "factory-artifacts",
        workdir_root=temp_root / "workdir",
        event_bus=event_bus,
        role_workspace_manager=RoleWorkspaceManager(
            runtime_root=temp_root / "workdir",
            repo_root=repo_root,
            workdir_root=temp_root / "workdir",
        ),
        role_launcher_manager=RoleLauncherManager(
            repo_root=repo_root,
            workdir_root=temp_root / "workdir",
        ),
    )
    loop_runner = CoordinatorLoopRunner(
        callback=coordinator_service.run_loop_once,
        interval_seconds=1.0,
    )
    return AppDependencies(
        config=None,  # type: ignore[arg-type]
        database=database,
        session_repository=session_repository,
        role_repository=role_repository,
        event_repository=event_repository,
        artifact_repository=artifact_repository,
        work_item_repository=work_item_repository,
        session_backend=session_backend,
        jira_adapter=jira_adapter,
        snapshot_adapter=snapshot_adapter,
        gitlab_adapter=gitlab_adapter,
        event_bus=event_bus,
        loop_runner=loop_runner,
        coordinator_service=coordinator_service,
    )


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    with managed_run_root(repo_root, "sdd-factory-story-subtasks-acceptance") as temp_root:
        deps = build_acceptance_dependencies(repo_root=repo_root, temp_root=temp_root)

        create_response = create_session(
            CreateSessionRequest(
                task_key="IOS-ACCEPT-STORY-001",
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

        prepare_response = prepare_session(
            PrepareSessionRequest(task_key="IOS-ACCEPT-STORY-001"),
            dependencies=deps,
        )
        assert prepare_response.followup_event_type == "proposal_context_requested"

        statuses_path = temp_root / "workdir" / "IOS-ACCEPT-STORY-001" / "statuses.md"
        statuses_path.write_text(
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-ACCEPT-STORY-001 | Story | Parent story | In Progress |
| IOS-51001 | Sub-task | Build data layer | To Do |
| IOS-51002 | Sub-task | Final polish | Ready for test |
"""
        )

        inject_event(
            InjectEventRequest(
                session_id=session_id,
                event_type="proposal_context_completed",
                payload={"summary": "Context prepared"},
            ),
            dependencies=deps,
        )
        inject_event(
            InjectEventRequest(
                session_id=session_id,
                event_type="requirements_completed",
                payload={"summary": "Requirements clarified"},
            ),
            dependencies=deps,
        )
        inject_event(
            InjectEventRequest(
                session_id=session_id,
                event_type="acceptance_criteria_completed",
                payload={"summary": "Acceptance prepared"},
            ),
            dependencies=deps,
        )
        inject_event(
            InjectEventRequest(
                session_id=session_id,
                event_type="constraints_completed",
                payload={"summary": "Constraints prepared"},
            ),
            dependencies=deps,
        )
        inject_event(
            InjectEventRequest(
                session_id=session_id,
                event_type="spec_verification_completed",
                payload={"summary": "Planning verified"},
            ),
            dependencies=deps,
        )
        inject_event(
            InjectEventRequest(
                session_id=session_id,
                event_type="story_spec_completed",
                payload={"summary": "Implementation structure prepared"},
            ),
            dependencies=deps,
        )
        decomposition_response = inject_event(
            InjectEventRequest(
                session_id=session_id,
                event_type="task_decomposition_completed",
                payload={
                    "summary": "Execution chunks prepared",
                    "task_breakdown": "Data layer first, then UI polish",
                    "plan_index_markdown": (
                        "# Execution Task List\n\n"
                        "| # | Task | Depends on | Status |\n"
                        "|---|------|------------|--------|\n"
                        "| 01 | [Build data layer](./01-build-data-layer.md) | — | ☐ |\n"
                    ),
                    "plan_task_files": [
                        {
                            "filename": "01-build-data-layer.md",
                            "content": (
                                "# Build data layer\n\n"
                                "## What to implement\n"
                                "Finish the data layer work for the story.\n"
                            ),
                        }
                    ],
                },
            ),
            dependencies=deps,
        )
        assert decomposition_response.followup_event_type == "subtask_implementation_requested"
        assert decomposition_response.session.current_stage == "subtask_implementation_requested"

        subtask_response = inject_event(
            InjectEventRequest(
                session_id=session_id,
                event_type="subtask_completed",
                payload={"summary": "First unresolved subtask done"},
            ),
            dependencies=deps,
        )
        assert subtask_response.followup_event_type == "verification_requested"
        assert subtask_response.session.current_stage == "verification_requested"

        verification_response = submit_role_output(
            RoleOutputRequest(
                session_id=session_id,
                role_name="verification-coordinator",
                output_type="passed",
                payload={"summary": "verification passed", "result": "passed"},
            ),
            dependencies=deps,
        )
        assert verification_response.followup_event_type == "send_to_test_completed"
        assert verification_response.session.status == "completed"

        events_response = list_events(session_id=session_id, dependencies=deps)
        assert [item.event_type for item in events_response.items] == [
            "task_started",
            "task_session_reused",
            "task_prepared",
            "role_input_dispatched",
            "proposal_context_requested",
            "proposal_context_completed",
            "role_input_dispatched",
            "requirements_requested",
            "requirements_completed",
            "role_input_dispatched",
            "acceptance_criteria_requested",
            "acceptance_criteria_completed",
            "role_input_dispatched",
            "constraints_requested",
            "constraints_completed",
            "role_input_dispatched",
            "spec_verification_requested",
            "spec_verification_completed",
            "role_input_dispatched",
            "story_spec_requested",
            "story_spec_completed",
            "role_input_dispatched",
            "task_decomposition_requested",
            "task_decomposition_completed",
            "role_input_dispatched",
            "implementation_requested",
            "jira_subtasks_created",
            "subtask_graph_requested",
            "role_input_dispatched",
            "subtask_implementation_requested",
            "subtask_completed",
            "subtask_snapshot_refreshed",
            "role_input_dispatched",
            "verification_requested",
            "verification_passed",
            "task_completed",
            "mr_handoff_completed",
            "send_to_test_completed",
        ]

        print(f"Story subtask operator acceptance passed for session {session_id}.")


if __name__ == "__main__":
    main()
