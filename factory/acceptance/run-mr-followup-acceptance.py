#!/usr/bin/env python3
"""Run MR follow-up acceptance through the operator route layer without binding a port."""

from __future__ import annotations

from pathlib import Path

from backend.api.routes_artifacts import list_artifacts
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
from backend.api.sse import SessionEventBus
from backend.coordinator.loop_runner import CoordinatorLoopRunner
from backend.coordinator.service import CoordinatorService
from backend.dependencies import AppDependencies
from backend.roles.contracts import DEFAULT_SESSION_ROLES, IMPLEMENTER_ROLE, MR_COMMENTS_ANALYST_ROLE
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
    with managed_run_root(repo_root, "sdd-factory-mr-followup-acceptance") as temp_root:
        deps = build_acceptance_dependencies(repo_root=repo_root, temp_root=temp_root)

        create_response = create_session(
            CreateSessionRequest(
                task_key="IOS-ACCEPT-MR-001",
                workflow_profile="oneshot",
                policy={
                    "self_review_policy": "required",
                    "boy_scout_policy": "disabled",
                    "doc_harvest_policy": "disabled",
                },
            ),
            dependencies=deps,
        )
        session_id = create_response.session.id

        prepare_response = prepare_session(
            PrepareSessionRequest(task_key="IOS-ACCEPT-MR-001"),
            dependencies=deps,
        )
        assert prepare_response.followup_event_type == "implementation_requested"

        implementation_response = submit_role_output(
            RoleOutputRequest(
                session_id=session_id,
                role_name="implementer",
                output_type="completed",
                payload={"summary": "implementation done"},
            ),
            dependencies=deps,
        )
        assert implementation_response.followup_event_type == "self_review_requested"

        review_response = submit_role_output(
            RoleOutputRequest(
                session_id=session_id,
                role_name="code-reviewer",
                output_type="passed",
                payload={"summary": "clean review"},
            ),
            dependencies=deps,
        )
        assert review_response.followup_event_type == "verification_requested"

        verification_passed_response = submit_role_output(
            RoleOutputRequest(
                session_id=session_id,
                role_name="verification-coordinator",
                output_type="passed",
                payload={"summary": "verification passed"},
            ),
            dependencies=deps,
        )
        assert verification_passed_response.followup_event_type == "send_to_test_completed"
        assert verification_passed_response.session.status == "completed"

        mr_followup_response = ingest_mr_comments(
            IngestMrCommentsRequest(
                session_id=session_id,
                platform="ios",
                mr_id="2942",
            ),
            dependencies=deps,
        )
        assert mr_followup_response.event_type == "mr_comments_received"
        assert mr_followup_response.followup_event_type == "mr_comments_analysis_requested"
        assert mr_followup_response.session.current_stage == "mr_comments_analysis_requested"
        assert mr_followup_response.session.status == "active"
        assert mr_followup_response.discussion_count == 1
        plan_dir = temp_root / "workdir" / "IOS-ACCEPT-MR-001" / "plan"
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / "index.md").write_text(
            "# Execution Task List\n\n"
            "| # | Task | Depends on | Status |\n"
            "|---|------|------------|--------|\n"
            "| 01 | [Address MR feedback](./01-address-mr-feedback.md) | — | ☐ |\n"
        )
        (plan_dir / "01-address-mr-feedback.md").write_text(
            "# Address MR feedback\n\n"
            "## What to implement\n"
            "Apply the grouped MR follow-up changes.\n"
        )

        analysis_response = submit_role_output(
            RoleOutputRequest(
                session_id=session_id,
                role_name=MR_COMMENTS_ANALYST_ROLE,
                output_type="completed",
                payload={"summary": "Grouped MR comments into actionable follow-up themes."},
            ),
            dependencies=deps,
        )
        assert analysis_response.followup_event_type == "mr_followup_requested"
        assert analysis_response.session.current_stage == "mr_followup_requested"
        assert analysis_response.session.current_owner == IMPLEMENTER_ROLE

        followup_response = submit_role_output(
            RoleOutputRequest(
                session_id=session_id,
                role_name=IMPLEMENTER_ROLE,
                output_type="completed",
                payload={"summary": "mr follow-up done"},
            ),
            dependencies=deps,
        )
        assert followup_response.followup_event_type == "verification_requested"

        final_verification_response = submit_role_output(
            RoleOutputRequest(
                session_id=session_id,
                role_name="verification-coordinator",
                output_type="passed",
                payload={"summary": "verification passed after mr follow-up"},
            ),
            dependencies=deps,
        )
        assert final_verification_response.followup_event_type == "send_to_test_completed"
        assert final_verification_response.session.status == "completed"

        events_response = list_events(session_id=session_id, dependencies=deps)
        assert [item.event_type for item in events_response.items] == [
            "task_started",
            "task_session_reused",
            "task_prepared",
            "role_input_dispatched",
            "implementation_requested",
            "implementation_completed",
            "role_input_dispatched",
            "self_review_requested",
            "self_review_passed",
            "role_input_dispatched",
            "verification_requested",
            "verification_passed",
            "task_completed",
            "mr_handoff_completed",
            "send_to_test_completed",
            "mr_comments_received",
            "role_input_dispatched",
            "mr_comments_analysis_requested",
            "mr_comments_analysis_completed",
            "jira_subtasks_created",
            "role_input_dispatched",
            "mr_followup_requested",
            "implementation_completed",
            "role_input_dispatched",
            "verification_requested",
            "verification_passed",
            "task_completed",
            "mr_handoff_completed",
            "send_to_test_completed",
        ]

        artifacts_response = list_artifacts(session_id=session_id, dependencies=deps)
        artifact_types = [item.artifact_type for item in artifacts_response.items]
        assert "jira_subtasks_summary" in artifact_types
        assert "mr_comments_markdown" in artifact_types
        assert "role_prompt" in artifact_types
        assert "role_output_summary" in artifact_types

        print(f"MR follow-up operator acceptance passed for session {session_id}.")


if __name__ == "__main__":
    main()
