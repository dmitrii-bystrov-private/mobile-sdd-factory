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
from backend.models.role import Role
from backend.models.work_item import WorkItem
from backend.roles.prompts import role_handoff_prompt
from backend.roles.contracts import IMPLEMENTER_ROLE, VERIFICATION_COORDINATOR_ROLE
from backend.session_backend.base import SessionBackend
from backend.session_backend.runtime_models import RuntimeOutputChunk, RuntimeRoleHandle
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
        if event_type == "verification_failed":
            session, followup_event = self._handle_verification_failed(session, accepted_event)
            return session, followup_event
        if event_type == "verification_passed":
            session, followup_event = self._handle_verification_passed(session, accepted_event)
            return session, followup_event
        return session, None

    def handle_role_output(
        self,
        session_id: int,
        role_name: str,
        output_type: str,
        payload: dict,
    ) -> tuple[Session, Event, Event | None]:
        session = self._get_session_or_raise(session_id)
        self._record_role_output_artifacts(
            session=session,
            role_name=role_name,
            output_type=output_type,
            payload=payload,
        )
        mapped_event_type = self._map_role_output_to_event_type(
            session=session,
            role_name=role_name,
            output_type=output_type,
        )
        accepted_event = self.event_repository.append(
            session_id=session_id,
            event_type=mapped_event_type,
            producer_type="role",
            producer_id=role_name,
            payload=payload,
        )
        followup_event: Event | None = None
        if mapped_event_type == "implementation_completed":
            session, followup_event = self._handle_implementation_completed(session, accepted_event)
        elif mapped_event_type == "verification_failed":
            session, followup_event = self._handle_verification_failed(session, accepted_event)
        elif mapped_event_type == "verification_passed":
            session, followup_event = self._handle_verification_passed(session, accepted_event)
        return session, accepted_event, followup_event

    def collect_role_output(
        self,
        session_id: int,
        role_name: str,
    ) -> tuple[Session, Event | None, int]:
        session = self._get_session_or_raise(session_id)
        role = self.role_repository.get_by_name(session_id, role_name)
        if role is None:
            raise IntakeError(f"Role {role_name} is missing for session {session_id}")

        runtime_role = RuntimeRoleHandle(
            role_id=role.runtime_handle or f"{role.runtime_backend}:{role.role_name}",
            session_id=f"session:{session.id}",
            backend_name=role.runtime_backend,
        )
        chunks = self.session_backend.read_output(runtime_role)
        if not chunks:
            return session, None, 0

        self._record_runtime_output_artifacts(session, role, chunks)
        event = self.event_repository.append(
            session_id=session.id,
            event_type="role_output_collected",
            producer_type="coordinator",
            payload={
                "role_name": role_name,
                "chunk_count": len(chunks),
            },
        )
        return session, event, len(chunks)

    def poll_session_output(
        self,
        session_id: int,
    ) -> tuple[Session, Event | None, int, int]:
        session = self._get_session_or_raise(session_id)
        roles = [
            role
            for role in self.role_repository.list_for_session(session_id)
            if role.runtime_handle is not None
        ]
        total_chunks = 0
        for role in roles:
            runtime_role = RuntimeRoleHandle(
                role_id=role.runtime_handle or f"{role.runtime_backend}:{role.role_name}",
                session_id=f"session:{session.id}",
                backend_name=role.runtime_backend,
            )
            chunks = self.session_backend.read_output(runtime_role)
            if not chunks:
                continue
            self._record_runtime_output_artifacts(session, role, chunks)
            total_chunks += len(chunks)

        if total_chunks == 0:
            return session, None, len(roles), 0

        event = self.event_repository.append(
            session_id=session.id,
            event_type="session_output_polled",
            producer_type="coordinator",
            payload={
                "role_count": len(roles),
                "chunk_count": total_chunks,
            },
        )
        return session, event, len(roles), total_chunks

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
        self._dispatch_role_work(
            session=session,
            role=implementer_role,
            work_item=work_item,
            stage_name="implementation_requested",
            instruction=f"Start implementation work for {resolved_task_key}.",
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
        self._dispatch_role_work(
            session=session,
            role=verification_role,
            work_item=verification_item,
            stage_name="verification_requested",
            instruction=f"Run deterministic verification for {session.task_key}.",
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

    def _handle_verification_failed(
        self,
        session: Session,
        source_event: Event,
    ) -> tuple[Session, Event]:
        verification_items = [
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "verification" and item.status != WorkItemStatus.COMPLETED
        ]
        if not verification_items:
            raise IntakeError("No active verification work item found for the session")

        active_item = verification_items[0]
        self.work_item_repository.update_status(active_item.id, WorkItemStatus.COMPLETED)

        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        if implementer_role is None:
            raise IntakeError("Implementer role is missing for the session")

        correction_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="verification_correction",
            title=f"Verification corrections for {session.task_key}",
            owner_role_id=implementer_role.id,
            source_event_id=source_event.id,
            priority=95,
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="verification_correction_requested",
            current_owner=IMPLEMENTER_ROLE,
        )
        self._dispatch_role_work(
            session=session,
            role=implementer_role,
            work_item=correction_item,
            stage_name="verification_correction_requested",
            instruction=f"Apply verification corrections for {session.task_key}.",
        )
        event = self.event_repository.append(
            session_id=session.id,
            event_type="verification_correction_requested",
            producer_type="coordinator",
            payload={
                "task_key": session.task_key,
                "role_name": IMPLEMENTER_ROLE,
                "work_item_id": correction_item.id,
                "current_stage": session.current_stage,
            },
        )
        return session, event

    def _handle_verification_passed(
        self,
        session: Session,
        source_event: Event,
    ) -> tuple[Session, Event]:
        verification_items = [
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "verification" and item.status != WorkItemStatus.COMPLETED
        ]
        if not verification_items:
            raise IntakeError("No active verification work item found for the session")

        active_item = verification_items[0]
        self.work_item_repository.update_status(active_item.id, WorkItemStatus.COMPLETED)
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="completed",
            current_owner=None,
        )
        session = self.session_repository.update_status(session.id, SessionStatus.COMPLETED)
        event = self.event_repository.append(
            session_id=session.id,
            event_type="task_completed",
            producer_type="coordinator",
            payload={
                "task_key": session.task_key,
                "source_event_id": source_event.id,
                "current_stage": session.current_stage,
                "status": session.status.value,
            },
        )
        return session, event

    def _get_session_or_raise(self, session_id: int) -> Session:
        for session in self.session_repository.list_all():
            if session.id == session_id:
                return session
        raise IntakeError(f"Session {session_id} was not found")

    def _map_role_output_to_event_type(
        self,
        session: Session,
        role_name: str,
        output_type: str,
    ) -> str:
        if role_name == IMPLEMENTER_ROLE and output_type == "completed":
            if session.current_stage in {"implementation_requested", "verification_correction_requested"}:
                return "implementation_completed"
        if role_name == VERIFICATION_COORDINATOR_ROLE:
            if output_type in {"passed", "completed"} and session.current_stage == "verification_requested":
                return "verification_passed"
            if output_type == "failed" and session.current_stage == "verification_requested":
                return "verification_failed"
        raise IntakeError(
            f"Unsupported role output: role={role_name}, output_type={output_type}, stage={session.current_stage}"
        )

    def _record_role_output_artifacts(
        self,
        session: Session,
        role_name: str,
        output_type: str,
        payload: dict,
    ) -> None:
        role = self.role_repository.get_by_name(session.id, role_name)
        if role is None:
            raise IntakeError(f"Role {role_name} is missing for session {session.id}")

        stage_name = f"role-output-{role_name}"
        payload_text = json.dumps(payload, indent=2, sort_keys=True)
        json_path = write_text_artifact(
            self.artifacts_root,
            session.task_key,
            stage_name,
            f"{output_type}.json",
            payload_text,
        )
        summary_path = write_text_artifact(
            self.artifacts_root,
            session.task_key,
            stage_name,
            f"{output_type}.txt",
            f"role={role_name}\noutput_type={output_type}\npayload={payload_text}\n",
        )
        metadata = {
            "role_name": role_name,
            "output_type": output_type,
            "current_stage": session.current_stage,
        }
        self.artifact_repository.create(
            session_id=session.id,
            role_id=role.id,
            stage_name=stage_name,
            artifact_type="role_output_json",
            path=str(json_path),
            metadata=metadata,
        )
        self.artifact_repository.create(
            session_id=session.id,
            role_id=role.id,
            stage_name=stage_name,
            artifact_type="role_output_summary",
            path=str(summary_path),
            metadata=metadata,
        )

    def _record_runtime_output_artifacts(
        self,
        session: Session,
        role: Role,
        chunks: list[RuntimeOutputChunk],
    ) -> None:
        stage_name = f"runtime-output-{role.role_name}"
        joined_text = "\n".join(chunk.text for chunk in chunks)
        output_path = write_text_artifact(
            self.artifacts_root,
            session.task_key,
            stage_name,
            "output.log",
            joined_text,
        )
        self.artifact_repository.create(
            session_id=session.id,
            role_id=role.id,
            stage_name=stage_name,
            artifact_type="runtime_output",
            path=str(output_path),
            metadata={
                "role_name": role.role_name,
                "chunk_count": len(chunks),
                "current_stage": session.current_stage,
            },
        )

    def _dispatch_role_work(
        self,
        session: Session,
        role: Role,
        work_item: WorkItem,
        stage_name: str,
        instruction: str,
    ) -> None:
        hydration = build_role_hydration(
            role_name=role.role_name,
            task_key=session.task_key,
            current_stage=session.current_stage,
            active_work_item=work_item,
        )
        prompt_text = role_handoff_prompt(
            role_name=role.role_name,
            instruction=instruction,
            hydration_payload=hydration,
        )
        hydration_path = write_text_artifact(
            self.artifacts_root,
            session.task_key,
            stage_name,
            f"{role.role_name}.hydration.json",
            json.dumps(hydration, indent=2, sort_keys=True),
        )
        prompt_path = write_text_artifact(
            self.artifacts_root,
            session.task_key,
            stage_name,
            f"{role.role_name}.prompt.txt",
            prompt_text,
        )
        updated_role = self.role_repository.increment_hydration_version(role.id)
        self.artifact_repository.create(
            session_id=session.id,
            role_id=role.id,
            stage_name=stage_name,
            artifact_type="hydration_payload",
            path=str(hydration_path),
            metadata={
                "role_name": role.role_name,
                "work_item_id": work_item.id,
                "hydration_version": updated_role.last_hydration_version,
            },
        )
        self.artifact_repository.create(
            session_id=session.id,
            role_id=role.id,
            stage_name=stage_name,
            artifact_type="role_prompt",
            path=str(prompt_path),
            metadata={
                "role_name": role.role_name,
                "work_item_id": work_item.id,
                "hydration_version": updated_role.last_hydration_version,
            },
        )
        runtime_role = RuntimeRoleHandle(
            role_id=role.runtime_handle or f"{role.runtime_backend}:{role.role_name}",
            session_id=f"session:{session.id}",
            backend_name=role.runtime_backend,
        )
        self.session_backend.send_input(runtime_role, prompt_text)
        self.event_repository.append(
            session_id=session.id,
            event_type="role_input_dispatched",
            producer_type="coordinator",
            payload={
                "role_name": role.role_name,
                "work_item_id": work_item.id,
                "stage_name": stage_name,
                "hydration_version": updated_role.last_hydration_version,
            },
        )
