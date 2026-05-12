"""Top-level coordinator facade."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json

from backend.coordinator.artifacts import write_text_artifact
from backend.coordinator.intake import IntakeError, classify_task_readiness
from backend.coordinator.hydration import build_role_hydration
from backend.models.event import Event
from backend.models.enums import RoleStatus, SessionStatus, WorkItemStatus
from backend.models.session import Session
from backend.roles.contracts import IMPLEMENTER_ROLE, VERIFICATION_COORDINATOR_ROLE
from backend.session_backend.base import SessionBackend
from backend.state.artifact_repository import ArtifactRepository
from backend.state.event_repository import EventRepository
from backend.state.role_repository import RoleRepository
from backend.state.session_repository import SessionRepository
from backend.state.work_item_repository import WorkItemRepository
from backend.tools.jira_adapter import JiraAdapter
from backend.tools.snapshot_adapter import SnapshotAdapter


@dataclass
class CoordinatorService:
    """Entry point for coordinator-owned use cases."""

    session_repository: SessionRepository
    role_repository: RoleRepository
    event_repository: EventRepository
    artifact_repository: ArtifactRepository
    work_item_repository: WorkItemRepository
    session_backend: SessionBackend
    default_roles: list[str]
    jira_adapter: JiraAdapter | None = None
    snapshot_adapter: SnapshotAdapter | None = None
    artifacts_root: Path | None = None

    def create_task_session(self, task_key: str) -> tuple[Session, Event, bool]:
        """Create or reuse a task session and emit the initial session event."""

        existing = self.session_repository.get_by_task_key(task_key)
        if existing is not None:
            event = self.event_repository.append(
                session_id=existing.id,
                event_type="task_session_reused",
                producer_type="coordinator",
                payload={
                    "task_key": task_key,
                    "current_stage": existing.current_stage,
                },
            )
            return existing, event, False

        session = self.session_repository.create(task_key=task_key, current_stage="intake")
        runtime_session = self.session_backend.create_task_session(task_key)
        for role_name in self.default_roles:
            runtime_role = self.session_backend.spawn_role(runtime_session, role_name)
            self.role_repository.create(
                session_id=session.id,
                role_name=role_name,
                runtime_backend=runtime_role.backend_name,
                runtime_handle=runtime_role.role_id,
                status=RoleStatus.RUNNING,
            )
        session = self.session_repository.update_status(session.id, SessionStatus.ACTIVE)
        event = self.event_repository.append(
            session_id=session.id,
            event_type="task_started",
            producer_type="coordinator",
            payload={
                "task_key": task_key,
                "current_stage": session.current_stage,
                "runtime_session_id": runtime_session.session_id,
                "roles": self.default_roles,
            },
        )
        return session, event, True

    def prepare_task_session(
        self, raw_task_key: str
    ) -> tuple[Session, Event, bool, dict[str, str | int | None]]:
        """Run deterministic intake/setup for a task session."""

        if self.jira_adapter is None or self.snapshot_adapter is None or self.artifacts_root is None:
            raise IntakeError("Coordinator is missing intake adapters or artifact root")

        parent_result = self.jira_adapter.resolve_parent(raw_task_key)
        if not parent_result.ok:
            raise IntakeError(parent_result.stderr or parent_result.stdout or "Failed to resolve parent task")
        resolved_task_key = parent_result.stdout.strip()
        if not resolved_task_key:
            raise IntakeError("Parent task resolution returned an empty key")

        issue_type_result = self.jira_adapter.get_issue_type(resolved_task_key)
        if not issue_type_result.ok:
            raise IntakeError(issue_type_result.stderr or issue_type_result.stdout or "Failed to resolve issue type")
        issue_type = issue_type_result.stdout.strip()
        if not issue_type:
            raise IntakeError("Issue type resolution returned an empty value")

        readiness = classify_task_readiness(resolved_task_key, issue_type)
        session, _, created = self.create_task_session(resolved_task_key)

        snapshot_result = self.snapshot_adapter.run(resolved_task_key)
        stdout_path = write_text_artifact(
            self.artifacts_root,
            resolved_task_key,
            "intake",
            "snapshot.stdout.log",
            snapshot_result.stdout,
        )
        stderr_path = write_text_artifact(
            self.artifacts_root,
            resolved_task_key,
            "intake",
            "snapshot.stderr.log",
            snapshot_result.stderr,
        )
        self.artifact_repository.create(
            session_id=session.id,
            stage_name="intake",
            artifact_type="snapshot_stdout",
            path=str(stdout_path),
            metadata={"task_key": resolved_task_key, "command": snapshot_result.command},
        )
        self.artifact_repository.create(
            session_id=session.id,
            stage_name="intake",
            artifact_type="snapshot_stderr",
            path=str(stderr_path),
            metadata={"task_key": resolved_task_key, "command": snapshot_result.command},
        )

        event_type = "task_prepared"
        if snapshot_result.returncode != 0:
            event_type = "task_preparation_failed"

        event = self.event_repository.append(
            session_id=session.id,
            event_type=event_type,
            producer_type="coordinator",
            payload={
                "raw_task_key": raw_task_key,
                "resolved_task_key": resolved_task_key,
                "issue_type": issue_type,
                "readiness": readiness,
                "snapshot_exit_code": snapshot_result.returncode,
            },
        )
        details = {
            "resolved_task_key": resolved_task_key,
            "issue_type": issue_type,
            "readiness": readiness,
            "snapshot_exit_code": snapshot_result.returncode,
            "followup_event_type": None,
        }
        if snapshot_result.ok and readiness == "ready_for_execution":
            details["followup_event_type"] = self._enqueue_initial_implementation(
                session=session,
                resolved_task_key=resolved_task_key,
                source_event=event,
            ).event_type
        return session, event, created, details

    def handle_operator_event(
        self,
        session_id: int,
        event_type: str,
        payload: dict,
    ) -> tuple[Session, Event | None]:
        session = self._get_session_or_raise(session_id)
        accepted_event = self.event_repository.append(
            session_id=session_id,
            event_type=event_type,
            producer_type="operator",
            payload=payload,
        )
        if event_type == "implementation_completed":
            session, followup_event = self._handle_implementation_completed(session, accepted_event)
            return session, followup_event
        return session, None

    def _enqueue_initial_implementation(
        self,
        session: Session,
        resolved_task_key: str,
        source_event: Event,
    ) -> Event:
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        if implementer_role is None:
            raise IntakeError("Implementer role is missing for the session")

        work_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="implementation",
            title=f"Initial implementation for {resolved_task_key}",
            owner_role_id=implementer_role.id,
            source_event_id=source_event.id,
            priority=100,
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="implementation_requested",
            current_owner=IMPLEMENTER_ROLE,
        )
        hydration = build_role_hydration(
            role_name=IMPLEMENTER_ROLE,
            task_key=resolved_task_key,
            current_stage=session.current_stage,
            active_work_item=work_item,
        )
        hydration_path = write_text_artifact(
            self.artifacts_root,
            resolved_task_key,
            "implementation_requested",
            "implementer.hydration.json",
            json.dumps(hydration, indent=2, sort_keys=True),
        )
        self.artifact_repository.create(
            session_id=session.id,
            role_id=implementer_role.id,
            stage_name="implementation_requested",
            artifact_type="hydration_payload",
            path=str(hydration_path),
            metadata={"role_name": IMPLEMENTER_ROLE, "work_item_id": work_item.id},
        )
        return self.event_repository.append(
            session_id=session.id,
            event_type="implementation_requested",
            producer_type="coordinator",
            payload={
                "task_key": resolved_task_key,
                "role_name": IMPLEMENTER_ROLE,
                "work_item_id": work_item.id,
                "current_stage": session.current_stage,
            },
        )

    def _handle_implementation_completed(
        self,
        session: Session,
        source_event: Event,
    ) -> tuple[Session, Event]:
        implementation_items = [
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "implementation" and item.status != WorkItemStatus.COMPLETED
        ]
        if not implementation_items:
            raise IntakeError("No active implementation work item found for the session")

        active_item = implementation_items[0]
        self.work_item_repository.update_status(active_item.id, WorkItemStatus.COMPLETED)

        verification_role = self.role_repository.get_by_name(session.id, VERIFICATION_COORDINATOR_ROLE)
        if verification_role is None:
            raise IntakeError("Verification coordinator role is missing for the session")

        verification_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="verification",
            title=f"Verification for {session.task_key}",
            owner_role_id=verification_role.id,
            source_event_id=source_event.id,
            priority=90,
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="verification_requested",
            current_owner=VERIFICATION_COORDINATOR_ROLE,
        )
        hydration = build_role_hydration(
            role_name=VERIFICATION_COORDINATOR_ROLE,
            task_key=session.task_key,
            current_stage=session.current_stage,
            active_work_item=verification_item,
        )
        hydration_path = write_text_artifact(
            self.artifacts_root,
            session.task_key,
            "verification_requested",
            "verification-coordinator.hydration.json",
            json.dumps(hydration, indent=2, sort_keys=True),
        )
        self.artifact_repository.create(
            session_id=session.id,
            role_id=verification_role.id,
            stage_name="verification_requested",
            artifact_type="hydration_payload",
            path=str(hydration_path),
            metadata={
                "role_name": VERIFICATION_COORDINATOR_ROLE,
                "work_item_id": verification_item.id,
            },
        )
        event = self.event_repository.append(
            session_id=session.id,
            event_type="verification_requested",
            producer_type="coordinator",
            payload={
                "task_key": session.task_key,
                "role_name": VERIFICATION_COORDINATOR_ROLE,
                "work_item_id": verification_item.id,
                "current_stage": session.current_stage,
            },
        )
        return session, event

    def _get_session_or_raise(self, session_id: int) -> Session:
        for session in self.session_repository.list_all():
            if session.id == session_id:
                return session
        raise IntakeError(f"Session {session_id} was not found")
