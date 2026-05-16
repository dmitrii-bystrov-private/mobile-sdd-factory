#!/usr/bin/env python3
"""Validate two implementer rounds against one live local process host."""

from __future__ import annotations

from pathlib import Path
import tempfile
import time

from backend.api.routes_events import inject_event, list_events
from backend.api.routes_roles import collect_role_output
from backend.api.routes_sessions import create_session, prepare_session
from backend.api.schemas import (
    CollectRoleOutputRequest,
    CreateSessionRequest,
    InjectEventRequest,
    PrepareSessionRequest,
)
from backend.api.sse import SessionEventBus
from backend.coordinator.loop_runner import CoordinatorLoopRunner
from backend.coordinator.service import CoordinatorService
from backend.dependencies import AppDependencies
from backend.roles.contracts import DEFAULT_SESSION_ROLES, IMPLEMENTER_ROLE
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


def collect_until_output(
    session_id: int,
    role_name: str,
    *,
    dependencies: AppDependencies,
    target_stage: str,
    timeout_seconds: float = 2.0,
) -> tuple[object, list]:
    deadline = time.time() + timeout_seconds
    last_response = None
    while time.time() < deadline:
        response = collect_role_output(
            CollectRoleOutputRequest(
                session_id=session_id,
                role_name=role_name,
            ),
            dependencies=dependencies,
        )
        last_response = response
        if response.chunk_count > 0 and response.session.current_stage == target_stage:
            events_response = list_events(session_id=session_id, dependencies=dependencies)
            return response, events_response.items
        time.sleep(0.05)
    assert last_response is not None
    events_response = list_events(session_id=session_id, dependencies=dependencies)
    return last_response, events_response.items


def build_acceptance_dependencies(repo_root: Path, temp_root: Path) -> AppDependencies:
    database = Database(temp_root / "acceptance.sqlite3")
    database.initialize()

    session_repository = SessionRepository(database)
    role_repository = RoleRepository(database)
    event_repository = EventRepository(database)
    artifact_repository = ArtifactRepository(database)
    work_item_repository = WorkItemRepository(database)
    session_backend = TmuxSessionBackend(
        mode="process",
        runtime_root=temp_root / "workdir",
    )
    jira_adapter = FakeJiraAdapter(repo_root)
    snapshot_adapter = FakeSnapshotAdapter(repo_root, temp_root / "workdir")
    gitlab_adapter = FakeGitLabAdapter(repo_root)
    event_bus = SessionEventBus()
    fixture = (
        repo_root
        / "tests"
        / "backend"
        / "fixtures"
        / "persistent_echo_agent.py"
    )
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
            launcher_command=["python3", "-u", str(fixture)],
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
    with tempfile.TemporaryDirectory(prefix="sdd-factory-two-round-live-validation.") as temp_dir:
        temp_root = Path(temp_dir)
        deps = build_acceptance_dependencies(repo_root=repo_root, temp_root=temp_root)

        task_key = "IOS-ACCEPT-LIVE-TWO-ROUND-001"
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

        prepare_response = prepare_session(
            PrepareSessionRequest(task_key=task_key),
            dependencies=deps,
        )
        assert prepare_response.followup_event_type == "implementation_requested"

        implementer_role = deps.role_repository.get_by_name(session_id, IMPLEMENTER_ROLE)
        runtime_handle = implementer_role.runtime_handle
        assert runtime_handle is not None

        first_collect, _ = collect_until_output(
            session_id=session_id,
            role_name=IMPLEMENTER_ROLE,
            dependencies=deps,
            target_stage="verification_requested",
        )
        assert first_collect.chunk_count > 0
        assert first_collect.session.current_stage == "verification_requested"
        assert first_collect.event_type == "role_output_collected"

        inject_event(
            InjectEventRequest(
                session_id=session_id,
                event_type="verification_failed",
                payload={"summary": "verification failed", "failures": ["lint"]},
            ),
            dependencies=deps,
        )

        second_collect, _ = collect_until_output(
            session_id=session_id,
            role_name=IMPLEMENTER_ROLE,
            dependencies=deps,
            target_stage="verification_requested",
        )
        assert second_collect.chunk_count > 0
        assert second_collect.session.current_stage == "verification_requested"
        assert second_collect.event_type == "role_output_collected"

        sent_inputs = deps.session_backend.get_sent_inputs(runtime_handle)
        assert len(sent_inputs) == 2
        assert "Start implementation work for IOS-ACCEPT-LIVE-TWO-ROUND-001." in sent_inputs[0]
        assert "Apply verification corrections for IOS-ACCEPT-LIVE-TWO-ROUND-001." in sent_inputs[1]

        events_response = list_events(session_id=session_id, dependencies=deps)
        event_types = [item.event_type for item in events_response.items]
        assert event_types.count("implementation_completed") == 2
        assert event_types.count("verification_requested") == 2
        assert "verification_failed" in event_types

        print(f"Implementer two-round live validation passed for session {session_id}.")


if __name__ == "__main__":
    main()
