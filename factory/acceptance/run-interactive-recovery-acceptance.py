#!/usr/bin/env python3
"""Acceptance harness for interactive operator-assisted continuation."""

from __future__ import annotations

from pathlib import Path
import tempfile
import time

from backend.api.routes_operator import send_runtime_input
from backend.api.routes_roles import collect_role_output
from backend.api.routes_sessions import create_session, get_interactive_state, prepare_session
from backend.api.schemas import (
    CollectRoleOutputRequest,
    CreateSessionRequest,
    PrepareSessionRequest,
    SendOperatorRuntimeInputRequest,
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


def build_dependencies(repo_root: Path, temp_root: Path, fixture: Path) -> AppDependencies:
    database = Database(temp_root / "acceptance.sqlite3")
    database.initialize()

    session_repository = SessionRepository(database)
    role_repository = RoleRepository(database)
    event_repository = EventRepository(database)
    artifact_repository = ArtifactRepository(database)
    work_item_repository = WorkItemRepository(database)
    session_backend = TmuxSessionBackend(mode="pty", runtime_root=temp_root / "workdir")
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
    fixture = repo_root / "tests" / "backend" / "fixtures" / "interactive_recovery_fixture.py"
    with tempfile.TemporaryDirectory(prefix="sdd-factory-interactive-recovery-acceptance.") as temp_dir:
        temp_root = Path(temp_dir)
        deps = build_dependencies(repo_root, temp_root, fixture)

        create_response = create_session(
            CreateSessionRequest(
                task_key="IOS-ACCEPT-INTERACTIVE-001",
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
            PrepareSessionRequest(task_key="IOS-ACCEPT-INTERACTIVE-001"),
            dependencies=deps,
        )
        assert prepare_response.followup_event_type == "implementation_requested"

        blocker_response = None
        for _ in range(24):
            blocker_response = collect_role_output(
                CollectRoleOutputRequest(
                    session_id=session_id,
                    role_name=IMPLEMENTER_ROLE,
                ),
                dependencies=deps,
            )
            if blocker_response.session.status == "waiting_for_operator":
                break
            time.sleep(0.2)
        assert blocker_response is not None
        assert blocker_response.session.status == "waiting_for_operator"

        interactive_before = get_interactive_state(session_id, dependencies=deps)
        assert interactive_before.available
        assert interactive_before.role_name == IMPLEMENTER_ROLE
        assert interactive_before.needs_operator_input

        send_response = send_runtime_input(
            SendOperatorRuntimeInputRequest(
                session_id=session_id,
                text="/mcp",
            ),
            dependencies=deps,
        )
        assert send_response.sent
        assert send_response.session.status == "active"

        post_input_response = collect_role_output(
            CollectRoleOutputRequest(
                session_id=session_id,
                role_name=IMPLEMENTER_ROLE,
            ),
            dependencies=deps,
        )
        assert post_input_response.session.status == "active"

        interactive_after = get_interactive_state(session_id, dependencies=deps)
        assert not interactive_after.available
        assert not interactive_after.needs_operator_input

        print(f"Interactive continuation acceptance passed for session {session_id}.")


if __name__ == "__main__":
    main()
