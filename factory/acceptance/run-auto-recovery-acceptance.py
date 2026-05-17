#!/usr/bin/env python3
"""Validate automatic runtime recovery for an unexpectedly dead owner role."""

from __future__ import annotations

from pathlib import Path
import time

from backend.api.routes_events import list_events
from backend.api.routes_roles import collect_role_output
from backend.api.routes_sessions import create_session, prepare_session
from backend.api.schemas import CollectRoleOutputRequest, CreateSessionRequest, PrepareSessionRequest
from backend.roles.contracts import DEFAULT_SESSION_ROLES, IMPLEMENTER_ROLE
from backend.roles.launcher import RoleLauncherManager
from backend.roles.workspace import RoleWorkspaceManager
from backend.session_backend.runtime_models import RuntimeRoleHandle
from backend.session_backend.tmux_backend import TmuxSessionBackend
from backend.state.artifact_repository import ArtifactRepository
from backend.state.db import Database
from backend.state.event_repository import EventRepository
from backend.state.role_repository import RoleRepository
from backend.state.session_repository import SessionRepository
from backend.state.work_item_repository import WorkItemRepository
from backend.tools.fake_adapters import FakeGitLabAdapter, FakeJiraAdapter, FakeSnapshotAdapter
from backend.api.sse import SessionEventBus
from backend.coordinator.loop_runner import CoordinatorLoopRunner
from backend.coordinator.service import CoordinatorService
from backend.dependencies import AppDependencies
from run_roots import managed_run_root, run_tmux_socket_root, shutdown_dependencies


def build_acceptance_dependencies(repo_root: Path, temp_root: Path) -> AppDependencies:
    database = Database(temp_root / "acceptance.sqlite3")
    database.initialize()

    session_repository = SessionRepository(database)
    role_repository = RoleRepository(database)
    event_repository = EventRepository(database)
    artifact_repository = ArtifactRepository(database)
    work_item_repository = WorkItemRepository(database)
    session_backend = TmuxSessionBackend(
        mode="tmux",
        runtime_root=temp_root / "workdir",
        socket_root=run_tmux_socket_root(temp_root),
    )
    jira_adapter = FakeJiraAdapter(repo_root)
    snapshot_adapter = FakeSnapshotAdapter(repo_root, temp_root / "workdir")
    gitlab_adapter = FakeGitLabAdapter(repo_root)
    event_bus = SessionEventBus()
    fixture = repo_root / "tests" / "backend" / "fixtures" / "persistent_echo_agent.py"
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


def wait_for_stage(
    session_id: int,
    role_name: str,
    *,
    dependencies: AppDependencies,
    target_stage: str,
    timeout_seconds: float = 20.0,
) -> object:
    deadline = time.time() + timeout_seconds
    last_response = None
    while time.time() < deadline:
        dependencies.loop_runner.run_once()
        response = collect_role_output(
            CollectRoleOutputRequest(
                session_id=session_id,
                role_name=role_name,
            ),
            dependencies=dependencies,
        )
        last_response = response
        if response.session.current_stage == target_stage:
            return response
        time.sleep(0.1)
    assert last_response is not None
    return last_response


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    with managed_run_root(repo_root, "sdd-factory-auto-recovery-acceptance") as temp_root:
        deps = build_acceptance_dependencies(repo_root=repo_root, temp_root=temp_root)

        task_key = f"IOS-ACCEPT-AUTO-RECOVERY-{temp_root.name.split('.')[-1].upper()}"
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
        assert implementer_role is not None
        old_handle = implementer_role.runtime_handle
        assert old_handle is not None

        deps.session_backend.stop_role(
            RuntimeRoleHandle(
                role_id=old_handle,
                session_id=old_handle.split(":", 1)[0],
                backend_name=implementer_role.runtime_backend,
            )
        )

        response = wait_for_stage(
            session_id=session_id,
            role_name=IMPLEMENTER_ROLE,
            dependencies=deps,
            target_stage="verification_requested",
        )
        assert response.session.current_stage == "verification_requested"

        refreshed_role = deps.role_repository.get_by_name(session_id, IMPLEMENTER_ROLE)
        assert refreshed_role is not None
        assert refreshed_role.runtime_handle is not None
        assert refreshed_role.status.value == "running"

        events = list_events(session_id=session_id, dependencies=deps).items
        event_types = [item.event_type for item in events]
        assert "runtime_role_auto_recovery_attempted" in event_types
        assert "role_input_dispatched" in event_types
        assert "implementation_completed" in event_types

        shutdown_dependencies(deps)
        print(f"Automatic runtime recovery acceptance passed for session {session_id}.")


if __name__ == "__main__":
    main()
