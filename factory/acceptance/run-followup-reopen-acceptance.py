#!/usr/bin/env python3
"""Run follow-up reopen acceptance through the operator route layer without binding a port."""

from __future__ import annotations

from pathlib import Path
import tempfile

from backend.api.routes_artifacts import list_artifacts
from backend.api.routes_events import inject_event, list_events
from backend.api.routes_operator import reopen_from_qa
from backend.api.routes_roles import submit_role_output
from backend.api.routes_sessions import create_session, prepare_session
from backend.api.schemas import (
    CreateSessionRequest,
    InjectEventRequest,
    PrepareSessionRequest,
    ReopenFromQaRequest,
    RoleOutputRequest,
)
from backend.api.sse import SessionEventBus
from backend.coordinator.loop_runner import CoordinatorLoopRunner
from backend.coordinator.service import CoordinatorService
from backend.dependencies import AppDependencies
from backend.roles.contracts import DEFAULT_SESSION_ROLES
from backend.roles.launcher import RoleLauncherManager
from backend.roles.workspace import RoleWorkspaceManager
from backend.session_backend.tmux_backend import TmuxSessionBackend
from backend.state.artifact_repository import ArtifactRepository
from backend.state.db import Database
from backend.state.event_repository import EventRepository
from backend.state.role_repository import RoleRepository
from backend.state.session_repository import SessionRepository
from backend.state.work_item_repository import WorkItemRepository
from backend.tools.fake_adapters import FakeGitLabAdapter, FakeJiraAdapter, FakeSnapshotAdapter


def build_acceptance_dependencies(repo_root: Path, temp_root: Path) -> AppDependencies:
    database = Database(temp_root / "acceptance.sqlite3")
    database.initialize()

    session_repository = SessionRepository(database)
    role_repository = RoleRepository(database)
    event_repository = EventRepository(database)
    artifact_repository = ArtifactRepository(database)
    work_item_repository = WorkItemRepository(database)
    session_backend = TmuxSessionBackend(
        mode="recording",
        runtime_root=temp_root / "runtime",
    )
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
        knowledge_root=repo_root / "knowledge",
        event_bus=event_bus,
        role_workspace_manager=RoleWorkspaceManager(
            runtime_root=temp_root / "runtime",
            repo_root=repo_root,
            workdir_root=temp_root / "workdir",
        ),
        role_launcher_manager=RoleLauncherManager(repo_root=repo_root),
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
    with tempfile.TemporaryDirectory(prefix="sdd-factory-followup-acceptance.") as temp_dir:
        deps = build_acceptance_dependencies(repo_root=repo_root, temp_root=Path(temp_dir))

        create_response = create_session(
            CreateSessionRequest(
                task_key="IOS-ACCEPT-REOPEN-001",
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
            PrepareSessionRequest(task_key="IOS-ACCEPT-REOPEN-001"),
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
        assert verification_passed_response.followup_event_type == "task_completed"
        assert verification_passed_response.session.status == "completed"

        reopen_response = reopen_from_qa(
            ReopenFromQaRequest(
                session_id=session_id,
                comment_text="QA: still failing on edge case",
            ),
            dependencies=deps,
        )
        assert reopen_response.event_type == "qa_reopened"
        assert reopen_response.followup_event_type == "qa_reopen_requested"
        assert reopen_response.session.current_stage == "qa_reopen_requested"
        assert reopen_response.session.status == "active"

        followup_response = inject_event(
            InjectEventRequest(
                session_id=session_id,
                event_type="implementation_completed",
                payload={"summary": "qa fix done"},
            ),
            dependencies=deps,
        )
        assert followup_response.followup_event_type == "verification_requested"

        final_verification_response = submit_role_output(
            RoleOutputRequest(
                session_id=session_id,
                role_name="verification-coordinator",
                output_type="passed",
                payload={"summary": "verification passed after qa reopen"},
            ),
            dependencies=deps,
        )
        assert final_verification_response.followup_event_type == "task_completed"
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
            "qa_reopened",
            "role_input_dispatched",
            "qa_reopen_requested",
            "implementation_completed",
            "role_input_dispatched",
            "verification_requested",
            "verification_passed",
            "task_completed",
        ]

        artifacts_response = list_artifacts(session_id=session_id, dependencies=deps)
        artifact_types = [item.artifact_type for item in artifacts_response.items]
        assert "qa_reopen_comments" in artifact_types
        assert "role_prompt" in artifact_types
        assert "role_output_summary" in artifact_types

        print(f"Follow-up reopen operator acceptance passed for session {session_id}.")


if __name__ == "__main__":
    main()
