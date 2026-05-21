"""Top-level coordinator facade."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import shutil
import subprocess
from pathlib import Path

from backend.api.sse import SessionEventBus
from backend.coordinator.artifacts import write_text_artifact
from backend.coordinator.intake import IntakeError, classify_task_readiness
from backend.coordinator.subtasks import completed_subtasks, read_snapshot_subtasks, unresolved_subtasks
from backend.coordinator.hydration import build_role_hydration
from backend.models.event import Event
from backend.models.artifact import Artifact
from backend.models.enums import RoleStatus, SessionStatus, WorkItemStatus
from backend.models.session import Session
from backend.models.role import Role
from backend.models.work_item import WorkItem
from backend.role_runtime_config import normalize_role_runtime_config
from backend.roles.prompts import role_handoff_prompt
from backend.roles.launcher import RoleLauncherManager
from backend.roles.workspace import RoleWorkspaceManager
from backend.roles.contracts import (
    ALLOWED_STAGE_ROLE_TARGETS,
    BUG_FIXER_ROLE,
    CODE_REVIEWER_ROLE,
    CODE_SCOUT_ROLE,
    DOC_HARVEST_ROLE,
    MR_COMMENTS_ANALYST_ROLE,
    PERSISTENT_SESSION_ROLES,
    ACCEPTANCE_CRITERIA_WORKER_ROLE,
    CONSTRAINTS_WORKER_ROLE,
    PROPOSAL_CONTEXT_WORKER_ROLE,
    REQUIREMENTS_CLARIFIER_WORKER_ROLE,
    SPEC_VERIFIER_WORKER_ROLE,
    TASK_DECOMPOSER_WORKER_ROLE,
    IMPLEMENTER_ROLE,
    STORY_SPEC_WORKER_ROLE,
    VERIFICATION_COORDINATOR_ROLE,
)
from backend.session_backend.base import SessionBackend
from backend.session_policy import infer_workflow_profile, normalize_session_policy
from backend.session_backend.runtime_models import RuntimeOutputChunk, RuntimeRoleHandle, RuntimeSessionHandle
from backend.state.artifact_repository import ArtifactRepository
from backend.state.event_repository import EventRepository
from backend.state.role_repository import RoleRepository
from backend.state.session_repository import SessionRepository
from backend.state.work_item_repository import WorkItemRepository
from backend.tools.gitlab_adapter import GitLabAdapter
from backend.tools.jira_adapter import JiraAdapter
from backend.tools.snapshot_adapter import SnapshotAdapter


_CLOSED_JIRA_STATUSES = {"resolved", "done", "closed", "cancelled"}
_TASK_KEY_PATTERN = re.compile(r"^[A-Z]+-\d+$")
_EXPLICIT_URL_PATTERN = re.compile(r"https?://[^\s)>\]]+")
_STORY_PLANNING_WORK_TYPE_BY_STAGE = {
    "proposal_context_requested": "proposal_context",
    "requirements_requested": "requirements",
    "acceptance_criteria_requested": "acceptance_criteria",
    "constraints_requested": "constraints",
    "spec_verification_requested": "spec_verification",
    "story_spec_requested": "story_spec",
    "task_decomposition_requested": "task_decomposition",
}
_STORY_PLANNING_ROLES = {
    PROPOSAL_CONTEXT_WORKER_ROLE,
    REQUIREMENTS_CLARIFIER_WORKER_ROLE,
    ACCEPTANCE_CRITERIA_WORKER_ROLE,
    CONSTRAINTS_WORKER_ROLE,
    SPEC_VERIFIER_WORKER_ROLE,
    STORY_SPEC_WORKER_ROLE,
    TASK_DECOMPOSER_WORKER_ROLE,
}


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
    gitlab_adapter: GitLabAdapter | None = None
    artifacts_root: Path | None = None
    workdir_root: Path | None = None
    event_bus: SessionEventBus | None = None
    role_workspace_manager: RoleWorkspaceManager | None = None
    role_launcher_manager: RoleLauncherManager | None = None

    def create_task_session(
        self,
        task_key: str,
        workflow_profile: str,
        policy: dict[str, str] | None = None,
        role_config: dict[str, dict[str, str]] | None = None,
    ) -> tuple[Session, Event, bool]:
        """Create or reuse a task session and emit the initial session event."""

        normalized_policy = normalize_session_policy(workflow_profile, policy)
        effective_roles = self._effective_role_names(
            normalized_policy.workflow_profile,
            normalized_policy.policy,
        )
        normalized_role_config = normalize_role_runtime_config(
            repo_root=self._repo_root(),
            role_names=effective_roles,
            provided=role_config,
        )
        existing = self.session_repository.get_by_task_key(task_key)
        if existing is not None:
            if existing.workflow_profile != normalized_policy.workflow_profile:
                raise IntakeError(
                    f"Session {task_key} already exists with workflow profile "
                    f"{existing.workflow_profile}, not {normalized_policy.workflow_profile}"
                )
            if (existing.policy or {}) != normalized_policy.policy:
                raise IntakeError(
                    f"Session {task_key} already exists with different stored policy"
                )
            if (existing.role_config or {}) != normalized_role_config:
                raise IntakeError(
                    f"Session {task_key} already exists with different stored role runtime config"
                )
            event = self._append_event(
                session_id=existing.id,
                event_type="task_session_reused",
                producer_type="coordinator",
                payload={
                    "task_key": task_key,
                    "current_stage": existing.current_stage,
                    "workflow_profile": existing.workflow_profile,
                    "policy": existing.policy or {},
                    "role_config": existing.role_config or {},
                },
            )
            return existing, event, False

        session = self.session_repository.create(
            task_key=task_key,
            current_stage="intake",
            workflow_profile=normalized_policy.workflow_profile,
            policy=normalized_policy.policy,
            role_config=normalized_role_config,
        )
        runtime_session = self.session_backend.create_task_session(task_key)
        for role_name in effective_roles:
            runtime_role = self._spawn_role_runtime(
                runtime_session=runtime_session,
                task_key=task_key,
                role_name=role_name,
                role_config=normalized_role_config.get(role_name),
            )
            self.role_repository.create(
                session_id=session.id,
                role_name=role_name,
                runtime_backend=runtime_role.backend_name,
                runtime_handle=runtime_role.role_id,
                status=RoleStatus.RUNNING,
            )
        session = self.session_repository.update_status(session.id, SessionStatus.ACTIVE)
        event = self._append_event(
            session_id=session.id,
            event_type="task_started",
            producer_type="coordinator",
            payload={
                "task_key": task_key,
                "current_stage": session.current_stage,
                "workflow_profile": session.workflow_profile,
                "policy": session.policy or {},
                "role_config": session.role_config or {},
                "runtime_session_id": runtime_session.session_id,
                "roles": effective_roles,
            },
        )
        return session, event, True

    def prepare_task_session(
        self,
        raw_task_key: str,
        workflow_profile: str | None = None,
        policy: dict[str, str] | None = None,
        role_config: dict[str, dict[str, str]] | None = None,
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
        existing = self.session_repository.get_by_task_key(resolved_task_key)
        session, _, created = self.create_task_session(
            resolved_task_key,
            workflow_profile=(
                workflow_profile
                if workflow_profile is not None
                else (
                    existing.workflow_profile
                    if existing is not None
                    else infer_workflow_profile(issue_type)
                )
            ),
            policy=policy if policy is not None else (existing.policy if existing is not None else None),
            role_config=(
                role_config
                if role_config is not None
                else (existing.role_config if existing is not None else None)
            ),
        )

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

        event = self._append_event(
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
            if session.workflow_profile == "bug_full":
                details["followup_event_type"] = self._enqueue_bug_analysis(
                    session=session,
                    source_event=event,
                ).event_type
            elif session.workflow_profile == "story_full":
                details["followup_event_type"] = self._enqueue_proposal_context(
                    session=session,
                    source_event=event,
                ).event_type
            else:
                details["followup_event_type"] = self._enqueue_initial_implementation(
                    session=session,
                    resolved_task_key=resolved_task_key,
                    source_event=event,
                ).event_type
            session = self._get_session_or_raise(session.id)
        return session, event, created, details

    def get_subtask_graph_summary(self, session_id: int) -> dict[str, object]:
        session = self.session_repository.get_by_id(session_id)
        if session is None:
            raise IntakeError(f"Session {session_id} does not exist")

        subtasks = self._read_snapshot_subtasks(session.task_key)
        if subtasks is None:
            return {
                "available": False,
                "rows": [],
                "completed_count": 0,
                "total_count": 0,
                "unresolved_count": 0,
            }

        completed = completed_subtasks(subtasks)
        unresolved = unresolved_subtasks(subtasks)
        return {
            "available": True,
            "rows": [
                {
                    "key": subtask.key,
                    "issue_type": subtask.issue_type,
                    "title": subtask.title,
                    "status": subtask.status,
                }
                for subtask in subtasks
            ],
            "completed_count": len(completed),
            "total_count": len(subtasks),
            "unresolved_count": len(unresolved),
        }

    def get_subtask_progress_summary(self, session_id: int) -> dict[str, object]:
        session = self.session_repository.get_by_id(session_id)
        if session is None:
            raise IntakeError(f"Session {session_id} does not exist")

        items = [
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "subtask_implementation"
        ]
        if not items:
            return {
                "available": False,
                "current_subtask_key": None,
                "current_subtask_title": None,
                "total_count": 0,
                "completed_count": 0,
                "remaining_count": 0,
                "items": [],
            }

        progress_items: list[dict[str, object]] = []
        for index, item in enumerate(items, start=1):
            parsed = self._parse_subtask_work_item_title(item.title)
            progress_items.append(
                {
                    "work_item_id": item.id,
                    "key": parsed["key"],
                    "title": parsed["title"],
                    "status": item.status.value,
                    "queue_position": index,
                }
            )

        current = next((item for item in progress_items if item["status"] == WorkItemStatus.ASSIGNED.value), None)
        completed_count = sum(1 for item in progress_items if item["status"] == WorkItemStatus.COMPLETED.value)
        remaining_count = sum(
            1
            for item in progress_items
            if item["status"] in {WorkItemStatus.ASSIGNED.value, WorkItemStatus.UNASSIGNED.value}
        )
        return {
            "available": True,
            "current_subtask_key": current["key"] if current is not None else None,
            "current_subtask_title": current["title"] if current is not None else None,
            "total_count": len(progress_items),
            "completed_count": completed_count,
            "remaining_count": remaining_count,
            "items": progress_items,
        }

    def get_created_jira_subtasks_summary(self, session_id: int) -> dict[str, object]:
        session = self.session_repository.get_by_id(session_id)
        if session is None:
            raise IntakeError(f"Session {session_id} does not exist")

        created_event = None
        for event in reversed(self.event_repository.list_for_session(session.id)):
            if event.event_type == "jira_subtasks_created":
                created_event = event
                break
        if created_event is None:
            return {
                "available": False,
                "total_count": 0,
                "items": [],
            }

        raw_keys = created_event.payload.get("created_subtask_keys", [])
        created_keys = [str(item).strip() for item in raw_keys if str(item).strip()]
        if not created_keys:
            return {
                "available": False,
                "total_count": 0,
                "items": [],
            }

        graph_summary = self.get_subtask_graph_summary(session.id)
        graph_rows_by_key = {
            str(row["key"]): row
            for row in graph_summary.get("rows", [])
            if isinstance(row, dict) and row.get("key") is not None
        }
        progress_summary = self.get_subtask_progress_summary(session.id)
        progress_items_by_key = {
            str(item["key"]): item
            for item in progress_summary.get("items", [])
            if isinstance(item, dict) and item.get("key") is not None
        }
        current_subtask_key = progress_summary.get("current_subtask_key")

        items: list[dict[str, object]] = []
        for key in created_keys:
            graph_row = graph_rows_by_key.get(key, {})
            progress_item = progress_items_by_key.get(key, {})
            items.append(
                {
                    "key": key,
                    "title": graph_row.get("title"),
                    "status": graph_row.get("status"),
                    "queue_position": progress_item.get("queue_position"),
                    "is_current": current_subtask_key == key,
                }
            )

        return {
            "available": True,
            "total_count": len(items),
            "items": items,
        }

    def get_interactive_state_summary(self, session_id: int) -> dict[str, object]:
        session = self.session_repository.get_by_id(session_id)
        if session is None:
            raise IntakeError(f"Session {session_id} does not exist")

        blocker_event = None
        clear_event = None
        for event in reversed(self.event_repository.list_for_session(session.id)):
            if (
                blocker_event is None
                and (
                    event.event_type == "session_escalated_to_operator"
                    or event.event_type == "role_runtime_error_reported"
                )
            ):
                blocker_event = event
            if (
                clear_event is None
                and event.event_type
                in {
                    "operator_runtime_input_sent",
                    "session_resumed_by_operator",
                    "session_retried_by_operator",
                    "session_redirected_by_operator",
                }
            ):
                clear_event = event
            if blocker_event is not None and clear_event is not None:
                break

        if blocker_event is not None and clear_event is not None and clear_event.id > blocker_event.id:
            blocker_event = None

        source_event = blocker_event
        if source_event is None:
            return {
                "available": False,
                "role_name": None,
                "current_stage": None,
                "summary": None,
                "details": None,
                "source_event_type": None,
                "source_reason": None,
                "needs_operator_input": False,
                "resume_strategy": None,
            }

        return {
            "available": True,
            "role_name": source_event.payload.get("role_name"),
            "current_stage": source_event.payload.get("current_stage", session.current_stage),
            "summary": source_event.payload.get("summary") or source_event.payload.get("reason"),
            "details": source_event.payload.get("details"),
            "source_event_type": source_event.event_type,
            "source_reason": source_event.payload.get("reason"),
            "needs_operator_input": bool(source_event.payload.get("needs_operator_input") is True),
            "resume_strategy": source_event.payload.get("resume_strategy"),
        }

    def handle_operator_event(
        self,
        session_id: int,
        event_type: str,
        payload: dict,
    ) -> tuple[Session, Event | None]:
        session = self._get_session_or_raise(session_id)
        accepted_event = self._append_event(
            session_id=session_id,
            event_type=event_type,
            producer_type="operator",
            payload=payload,
        )
        if event_type == "bug_analysis_completed":
            session, followup_event = self._handle_bug_analysis_completed(session, accepted_event)
            return session, followup_event
        if event_type == "proposal_context_completed":
            session, followup_event = self._handle_proposal_context_completed(session, accepted_event)
            return session, followup_event
        if event_type == "spec_verification_blocked":
            session, followup_event = self._handle_spec_verification_blocked(session, accepted_event)
            return session, followup_event
        if event_type == "mr_comments_analysis_completed":
            session, followup_event = self._handle_mr_comments_analysis_completed(session, accepted_event)
            return session, followup_event
        if event_type == "requirements_completed":
            session, followup_event = self._handle_requirements_completed(session, accepted_event)
            return session, followup_event
        if event_type == "boy_scout_completed":
            session, followup_event = self._handle_boy_scout_completed(session, accepted_event)
            return session, followup_event
        if event_type == "acceptance_criteria_completed":
            session, followup_event = self._handle_acceptance_criteria_completed(session, accepted_event)
            return session, followup_event
        if event_type == "constraints_completed":
            session, followup_event = self._handle_constraints_completed(session, accepted_event)
            return session, followup_event
        if event_type == "spec_verification_completed":
            session, followup_event = self._handle_spec_verification_completed(session, accepted_event)
            return session, followup_event
        if event_type == "story_spec_completed":
            session, followup_event = self._handle_story_spec_completed(session, accepted_event)
            return session, followup_event
        if event_type == "task_decomposition_completed":
            session, followup_event = self._handle_task_decomposition_completed(session, accepted_event)
            return session, followup_event
        if event_type == "subtask_completed":
            session, followup_event = self._handle_subtask_completed(session, accepted_event)
            return session, followup_event
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

    def ingest_mr_comments(
        self,
        session_id: int,
        platform: str,
        mr_id: str,
    ) -> tuple[Session, Event, Event | None, int]:
        if self.gitlab_adapter is None or self.artifacts_root is None:
            raise IntakeError("Coordinator is missing GitLab adapter or artifact root")

        session = self._get_session_or_raise(session_id)
        if session.status != SessionStatus.COMPLETED:
            raise IntakeError(
                f"Session {session_id} must be completed before MR comments can reopen it"
            )
        if platform not in {"ios", "android"}:
            raise IntakeError("Platform must be 'ios' or 'android'")

        comments_result = self.gitlab_adapter.fetch_mr_comments(platform=platform, mr_id=mr_id)
        if comments_result.returncode == 2:
            event = self._append_event(
                session_id=session.id,
                event_type="mr_comments_empty",
                producer_type="coordinator",
                payload={"platform": platform, "mr_id": mr_id},
            )
            return session, event, None, 0
        if not comments_result.ok:
            raise IntakeError(
                comments_result.stderr or comments_result.stdout or "Failed to fetch MR comments"
            )

        discussion_count = self._count_mr_discussions(comments_result.stdout)
        artifact_path = write_text_artifact(
            self.artifacts_root,
            session.task_key,
            "mr-followup",
            f"mr-{mr_id}-comments.md",
            comments_result.stdout,
        )
        self.artifact_repository.create(
            session_id=session.id,
            stage_name="mr-followup",
            artifact_type="mr_comments_markdown",
            path=str(artifact_path),
            metadata={
                "platform": platform,
                "mr_id": mr_id,
                "discussion_count": discussion_count,
            },
        )
        event = self._append_event(
            session_id=session.id,
            event_type="mr_comments_received",
            producer_type="coordinator",
            payload={
                "platform": platform,
                "mr_id": mr_id,
                "discussion_count": discussion_count,
            },
        )
        followup_event = self._enqueue_mr_comments_analysis(
            session=session,
            source_event=event,
            mr_id=mr_id,
            discussion_count=discussion_count,
        )
        refreshed = self._get_session_or_raise(session.id)
        return refreshed, event, followup_event, discussion_count

    def _enqueue_mr_comments_analysis(
        self,
        session: Session,
        source_event: Event,
        mr_id: str,
        discussion_count: int,
    ) -> Event:
        analyst_role = self._ensure_on_demand_role(session, MR_COMMENTS_ANALYST_ROLE)
        work_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="mr_comments_analysis",
            title=f"MR comment analysis for {session.task_key} from !{mr_id}",
            owner_role_id=analyst_role.id,
            source_event_id=source_event.id,
            priority=111,
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="mr_comments_analysis_requested",
            current_owner=MR_COMMENTS_ANALYST_ROLE,
        )
        session = self.session_repository.update_status(session.id, SessionStatus.ACTIVE)
        instruction = (
            f"Analyze unresolved MR comments for {session.task_key} from MR !{mr_id}. "
            f"Group the {discussion_count} unresolved discussion threads into actionable themes, "
            "write the follow-up plan package under `plan/`, and produce a compact routed summary for the implementer."
        )
        self._dispatch_role_work(
            session=session,
            role=analyst_role,
            work_item=work_item,
            stage_name="mr_comments_analysis_requested",
            instruction=instruction,
        )
        return self._append_event(
            session_id=session.id,
            event_type="mr_comments_analysis_requested",
            producer_type="coordinator",
            payload={
                "task_key": session.task_key,
                "role_name": MR_COMMENTS_ANALYST_ROLE,
                "work_item_id": work_item.id,
                "current_stage": session.current_stage,
                "mr_id": mr_id,
                "discussion_count": discussion_count,
            },
        )

    def create_mr_handoff(
        self,
        session_id: int,
    ) -> tuple[Session, Event, str | None]:
        if self.gitlab_adapter is None or self.artifacts_root is None:
            raise IntakeError("Coordinator is missing GitLab adapter or artifact root")

        session = self._get_session_or_raise(session_id)
        allowed_retry = (
            session.status == SessionStatus.WAITING_FOR_OPERATOR
            and session.current_stage == "mr_handoff_failed"
        )
        if session.status != SessionStatus.COMPLETED and not allowed_retry:
            raise IntakeError(
                f"Session {session_id} must be completed before MR handoff can run"
            )
        if session.current_stage == "mr_handoff_completed":
            raise IntakeError(f"Session {session_id} has already completed MR handoff")

        result = self.gitlab_adapter.create_mr(session.task_key)
        stdout_path = write_text_artifact(
            self.artifacts_root,
            session.task_key,
            "mr-handoff",
            "create-mr.stdout.log",
            result.stdout,
        )
        stderr_path = write_text_artifact(
            self.artifacts_root,
            session.task_key,
            "mr-handoff",
            "create-mr.stderr.log",
            result.stderr,
        )
        mr_url = self._extract_mr_url(result.stdout)
        self.artifact_repository.create(
            session_id=session.id,
            stage_name="mr-handoff",
            artifact_type="mr_handoff_stdout",
            path=str(stdout_path),
            metadata={
                "task_key": session.task_key,
                "command": result.command,
                "returncode": result.returncode,
                "mr_url": mr_url,
            },
        )
        self.artifact_repository.create(
            session_id=session.id,
            stage_name="mr-handoff",
            artifact_type="mr_handoff_stderr",
            path=str(stderr_path),
            metadata={
                "task_key": session.task_key,
                "command": result.command,
                "returncode": result.returncode,
            },
        )

        if not result.ok:
            session = self.session_repository.update_stage_and_owner(
                session.id,
                current_stage="mr_handoff_failed",
                current_owner=None,
            )
            session = self.session_repository.update_status(session.id, SessionStatus.WAITING_FOR_OPERATOR)
            event = self._append_event(
                session_id=session.id,
                event_type="mr_handoff_failed",
                producer_type="coordinator",
                payload={
                    "task_key": session.task_key,
                    "returncode": result.returncode,
                    "mr_url": mr_url,
                },
            )
            return session, event, mr_url

        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="mr_handoff_completed",
            current_owner=None,
        )
        session = self.session_repository.update_status(session.id, SessionStatus.COMPLETED)
        event = self._append_event(
            session_id=session.id,
            event_type="mr_handoff_completed",
            producer_type="coordinator",
            payload={
                "task_key": session.task_key,
                "returncode": result.returncode,
                "mr_url": mr_url,
                "current_stage": session.current_stage,
                "status": session.status.value,
            },
        )
        return session, event, mr_url

    def complete_doc_harvest(
        self,
        session_id: int,
        summary: str,
    ) -> tuple[Session, Event]:
        if self.artifacts_root is None:
            raise IntakeError("Coordinator is missing artifact root")

        session = self._get_session_or_raise(session_id)
        normalized_summary = summary.strip()
        if not normalized_summary:
            raise IntakeError("Doc harvest summary must not be empty")

        if session.current_stage not in {"completed", "doc_harvest_requested"}:
            raise IntakeError(
                f"Session {session_id} is not in a doc-harvest-capable stage"
            )
        policy_mode = self._optional_lane_policy_mode(session.policy, "doc_harvest_policy")
        if policy_mode == "disabled":
            raise IntakeError(f"Session {session_id} has doc harvest disabled by policy")
        if policy_mode != "enabled":
            raise IntakeError("Manual doc harvest completion is only allowed when doc_harvest_policy is enabled")
        if session.current_stage == "doc_harvest_requested":
            doc_items = [
                item
                for item in self.work_item_repository.list_for_session(session.id)
                if item.work_type == "doc_harvest" and item.status != WorkItemStatus.COMPLETED
            ]
            if doc_items:
                self.work_item_repository.update_status(doc_items[0].id, WorkItemStatus.COMPLETED)
            self._stop_on_demand_role(session, DOC_HARVEST_ROLE)
        return self._finalize_doc_harvest(
            session=session,
            summary=normalized_summary,
            producer_type="coordinator",
            producer_id=None,
        )

    def skip_boy_scout(
        self,
        session_id: int,
        reason: str,
    ) -> tuple[Session, Event, Event]:
        session = self._get_session_or_raise(session_id)
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise IntakeError("Boy Scout skip reason must not be empty")
        if session.current_stage != "boy_scout_requested":
            raise IntakeError(f"Session {session_id} is not waiting on Boy Scout")
        if session.status != SessionStatus.WAITING_FOR_OPERATOR:
            raise IntakeError(f"Session {session_id} does not have skippable Boy Scout findings")
        if self._optional_lane_policy_mode(session.policy, "boy_scout_policy") != "enabled":
            raise IntakeError("Manual Boy Scout skip is only allowed when boy_scout_policy is enabled")

        pending_items = [
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "boy_scout_review" and item.status != WorkItemStatus.COMPLETED
        ]
        if not pending_items:
            raise IntakeError(f"Session {session_id} has no pending Boy Scout review decision")
        self.work_item_repository.update_status(pending_items[0].id, WorkItemStatus.COMPLETED)
        self._materialize_boy_scout_deferred(session=session, reason=normalized_reason)

        event = self._append_event(
            session_id=session.id,
            event_type="boy_scout_skipped_by_operator",
            producer_type="operator",
            payload={
                "task_key": session.task_key,
                "reason": normalized_reason,
                "current_stage": session.current_stage,
            },
        )
        session = self.session_repository.update_status(session.id, SessionStatus.ACTIVE)
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage=session.current_stage,
            current_owner=None,
        )
        session, followup_event = self._enqueue_verification(session=session, source_event=event)
        return session, event, followup_event

    def resolve_boy_scout_findings(
        self,
        session_id: int,
        resolution: str,
    ) -> tuple[Session, Event, Event]:
        session = self._get_session_or_raise(session_id)
        if session.current_stage != "boy_scout_requested":
            raise IntakeError(f"Session {session_id} is not waiting on Boy Scout")
        if session.status != SessionStatus.WAITING_FOR_OPERATOR:
            raise IntakeError(f"Session {session_id} does not have resolvable Boy Scout findings")
        if resolution not in {"implement_now", "create_tech_debt"}:
            raise IntakeError("Boy Scout resolution must be 'implement_now' or 'create_tech_debt'")

        pending_items = [
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "boy_scout_review" and item.status != WorkItemStatus.COMPLETED
        ]
        if not pending_items:
            raise IntakeError(f"Session {session_id} has no pending Boy Scout review decision")
        self.work_item_repository.update_status(pending_items[0].id, WorkItemStatus.COMPLETED)

        implement_now_findings, tech_debt_findings = self._classify_boy_scout_findings(session)
        if resolution == "create_tech_debt" and not tech_debt_findings:
            raise IntakeError("No tech-debt-eligible Boy Scout findings are available")

        created_issues: list[dict[str, str]] = []
        chosen_findings = list(implement_now_findings)
        if resolution == "create_tech_debt":
            created_issues = self._create_boy_scout_tech_debt_stories(session, tech_debt_findings)
            self._materialize_boy_scout_deferred_entries(session=session, created_issues=created_issues)
        else:
            chosen_findings = implement_now_findings + tech_debt_findings

        event = self._append_event(
            session_id=session.id,
            event_type=(
                "boy_scout_tech_debt_created"
                if resolution == "create_tech_debt"
                else "boy_scout_implement_now_selected"
            ),
            producer_type="operator",
            payload={
                "task_key": session.task_key,
                "resolution": resolution,
                "implement_now_count": len(chosen_findings),
                "tech_debt_count": len(tech_debt_findings),
                "created_issues": created_issues,
                "current_stage": session.current_stage,
            },
        )
        session = self.session_repository.update_status(session.id, SessionStatus.ACTIVE)
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage=session.current_stage,
            current_owner=None,
        )

        if chosen_findings:
            actionable_path = self._materialize_boy_scout_actionable_findings(
                session=session,
                findings=chosen_findings,
                filename="boy-scout-actionable.md",
            )
            session, followup_event = self._enqueue_boy_scout_correction(
                session=session,
                source_event=event,
                actionable_findings_path=actionable_path,
            )
            return session, event, followup_event

        session, followup_event = self._enqueue_verification(session=session, source_event=event)
        return session, event, followup_event

    def complete_self_review(
        self,
        session_id: int,
        outcome: str,
        summary: str,
    ) -> tuple[Session, Event, Event]:
        if self.artifacts_root is None:
            raise IntakeError("Coordinator is missing artifact root")

        session = self._get_session_or_raise(session_id)
        normalized_summary = summary.strip()
        if not normalized_summary:
            raise IntakeError("Self review summary must not be empty")
        if outcome not in {"passed", "issues_found"}:
            raise IntakeError("Self review outcome must be 'passed' or 'issues_found'")
        if session.current_stage != "self_review_requested":
            raise IntakeError(f"Session {session_id} is not waiting for self review")
        policy_mode = self._optional_lane_policy_mode(session.policy, "self_review_policy")
        if policy_mode == "disabled":
            raise IntakeError(f"Session {session_id} has self review disabled by policy")
        if policy_mode != "enabled":
            raise IntakeError("Manual self review completion is only allowed when self_review_policy is enabled")

        review_output_type = "passed" if outcome == "passed" else "failed"
        self._materialize_self_review_report(
            session=session,
            output_type=review_output_type,
            payload={"summary": normalized_summary},
        )

        artifact_path = write_text_artifact(
            self.artifacts_root,
            session.task_key,
            "self-review",
            "self-review-summary.md",
            normalized_summary,
        )
        self.artifact_repository.create(
            session_id=session.id,
            stage_name="self-review",
            artifact_type="self_review_summary",
            path=str(artifact_path),
            metadata={
                "outcome": outcome,
                "summary_length": len(normalized_summary),
            },
        )

        if outcome == "passed":
            event = self._append_event(
                session_id=session.id,
                event_type="self_review_passed",
                producer_type="coordinator",
                payload={
                    "task_key": session.task_key,
                    "summary_length": len(normalized_summary),
                    "current_stage": session.current_stage,
                    "status": session.status.value,
                },
            )
            session, followup_event = self._handle_self_review_passed(session, event)
            return session, event, followup_event

        event = self._append_event(
            session_id=session.id,
            event_type="self_review_issues_found",
            producer_type="coordinator",
            payload={
                "task_key": session.task_key,
                "summary_length": len(normalized_summary),
                "current_stage": session.current_stage,
                "status": session.status.value,
            },
        )
        session, followup_event = self._handle_self_review_issues_found(session, event)
        return session, event, followup_event

    def send_to_test_handoff(
        self,
        session_id: int,
    ) -> tuple[Session, Event]:
        if self.jira_adapter is None or self.artifacts_root is None:
            raise IntakeError("Coordinator is missing Jira adapter or artifact root")

        session = self._get_session_or_raise(session_id)
        allowed_retry = (
            session.status == SessionStatus.WAITING_FOR_OPERATOR
            and session.current_stage == "send_to_test_failed"
        )
        if session.status != SessionStatus.COMPLETED and not allowed_retry:
            raise IntakeError(
                f"Session {session_id} must be completed before send-to-test handoff can run"
            )
        if session.current_stage not in {"mr_handoff_completed", "send_to_test_failed"}:
            raise IntakeError(
                f"Session {session_id} must complete MR handoff before send-to-test handoff"
            )

        result = self.jira_adapter.send_to_test(session.task_key)
        stdout_path = write_text_artifact(
            self.artifacts_root,
            session.task_key,
            "send-to-test",
            "send-to-test.stdout.log",
            result.stdout,
        )
        stderr_path = write_text_artifact(
            self.artifacts_root,
            session.task_key,
            "send-to-test",
            "send-to-test.stderr.log",
            result.stderr,
        )
        self.artifact_repository.create(
            session_id=session.id,
            stage_name="send-to-test",
            artifact_type="send_to_test_stdout",
            path=str(stdout_path),
            metadata={
                "task_key": session.task_key,
                "command": result.command,
                "returncode": result.returncode,
            },
        )
        self.artifact_repository.create(
            session_id=session.id,
            stage_name="send-to-test",
            artifact_type="send_to_test_stderr",
            path=str(stderr_path),
            metadata={
                "task_key": session.task_key,
                "command": result.command,
                "returncode": result.returncode,
            },
        )

        if not result.ok:
            session = self.session_repository.update_stage_and_owner(
                session.id,
                current_stage="send_to_test_failed",
                current_owner=None,
            )
            session = self.session_repository.update_status(session.id, SessionStatus.WAITING_FOR_OPERATOR)
            event = self._append_event(
                session_id=session.id,
                event_type="send_to_test_failed",
                producer_type="coordinator",
                payload={
                    "task_key": session.task_key,
                    "returncode": result.returncode,
                    "current_stage": session.current_stage,
                    "status": session.status.value,
                },
            )
            return session, event

        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="send_to_test_completed",
            current_owner=None,
        )
        session = self.session_repository.update_status(session.id, SessionStatus.COMPLETED)
        event = self._append_event(
            session_id=session.id,
            event_type="send_to_test_completed",
            producer_type="coordinator",
            payload={
                "task_key": session.task_key,
                "returncode": result.returncode,
                "current_stage": session.current_stage,
                "status": session.status.value,
            },
        )
        return session, event

    def create_subtasks_from_plan(
        self,
        session_id: int,
    ) -> tuple[Session, Event, Event | None]:
        if (
            self.jira_adapter is None
            or self.snapshot_adapter is None
            or self.artifacts_root is None
            or self.workdir_root is None
        ):
            raise IntakeError("Coordinator is missing Jira adapter, snapshot adapter, workdir root, or artifact root")

        session = self._get_session_or_raise(session_id)
        if (
            session.workflow_profile != "story_full"
            and session.current_stage != "mr_comments_analysis_requested"
        ):
            raise IntakeError(
                f"Session {session_id} is {session.workflow_profile}, but plan-based subtask creation is only supported for story_full or MR follow-up plan materialization"
            )

        plan_index_path = self.workdir_root / session.task_key / "plan" / "index.md"
        if not plan_index_path.exists():
            raise IntakeError(f"plan/index.md not found for session {session.task_key}")

        plan_dir = plan_index_path.parent
        result = self.jira_adapter.create_subtasks(session.task_key, plan_dir)
        stdout_path = write_text_artifact(
            self.artifacts_root,
            session.task_key,
            "subtasks-batch",
            "create-subtasks.stdout.log",
            result.stdout,
        )
        stderr_path = write_text_artifact(
            self.artifacts_root,
            session.task_key,
            "subtasks-batch",
            "create-subtasks.stderr.log",
            result.stderr,
        )
        self.artifact_repository.create(
            session_id=session.id,
            stage_name="subtasks-batch",
            artifact_type="jira_subtasks_stdout",
            path=str(stdout_path),
            metadata={
                "task_key": session.task_key,
                "command": result.command,
                "returncode": result.returncode,
            },
        )
        self.artifact_repository.create(
            session_id=session.id,
            stage_name="subtasks-batch",
            artifact_type="jira_subtasks_stderr",
            path=str(stderr_path),
            metadata={
                "task_key": session.task_key,
                "command": result.command,
                "returncode": result.returncode,
            },
        )
        created_subtask_keys = self._extract_created_subtask_keys(result.stdout)
        if created_subtask_keys:
            summary_path = write_text_artifact(
                self.artifacts_root,
                session.task_key,
                "subtasks-batch",
                "created-subtasks.md",
                self._jira_subtasks_summary_markdown(created_subtask_keys),
            )
            self.artifact_repository.create(
                session_id=session.id,
                stage_name="subtasks-batch",
                artifact_type="jira_subtasks_summary",
                path=str(summary_path),
                metadata={
                    "task_key": session.task_key,
                    "created_subtask_keys": created_subtask_keys,
                },
            )

        snapshot_refresh_exit_code: int | None = None
        if result.ok:
            self._cleanup_temporary_plan_package(session)
            refresh_result = self.snapshot_adapter.run(session.task_key)
            snapshot_refresh_exit_code = refresh_result.returncode
            refresh_stdout_path = write_text_artifact(
                self.artifacts_root,
                session.task_key,
                "subtasks-batch",
                "refresh-snapshot.stdout.log",
                refresh_result.stdout,
            )
            refresh_stderr_path = write_text_artifact(
                self.artifacts_root,
                session.task_key,
                "subtasks-batch",
                "refresh-snapshot.stderr.log",
                refresh_result.stderr,
            )
            self.artifact_repository.create(
                session_id=session.id,
                stage_name="subtasks-batch",
                artifact_type="subtasks_snapshot_stdout",
                path=str(refresh_stdout_path),
                metadata={
                    "task_key": session.task_key,
                    "command": refresh_result.command,
                    "returncode": refresh_result.returncode,
                },
            )
            self.artifact_repository.create(
                session_id=session.id,
                stage_name="subtasks-batch",
                artifact_type="subtasks_snapshot_stderr",
                path=str(refresh_stderr_path),
                metadata={
                    "task_key": session.task_key,
                    "command": refresh_result.command,
                    "returncode": refresh_result.returncode,
                },
            )

        event_type = "jira_subtasks_created" if result.ok else "jira_subtasks_creation_failed"
        if not result.ok:
            session = self.session_repository.update_stage_and_owner(
                session.id,
                current_stage="subtask_creation_requested",
                current_owner=None,
            )
            session = self.session_repository.update_status(session.id, SessionStatus.WAITING_FOR_OPERATOR)
        event = self._append_event(
            session_id=session.id,
            event_type=event_type,
            producer_type="coordinator",
            payload={
                "task_key": session.task_key,
                "returncode": result.returncode,
                "created_subtask_keys": created_subtask_keys,
                "snapshot_refresh_exit_code": snapshot_refresh_exit_code,
                "current_stage": session.current_stage,
                "status": session.status.value,
            },
        )
        followup_event: Event | None = None
        if result.ok and session.current_stage in {"implementation_requested", "subtask_creation_requested"}:
            active_item: WorkItem | None = None
            if session.current_stage == "implementation_requested":
                active_item = self._find_active_primary_coding_work_item(session)
            elif session.current_stage == "subtask_creation_requested":
                implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
                if implementer_role is not None:
                    active_item = next(
                        (
                            item
                            for item in self.work_item_repository.list_for_session(session.id)
                            if item.work_type == "implementation"
                            and item.owner_role_id == implementer_role.id
                            and item.status in {WorkItemStatus.ASSIGNED, WorkItemStatus.WAITING_FOR_OPERATOR}
                        ),
                        None,
                    )
            decomposition_artifact = self._latest_artifact_for_session_type(
                session.id,
                "task_decomposition_markdown",
            )
            subtasks = self._read_snapshot_subtasks(session.task_key)
            if (
                active_item is not None
                and active_item.work_type == "implementation"
                and decomposition_artifact is not None
                and subtasks is not None
                and unresolved_subtasks(subtasks)
            ):
                if active_item.status == WorkItemStatus.WAITING_FOR_OPERATOR:
                    self.work_item_repository.update_status(active_item.id, WorkItemStatus.ASSIGNED)
                _graph_event, followup_event = self._start_subtask_graph_flow(
                    session=session,
                    producer_type="coordinator",
                    subtasks=subtasks,
                    initial_work_item=active_item,
                    decomposition_artifact=decomposition_artifact,
                )
                session = self._get_session_or_raise(session.id)
        if not result.ok:
            self._append_event(
                session_id=session.id,
                event_type="session_escalated_to_operator",
                producer_type="coordinator",
                payload={
                    "reason": "subtask_creation_failed",
                    "summary": "jira subtask creation failed",
                    "details": "Fix Jira subtask creation or snapshot issues, then retry subtask materialization.",
                    "current_stage": session.current_stage,
                },
            )
        return session, event, followup_event

    def refresh_subtask_state(
        self,
        session_id: int,
    ) -> tuple[Session, Event, Event | None]:
        if self.snapshot_adapter is None or self.workdir_root is None:
            raise IntakeError("Coordinator is missing snapshot adapter or workdir root")

        session = self._get_session_or_raise(session_id)
        subtasks, refresh_ok = self._refresh_subtask_snapshot(session)
        session = self._get_session_or_raise(session.id)

        if not refresh_ok:
            event = self._append_event(
                session_id=session.id,
                event_type="subtask_state_refresh_failed_by_operator",
                producer_type="operator",
                payload={
                    "task_key": session.task_key,
                    "current_stage": session.current_stage,
                    "status": session.status.value,
                },
            )
            return session, event, None

        unresolved = unresolved_subtasks(subtasks) if subtasks is not None else []
        event = self._append_event(
            session_id=session.id,
            event_type="subtask_state_refreshed_by_operator",
            producer_type="operator",
            payload={
                "task_key": session.task_key,
                "current_stage": session.current_stage,
                "status": session.status.value,
                "subtask_count": len(subtasks or []),
                "unresolved_count": len(unresolved),
            },
        )

        if not unresolved or session.current_stage not in {
            "implementation_requested",
            "subtask_creation_requested",
            "subtask_implementation_requested",
        }:
            return session, event, None

        active_item: WorkItem | None
        if session.current_stage == "subtask_creation_requested":
            active_item = self._find_operator_pending_work_item(session.id)
            if active_item is not None:
                self.work_item_repository.update_status(active_item.id, WorkItemStatus.ASSIGNED)
        elif session.current_stage == "subtask_implementation_requested":
            active_item = self._find_active_primary_coding_work_item(session)
        else:
            active_item = self._find_active_primary_coding_work_item(session)
        decomposition_artifact = self._latest_artifact_for_session_type(
            session.id,
            "task_decomposition_markdown",
        )
        if active_item is None or decomposition_artifact is None or subtasks is None:
            return session, event, None

        if session.current_stage == "subtask_implementation_requested":
            if active_item.work_type != "subtask_implementation":
                return session, event, None
            completed_subtask_keys = {
                parsed["key"]
                for item in self.work_item_repository.list_for_session(session.id)
                if item.work_type == "subtask_implementation"
                and item.status == WorkItemStatus.COMPLETED
                for parsed in [self._parse_subtask_work_item_title(item.title)]
                if parsed["key"] is not None
            }
            active_subtask_key = self._parse_subtask_work_item_title(active_item.title)["key"]
            queued_items = [
                item
                for item in self.work_item_repository.list_for_session(session.id)
                if item.work_type == "subtask_implementation"
                and item.status == WorkItemStatus.UNASSIGNED
            ]
            self._reconcile_subtask_queue_after_refresh(
                session=session,
                source_event=event,
                queued_items=queued_items,
                unresolved=[
                    subtask
                    for subtask in unresolved
                    if subtask.key not in completed_subtask_keys and subtask.key != active_subtask_key
                ],
            )
            session = self._get_session_or_raise(session.id)
            return session, event, None

        if active_item.work_type != "implementation":
            return session, event, None

        _graph_event, followup_event = self._start_subtask_graph_flow(
            session=session,
            producer_type="coordinator",
            subtasks=subtasks,
            initial_work_item=active_item,
            decomposition_artifact=decomposition_artifact,
        )
        session = self._get_session_or_raise(session.id)
        return session, event, followup_event

    def refresh_snapshot_and_continue(
        self,
        session_id: int,
    ) -> tuple[Session, Event, Event | None]:
        if self.snapshot_adapter is None or self.workdir_root is None or self.artifacts_root is None:
            raise IntakeError("Coordinator is missing snapshot adapter or workdir root")

        session = self._get_session_or_raise(session_id)
        result = self.snapshot_adapter.run(session.task_key)

        stdout_path = write_text_artifact(
            self.artifacts_root,
            session.task_key,
            "operator-refresh",
            "snapshot-refresh.stdout.txt",
            result.stdout,
        )
        self.artifact_repository.create(
            session_id=session.id,
            stage_name="operator-refresh",
            artifact_type="snapshot_refresh_stdout",
            path=str(stdout_path),
            metadata={"task_key": session.task_key, "command": result.command, "exit_code": result.returncode},
        )
        stderr_path = write_text_artifact(
            self.artifacts_root,
            session.task_key,
            "operator-refresh",
            "snapshot-refresh.stderr.txt",
            result.stderr,
        )
        self.artifact_repository.create(
            session_id=session.id,
            stage_name="operator-refresh",
            artifact_type="snapshot_refresh_stderr",
            path=str(stderr_path),
            metadata={"task_key": session.task_key, "command": result.command, "exit_code": result.returncode},
        )

        if not result.ok:
            event = self._append_event(
                session_id=session.id,
                event_type="snapshot_refresh_failed_by_operator",
                producer_type="operator",
                payload={
                    "task_key": session.task_key,
                    "current_stage": session.current_stage,
                    "status": session.status.value,
                    "snapshot_exit_code": result.returncode,
                },
            )
            return session, event, None

        event = self._append_event(
            session_id=session.id,
            event_type="snapshot_refreshed_by_operator",
            producer_type="operator",
            payload={
                "task_key": session.task_key,
                "current_stage": session.current_stage,
                "status": session.status.value,
                "snapshot_exit_code": result.returncode,
            },
        )

        if session.status == SessionStatus.COMPLETED and session.workflow_profile == "story_full":
            subtasks = self._read_snapshot_subtasks(session.task_key)
            unresolved = unresolved_subtasks(subtasks) if subtasks is not None else []
            decomposition_artifact = self._latest_artifact_for_session_type(
                session.id,
                "task_decomposition_markdown",
            )
            if unresolved and subtasks is not None and decomposition_artifact is not None:
                implementation_item = self.work_item_repository.create(
                    session_id=session.id,
                    work_type="implementation",
                    title=f"Post-delivery implementation follow-up for {session.task_key}",
                    owner_role_id=None,
                    source_event_id=event.id,
                    priority=95,
                )
                session = self.session_repository.update_stage_and_owner(
                    session.id,
                    current_stage="implementation_requested",
                    current_owner=None,
                )
                session = self.session_repository.update_status(session.id, SessionStatus.ACTIVE)
                _graph_event, followup_event = self._start_subtask_graph_flow(
                    session=session,
                    producer_type="operator",
                    subtasks=subtasks,
                    initial_work_item=implementation_item,
                    decomposition_artifact=decomposition_artifact,
                )
                session = self._get_session_or_raise(session.id)
                return session, event, followup_event

        if session.status != SessionStatus.ACTIVE:
            return session, event, None

        loop_event, session_count, chunk_count = self.run_loop_once()
        session = self._get_session_or_raise(session.id)
        followup_event = None
        if loop_event is not None:
            followup_event = self._append_event(
                session_id=session.id,
                event_type="snapshot_continue_processed",
                producer_type="coordinator",
                payload={
                    "task_key": session.task_key,
                    "session_count": session_count,
                    "chunk_count": chunk_count,
                    "loop_event_type": loop_event.event_type,
                },
            )
        return session, event, followup_event

    def reopen_from_qa(
        self,
        session_id: int,
        comment_text: str,
    ) -> tuple[Session, Event, Event]:
        if self.artifacts_root is None:
            raise IntakeError("Coordinator is missing artifact root")
        session = self._get_session_or_raise(session_id)
        if session.status != SessionStatus.COMPLETED:
            raise IntakeError(
                f"Session {session_id} must be completed before QA can reopen it"
            )
        normalized_comment = comment_text.strip()
        if not normalized_comment:
            raise IntakeError("QA comment text must not be empty")

        artifact_path = write_text_artifact(
            self.artifacts_root,
            session.task_key,
            "qa-reopen",
            "qa-comments.md",
            normalized_comment,
        )
        self.artifact_repository.create(
            session_id=session.id,
            stage_name="qa-reopen",
            artifact_type="qa_reopen_comments",
            path=str(artifact_path),
            metadata={"comment_length": len(normalized_comment)},
        )
        event = self._append_event(
            session_id=session.id,
            event_type="qa_reopened",
            producer_type="coordinator",
            payload={"comment_length": len(normalized_comment)},
        )
        if session.workflow_profile == "story_full":
            decomposition_artifact = self._latest_artifact_for_session_type(
                session.id,
                "task_decomposition_markdown",
            )
            subtasks: list | None
            refresh_ok = False
            if decomposition_artifact is not None and self.snapshot_adapter is not None and self.workdir_root is not None:
                subtasks, refresh_ok = self._refresh_subtask_snapshot(session)
            else:
                subtasks = self._read_snapshot_subtasks(session.task_key)
            unresolved = unresolved_subtasks(subtasks) if subtasks is not None else []
            if unresolved and subtasks is not None and decomposition_artifact is not None:
                coding_role = self._primary_coding_role_for_work_type(session, "followup_implementation")
                work_item = self.work_item_repository.create(
                    session_id=session.id,
                    work_type="followup_implementation",
                    title=f"QA reopen execution for {session.task_key}",
                    owner_role_id=coding_role.id,
                    source_event_id=event.id,
                    priority=115,
                )
                _graph_event, followup_event = self._start_subtask_graph_flow(
                    session=session,
                    producer_type="coordinator" if refresh_ok else "coordinator",
                    subtasks=subtasks,
                    initial_work_item=work_item,
                    decomposition_artifact=decomposition_artifact,
                )
                refreshed = self._get_session_or_raise(session.id)
                return refreshed, event, followup_event
        followup_event = self._enqueue_qa_followup(
            session=session,
            source_event=event,
        )
        refreshed = self._get_session_or_raise(session.id)
        return refreshed, event, followup_event

    def start_subtask_graph(
        self,
        session_id: int,
    ) -> tuple[Session, Event, Event]:
        if self.workdir_root is None or self.artifacts_root is None:
            raise IntakeError("Coordinator is missing workdir root or artifact root")

        session = self._get_session_or_raise(session_id)
        if session.workflow_profile != "story_full":
            raise IntakeError(
                f"Session {session_id} is {session.workflow_profile}, but subtask graph is only supported for story_full"
            )
        active_item: WorkItem | None = None
        if session.current_stage == "implementation_requested" and session.status == SessionStatus.ACTIVE:
            active_item = self._find_active_primary_coding_work_item(session)
        elif session.current_stage == "subtask_creation_requested" and session.status == SessionStatus.WAITING_FOR_OPERATOR:
            active_item = self._find_operator_pending_work_item(session.id)
            if active_item is not None:
                self.work_item_repository.update_status(active_item.id, WorkItemStatus.ASSIGNED)
        else:
            raise IntakeError(
                f"Session {session_id} must be at implementation_requested or subtask_creation_requested before starting subtask graph"
            )
        if active_item is None or active_item.work_type != "implementation":
            raise IntakeError("No implementation work item found for subtask graph start")
        decomposition_item = next(
            (
                item
                for item in self.work_item_repository.list_for_session(session.id)
                if item.work_type == "task_decomposition"
                and item.status == WorkItemStatus.COMPLETED
            ),
            None,
        )
        if decomposition_item is None:
            raise IntakeError("A completed task decomposition is required before starting subtask graph")
        decomposition_artifact = self._latest_artifact_for_session_type(
            session.id,
            "task_decomposition_markdown",
        )
        if decomposition_artifact is None:
            raise IntakeError("Task decomposition artifact is missing for subtask graph start")

        subtasks = self._read_snapshot_subtasks_or_raise(session.task_key)
        unresolved = unresolved_subtasks(subtasks)
        if not unresolved:
            raise IntakeError(f"No unresolved subtasks found for session {session.task_key}")
        event, followup_event = self._start_subtask_graph_flow(
            session=session,
            producer_type="operator",
            subtasks=subtasks,
            initial_work_item=active_item,
            decomposition_artifact=decomposition_artifact,
        )
        refreshed = self._get_session_or_raise(session.id)
        return refreshed, event, followup_event

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
            payload=payload,
        )
        accepted_event = self._append_event(
            session_id=session_id,
            event_type=mapped_event_type,
            producer_type="role",
            producer_id=role_name,
            payload=payload,
        )
        followup_event: Event | None = None
        if mapped_event_type == "bug_analysis_completed":
            session, followup_event = self._handle_bug_analysis_completed(session, accepted_event)
        elif mapped_event_type == "proposal_context_completed":
            session, followup_event = self._handle_proposal_context_completed(session, accepted_event)
        elif mapped_event_type == "spec_verification_blocked":
            session, followup_event = self._handle_spec_verification_blocked(session, accepted_event)
        elif mapped_event_type == "mr_comments_analysis_completed":
            session, followup_event = self._handle_mr_comments_analysis_completed(session, accepted_event)
        elif mapped_event_type == "requirements_completed":
            session, followup_event = self._handle_requirements_completed(session, accepted_event)
        elif mapped_event_type == "story_planning_blocked":
            session, followup_event = self._handle_story_planning_blocked(session, accepted_event)
        elif mapped_event_type == "boy_scout_completed":
            session, followup_event = self._handle_boy_scout_completed(session, accepted_event)
        elif mapped_event_type == "doc_harvest_completed":
            session, followup_event = self._handle_doc_harvest_completed(session, accepted_event)
        elif mapped_event_type == "acceptance_criteria_completed":
            session, followup_event = self._handle_acceptance_criteria_completed(session, accepted_event)
        elif mapped_event_type == "constraints_completed":
            session, followup_event = self._handle_constraints_completed(session, accepted_event)
        elif mapped_event_type == "spec_verification_completed":
            session, followup_event = self._handle_spec_verification_completed(session, accepted_event)
        elif mapped_event_type == "story_spec_completed":
            session, followup_event = self._handle_story_spec_completed(session, accepted_event)
        elif mapped_event_type == "task_decomposition_completed":
            session, followup_event = self._handle_task_decomposition_completed(session, accepted_event)
        elif mapped_event_type == "subtask_completed":
            session, followup_event = self._handle_subtask_completed(session, accepted_event)
        elif mapped_event_type == "implementation_completed":
            session, followup_event = self._handle_implementation_completed(session, accepted_event)
        elif mapped_event_type == "verification_failed":
            session, followup_event = self._handle_verification_failed(session, accepted_event)
        elif mapped_event_type == "verification_passed":
            session, followup_event = self._handle_verification_passed(session, accepted_event)
        elif mapped_event_type == "verification_blocked":
            session, followup_event = self._handle_verification_blocked(session, accepted_event)
        elif mapped_event_type == "self_review_passed":
            session, followup_event = self._handle_self_review_passed(session, accepted_event)
        elif mapped_event_type == "self_review_issues_found":
            session, followup_event = self._handle_self_review_issues_found(session, accepted_event)
        elif mapped_event_type == "self_review_blocked":
            session, followup_event = self._handle_self_review_blocked(session, accepted_event)
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
            session_id=self._runtime_session_id_for_role(role, session),
            backend_name=role.runtime_backend,
        )
        chunks = self.session_backend.read_output(runtime_role)
        file_result = self._consume_role_result_file(session, role)
        if not chunks and file_result is None:
            return session, None, 0

        if chunks:
            self._record_runtime_output_artifacts(session, role, chunks)
        if file_result is not None:
            output_type, output_payload = file_result
            handled_session = self._handle_collected_role_output(
                session=session,
                role=role,
                output_type=output_type,
                output_payload=output_payload,
            )
            if handled_session is not None:
                session = handled_session
        elif chunks:
            session = self._apply_runtime_output_markers(session, role, chunks)
        event = self._append_event(
            session_id=session.id,
            event_type="role_output_collected",
            producer_type="coordinator",
            payload={
                "role_name": role_name,
                "chunk_count": len(chunks) + (1 if file_result is not None else 0),
            },
        )
        return session, event, len(chunks) + (1 if file_result is not None else 0)

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
                session_id=self._runtime_session_id_for_role(role, session),
                backend_name=role.runtime_backend,
            )
            chunks = self.session_backend.read_output(runtime_role)
            file_result = self._consume_role_result_file(session, role)
            if not chunks and file_result is None:
                continue
            if chunks:
                self._record_runtime_output_artifacts(session, role, chunks)
            if file_result is not None:
                output_type, output_payload = file_result
                handled_session = self._handle_collected_role_output(
                    session=session,
                    role=role,
                    output_type=output_type,
                    output_payload=output_payload,
                )
                if handled_session is not None:
                    session = handled_session
            elif chunks:
                session = self._apply_runtime_output_markers(session, role, chunks)
            total_chunks += len(chunks) + (1 if file_result is not None else 0)

        if total_chunks == 0:
            return session, None, len(roles), 0

        event = self._append_event(
            session_id=session.id,
            event_type="session_output_polled",
            producer_type="coordinator",
            payload={
                "role_count": len(roles),
                "chunk_count": total_chunks,
            },
        )
        return session, event, len(roles), total_chunks

    def _consume_role_result_file(
        self,
        session: Session,
        role: Role,
    ) -> tuple[str, dict] | None:
        if self.role_workspace_manager is None:
            return None
        result_path = self.role_workspace_manager.role_directory(session.task_key, role.role_name) / "RESULT.json"
        if not result_path.is_file():
            return None
        raw_text = result_path.read_text()
        parsed = self._parse_role_result_json(raw_text)
        if parsed is None:
            return None
        if not isinstance(parsed, dict):
            return None
        output_type = parsed.get("output_type")
        output_payload = parsed.get("payload")
        if not isinstance(output_type, str) or not isinstance(output_payload, dict):
            return None
        artifact_path = write_text_artifact(
            self.artifacts_root,
            session.task_key,
            f"role-result-{role.role_name}",
            "RESULT.json",
            json.dumps(parsed, indent=2, sort_keys=True),
        )
        self.artifact_repository.create(
            session_id=session.id,
            role_id=role.id,
            stage_name=f"role-result-{role.role_name}",
            artifact_type="role_result_json",
            path=str(artifact_path),
            metadata={
                "role_name": role.role_name,
                "current_stage": session.current_stage,
                "source_path": str(result_path),
            },
        )
        result_path.unlink(missing_ok=True)
        return output_type, output_payload

    def _parse_role_result_json(self, raw_text: str) -> dict[str, object] | None:
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            repaired_text = self._escape_raw_control_chars_in_json_strings(raw_text)
            try:
                parsed = json.loads(repaired_text)
            except json.JSONDecodeError:
                return None
        if not isinstance(parsed, dict):
            return None
        return parsed

    def _escape_raw_control_chars_in_json_strings(self, raw_text: str) -> str:
        result: list[str] = []
        in_string = False
        escape = False
        for char in raw_text:
            if in_string:
                if escape:
                    result.append(char)
                    escape = False
                    continue
                if char == "\\":
                    result.append(char)
                    escape = True
                    continue
                if char == '"':
                    result.append(char)
                    in_string = False
                    continue
                if char == "\n":
                    result.append("\\n")
                    continue
                if char == "\r":
                    result.append("\\r")
                    continue
                if char == "\t":
                    result.append("\\t")
                    continue
                result.append(char)
                continue
            result.append(char)
            if char == '"':
                in_string = True
                escape = False
        return "".join(result)

    def _handle_collected_role_output(
        self,
        session: Session,
        role: Role,
        output_type: str,
        output_payload: dict,
    ) -> Session | None:
        output_mismatch = self._stale_role_output_mismatch(
            session=session,
            role_name=role.role_name,
            output_type=output_type,
            output_payload=output_payload,
        )
        if output_mismatch is not None:
            self._append_event(
                session_id=session.id,
                event_type="stale_role_output_ignored",
                producer_type="coordinator",
                payload={
                    "role_name": role.role_name,
                    "output_type": output_type,
                    "current_stage": session.current_stage,
                    "current_owner": session.current_owner,
                    **output_mismatch,
                },
            )
            return None
        if self._should_ignore_stale_role_output(
            session=session,
            role_name=role.role_name,
            output_type=output_type,
        ):
            self._append_event(
                session_id=session.id,
                event_type="stale_role_output_ignored",
                producer_type="coordinator",
                payload={
                    "role_name": role.role_name,
                    "output_type": output_type,
                    "current_stage": session.current_stage,
                    "current_owner": session.current_owner,
                },
            )
            return None
        if output_type == "error":
            self._record_runtime_marker_artifact(
                session=session,
                role=role,
                marker_type="error",
                payload=output_payload,
            )
            self._append_runtime_marker_event(
                session=session,
                role=role,
                marker_type="error",
                payload=output_payload,
            )
            return self._escalate_runtime_error(
                session=session,
                role=role,
                payload=output_payload,
            )
        updated_session, _, _ = self.handle_role_output(
            session_id=session.id,
            role_name=role.role_name,
            output_type=output_type,
            payload=output_payload,
        )
        return updated_session

    def _should_ignore_stale_role_output(
        self,
        session: Session,
        role_name: str,
        output_type: str,
    ) -> bool:
        # A live verifier can finish its previous round slightly after the coordinator has
        # already routed the implementer into verification corrections. Treat that late
        # result as stale instead of failing the whole session intake path.
        if (
            role_name in {IMPLEMENTER_ROLE, BUG_FIXER_ROLE}
            and output_type in {"completed", "error"}
            and session.current_owner != role_name
        ):
            return True
        if (
            role_name == IMPLEMENTER_ROLE
            and output_type == "completed"
            and session.current_stage == "subtask_implementation_requested"
            and self._active_subtask_completion_dispatch_missing(session)
        ):
            return True
        if (
            role_name == VERIFICATION_COORDINATOR_ROLE
            and output_type in {"passed", "completed", "failed", "blocked_verification_cycle", "error"}
            and session.current_owner != VERIFICATION_COORDINATOR_ROLE
        ):
            return True
        if (
            role_name == CODE_REVIEWER_ROLE
            and output_type in {"passed", "completed", "failed", "blocked_review_cycle", "error"}
            and session.current_owner != CODE_REVIEWER_ROLE
        ):
            return True
        if (
            role_name == CODE_SCOUT_ROLE
            and output_type in {"passed", "completed", "skipped_not_needed", "error"}
            and session.current_owner != CODE_SCOUT_ROLE
        ):
            return True
        if (
            role_name == DOC_HARVEST_ROLE
            and output_type in {"passed", "completed", "skipped_not_needed", "error"}
            and session.current_owner != DOC_HARVEST_ROLE
        ):
            return True
        if (
            role_name == MR_COMMENTS_ANALYST_ROLE
            and output_type in {"passed", "completed", "error"}
            and session.current_owner != MR_COMMENTS_ANALYST_ROLE
        ):
            return True
        return False

    def _stale_role_output_mismatch(
        self,
        *,
        session: Session,
        role_name: str,
        output_type: str,
        output_payload: dict,
    ) -> dict[str, str | int | None] | None:
        if role_name not in {IMPLEMENTER_ROLE, BUG_FIXER_ROLE} or output_type != "completed":
            return None

        active_item = self._find_active_primary_coding_work_item(session)
        if active_item is None:
            return None

        payload_work_item_id = output_payload.get("work_item_id")
        if payload_work_item_id != active_item.id:
            return {
                "reason": "address_mismatch",
                "expected_work_item_id": active_item.id,
                "payload_work_item_id": payload_work_item_id if isinstance(payload_work_item_id, int) else None,
                "expected_subtask_key": None,
                "payload_subtask_key": None,
            }

        if active_item.work_type != "subtask_implementation":
            return None

        expected_subtask_key = self._parse_subtask_work_item_title(active_item.title)["key"]
        payload_subtask_key = output_payload.get("subtask_key")
        normalized_payload_subtask_key = (
            payload_subtask_key.strip()
            if isinstance(payload_subtask_key, str)
            else None
        )

        if normalized_payload_subtask_key == expected_subtask_key:
            return None

        return {
            "reason": "address_mismatch",
            "expected_work_item_id": active_item.id,
            "payload_work_item_id": payload_work_item_id,
            "expected_subtask_key": expected_subtask_key,
            "payload_subtask_key": normalized_payload_subtask_key,
        }

    def _active_subtask_completion_dispatch_missing(self, session: Session) -> bool:
        active_item = self._find_active_primary_coding_work_item(session)
        if active_item is None:
            return True
        return not self._has_dispatch_event(
            session.id,
            active_item.id,
            "subtask_implementation_requested",
        )

    def run_loop_once(self) -> tuple[Event | None, int, int]:
        active_sessions = self.session_repository.list_by_status(SessionStatus.ACTIVE)
        total_chunks = 0
        polled_sessions = 0
        reconciled_sessions = 0

        for session in active_sessions:
            session = self._recover_dead_owner_runtime_if_needed(session)
            if self._reconcile_session_dispatch(session):
                reconciled_sessions += 1
            _, _, _, chunk_count = self.poll_session_output(session.id)
            polled_sessions += 1
            total_chunks += chunk_count

        if polled_sessions == 0:
            return None, 0, 0

        summary_event = self._append_event(
            session_id=active_sessions[0].id,
            event_type="coordinator_loop_ran",
            producer_type="coordinator",
            payload={
                "session_count": polled_sessions,
                "chunk_count": total_chunks,
                "reconciled_count": reconciled_sessions,
            },
        )
        return summary_event, polled_sessions, total_chunks

    def _recover_dead_owner_runtime_if_needed(self, session: Session) -> Session:
        if session.current_owner is None:
            return session
        role = self.role_repository.get_by_name(session.id, session.current_owner)
        if role is None or role.runtime_handle is None or role.status != RoleStatus.RUNNING:
            return session

        runtime_role = RuntimeRoleHandle(
            role_id=role.runtime_handle,
            session_id=self._runtime_session_id_for_role(role, session),
            backend_name=role.runtime_backend,
        )
        if self.session_backend.is_role_alive(runtime_role):
            return session

        if self._auto_recovery_already_attempted(session.id, role.role_name, role.runtime_handle):
            return session

        return self._attempt_dead_owner_runtime_recovery(session, role)

    def _auto_recovery_already_attempted(self, session_id: int, role_name: str, dead_runtime_handle: str) -> bool:
        for event in reversed(self.event_repository.list_for_session(session_id)):
            if event.event_type not in {
                "runtime_role_auto_recovery_attempted",
                "runtime_role_auto_recovery_failed",
            }:
                continue
            if event.payload.get("role_name") != role_name:
                continue
            if event.payload.get("dead_runtime_handle") == dead_runtime_handle:
                return True
        return False

    def _attempt_dead_owner_runtime_recovery(self, session: Session, role: Role) -> Session:
        dead_runtime_handle = role.runtime_handle
        assert dead_runtime_handle is not None
        recovery_event_type = "runtime_role_auto_recovery_attempted"
        try:
            runtime_role = self._spawn_role_runtime(
                runtime_session=self._runtime_session_handle_for_session(session),
                task_key=session.task_key,
                role_name=role.role_name,
                role_config=(session.role_config or {}).get(role.role_name),
                resume_mode="native",
            )
        except Exception as exc:
            self.role_repository.update_status(role.id, RoleStatus.FAILED)
            self._append_event(
                session_id=session.id,
                event_type="runtime_role_auto_recovery_failed",
                producer_type="coordinator",
                payload={
                    "role_name": role.role_name,
                    "dead_runtime_handle": dead_runtime_handle,
                    "error": str(exc),
                    "current_stage": session.current_stage,
                },
            )
            self.work_item_repository.mark_assigned_as_waiting_for_operator(session.id)
            session = self.session_repository.update_stage_and_owner(
                session.id,
                current_stage=session.current_stage,
                current_owner=None,
            )
            session = self.session_repository.update_status(session.id, SessionStatus.WAITING_FOR_OPERATOR)
            self._append_event(
                session_id=session.id,
                event_type="session_escalated_to_operator",
                producer_type="coordinator",
                payload={
                    "reason": "runtime_recovery_failed",
                    "role_name": role.role_name,
                    "summary": "automatic runtime recovery failed",
                    "details": str(exc),
                    "current_stage": session.current_stage,
                },
            )
            return session

        role = self.role_repository.update_runtime(
            role.id,
            runtime_backend=runtime_role.backend_name,
            runtime_handle=runtime_role.role_id,
            status=RoleStatus.RUNNING,
        )
        session = self.session_repository.update_status(session.id, SessionStatus.ACTIVE)
        self._append_event(
            session_id=session.id,
            event_type=recovery_event_type,
            producer_type="coordinator",
            payload={
                "role_name": role.role_name,
                "dead_runtime_handle": dead_runtime_handle,
                "runtime_handle": role.runtime_handle,
                "current_stage": session.current_stage,
            },
        )
        self._reactivate_restarted_owner_work(session, role)
        return self._get_session_or_raise(session.id)

    def pause_session(self, session_id: int) -> tuple[Session, Event]:
        session = self._get_session_or_raise(session_id)
        if session.status != SessionStatus.ACTIVE:
            raise IntakeError(
                f"Session {session_id} is not active; current status is {session.status.value}"
            )
        session = self.session_repository.update_status(session.id, SessionStatus.PAUSED)
        event = self._append_event(
            session_id=session.id,
            event_type="session_paused_by_operator",
            producer_type="operator",
            payload={
                "current_stage": session.current_stage,
                "current_owner": session.current_owner,
            },
        )
        return session, event

    def resume_session(self, session_id: int) -> tuple[Session, Event, Event | None]:
        session = self._get_session_or_raise(session_id)
        if session.status == SessionStatus.WAITING_FOR_OPERATOR:
            return self._resume_waiting_session(session)
        if session.status == SessionStatus.PAUSED:
            return self._resume_paused_session(session)
        raise IntakeError(
            f"Session {session_id} is not resumable; current status is {session.status.value}"
        )

    def _resume_waiting_session(self, session: Session) -> tuple[Session, Event, Event | None]:
        work_item = self._find_operator_pending_work_item(session.id)
        if work_item is None:
            raise IntakeError(f"Session {session.id} has no operator-pending work item to resume")
        if work_item.owner_role_id is None:
            raise IntakeError(f"Work item {work_item.id} is missing an owner role")

        role = self.role_repository.get_by_id(work_item.owner_role_id)
        if role is None:
            raise IntakeError(f"Owner role {work_item.owner_role_id} is missing for session {session.id}")

        self.work_item_repository.update_status(work_item.id, WorkItemStatus.ASSIGNED)
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage=session.current_stage,
            current_owner=role.role_name,
        )
        session = self.session_repository.update_status(session.id, SessionStatus.ACTIVE)
        resumed_event = self._append_event(
            session_id=session.id,
            event_type="session_resumed_by_operator",
            producer_type="operator",
            payload={
                "resume_reason": "waiting_for_operator",
                "role_name": role.role_name,
                "work_item_id": work_item.id,
                "current_stage": session.current_stage,
            },
        )
        runtime_blocker = self._latest_runtime_blocker_event(session.id)
        if runtime_blocker is not None and runtime_blocker.payload.get("resume_strategy") == "reactivate_only":
            return session, resumed_event, None
        if session.current_stage == "subtask_creation_requested":
            return self._resume_after_subtask_creation(session, role, work_item, resumed_event)
        instruction = self._stage_instruction(
            session.current_stage,
            session.task_key,
            workflow_profile=session.workflow_profile,
            role_name=role.role_name,
            session_policy=session.policy,
        )
        if instruction is None:
            raise IntakeError(f"Session {session.id} cannot be resumed from stage {session.current_stage}")
        dispatch_event = self._dispatch_role_work(
            session=session,
            role=role,
            work_item=work_item,
            stage_name=session.current_stage,
            instruction=instruction,
        )
        return session, resumed_event, dispatch_event

    def _resume_after_subtask_creation(
        self,
        session: Session,
        role: Role,
        work_item: WorkItem,
        resumed_event: Event,
    ) -> tuple[Session, Event, Event | None]:
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="implementation_requested",
            current_owner=role.role_name,
        )
        subtasks = self._read_snapshot_subtasks(session.task_key)
        decomposition_artifact = self._latest_artifact_for_session_type(
            session.id,
            "task_decomposition_markdown",
        )
        if (
            work_item.work_type == "implementation"
            and decomposition_artifact is not None
            and subtasks is not None
            and unresolved_subtasks(subtasks)
        ):
            _graph_event, followup_event = self._start_subtask_graph_flow(
                session=session,
                producer_type="operator",
                subtasks=subtasks,
                initial_work_item=work_item,
                decomposition_artifact=decomposition_artifact,
            )
            refreshed = self._get_session_or_raise(session.id)
            return refreshed, resumed_event, followup_event

        instruction = self._stage_instruction(
            "implementation_requested",
            session.task_key,
            workflow_profile=session.workflow_profile,
            role_name=role.role_name,
            session_policy=session.policy,
        )
        if instruction is None:
            raise IntakeError(f"Session {session.id} cannot start implementation after subtask creation")
        dispatch_event = self._dispatch_role_work(
            session=session,
            role=role,
            work_item=work_item,
            stage_name="implementation_requested",
            instruction=instruction,
        )
        refreshed = self._get_session_or_raise(session.id)
        return refreshed, resumed_event, dispatch_event

    def _latest_runtime_blocker_event(self, session_id: int) -> Event | None:
        for event in reversed(self.event_repository.list_for_session(session_id)):
            if (
                event.event_type == "session_escalated_to_operator"
                and event.payload.get("reason") == "runtime_error"
            ) or event.event_type == "role_runtime_error_reported":
                return event
        return None

    def send_operator_runtime_input(self, session_id: int, text: str) -> tuple[Session, Event]:
        session = self._get_session_or_raise(session_id)
        if session.status != SessionStatus.WAITING_FOR_OPERATOR:
            raise IntakeError(
                f"Session {session_id} is not waiting for operator; current status is {session.status.value}"
            )
        work_item = self._find_operator_pending_work_item(session.id)
        if work_item is None:
            raise IntakeError(f"Session {session.id} has no operator-pending work item to continue")
        if work_item.owner_role_id is None:
            raise IntakeError(f"Work item {work_item.id} is missing an owner role")
        role = self.role_repository.get_by_id(work_item.owner_role_id)
        if role is None:
            raise IntakeError(f"Owner role {work_item.owner_role_id} is missing for session {session.id}")
        if role.runtime_handle is None:
            raise IntakeError(f"Role {role.role_name} has no runtime handle for session {session.id}")

        self.work_item_repository.update_status(work_item.id, WorkItemStatus.ASSIGNED)
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage=session.current_stage,
            current_owner=role.role_name,
        )
        session = self.session_repository.update_status(session.id, SessionStatus.ACTIVE)
        runtime_role = RuntimeRoleHandle(
            role_id=role.runtime_handle,
            session_id=self._runtime_session_id_for_role(role, session),
            backend_name=role.runtime_backend,
        )
        self.session_backend.send_input(runtime_role, text)
        event = self._append_event(
            session_id=session.id,
            event_type="operator_runtime_input_sent",
            producer_type="operator",
            payload={
                "role_name": role.role_name,
                "current_stage": session.current_stage,
                "input_length": len(text),
            },
        )
        return session, event

    def _resume_paused_session(self, session: Session) -> tuple[Session, Event, Event]:
        if session.current_owner is None:
            raise IntakeError(
                f"Paused session {session.id} has no current owner and cannot be resumed"
            )
        role = self.role_repository.get_by_name(session.id, session.current_owner)
        if role is None:
            raise IntakeError(f"Owner role {session.current_owner} is missing for session {session.id}")
        work_item = self._find_active_work_item_for_role(session.id, role.id)
        if work_item is None:
            raise IntakeError(f"Paused session {session.id} has no assigned work item to resume")
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage=session.current_stage,
            current_owner=role.role_name,
        )
        session = self.session_repository.update_status(session.id, SessionStatus.ACTIVE)
        resumed_event = self._append_event(
            session_id=session.id,
            event_type="session_resumed_by_operator",
            producer_type="operator",
            payload={
                "resume_reason": "paused",
                "role_name": role.role_name,
                "work_item_id": work_item.id,
                "current_stage": session.current_stage,
            },
        )
        instruction = self._stage_instruction(
            session.current_stage,
            session.task_key,
            workflow_profile=session.workflow_profile,
            role_name=role.role_name,
            session_policy=session.policy,
        )
        if instruction is None:
            raise IntakeError(f"Session {session.id} cannot be resumed from stage {session.current_stage}")
        dispatch_event = self._dispatch_role_work(
            session=session,
            role=role,
            work_item=work_item,
            stage_name=session.current_stage,
            instruction=instruction,
        )
        return session, resumed_event, dispatch_event

    def retry_session(self, session_id: int) -> tuple[Session, Event, Event]:
        session = self._get_session_or_raise(session_id)
        if session.status != SessionStatus.WAITING_FOR_OPERATOR:
            raise IntakeError(
                f"Session {session_id} is not waiting for operator; current status is {session.status.value}"
            )

        previous_work_item = self._find_operator_pending_work_item(session.id)
        if previous_work_item is None:
            raise IntakeError(f"Session {session_id} has no operator-pending work item to retry")
        if previous_work_item.owner_role_id is None:
            raise IntakeError(f"Work item {previous_work_item.id} is missing an owner role")

        role = self.role_repository.get_by_id(previous_work_item.owner_role_id)
        if role is None:
            raise IntakeError(
                f"Owner role {previous_work_item.owner_role_id} is missing for session {session_id}"
            )

        retry_item = self.work_item_repository.create(
            session_id=session.id,
            work_type=previous_work_item.work_type,
            title=self._retry_work_item_title(previous_work_item.title),
            owner_role_id=previous_work_item.owner_role_id,
            source_event_id=None,
            priority=previous_work_item.priority,
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage=session.current_stage,
            current_owner=role.role_name,
        )
        session = self.session_repository.update_status(session.id, SessionStatus.ACTIVE)
        retried_event = self._append_event(
            session_id=session.id,
            event_type="session_retried_by_operator",
            producer_type="operator",
            payload={
                "role_name": role.role_name,
                "previous_work_item_id": previous_work_item.id,
                "retry_work_item_id": retry_item.id,
                "current_stage": session.current_stage,
            },
        )
        instruction = self._stage_instruction(
            session.current_stage,
            session.task_key,
            workflow_profile=session.workflow_profile,
            role_name=role.role_name,
            session_policy=session.policy,
        )
        if instruction is None:
            raise IntakeError(f"Session {session_id} cannot be retried from stage {session.current_stage}")
        dispatch_event = self._dispatch_role_work(
            session=session,
            role=role,
            work_item=retry_item,
            stage_name=session.current_stage,
            instruction=instruction,
        )
        return session, retried_event, dispatch_event

    def redirect_session(
        self,
        session_id: int,
        target_role_name: str,
    ) -> tuple[Session, Event, Event]:
        session = self._get_session_or_raise(session_id)
        if session.status != SessionStatus.WAITING_FOR_OPERATOR:
            raise IntakeError(
                f"Session {session_id} is not waiting for operator; current status is {session.status.value}"
            )
        allowed_targets = ALLOWED_STAGE_ROLE_TARGETS.get(session.current_stage, set())
        if target_role_name not in allowed_targets:
            allowed_list = ", ".join(sorted(allowed_targets)) if allowed_targets else "none"
            raise IntakeError(
                f"Role {target_role_name} is not allowed for stage {session.current_stage}; "
                f"allowed targets: {allowed_list}"
            )

        previous_work_item = self._find_operator_pending_work_item(session.id)
        if previous_work_item is None:
            raise IntakeError(f"Session {session_id} has no operator-pending work item to redirect")
        if previous_work_item.owner_role_id is None:
            raise IntakeError(f"Work item {previous_work_item.id} is missing an owner role")

        previous_role = self.role_repository.get_by_id(previous_work_item.owner_role_id)
        if previous_role is None:
            raise IntakeError(
                f"Owner role {previous_work_item.owner_role_id} is missing for session {session_id}"
            )
        if previous_role.role_name == target_role_name:
            raise IntakeError(
                f"Redirect target role must differ from current parked owner {target_role_name}"
            )

        target_role = self.role_repository.get_by_name(session.id, target_role_name)
        if target_role is None:
            raise IntakeError(f"Target role {target_role_name} is missing for session {session_id}")

        redirected_work_item = self.work_item_repository.create(
            session_id=session.id,
            work_type=previous_work_item.work_type,
            title=self._redirect_work_item_title(previous_work_item.title, target_role_name),
            owner_role_id=target_role.id,
            source_event_id=None,
            priority=previous_work_item.priority,
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage=session.current_stage,
            current_owner=target_role.role_name,
        )
        session = self.session_repository.update_status(session.id, SessionStatus.ACTIVE)
        redirected_event = self._append_event(
            session_id=session.id,
            event_type="session_redirected_by_operator",
            producer_type="operator",
            payload={
                "previous_role_name": previous_role.role_name,
                "target_role_name": target_role.role_name,
                "previous_work_item_id": previous_work_item.id,
                "redirect_work_item_id": redirected_work_item.id,
                "current_stage": session.current_stage,
            },
        )
        instruction = self._stage_instruction(
            session.current_stage,
            session.task_key,
            workflow_profile=session.workflow_profile,
            role_name=target_role.role_name,
            session_policy=session.policy,
        )
        if instruction is None:
            raise IntakeError(f"Session {session_id} cannot be redirected from stage {session.current_stage}")
        dispatch_event = self._dispatch_role_work(
            session=session,
            role=target_role,
            work_item=redirected_work_item,
            stage_name=session.current_stage,
            instruction=instruction,
        )
        return session, redirected_event, dispatch_event

    def _enqueue_initial_implementation(
        self,
        session: Session,
        resolved_task_key: str,
        source_event: Event,
        additional_context: str | None = None,
    ) -> Event:
        coding_role = self._primary_coding_role_for_work_type(session, "implementation")

        work_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="implementation",
            title=f"Initial implementation for {resolved_task_key}",
            owner_role_id=coding_role.id,
            source_event_id=source_event.id,
            priority=100,
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="implementation_requested",
            current_owner=coding_role.role_name,
        )
        instruction = self._stage_instruction(
            "implementation_requested",
            resolved_task_key,
            workflow_profile=session.workflow_profile,
            role_name=coding_role.role_name,
            session_policy=session.policy,
        )
        if instruction is None:
            raise IntakeError(
                f"No implementation instruction is available for role {coding_role.role_name}"
            )
        if additional_context:
            instruction = f"{instruction}\n\n{additional_context}"
        self._dispatch_role_work(
            session=session,
            role=coding_role,
            work_item=work_item,
            stage_name="implementation_requested",
            instruction=instruction,
        )
        return self._append_event(
            session_id=session.id,
            event_type="implementation_requested",
            producer_type="coordinator",
            payload={
                "task_key": resolved_task_key,
                "role_name": coding_role.role_name,
                "work_item_id": work_item.id,
                "current_stage": session.current_stage,
            },
        )

    def _enqueue_bug_analysis(
        self,
        session: Session,
        source_event: Event,
        additional_context: str | None = None,
    ) -> Event:
        coding_role = self._primary_coding_role_for_work_type(session, "bug_analysis")

        work_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="bug_analysis",
            title=f"Bug analysis for {session.task_key}",
            owner_role_id=coding_role.id,
            source_event_id=source_event.id,
            priority=105,
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="bug_analysis_requested",
            current_owner=coding_role.role_name,
        )
        test_policy = (session.policy or {}).get("test_policy", "enabled")
        base_instruction = self._stage_instruction(
            "bug_analysis_requested",
            session.task_key,
            workflow_profile=session.workflow_profile,
            role_name=coding_role.role_name,
            session_policy=session.policy,
        )
        if base_instruction is None:
            raise IntakeError(
                f"No bug analysis instruction is available for role {coding_role.role_name}"
            )
        instruction = (
            f"{base_instruction}\n"
            f"Test policy for this session: {test_policy}."
        )
        if additional_context:
            instruction = f"{instruction}\n\n{additional_context}"
        self._dispatch_role_work(
            session=session,
            role=coding_role,
            work_item=work_item,
            stage_name="bug_analysis_requested",
            instruction=instruction,
        )
        return self._append_event(
            session_id=session.id,
            event_type="bug_analysis_requested",
            producer_type="coordinator",
            payload={
                "task_key": session.task_key,
                "role_name": coding_role.role_name,
                "work_item_id": work_item.id,
                "current_stage": session.current_stage,
                "test_policy": test_policy,
            },
        )

    def _enqueue_story_spec(
        self,
        session: Session,
        source_event: Event,
        additional_context: str | None = None,
    ) -> Event:
        story_spec_role = self._ensure_on_demand_role(session, STORY_SPEC_WORKER_ROLE)

        work_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="story_spec",
            title=f"Story planning and spec for {session.task_key}",
            owner_role_id=story_spec_role.id,
            source_event_id=source_event.id,
            priority=104,
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="story_spec_requested",
            current_owner=STORY_SPEC_WORKER_ROLE,
        )
        instruction = (
            f"Prepare the final implementation-shaping story spec for {session.task_key} before coding. "
            "Turn the verified planning package into a durable implementation guide that clarifies intended scope, key constraints, implementation approach, "
            "and architecture-sensitive decisions that should guide decomposition and coding."
        )
        if additional_context:
            instruction = f"{instruction}\n\n{additional_context}"
        self._dispatch_role_work(
            session=session,
            role=story_spec_role,
            work_item=work_item,
            stage_name="story_spec_requested",
            instruction=instruction,
        )
        return self._append_event(
            session_id=session.id,
            event_type="story_spec_requested",
            producer_type="coordinator",
            payload={
                "task_key": session.task_key,
                "role_name": STORY_SPEC_WORKER_ROLE,
                "work_item_id": work_item.id,
                "current_stage": session.current_stage,
            },
        )

    def _enqueue_proposal_context(
        self,
        session: Session,
        source_event: Event,
        additional_context: str | None = None,
    ) -> Event:
        proposal_role = self._ensure_on_demand_role(session, PROPOSAL_CONTEXT_WORKER_ROLE)

        work_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="proposal_context",
            title=f"Proposal and context preparation for {session.task_key}",
            owner_role_id=proposal_role.id,
            source_event_id=source_event.id,
            priority=103,
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="proposal_context_requested",
            current_owner=PROPOSAL_CONTEXT_WORKER_ROLE,
        )
        instruction = (
            f"Produce the proposal and context package for story {session.task_key} before requirements and final story spec. "
            "Write or refresh `spec/proposal.md`, always write `spec/context/feature-overview.md`, "
            "write the other `spec/context/*` files only when they contain grounded task-specific findings, "
            "and synthesize the key problem statement, conflicts or clarifications from the snapshot, and the smallest useful project/context findings for later story roles."
        )
        if additional_context:
            instruction = f"{instruction}\n\n{additional_context}"
        self._dispatch_role_work(
            session=session,
            role=proposal_role,
            work_item=work_item,
            stage_name="proposal_context_requested",
            instruction=instruction,
        )
        self._emit_proposal_context_link_warning(session)
        return self._append_event(
            session_id=session.id,
            event_type="proposal_context_requested",
            producer_type="coordinator",
            payload={
                "task_key": session.task_key,
                "role_name": PROPOSAL_CONTEXT_WORKER_ROLE,
                "work_item_id": work_item.id,
                "current_stage": session.current_stage,
            },
        )

    def _enqueue_requirements(
        self,
        session: Session,
        source_event: Event,
        additional_context: str | None = None,
    ) -> Event:
        requirements_role = self._ensure_on_demand_role(session, REQUIREMENTS_CLARIFIER_WORKER_ROLE)

        work_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="requirements",
            title=f"Requirements clarification for {session.task_key}",
            owner_role_id=requirements_role.id,
            source_event_id=source_event.id,
            priority=102,
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="requirements_requested",
            current_owner=REQUIREMENTS_CLARIFIER_WORKER_ROLE,
        )
        clarification_mode = self._requirements_clarification_mode(session.policy)
        instruction = (
            f"Clarify the implementation requirements for story {session.task_key}. "
            "Resolve assumptions, edge cases, and out-of-scope boundaries so the later story-spec step can focus on implementation structure.\n"
            f"Clarification mode for this session: {clarification_mode}."
        )
        if additional_context:
            instruction = f"{instruction}\n\n{additional_context}"
        self._dispatch_role_work(
            session=session,
            role=requirements_role,
            work_item=work_item,
            stage_name="requirements_requested",
            instruction=instruction,
            extra_hydration={
                "requirements_clarification_mode": clarification_mode,
            },
        )
        return self._append_event(
            session_id=session.id,
            event_type="requirements_requested",
            producer_type="coordinator",
            payload={
                "task_key": session.task_key,
                "role_name": REQUIREMENTS_CLARIFIER_WORKER_ROLE,
                "work_item_id": work_item.id,
                "current_stage": session.current_stage,
            },
        )

    def _enqueue_acceptance_criteria(
        self,
        session: Session,
        source_event: Event,
        additional_context: str | None = None,
    ) -> Event:
        acceptance_role = self._ensure_on_demand_role(session, ACCEPTANCE_CRITERIA_WORKER_ROLE)

        work_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="acceptance_criteria",
            title=f"Acceptance criteria preparation for {session.task_key}",
            owner_role_id=acceptance_role.id,
            source_event_id=source_event.id,
            priority=101,
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="acceptance_criteria_requested",
            current_owner=ACCEPTANCE_CRITERIA_WORKER_ROLE,
        )
        instruction = (
            f"Prepare explicit acceptance criteria for story {session.task_key}. "
            "Use independently testable WHEN-THEN-SHALL criteria, cover happy paths, edge cases, and error scenarios from the clarified requirements, "
            "and ensure every meaningful clarified requirement decision is covered before the final story-spec step."
        )
        if additional_context:
            instruction = f"{instruction}\n\n{additional_context}"
        self._dispatch_role_work(
            session=session,
            role=acceptance_role,
            work_item=work_item,
            stage_name="acceptance_criteria_requested",
            instruction=instruction,
        )
        return self._append_event(
            session_id=session.id,
            event_type="acceptance_criteria_requested",
            producer_type="coordinator",
            payload={
                "task_key": session.task_key,
                "role_name": ACCEPTANCE_CRITERIA_WORKER_ROLE,
                "work_item_id": work_item.id,
                "current_stage": session.current_stage,
            },
        )

    def _enqueue_constraints(
        self,
        session: Session,
        source_event: Event,
        additional_context: str | None = None,
    ) -> Event:
        constraints_role = self._ensure_on_demand_role(session, CONSTRAINTS_WORKER_ROLE)

        work_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="constraints",
            title=f"Constraints preparation for {session.task_key}",
            owner_role_id=constraints_role.id,
            source_event_id=source_event.id,
            priority=100,
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="constraints_requested",
            current_owner=CONSTRAINTS_WORKER_ROLE,
        )
        instruction = (
            f"Prepare grounded implementation constraints for story {session.task_key}. "
            "Use `spec/context/project.md` as architectural ground truth, cite it instead of restating generic conventions, "
            "and surface task-specific MUST, MUST NOT, and SHOULD constraints that should guide the final story-spec step."
        )
        if additional_context:
            instruction = f"{instruction}\n\n{additional_context}"
        self._dispatch_role_work(
            session=session,
            role=constraints_role,
            work_item=work_item,
            stage_name="constraints_requested",
            instruction=instruction,
        )
        return self._append_event(
            session_id=session.id,
            event_type="constraints_requested",
            producer_type="coordinator",
            payload={
                "task_key": session.task_key,
                "role_name": CONSTRAINTS_WORKER_ROLE,
                "work_item_id": work_item.id,
                "current_stage": session.current_stage,
            },
        )

    def _enqueue_spec_verification(
        self,
        session: Session,
        source_event: Event,
        additional_context: str | None = None,
    ) -> Event:
        verifier_role = self._ensure_on_demand_role(session, SPEC_VERIFIER_WORKER_ROLE)

        work_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="spec_verification",
            title=f"Planning verification for {session.task_key}",
            owner_role_id=verifier_role.id,
            source_event_id=source_event.id,
            priority=99,
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="spec_verification_requested",
            current_owner=SPEC_VERIFIER_WORKER_ROLE,
        )
        instruction = (
            f"Verify the assembled planning package for story {session.task_key} before the final story-spec step. "
            "Check for contradictions, missing implementation-shaping details, or planning gaps that should be surfaced before coding starts."
        )
        if additional_context:
            instruction = f"{instruction}\n\n{additional_context}"
        self._dispatch_role_work(
            session=session,
            role=verifier_role,
            work_item=work_item,
            stage_name="spec_verification_requested",
            instruction=instruction,
        )
        return self._append_event(
            session_id=session.id,
            event_type="spec_verification_requested",
            producer_type="coordinator",
            payload={
                "task_key": session.task_key,
                "role_name": SPEC_VERIFIER_WORKER_ROLE,
                "work_item_id": work_item.id,
                "current_stage": session.current_stage,
            },
        )

    def _enqueue_task_decomposition(
        self,
        session: Session,
        source_event: Event,
        additional_context: str | None = None,
    ) -> Event:
        decomposer_role = self._ensure_on_demand_role(session, TASK_DECOMPOSER_WORKER_ROLE)

        work_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="task_decomposition",
            title=f"Task decomposition for {session.task_key}",
            owner_role_id=decomposer_role.id,
            source_event_id=source_event.id,
            priority=97,
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="task_decomposition_requested",
            current_owner=TASK_DECOMPOSER_WORKER_ROLE,
        )
        instruction = (
            f"Prepare task decomposition for story {session.task_key} before implementation starts. "
            "Produce a temporary `plan/index.md` plus self-contained `plan/NN-*.md` task package only for Jira subtask materialization, and break the verified planning package into the smallest useful execution-oriented chunks."
        )
        if additional_context:
            instruction = f"{instruction}\n\n{additional_context}"
        self._dispatch_role_work(
            session=session,
            role=decomposer_role,
            work_item=work_item,
            stage_name="task_decomposition_requested",
            instruction=instruction,
        )
        return self._append_event(
            session_id=session.id,
            event_type="task_decomposition_requested",
            producer_type="coordinator",
            payload={
                "task_key": session.task_key,
                "role_name": TASK_DECOMPOSER_WORKER_ROLE,
                "work_item_id": work_item.id,
                "current_stage": session.current_stage,
            },
        )

    def _handle_bug_analysis_completed(
        self,
        session: Session,
        source_event: Event,
    ) -> tuple[Session, Event]:
        analysis_items = [
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "bug_analysis" and item.status != WorkItemStatus.COMPLETED
        ]
        if not analysis_items:
            raise IntakeError("No active bug analysis work item found for the session")

        active_item = analysis_items[0]
        self.work_item_repository.update_status(active_item.id, WorkItemStatus.COMPLETED)

        summary = str(source_event.payload.get("summary") or "").strip()
        proposed_test = str(source_event.payload.get("test_strategy") or "").strip()
        context_lines: list[str] = []
        if summary:
            context_lines.append(f"Bug analysis summary: {summary}")
        if proposed_test:
            context_lines.append(f"Suggested test strategy: {proposed_test}")
        additional_context = "\n".join(context_lines) if context_lines else None

        event = self._enqueue_initial_implementation(
            session=session,
            resolved_task_key=session.task_key,
            source_event=source_event,
            additional_context=additional_context,
        )
        session = self._get_session_or_raise(session.id)
        return session, event

    def _handle_proposal_context_completed(
        self,
        session: Session,
        source_event: Event,
    ) -> tuple[Session, Event]:
        proposal_items = [
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "proposal_context" and item.status != WorkItemStatus.COMPLETED
        ]
        if not proposal_items:
            raise IntakeError("No active proposal/context work item found for the session")

        active_item = proposal_items[0]
        self.work_item_repository.update_status(active_item.id, WorkItemStatus.COMPLETED)
        self._stop_on_demand_role(session, PROPOSAL_CONTEXT_WORKER_ROLE)
        self._sync_role_workspace_outputs_to_task_snapshot(
            session=session,
            role_name=PROPOSAL_CONTEXT_WORKER_ROLE,
            outputs=source_event.payload.get("outputs"),
        )
        self._materialize_story_spec_file(
            session=session,
            filename="proposal.md",
            artifact_type="proposal_markdown",
            title="Proposal",
            explicit_markdown=str(source_event.payload.get("proposal_markdown") or "").strip(),
            sections=[
                ("Summary", str(source_event.payload.get("summary") or "").strip()),
                ("Key Context Findings", str(source_event.payload.get("context_findings") or "").strip()),
            ],
        )

        summary = str(source_event.payload.get("summary") or "").strip()
        context_findings = str(source_event.payload.get("context_findings") or "").strip()
        context_lines: list[str] = []
        if summary:
            context_lines.append(f"Proposal/context summary: {summary}")
        if context_findings:
            context_lines.append(f"Key context findings: {context_findings}")
        context_lines.append(
            "Context package available under `spec/context/`; read `feature-overview.md` first and use the other context files selectively."
        )
        additional_context = "\n".join(context_lines) if context_lines else None

        event = self._enqueue_requirements(
            session=session,
            source_event=source_event,
            additional_context=additional_context,
        )
        session = self._get_session_or_raise(session.id)
        return session, event

    def _handle_mr_comments_analysis_completed(
        self,
        session: Session,
        source_event: Event,
    ) -> tuple[Session, Event]:
        analysis_items = [
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "mr_comments_analysis" and item.status != WorkItemStatus.COMPLETED
        ]
        if not analysis_items:
            raise IntakeError("No active MR comments analysis work item found for the session")

        active_item = analysis_items[0]
        self.work_item_repository.update_status(active_item.id, WorkItemStatus.COMPLETED)
        self._stop_on_demand_role(session, MR_COMMENTS_ANALYST_ROLE)

        mr_id = str(source_event.payload.get("mr_id") or "").strip() or "unknown"
        discussion_count = int(source_event.payload.get("discussion_count") or 0)
        summary = str(source_event.payload.get("summary") or "").strip()
        additional_context_lines: list[str] = []
        if summary:
            additional_context_lines.append(f"MR analysis summary: {summary}")
        additional_context_lines.append(
            "Use the generated follow-up plan package only to materialize Jira subtasks; after snapshot refresh, execution must continue from the Jira subtasks flow rather than from `plan/` files."
        )
        plan_artifact: Artifact | None = None
        if self.workdir_root is not None:
            plan_index_path = self.workdir_root / session.task_key / "plan" / "index.md"
            if plan_index_path.exists():
                plan_artifact = self.artifact_repository.create(
                    session_id=session.id,
                    stage_name="mr_comments_analysis_requested",
                    artifact_type="mr_followup_plan_markdown",
                    path=str(plan_index_path),
                    metadata={
                        "task_key": session.task_key,
                        "mr_id": mr_id,
                        "discussion_count": discussion_count,
                    },
                )
                session, _subtasks_event, _subtasks_followup = self.create_subtasks_from_plan(session.id)
        if plan_artifact is not None:
            subtasks = self._read_snapshot_subtasks(session.task_key)
            unresolved = unresolved_subtasks(subtasks) if subtasks is not None else []
            if unresolved:
                coding_role = self._primary_coding_role_for_work_type(session, "followup_implementation")
                work_item = self.work_item_repository.create(
                    session_id=session.id,
                    work_type="followup_implementation",
                    title=f"MR follow-up execution for {session.task_key} from !{mr_id}",
                    owner_role_id=coding_role.id,
                    source_event_id=source_event.id,
                    priority=110,
                )
                _graph_event, followup_event = self._start_subtask_graph_flow(
                    session=session,
                    producer_type="coordinator",
                    subtasks=subtasks,
                    initial_work_item=work_item,
                    decomposition_artifact=plan_artifact,
                )
                session = self._get_session_or_raise(session.id)
                return session, followup_event
        event = self._enqueue_mr_followup(
            session=session,
            source_event=source_event,
            mr_id=mr_id,
            discussion_count=discussion_count,
            additional_context="\n".join(additional_context_lines),
        )
        session = self._get_session_or_raise(session.id)
        return session, event

    def _handle_requirements_completed(
        self,
        session: Session,
        source_event: Event,
    ) -> tuple[Session, Event]:
        requirements_items = [
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "requirements" and item.status != WorkItemStatus.COMPLETED
        ]
        if not requirements_items:
            raise IntakeError("No active requirements work item found for the session")

        active_item = requirements_items[0]
        self.work_item_repository.update_status(active_item.id, WorkItemStatus.COMPLETED)
        self._stop_on_demand_role(session, REQUIREMENTS_CLARIFIER_WORKER_ROLE)
        self._sync_role_workspace_outputs_to_task_snapshot(
            session=session,
            role_name=REQUIREMENTS_CLARIFIER_WORKER_ROLE,
            outputs=source_event.payload.get("outputs"),
        )
        self._materialize_story_spec_file(
            session=session,
            filename="requirements.md",
            artifact_type="requirements_markdown",
            title="Requirements",
            explicit_markdown=str(source_event.payload.get("requirements_markdown") or "").strip(),
            sections=[
                ("Summary", str(source_event.payload.get("summary") or "").strip()),
                ("Assumptions", str(source_event.payload.get("assumptions") or "").strip()),
            ],
        )

        summary = str(source_event.payload.get("summary") or "").strip()
        assumptions = str(source_event.payload.get("assumptions") or "").strip()
        context_lines: list[str] = []
        if summary:
            context_lines.append(f"Requirements summary: {summary}")
        if assumptions:
            context_lines.append(f"Explicit assumptions: {assumptions}")
        additional_context = "\n".join(context_lines) if context_lines else None

        event = self._enqueue_acceptance_criteria(
            session=session,
            source_event=source_event,
            additional_context=additional_context,
        )
        session = self._get_session_or_raise(session.id)
        return session, event

    def _handle_story_planning_blocked(
        self,
        session: Session,
        source_event: Event,
    ) -> tuple[Session, Event]:
        work_type = _STORY_PLANNING_WORK_TYPE_BY_STAGE.get(session.current_stage)
        if work_type is None:
            raise IntakeError(f"Stage {session.current_stage} is not a story planning stage")

        planning_items = [
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == work_type and item.status != WorkItemStatus.COMPLETED
        ]
        if not planning_items:
            raise IntakeError(f"No active {work_type} work item found for the session")

        active_item = planning_items[0]
        self.work_item_repository.update_status(active_item.id, WorkItemStatus.WAITING_FOR_OPERATOR)
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage=session.current_stage,
            current_owner=source_event.producer_id,
        )
        session = self.session_repository.update_status(session.id, SessionStatus.WAITING_FOR_OPERATOR)
        if source_event.producer_id in _STORY_PLANNING_ROLES:
            self._sync_role_workspace_outputs_to_task_snapshot(
                session=session,
                role_name=source_event.producer_id,
                outputs=source_event.payload.get("outputs"),
            )

        summary = str(source_event.payload.get("summary") or "").strip() or f"{work_type} requires operator input"
        detail_lines: list[str] = []
        for key, label in (
            ("failures", "Failures"),
            ("missing_inputs", "Missing inputs"),
            ("pending_decisions", "Pending decisions"),
        ):
            value = source_event.payload.get(key)
            if isinstance(value, list):
                rendered = [str(item).strip() for item in value if str(item).strip()]
                if rendered:
                    detail_lines.append(f"{label}:")
                    detail_lines.extend(f"- {item}" for item in rendered)
        next_step = str(source_event.payload.get("next_step") or "").strip()
        if next_step:
            detail_lines.append(f"Next step: {next_step}")
        details = "\n".join(detail_lines).strip()

        event = self._append_event(
            session_id=session.id,
            event_type="session_escalated_to_operator",
            producer_type="coordinator",
            payload={
                "reason": f"{work_type}_blocked",
                "role_name": source_event.producer_id,
                "work_item_id": active_item.id,
                "summary": summary,
                "details": details,
                "needs_operator_input": True,
                "current_stage": session.current_stage,
            },
        )
        return session, event

    def _handle_acceptance_criteria_completed(
        self,
        session: Session,
        source_event: Event,
    ) -> tuple[Session, Event]:
        acceptance_items = [
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "acceptance_criteria" and item.status != WorkItemStatus.COMPLETED
        ]
        if not acceptance_items:
            raise IntakeError("No active acceptance criteria work item found for the session")

        active_item = acceptance_items[0]
        self.work_item_repository.update_status(active_item.id, WorkItemStatus.COMPLETED)
        self._stop_on_demand_role(session, ACCEPTANCE_CRITERIA_WORKER_ROLE)
        self._sync_role_workspace_outputs_to_task_snapshot(
            session=session,
            role_name=ACCEPTANCE_CRITERIA_WORKER_ROLE,
            outputs=source_event.payload.get("outputs"),
        )
        self._materialize_story_spec_file(
            session=session,
            filename="acceptance_criteria.md",
            artifact_type="acceptance_criteria_markdown",
            title="Acceptance Criteria",
            explicit_markdown=str(source_event.payload.get("acceptance_criteria_markdown") or "").strip(),
            sections=[
                ("Summary", str(source_event.payload.get("summary") or "").strip()),
                ("Highlighted Cases", str(source_event.payload.get("highlighted_cases") or "").strip()),
            ],
        )

        summary = str(source_event.payload.get("summary") or "").strip()
        highlighted_cases = str(source_event.payload.get("highlighted_cases") or "").strip()
        context_lines: list[str] = []
        if summary:
            context_lines.append(f"Acceptance criteria summary: {summary}")
        if highlighted_cases:
            context_lines.append(f"Highlighted cases: {highlighted_cases}")
        additional_context = "\n".join(context_lines) if context_lines else None

        event = self._enqueue_constraints(
            session=session,
            source_event=source_event,
            additional_context=additional_context,
        )
        session = self._get_session_or_raise(session.id)
        return session, event

    def _handle_constraints_completed(
        self,
        session: Session,
        source_event: Event,
    ) -> tuple[Session, Event]:
        constraint_items = [
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "constraints" and item.status != WorkItemStatus.COMPLETED
        ]
        if not constraint_items:
            raise IntakeError("No active constraints work item found for the session")

        active_item = constraint_items[0]
        self.work_item_repository.update_status(active_item.id, WorkItemStatus.COMPLETED)
        self._stop_on_demand_role(session, CONSTRAINTS_WORKER_ROLE)
        self._sync_role_workspace_outputs_to_task_snapshot(
            session=session,
            role_name=CONSTRAINTS_WORKER_ROLE,
            outputs=source_event.payload.get("outputs"),
        )
        self._materialize_story_spec_file(
            session=session,
            filename="constraints.md",
            artifact_type="constraints_markdown",
            title="Constraints",
            explicit_markdown=str(source_event.payload.get("constraints_markdown") or "").strip(),
            sections=[
                ("Summary", str(source_event.payload.get("summary") or "").strip()),
                ("Key Constraints", str(source_event.payload.get("key_constraints") or "").strip()),
            ],
        )

        summary = str(source_event.payload.get("summary") or "").strip()
        key_constraints = str(source_event.payload.get("key_constraints") or "").strip()
        context_lines: list[str] = []
        if summary:
            context_lines.append(f"Constraints summary: {summary}")
        if key_constraints:
            context_lines.append(f"Key constraints: {key_constraints}")
        additional_context = "\n".join(context_lines) if context_lines else None

        event = self._enqueue_spec_verification(
            session=session,
            source_event=source_event,
            additional_context=additional_context,
        )
        session = self._get_session_or_raise(session.id)
        return session, event

    def _handle_spec_verification_completed(
        self,
        session: Session,
        source_event: Event,
    ) -> tuple[Session, Event]:
        verification_items = [
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "spec_verification" and item.status != WorkItemStatus.COMPLETED
        ]
        if not verification_items:
            raise IntakeError("No active spec verification work item found for the session")

        active_item = verification_items[0]
        self.work_item_repository.update_status(active_item.id, WorkItemStatus.COMPLETED)
        self._stop_on_demand_role(session, SPEC_VERIFIER_WORKER_ROLE)
        self._sync_role_workspace_outputs_to_task_snapshot(
            session=session,
            role_name=SPEC_VERIFIER_WORKER_ROLE,
            outputs=source_event.payload.get("outputs"),
        )
        self._materialize_story_spec_file(
            session=session,
            filename="spec_verification.md",
            artifact_type="spec_verification_markdown",
            title="Spec Verification",
            explicit_markdown=str(source_event.payload.get("spec_verification_markdown") or "").strip(),
            sections=[
                ("Summary", str(source_event.payload.get("summary") or "").strip()),
                ("Verified Focus", str(source_event.payload.get("verified_focus") or "").strip()),
            ],
        )

        summary = str(source_event.payload.get("summary") or "").strip()
        verified_focus = str(source_event.payload.get("verified_focus") or "").strip()
        context_lines: list[str] = []
        if summary:
            context_lines.append(f"Planning verification summary: {summary}")
        if verified_focus:
            context_lines.append(f"Verified focus: {verified_focus}")
        additional_context = "\n".join(context_lines) if context_lines else None

        event = self._enqueue_story_spec(
            session=session,
            source_event=source_event,
            additional_context=additional_context,
        )
        session = self._get_session_or_raise(session.id)
        return session, event

    def _handle_story_spec_completed(
        self,
        session: Session,
        source_event: Event,
    ) -> tuple[Session, Event]:
        spec_items = [
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "story_spec" and item.status != WorkItemStatus.COMPLETED
        ]
        if not spec_items:
            raise IntakeError("No active story spec work item found for the session")

        active_item = spec_items[0]
        self.work_item_repository.update_status(active_item.id, WorkItemStatus.COMPLETED)
        self._stop_on_demand_role(session, STORY_SPEC_WORKER_ROLE)
        self._sync_role_workspace_outputs_to_task_snapshot(
            session=session,
            role_name=STORY_SPEC_WORKER_ROLE,
            outputs=source_event.payload.get("outputs"),
        )
        self._materialize_story_spec_file(
            session=session,
            filename="story_spec.md",
            artifact_type="story_spec_markdown",
            title="Story Spec",
            explicit_markdown=str(source_event.payload.get("story_spec_markdown") or "").strip(),
            sections=[
                ("Summary", str(source_event.payload.get("summary") or "").strip()),
                ("Key Constraints", str(source_event.payload.get("constraints") or "").strip()),
            ],
        )

        summary = str(source_event.payload.get("summary") or "").strip()
        constraints = str(source_event.payload.get("constraints") or "").strip()
        context_lines: list[str] = []
        if summary:
            context_lines.append(f"Story spec summary: {summary}")
        if constraints:
            context_lines.append(f"Key constraints: {constraints}")
        additional_context = "\n".join(context_lines) if context_lines else None

        event = self._enqueue_task_decomposition(
            session=session,
            source_event=source_event,
            additional_context=additional_context,
        )
        session = self._get_session_or_raise(session.id)
        return session, event

    def _handle_task_decomposition_completed(
        self,
        session: Session,
        source_event: Event,
    ) -> tuple[Session, Event]:
        decomposition_items = [
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "task_decomposition" and item.status != WorkItemStatus.COMPLETED
        ]
        if not decomposition_items:
            raise IntakeError("No active task decomposition work item found for the session")

        active_item = decomposition_items[0]
        summary = str(source_event.payload.get("summary") or "").strip()
        task_breakdown = str(source_event.payload.get("task_breakdown") or "").strip()
        self._sync_role_workspace_outputs_to_task_snapshot(
            session=session,
            role_name=TASK_DECOMPOSER_WORKER_ROLE,
            outputs=source_event.payload.get("outputs"),
        )
        try:
            plan_index_markdown, raw_plan_task_files = self._normalize_task_decomposition_plan_package(
                session=session,
                payload=source_event.payload,
            )
        except IntakeError as exc:
            self._stop_on_demand_role(session, TASK_DECOMPOSER_WORKER_ROLE)
            self.work_item_repository.update_status(active_item.id, WorkItemStatus.WAITING_FOR_OPERATOR)
            session = self.session_repository.update_stage_and_owner(
                session.id,
                current_stage="task_decomposition_requested",
                current_owner=None,
            )
            session = self.session_repository.update_status(session.id, SessionStatus.WAITING_FOR_OPERATOR)
            event = self._append_event(
                session_id=session.id,
                event_type="session_escalated_to_operator",
                producer_type="coordinator",
                payload={
                    "reason": "task_decomposition_package_invalid",
                    "role_name": TASK_DECOMPOSER_WORKER_ROLE,
                    "work_item_id": active_item.id,
                    "summary": summary or "task decomposition package is invalid",
                    "details": str(exc),
                    "current_stage": session.current_stage,
                },
            )
            return session, event

        self.work_item_repository.update_status(active_item.id, WorkItemStatus.COMPLETED)
        self._stop_on_demand_role(session, TASK_DECOMPOSER_WORKER_ROLE)
        decomposition_artifact: Artifact | None = None
        if self.artifacts_root is not None:
            artifact_path = write_text_artifact(
                self.artifacts_root,
                session.task_key,
                "planning",
                "task_decomposition.md",
                self._task_decomposition_markdown(summary=summary, task_breakdown=task_breakdown),
            )
            decomposition_artifact = self.artifact_repository.create(
                session_id=session.id,
                stage_name="planning",
                artifact_type="task_decomposition_markdown",
                path=str(artifact_path),
                metadata={
                    "task_key": session.task_key,
                },
            )
            self._write_task_decomposition_plan_package(
                session=session,
                plan_index_markdown=plan_index_markdown,
                raw_plan_task_files=raw_plan_task_files,
            )
        coding_role = self._primary_coding_role_for_work_type(session, "implementation")
        self.work_item_repository.create(
            session_id=session.id,
            work_type="implementation",
            title=f"Initial implementation for {session.task_key}",
            owner_role_id=coding_role.id,
            source_event_id=source_event.id,
            priority=100,
            status=WorkItemStatus.WAITING_FOR_OPERATOR,
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="subtask_creation_requested",
            current_owner=None,
        )
        session = self.session_repository.update_status(session.id, SessionStatus.WAITING_FOR_OPERATOR)
        batch_session, batch_event, followup_event = self.create_subtasks_from_plan(session.id)
        if followup_event is not None:
            return batch_session, followup_event
        if batch_event.event_type == "jira_subtasks_creation_failed":
            return batch_session, batch_event
        return batch_session, batch_event

    def _enqueue_subtask_graph(
        self,
        session: Session,
        source_event: Event,
        subtasks: list,
        initial_work_item: WorkItem,
        decomposition_artifact: Artifact,
    ) -> Event:
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        if implementer_role is None:
            raise IntakeError("Implementer role is missing for the session")

        unresolved = unresolved_subtasks(subtasks)
        if not unresolved:
            raise IntakeError("No unresolved subtasks found for subtask graph dispatch")

        first_subtask = unresolved[0]
        active_item = self.work_item_repository.update_shape(
            initial_work_item.id,
            work_type="subtask_implementation",
            title=f"Subtask implementation for {first_subtask.key}: {first_subtask.title}",
            owner_role_id=implementer_role.id,
            status=WorkItemStatus.ASSIGNED,
        )
        for index, subtask in enumerate(unresolved[1:], start=1):
            self.work_item_repository.create(
                session_id=session.id,
                work_type="subtask_implementation",
                title=f"Subtask implementation for {subtask.key}: {subtask.title}",
                owner_role_id=None,
                source_event_id=source_event.id,
                priority=max(70 - index, 1),
                status=WorkItemStatus.UNASSIGNED,
            )

        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="subtask_implementation_requested",
            current_owner=IMPLEMENTER_ROLE,
        )
        session = self.session_repository.update_status(session.id, SessionStatus.ACTIVE)
        self._dispatch_role_work(
            session=session,
            role=implementer_role,
            work_item=active_item,
            stage_name="subtask_implementation_requested",
            instruction=(
                f"Implement subtask {first_subtask.key} for parent task {session.task_key}. "
                "Use the refreshed Jira subtask snapshot as the source of truth for scope and status. "
                "Focus only on this subtask scope before moving to the next one."
            ),
        )
        return self._append_event(
            session_id=session.id,
            event_type="subtask_implementation_requested",
            producer_type="coordinator",
            payload={
                "task_key": session.task_key,
                "role_name": IMPLEMENTER_ROLE,
                "work_item_id": active_item.id,
                "current_stage": session.current_stage,
                "subtask_key": first_subtask.key,
                "remaining_subtask_count": len(unresolved),
                "decomposition_artifact_id": decomposition_artifact.id,
            },
        )

    def _start_subtask_graph_flow(
        self,
        session: Session,
        producer_type: str,
        subtasks: list,
        initial_work_item: WorkItem,
        decomposition_artifact: Artifact,
    ) -> tuple[Event, Event]:
        unresolved = unresolved_subtasks(subtasks)
        self._record_subtask_statuses_artifact(session, subtasks)
        event = self._append_event(
            session_id=session.id,
            event_type="subtask_graph_requested",
            producer_type=producer_type,
            payload={
                "subtask_count": len(subtasks),
                "unresolved_count": len(unresolved),
                "decomposition_artifact_id": decomposition_artifact.id,
            },
        )
        followup_event = self._enqueue_subtask_graph(
            session=session,
            source_event=event,
            subtasks=subtasks,
            initial_work_item=initial_work_item,
            decomposition_artifact=decomposition_artifact,
        )
        return event, followup_event

    def _handle_subtask_completed(
        self,
        session: Session,
        source_event: Event,
    ) -> tuple[Session, Event]:
        active_item = self._find_active_primary_coding_work_item(session)
        if active_item is None or active_item.work_type != "subtask_implementation":
            raise IntakeError("No active subtask implementation work item found for the session")

        self.work_item_repository.update_status(active_item.id, WorkItemStatus.COMPLETED)
        parsed_subtask = self._parse_subtask_work_item_title(active_item.title)
        subtask_context = (
            f"subtask {parsed_subtask['key']}"
            if parsed_subtask["key"] is not None
            else "subtask implementation"
        )
        session, commit_event = self._commit_task_state(session, subtask_context)
        if commit_event is not None:
            return session, commit_event
        if parsed_subtask["key"] is not None:
            session, transition_event = self._complete_subtask_in_jira(
                session=session,
                subtask_key=parsed_subtask["key"],
            )
            if transition_event is not None:
                return session, transition_event
        refreshed_subtasks, _refresh_ok = self._refresh_subtask_snapshot(session)
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        if implementer_role is None:
            raise IntakeError("Implementer role is missing for the session")

        remaining_items = [
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "subtask_implementation"
            and item.status == WorkItemStatus.UNASSIGNED
        ]
        if refreshed_subtasks is not None:
            completed_subtask_keys = {
                parsed["key"]
                for item in self.work_item_repository.list_for_session(session.id)
                if item.work_type == "subtask_implementation"
                and item.status == WorkItemStatus.COMPLETED
                for parsed in [self._parse_subtask_work_item_title(item.title)]
                if parsed["key"] is not None
            }
            remaining_items = self._reconcile_subtask_queue_after_refresh(
                session=session,
                source_event=source_event,
                queued_items=remaining_items,
                unresolved=[
                    subtask
                    for subtask in unresolved_subtasks(refreshed_subtasks)
                    if subtask.key not in completed_subtask_keys
                ],
            )
        if remaining_items:
            next_item = self.work_item_repository.update_assignment(
                remaining_items[0].id,
                owner_role_id=implementer_role.id,
                status=WorkItemStatus.ASSIGNED,
            )
            session = self.session_repository.update_stage_and_owner(
                session.id,
                current_stage="subtask_implementation_requested",
                current_owner=IMPLEMENTER_ROLE,
            )
            session = self.session_repository.update_status(session.id, SessionStatus.ACTIVE)
            self._dispatch_role_work(
                session=session,
                role=implementer_role,
                work_item=next_item,
                stage_name="subtask_implementation_requested",
                instruction=(
                    f"Continue subtask implementation for parent task {session.task_key}. "
                    "Finish this subtask before moving forward."
                ),
            )
            return session, self._append_event(
                session_id=session.id,
                event_type="subtask_implementation_requested",
                producer_type="coordinator",
                payload={
                    "task_key": session.task_key,
                    "role_name": IMPLEMENTER_ROLE,
                    "work_item_id": next_item.id,
                    "current_stage": session.current_stage,
                    "remaining_subtask_count": len(remaining_items),
                    "subtask_key": self._parse_subtask_work_item_title(next_item.title)["key"],
                },
            )

        return self._advance_after_coding_completion(
            session=session,
            source_event=source_event,
            completed_work_type="subtask_implementation",
        )

    def _complete_subtask_in_jira(
        self,
        *,
        session: Session,
        subtask_key: str,
    ) -> tuple[Session, Event | None]:
        if self.jira_adapter is None or self.artifacts_root is None:
            return session, None

        result = self.jira_adapter.complete_subtask(subtask_key)
        stdout_path = write_text_artifact(
            self.artifacts_root,
            session.task_key,
            "subtask-transition",
            f"{subtask_key}.stdout.log",
            result.stdout,
        )
        stderr_path = write_text_artifact(
            self.artifacts_root,
            session.task_key,
            "subtask-transition",
            f"{subtask_key}.stderr.log",
            result.stderr,
        )
        self.artifact_repository.create(
            session_id=session.id,
            stage_name="subtask-transition",
            artifact_type="subtask_transition_stdout",
            path=str(stdout_path),
            metadata={
                "task_key": session.task_key,
                "subtask_key": subtask_key,
                "command": result.command,
                "returncode": result.returncode,
            },
        )
        self.artifact_repository.create(
            session_id=session.id,
            stage_name="subtask-transition",
            artifact_type="subtask_transition_stderr",
            path=str(stderr_path),
            metadata={
                "task_key": session.task_key,
                "subtask_key": subtask_key,
                "command": result.command,
                "returncode": result.returncode,
            },
        )

        if not result.ok:
            session = self.session_repository.update_stage_and_owner(
                session.id,
                current_stage="subtask_implementation_requested",
                current_owner=None,
            )
            session = self.session_repository.update_status(session.id, SessionStatus.WAITING_FOR_OPERATOR)
            event = self._append_event(
                session_id=session.id,
                event_type="subtask_transition_failed",
                producer_type="coordinator",
                payload={
                    "task_key": session.task_key,
                    "subtask_key": subtask_key,
                    "returncode": result.returncode,
                    "current_stage": session.current_stage,
                    "status": session.status.value,
                },
            )
            return session, event

        self._append_event(
            session_id=session.id,
            event_type="subtask_transition_completed",
            producer_type="coordinator",
            payload={
                "task_key": session.task_key,
                "subtask_key": subtask_key,
                "returncode": result.returncode,
                "current_stage": session.current_stage,
                "status": session.status.value,
            },
        )
        return session, None

    def _handle_implementation_completed(
        self,
        session: Session,
        source_event: Event,
    ) -> tuple[Session, Event]:
        active_item = self._find_active_primary_coding_work_item(session)
        if active_item is None:
            raise IntakeError("No active coding work item found for the session")
        self.work_item_repository.update_status(active_item.id, WorkItemStatus.COMPLETED)
        session, commit_event = self._commit_task_state(
            session,
            self._commit_context_for_work_type(active_item.work_type),
        )
        if commit_event is not None:
            return session, commit_event
        if active_item.work_type == "boy_scout_correction":
            return self._enqueue_verification(session=session, source_event=source_event)
        if active_item.work_type == "self_review_correction":
            return self._enqueue_self_review(session=session, source_event=source_event)
        if active_item.work_type == "verification_correction":
            return self._enqueue_verification(session=session, source_event=source_event)

        return self._advance_after_coding_completion(
            session=session,
            source_event=source_event,
            completed_work_type=active_item.work_type,
        )

    def _advance_after_coding_completion(
        self,
        session: Session,
        source_event: Event,
        completed_work_type: str,
    ) -> tuple[Session, Event]:

        if (
            completed_work_type in {"implementation", "subtask_implementation"}
            and self._optional_lane_policy_mode(session.policy, "self_review_policy") != "disabled"
        ):
            return self._enqueue_self_review(session=session, source_event=source_event)

        return self._enqueue_post_implementation_quality_gate(
            session=session,
            source_event=source_event,
        )

    def _commit_context_for_work_type(self, work_type: str) -> str:
        if work_type == "implementation":
            return "implementation pass"
        if work_type == "followup_implementation":
            return "follow-up pass"
        if work_type == "self_review_correction":
            return "self-review fixes"
        if work_type == "boy_scout_correction":
            return "boy-scout fixes"
        if work_type == "verification_correction":
            return "verification fixes"
        return work_type.replace("_", " ")

    def _commit_task_state(
        self,
        session: Session,
        context: str | None,
    ) -> tuple[Session, Event | None]:
        if self.gitlab_adapter is None or self.artifacts_root is None:
            return session, None

        result = self.gitlab_adapter.commit_task_state(session.task_key, context=context)
        context_slug = re.sub(r"[^a-z0-9]+", "-", (context or "checkpoint").lower()).strip("-") or "checkpoint"
        stdout_path = write_text_artifact(
            self.artifacts_root,
            session.task_key,
            "commit-task-state",
            f"{context_slug}.stdout.log",
            result.stdout,
        )
        stderr_path = write_text_artifact(
            self.artifacts_root,
            session.task_key,
            "commit-task-state",
            f"{context_slug}.stderr.log",
            result.stderr,
        )
        self.artifact_repository.create(
            session_id=session.id,
            stage_name="commit-task-state",
            artifact_type="commit_task_state_stdout",
            path=str(stdout_path),
            metadata={
                "task_key": session.task_key,
                "context": context,
                "command": result.command,
                "returncode": result.returncode,
            },
        )
        self.artifact_repository.create(
            session_id=session.id,
            stage_name="commit-task-state",
            artifact_type="commit_task_state_stderr",
            path=str(stderr_path),
            metadata={
                "task_key": session.task_key,
                "context": context,
                "command": result.command,
                "returncode": result.returncode,
            },
        )
        if not result.ok:
            session = self.session_repository.update_stage_and_owner(
                session.id,
                current_stage=session.current_stage,
                current_owner=None,
            )
            session = self.session_repository.update_status(session.id, SessionStatus.WAITING_FOR_OPERATOR)
            event = self._append_event(
                session_id=session.id,
                event_type="git_commit_failed",
                producer_type="coordinator",
                payload={
                    "task_key": session.task_key,
                    "context": context,
                    "returncode": result.returncode,
                    "current_stage": session.current_stage,
                    "status": session.status.value,
                },
            )
            return session, event

        self._append_event(
            session_id=session.id,
            event_type="git_commit_completed",
            producer_type="coordinator",
            payload={
                "task_key": session.task_key,
                "context": context,
                "current_stage": session.current_stage,
                "status": session.status.value,
            },
        )
        return session, None

    def _enqueue_self_review(
        self,
        session: Session,
        source_event: Event,
    ) -> tuple[Session, Event]:
        reviewer_role = self.role_repository.get_by_name(session.id, CODE_REVIEWER_ROLE)
        if reviewer_role is None:
            raise IntakeError("Code reviewer role is missing for the session")

        review_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="self_review",
            title=f"Self review for {session.task_key}",
            owner_role_id=reviewer_role.id,
            source_event_id=source_event.id,
            priority=89,
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="self_review_requested",
            current_owner=CODE_REVIEWER_ROLE,
        )
        session = self.session_repository.update_status(session.id, SessionStatus.ACTIVE)
        previous_review_reports = self._previous_self_review_report_paths(session.id)
        review_report_path = self._next_self_review_report_target_path(session)
        instruction = (
            f"Review the current task changes for {session.task_key}. "
            "Start from the current diff, read only the relevant convention sources, "
            "write or refresh the current structured review report at the routed review report path, "
            "and report a clean pass or remaining issues."
        )
        if previous_review_reports:
            instruction += (
                "\nPrevious review reports (read first and do not re-flag the same issues):\n"
                + "\n".join(previous_review_reports)
            )
        self._dispatch_role_work(
            session=session,
            role=reviewer_role,
            work_item=review_item,
            stage_name="self_review_requested",
            instruction=instruction,
            extra_hydration={
                "review_scope": "current_diff_only",
                "review_report_path": str(review_report_path) if review_report_path is not None else None,
                "previous_review_report_paths": "\n".join(previous_review_reports)
                if previous_review_reports
                else None,
            },
        )
        event = self._append_event(
            session_id=session.id,
            event_type="self_review_requested",
            producer_type="coordinator",
            payload={
                "task_key": session.task_key,
                "role_name": CODE_REVIEWER_ROLE,
                "work_item_id": review_item.id,
                "source_event_id": source_event.id,
                "current_stage": session.current_stage,
                "status": session.status.value,
            },
        )
        return session, event

    def _handle_spec_verification_blocked(
        self,
        session: Session,
        source_event: Event,
    ) -> tuple[Session, Event]:
        verification_items = [
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "spec_verification" and item.status != WorkItemStatus.COMPLETED
        ]
        if not verification_items:
            raise IntakeError("No active spec verification work item found for the session")

        active_item = verification_items[0]
        self.work_item_repository.update_status(active_item.id, WorkItemStatus.WAITING_FOR_OPERATOR)
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="spec_verification_requested",
            current_owner=SPEC_VERIFIER_WORKER_ROLE,
        )
        session = self.session_repository.update_status(session.id, SessionStatus.WAITING_FOR_OPERATOR)
        summary = str(source_event.payload.get("summary") or "").strip() or "spec verification blockers require operator input"
        details = str(source_event.payload.get("details") or "").strip()
        blocker_questions = source_event.payload.get("blocker_questions")
        if isinstance(blocker_questions, list) and blocker_questions:
            rendered = "\n".join(f"- {str(item).strip()}" for item in blocker_questions if str(item).strip())
            if rendered:
                details = f"{details}\n\nQuestions:\n{rendered}".strip() if details else f"Questions:\n{rendered}"
        event = self._append_event(
            session_id=session.id,
            event_type="session_escalated_to_operator",
            producer_type="coordinator",
            payload={
                "reason": "spec_verification_blockers",
                "role_name": SPEC_VERIFIER_WORKER_ROLE,
                "work_item_id": active_item.id,
                "summary": summary,
                "details": details or "Resolve planning blockers with the verifier, then continue in the same live session.",
                "needs_operator_input": True,
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
        self._materialize_final_verification_file(session=session, source_event=source_event)

        coding_role = self._primary_coding_role_for_work_type(session, "verification_correction")

        correction_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="verification_correction",
            title=f"Verification corrections for {session.task_key}",
            owner_role_id=coding_role.id,
            source_event_id=source_event.id,
            priority=95,
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="verification_correction_requested",
            current_owner=coding_role.role_name,
        )
        instruction = self._stage_instruction(
            "verification_correction_requested",
            session.task_key,
            workflow_profile=session.workflow_profile,
            role_name=coding_role.role_name,
            session_policy=session.policy,
        )
        if instruction is None:
            raise IntakeError(
                f"No verification correction instruction is available for role {coding_role.role_name}"
            )
        self._dispatch_role_work(
            session=session,
            role=coding_role,
            work_item=correction_item,
            stage_name="verification_correction_requested",
            instruction=instruction,
        )
        event = self._append_event(
            session_id=session.id,
            event_type="verification_correction_requested",
            producer_type="coordinator",
            payload={
                "task_key": session.task_key,
                "role_name": coding_role.role_name,
                "work_item_id": correction_item.id,
                "current_stage": session.current_stage,
            },
        )
        return session, event

    def _handle_verification_blocked(
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
        self._materialize_final_verification_file(session=session, source_event=source_event)
        verification_role = self.role_repository.get_by_name(session.id, VERIFICATION_COORDINATOR_ROLE)
        if verification_role is None:
            raise IntakeError("Verification coordinator role is missing for the session")
        self.work_item_repository.create(
            session_id=session.id,
            work_type="verification_cycle_review",
            title=f"Verification cycle resolution for {session.task_key}",
            owner_role_id=verification_role.id,
            source_event_id=source_event.id,
            priority=96,
            status=WorkItemStatus.WAITING_FOR_OPERATOR,
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="verification_requested",
            current_owner=VERIFICATION_COORDINATOR_ROLE,
        )
        session = self.session_repository.update_status(session.id, SessionStatus.WAITING_FOR_OPERATOR)
        report_path = self._latest_artifact_path(session.id, "final_verification_markdown")
        event = self._append_event(
            session_id=session.id,
            event_type="session_escalated_to_operator",
            producer_type="coordinator",
            payload={
                "reason": "verification_cycle",
                "summary": str(source_event.payload.get("summary") or "").strip() or "verification cycle blocked",
                "details": str(source_event.payload.get("details") or "").strip()
                or "The verifier reported a non-converging verification cycle and stopped automatic retries.",
                "verification_report_path": report_path,
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
        self._materialize_final_verification_file(session=session, source_event=source_event)
        doc_harvest_policy = self._optional_lane_policy_mode(session.policy, "doc_harvest_policy")
        if doc_harvest_policy != "disabled":
            session, event = self._enqueue_doc_harvest(session=session, source_event=source_event)
            return session, event
        return self._complete_session_and_attempt_delivery(session=session, source_event=source_event)

    def _complete_session_and_attempt_delivery(
        self,
        session: Session,
        source_event: Event,
    ) -> tuple[Session, Event]:
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="completed",
            current_owner=None,
        )
        session = self.session_repository.update_status(session.id, SessionStatus.COMPLETED)
        completed_event = self._append_event(
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
        if self.gitlab_adapter is None or self.jira_adapter is None:
            return session, completed_event
        session, mr_event, _mr_url = self.create_mr_handoff(session.id)
        if mr_event.event_type != "mr_handoff_completed":
            return session, mr_event
        session, send_event = self.send_to_test_handoff(session.id)
        return session, send_event

    def _handle_boy_scout_completed(
        self,
        session: Session,
        source_event: Event,
    ) -> tuple[Session, Event]:
        scout_items = [
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "boy_scout" and item.status != WorkItemStatus.COMPLETED
        ]
        if not scout_items:
            raise IntakeError("No active Boy Scout work item found for the session")

        active_item = scout_items[0]
        self.work_item_repository.update_status(active_item.id, WorkItemStatus.COMPLETED)
        self._stop_on_demand_role(session, CODE_SCOUT_ROLE)

        result = str(source_event.payload.get("result") or "clean").strip() or "clean"
        if result == "findings_found":
            findings_path = None
            if self.workdir_root is not None:
                candidate = self.workdir_root / session.task_key / "spec" / "findings.md"
                if candidate.is_file():
                    findings_path = candidate
            if findings_path is not None:
                self.artifact_repository.create(
                    session_id=session.id,
                    stage_name="boy-scout",
                    artifact_type="boy_scout_findings",
                    path=str(findings_path),
                    metadata={"result": result},
                )
            implement_now_findings, tech_debt_findings = self._classify_boy_scout_findings(session)
            if implement_now_findings and not tech_debt_findings:
                actionable_path = self._materialize_boy_scout_actionable_findings(
                    session=session,
                    findings=implement_now_findings,
                    filename="boy-scout-actionable.md",
                )
                return self._enqueue_boy_scout_correction(
                    session=session,
                    source_event=source_event,
                    actionable_findings_path=actionable_path,
                )
            self.work_item_repository.create(
                session_id=session.id,
                work_type="boy_scout_review",
                title=f"Boy Scout review decision for {session.task_key}",
                owner_role_id=None,
                source_event_id=source_event.id,
                priority=91,
                status=WorkItemStatus.WAITING_FOR_OPERATOR,
            )
            session = self.session_repository.update_stage_and_owner(
                session.id,
                current_stage="boy_scout_requested",
                current_owner=None,
            )
            session = self.session_repository.update_status(session.id, SessionStatus.WAITING_FOR_OPERATOR)
            event = self._append_event(
                session_id=session.id,
                event_type="session_escalated_to_operator",
                producer_type="coordinator",
                payload={
                    "reason": "boy_scout_findings",
                    "summary": "boy scout findings need operator decision",
                    "details": str(source_event.payload.get("summary") or "").strip()
                    or "Review Boy Scout findings and choose whether to implement all of them now or create tech-debt stories for the old-code candidates.",
                    "implement_now_count": len(implement_now_findings),
                    "tech_debt_candidate_count": len(tech_debt_findings),
                    "current_stage": session.current_stage,
                },
            )
            return session, event

        return self._enqueue_verification(session=session, source_event=source_event)

    def _enqueue_mr_followup(
        self,
        session: Session,
        source_event: Event,
        mr_id: str,
        discussion_count: int,
        additional_context: str | None = None,
    ) -> Event:
        instruction = (
            f"Apply MR follow-up changes for {session.task_key} from MR !{mr_id}. "
            f"There are {discussion_count} unresolved discussion groups recorded in artifacts."
        )
        if additional_context:
            instruction = f"{instruction}\n\n{additional_context}"
        return self._enqueue_followup_implementation(
            session=session,
            source_event=source_event,
            stage_name="mr_followup_requested",
            event_type="mr_followup_requested",
            title=f"MR follow-up for {session.task_key} from !{mr_id}",
            instruction=instruction,
            priority=110,
            payload={
                "mr_id": mr_id,
                "discussion_count": discussion_count,
            },
        )

    def _enqueue_qa_followup(
        self,
        session: Session,
        source_event: Event,
    ) -> Event:
        return self._enqueue_followup_implementation(
            session=session,
            source_event=source_event,
            stage_name="qa_reopen_requested",
            event_type="qa_reopen_requested",
            title=f"QA reopen follow-up for {session.task_key}",
            instruction=(
                f"Apply QA reopen follow-up changes for {session.task_key}. "
                "Use the latest QA comments artifact as the highest-priority scope."
            ),
            priority=115,
            payload={},
        )

    def _enqueue_followup_implementation(
        self,
        session: Session,
        source_event: Event,
        stage_name: str,
        event_type: str,
        title: str,
        instruction: str,
        priority: int,
        payload: dict,
    ) -> Event:
        coding_role = self._primary_coding_role_for_work_type(session, "followup_implementation")

        work_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="followup_implementation",
            title=title,
            owner_role_id=coding_role.id,
            source_event_id=source_event.id,
            priority=priority,
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage=stage_name,
            current_owner=coding_role.role_name,
        )
        session = self.session_repository.update_status(session.id, SessionStatus.ACTIVE)
        effective_instruction = self._stage_instruction(
            stage_name,
            session.task_key,
            workflow_profile=session.workflow_profile,
            role_name=coding_role.role_name,
            session_policy=session.policy,
        )
        if effective_instruction is None:
            effective_instruction = instruction
        self._dispatch_role_work(
            session=session,
            role=coding_role,
            work_item=work_item,
            stage_name=stage_name,
            instruction=effective_instruction,
        )
        return self._append_event(
            session_id=session.id,
            event_type=event_type,
            producer_type="coordinator",
            payload={
                "task_key": session.task_key,
                "role_name": coding_role.role_name,
                "work_item_id": work_item.id,
                "current_stage": session.current_stage,
                **payload,
            },
        )

    def _enqueue_self_review_correction(
        self,
        session: Session,
        source_event: Event,
    ) -> tuple[Session, Event]:
        coding_role = self._primary_coding_role_for_work_type(session, "self_review_correction")

        correction_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="self_review_correction",
            title=f"Self review corrections for {session.task_key}",
            owner_role_id=coding_role.id,
            source_event_id=source_event.id,
            priority=92,
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="self_review_correction_requested",
            current_owner=coding_role.role_name,
        )
        session = self.session_repository.update_status(session.id, SessionStatus.ACTIVE)
        instruction = self._stage_instruction(
            "self_review_correction_requested",
            session.task_key,
            workflow_profile=session.workflow_profile,
            role_name=coding_role.role_name,
            session_policy=session.policy,
        )
        if instruction is None:
            raise IntakeError(
                f"No self review correction instruction is available for role {coding_role.role_name}"
            )
        self._dispatch_role_work(
            session=session,
            role=coding_role,
            work_item=correction_item,
            stage_name="self_review_correction_requested",
            instruction=instruction,
        )
        event = self._append_event(
            session_id=session.id,
            event_type="self_review_correction_requested",
            producer_type="coordinator",
            payload={
                "task_key": session.task_key,
                "role_name": coding_role.role_name,
                "work_item_id": correction_item.id,
                "current_stage": session.current_stage,
            },
        )
        return session, event

    def _enqueue_boy_scout_correction(
        self,
        session: Session,
        source_event: Event,
        actionable_findings_path: Path,
    ) -> tuple[Session, Event]:
        coding_role = self._primary_coding_role_for_work_type(session, "boy_scout_correction")
        correction_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="boy_scout_correction",
            title=f"Boy Scout improvements for {session.task_key}",
            owner_role_id=coding_role.id,
            source_event_id=source_event.id,
            priority=93,
        )
        self.artifact_repository.create(
            session_id=session.id,
            stage_name="boy-scout",
            artifact_type="boy_scout_actionable_markdown",
            path=str(actionable_findings_path),
            metadata={"source_event_id": source_event.id},
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="boy_scout_correction_requested",
            current_owner=coding_role.role_name,
        )
        session = self.session_repository.update_status(session.id, SessionStatus.ACTIVE)
        instruction = self._stage_instruction(
            "boy_scout_correction_requested",
            session.task_key,
            workflow_profile=session.workflow_profile,
            role_name=coding_role.role_name,
            session_policy=session.policy,
        )
        if instruction is None:
            raise IntakeError(
                f"No Boy Scout correction instruction is available for role {coding_role.role_name}"
            )
        self._dispatch_role_work(
            session=session,
            role=coding_role,
            work_item=correction_item,
            stage_name="boy_scout_correction_requested",
            instruction=instruction,
        )
        event = self._append_event(
            session_id=session.id,
            event_type="boy_scout_correction_requested",
            producer_type="coordinator",
            payload={
                "task_key": session.task_key,
                "role_name": coding_role.role_name,
                "work_item_id": correction_item.id,
                "current_stage": session.current_stage,
            },
        )
        return session, event

    def _handle_self_review_passed(
        self,
        session: Session,
        source_event: Event,
    ) -> tuple[Session, Event]:
        self._complete_active_self_review_work_item(session)
        return self._enqueue_post_implementation_quality_gate(
            session=session,
            source_event=source_event,
        )

    def _handle_self_review_issues_found(
        self,
        session: Session,
        source_event: Event,
    ) -> tuple[Session, Event]:
        self._complete_active_self_review_work_item(session)
        return self._enqueue_self_review_correction(
            session=session,
            source_event=source_event,
        )

    def _handle_self_review_blocked(
        self,
        session: Session,
        source_event: Event,
    ) -> tuple[Session, Event]:
        self._complete_active_self_review_work_item(session)
        reviewer_role = self.role_repository.get_by_name(session.id, CODE_REVIEWER_ROLE)
        if reviewer_role is None:
            raise IntakeError("Code reviewer role is missing for the session")
        self.work_item_repository.create(
            session_id=session.id,
            work_type="self_review_cycle_review",
            title=f"Self review cycle resolution for {session.task_key}",
            owner_role_id=reviewer_role.id,
            source_event_id=source_event.id,
            priority=92,
            status=WorkItemStatus.WAITING_FOR_OPERATOR,
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="self_review_requested",
            current_owner=CODE_REVIEWER_ROLE,
        )
        session = self.session_repository.update_status(session.id, SessionStatus.WAITING_FOR_OPERATOR)
        report_paths = self._previous_self_review_report_paths(session.id)[-2:]
        event = self._append_event(
            session_id=session.id,
            event_type="session_escalated_to_operator",
            producer_type="coordinator",
            payload={
                "reason": "self_review_cycle",
                "summary": str(source_event.payload.get("summary") or "").strip() or "self review cycle blocked",
                "details": str(source_event.payload.get("details") or "").strip()
                or "The reviewer reported a non-converging review cycle and stopped automatic retries.",
                "review_report_paths": report_paths,
                "current_stage": session.current_stage,
            },
        )
        return session, event

    def _enqueue_verification(
        self,
        session: Session,
        source_event: Event,
    ) -> tuple[Session, Event]:
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
        session = self.session_repository.update_status(session.id, SessionStatus.ACTIVE)
        verification_report_path = None
        if self.workdir_root is not None:
            verification_report_path = str(
                self.workdir_root / session.task_key / "spec" / "final-verification.md"
            )
        self._dispatch_role_work(
            session=session,
            role=verification_role,
            work_item=verification_item,
            stage_name="verification_requested",
            instruction=(
                f"Run deterministic verification for {session.task_key}. "
                "Treat this as a fresh workflow-level gate: run `run-test.sh` and `run-lint.sh`, "
                "do not run `run-build.sh`, do not modify code, and refresh the final verification evidence."
            ),
            extra_hydration={
                "verification_gate": "run-test.sh + run-lint.sh",
                "verification_report_path": verification_report_path,
            },
        )
        event = self._append_event(
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

    def _handle_doc_harvest_completed(
        self,
        session: Session,
        source_event: Event,
    ) -> tuple[Session, Event | None]:
        doc_items = [
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "doc_harvest" and item.status != WorkItemStatus.COMPLETED
        ]
        if not doc_items:
            raise IntakeError("No active doc harvest work item found for the session")

        active_item = doc_items[0]
        self.work_item_repository.update_status(active_item.id, WorkItemStatus.COMPLETED)
        self._stop_on_demand_role(session, DOC_HARVEST_ROLE)
        summary = str(source_event.payload.get("summary") or "").strip()
        if not summary:
            summary = "Documentation harvest completed."
        session, _ = self._finalize_doc_harvest(
            session=self._get_session_or_raise(session.id),
            summary=summary,
            producer_type="coordinator",
            producer_id=DOC_HARVEST_ROLE,
            emit_event=False,
        )
        session, commit_event = self._commit_task_state(session, "doc harvest")
        if commit_event is not None:
            return session, commit_event
        session, event = self._complete_session_and_attempt_delivery(session=session, source_event=source_event)
        return session, event

    def _finalize_doc_harvest(
        self,
        session: Session,
        summary: str,
        producer_type: str,
        producer_id: str | None,
        emit_event: bool = True,
    ) -> tuple[Session, Event | None]:
        if self.artifacts_root is None:
            raise IntakeError("Coordinator is missing artifact root")

        artifact_path = write_text_artifact(
            self.artifacts_root,
            session.task_key,
            "doc-harvest",
            "doc-harvest-summary.md",
            summary,
        )
        self.artifact_repository.create(
            session_id=session.id,
            stage_name="doc-harvest",
            artifact_type="doc_harvest_summary",
            path=str(artifact_path),
            metadata={"summary_length": len(summary)},
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="doc_harvest_completed",
            current_owner=None,
        )
        session = self.session_repository.update_status(session.id, SessionStatus.COMPLETED)
        if not emit_event:
            return session, None
        event = self._append_event(
            session_id=session.id,
            event_type="doc_harvest_completed",
            producer_type=producer_type,
            producer_id=producer_id,
            payload={
                "task_key": session.task_key,
                "summary_length": len(summary),
                "current_stage": session.current_stage,
                "status": session.status.value,
            },
        )
        return session, event

    def _enqueue_doc_harvest(
        self,
        session: Session,
        source_event: Event,
    ) -> tuple[Session, Event]:
        doc_role = self._ensure_on_demand_role(session, DOC_HARVEST_ROLE)
        doc_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="doc_harvest",
            title=f"Doc harvest for {session.task_key}",
            owner_role_id=doc_role.id,
            source_event_id=source_event.id,
            priority=112,
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="doc_harvest_requested",
            current_owner=DOC_HARVEST_ROLE,
        )
        session = self.session_repository.update_status(session.id, SessionStatus.ACTIVE)
        full_diff_path = None
        if self.workdir_root is not None:
            full_diff_path = str(self.workdir_root / session.task_key / "spec" / "full-diff.md")
        self._dispatch_role_work(
            session=session,
            role=doc_role,
            work_item=doc_item,
            stage_name="doc_harvest_requested",
            instruction=(
                f"Run documentation harvest for {session.task_key}. "
                "Generate or refresh `spec/full-diff.md`, use it as the source of truth, "
                "update grounded feature-level README targets only, commit only the documentation changes, "
                "and report a compact result summary."
            ),
            extra_hydration={
                "full_diff_path": full_diff_path,
            },
        )
        event = self._append_event(
            session_id=session.id,
            event_type="doc_harvest_requested",
            producer_type="coordinator",
            payload={
                "task_key": session.task_key,
                "role_name": DOC_HARVEST_ROLE,
                "work_item_id": doc_item.id,
                "source_event_id": source_event.id,
                "current_stage": session.current_stage,
                "status": session.status.value,
            },
        )
        return session, event

    def _enqueue_post_implementation_quality_gate(
        self,
        session: Session,
        source_event: Event,
    ) -> tuple[Session, Event]:
        if (session.policy or {}).get("boy_scout_policy") == "disabled":
            return self._enqueue_verification(session=session, source_event=source_event)
        return self._enqueue_boy_scout(session=session, source_event=source_event)

    def _enqueue_boy_scout(
        self,
        session: Session,
        source_event: Event,
    ) -> tuple[Session, Event]:
        scout_role = self._ensure_on_demand_role(session, CODE_SCOUT_ROLE)
        scout_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="boy_scout",
            title=f"Boy Scout pass for {session.task_key}",
            owner_role_id=scout_role.id,
            source_event_id=source_event.id,
            priority=91,
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="boy_scout_requested",
            current_owner=CODE_SCOUT_ROLE,
        )
        session = self.session_repository.update_status(session.id, SessionStatus.ACTIVE)
        findings_path = None
        deferred_path = None
        diff_path = None
        if self.workdir_root is not None:
            spec_root = self.workdir_root / session.task_key / "spec"
            diff_path = str(spec_root / "diff.md")
            findings_path = str(spec_root / "findings.md")
            deferred_candidate = spec_root / "scout-deferred.md"
            if deferred_candidate.is_file():
                deferred_path = str(deferred_candidate)
        self._dispatch_role_work(
            session=session,
            role=scout_role,
            work_item=scout_item,
            stage_name="boy_scout_requested",
            instruction=(
                f"Run a Boy Scout maintainability pass for {session.task_key}. "
                "Start from `spec/diff.md`, inspect only the highest-signal changed files, "
                "write `spec/findings.md` only when real maintainability findings exist, "
                "and otherwise return a clean result."
            ),
            extra_hydration={
                "diff_path": diff_path,
                "findings_path": findings_path,
                "deferred_findings_path": deferred_path,
            },
        )
        event = self._append_event(
            session_id=session.id,
            event_type="boy_scout_requested",
            producer_type="coordinator",
            payload={
                "task_key": session.task_key,
                "role_name": CODE_SCOUT_ROLE,
                "work_item_id": scout_item.id,
                "current_stage": session.current_stage,
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
        payload: dict,
    ) -> str:
        if (
            role_name in _STORY_PLANNING_ROLES
            and session.current_stage in _STORY_PLANNING_WORK_TYPE_BY_STAGE
            and (
                output_type == "failed"
                or (
                    output_type in {"passed", "completed"}
                    and bool(payload.get("needs_operator_input") is True)
                )
            )
        ):
            return "story_planning_blocked"
        if role_name in {IMPLEMENTER_ROLE, BUG_FIXER_ROLE} and output_type == "completed":
            if session.current_stage == "bug_analysis_requested":
                return "bug_analysis_completed"
            if session.current_stage == "story_spec_requested":
                return "story_spec_completed"
            if session.current_stage == "subtask_implementation_requested":
                return "subtask_completed"
            if session.current_stage in {
                "implementation_requested",
                "boy_scout_correction_requested",
                "self_review_correction_requested",
                "verification_correction_requested",
                "mr_followup_requested",
                "qa_reopen_requested",
            }:
                return "implementation_completed"
        if role_name == VERIFICATION_COORDINATOR_ROLE:
            if output_type in {"passed", "completed"} and session.current_stage == "verification_requested":
                return "verification_passed"
            if output_type == "failed" and session.current_stage == "verification_requested":
                return "verification_failed"
            if output_type == "blocked_verification_cycle" and session.current_stage == "verification_requested":
                return "verification_blocked"
        if role_name == CODE_REVIEWER_ROLE and session.current_stage == "self_review_requested":
            if output_type in {"passed", "completed"}:
                return "self_review_passed"
            if output_type == "skipped_not_needed":
                if self._optional_lane_policy_mode(session.policy, "self_review_policy") != "enabled":
                    raise IntakeError("Self review cannot be skipped when self_review_policy is required")
                return "self_review_passed"
            if output_type == "failed":
                return "self_review_issues_found"
            if output_type == "blocked_review_cycle":
                return "self_review_blocked"
        if role_name == CODE_SCOUT_ROLE and session.current_stage == "boy_scout_requested":
            if output_type in {"passed", "completed"}:
                return "boy_scout_completed"
            if output_type == "skipped_not_needed":
                if self._optional_lane_policy_mode(session.policy, "boy_scout_policy") != "enabled":
                    raise IntakeError("Boy Scout cannot be skipped when boy_scout_policy is required")
                return "boy_scout_completed"
        if role_name == DOC_HARVEST_ROLE and session.current_stage == "doc_harvest_requested":
            if output_type in {"passed", "completed"}:
                return "doc_harvest_completed"
            if output_type == "skipped_not_needed":
                if self._optional_lane_policy_mode(session.policy, "doc_harvest_policy") != "enabled":
                    raise IntakeError("Doc harvest cannot be skipped when doc_harvest_policy is required")
                return "doc_harvest_completed"
        if role_name == MR_COMMENTS_ANALYST_ROLE and session.current_stage == "mr_comments_analysis_requested":
            if output_type in {"passed", "completed"}:
                return "mr_comments_analysis_completed"
        if role_name == PROPOSAL_CONTEXT_WORKER_ROLE and session.current_stage == "proposal_context_requested":
            if output_type in {"passed", "completed"}:
                return "proposal_context_completed"
        if role_name == REQUIREMENTS_CLARIFIER_WORKER_ROLE and session.current_stage == "requirements_requested":
            if output_type in {"passed", "completed"}:
                return "requirements_completed"
        if role_name == ACCEPTANCE_CRITERIA_WORKER_ROLE and session.current_stage == "acceptance_criteria_requested":
            if output_type in {"passed", "completed"}:
                return "acceptance_criteria_completed"
        if role_name == CONSTRAINTS_WORKER_ROLE and session.current_stage == "constraints_requested":
            if output_type in {"passed", "completed"}:
                return "constraints_completed"
        if role_name == SPEC_VERIFIER_WORKER_ROLE and session.current_stage == "spec_verification_requested":
            if output_type in {"passed", "completed"}:
                return "spec_verification_completed"
            if output_type == "failed":
                return "spec_verification_blocked"
        if role_name == STORY_SPEC_WORKER_ROLE and session.current_stage == "story_spec_requested":
            if output_type in {"passed", "completed"}:
                return "story_spec_completed"
        if role_name == TASK_DECOMPOSER_WORKER_ROLE and session.current_stage == "task_decomposition_requested":
            if output_type in {"passed", "completed"}:
                return "task_decomposition_completed"
        raise IntakeError(
            f"Unsupported role output: role={role_name}, output_type={output_type}, stage={session.current_stage}"
        )

    def _record_role_output_artifacts(
        self,
        session: Session,
        role_name: str,
        output_type: str,
        payload: dict,
    ) -> Event:
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
        if role_name == CODE_REVIEWER_ROLE and session.current_stage == "self_review_requested":
            self._materialize_self_review_report(
                session=session,
                output_type=output_type,
                payload=payload,
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

    def _apply_runtime_output_markers(
        self,
        session: Session,
        role: Role,
        chunks: list[RuntimeOutputChunk],
    ) -> Session:
        current_session = session
        for chunk in chunks:
            for marker_type, payload in self._extract_output_markers(chunk.text):
                if marker_type == "output":
                    self._append_event(
                        session_id=current_session.id,
                        event_type="runtime_terminal_output_echo_ignored",
                        producer_type="coordinator",
                        payload={
                            "role_name": role.role_name,
                            "current_stage": current_session.current_stage,
                            "current_owner": current_session.current_owner,
                        },
                    )
                    continue
                self._record_runtime_marker_artifact(
                    session=current_session,
                    role=role,
                    marker_type=marker_type,
                    payload=payload,
                )
                self._append_runtime_marker_event(
                    session=current_session,
                    role=role,
                    marker_type=marker_type,
                    payload=payload,
                )
                if marker_type == "error":
                    current_session = self._escalate_runtime_error(
                        session=current_session,
                        role=role,
                        payload=payload,
                    )
        return current_session

    def _extract_output_markers(self, text: str) -> list[tuple[str, dict]]:
        results: list[tuple[str, dict]] = []
        lines = text.splitlines()
        index = 0
        while index < len(lines):
            line = lines[index]
            marker_type = self._line_marker_type(line)
            if marker_type is None:
                index += 1
                continue
            payload_lines = [line.split(":", 1)[1].strip()]
            cursor = index + 1
            parsed_payload: dict | None = None
            while True:
                raw_payload = "".join(
                    part if position == 0 else part.lstrip()
                    for position, part in enumerate(payload_lines)
                )
                try:
                    parsed = json.loads(raw_payload)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, dict):
                    parsed_payload = parsed
                    break
                if cursor >= len(lines) or self._line_marker_type(lines[cursor]) is not None:
                    break
                payload_lines.append(lines[cursor])
                cursor += 1
            if parsed_payload is not None:
                results.append((marker_type, parsed_payload))
            index = cursor
        return results

    def _line_marker_type(self, line: str) -> str | None:
        normalized = line.lstrip()
        if normalized.startswith("• "):
            normalized = normalized[2:].lstrip()
        if normalized.startswith("SDD_OUTPUT:"):
            return "output"
        if normalized.startswith("SDD_PROGRESS:"):
            return "progress"
        if normalized.startswith("SDD_ERROR:"):
            return "error"
        return None

    def _record_runtime_marker_artifact(
        self,
        session: Session,
        role: Role,
        marker_type: str,
        payload: dict,
    ) -> None:
        stage_name = f"runtime-marker-{role.role_name}"
        payload_text = json.dumps(payload, indent=2, sort_keys=True)
        artifact_path = write_text_artifact(
            self.artifacts_root,
            session.task_key,
            stage_name,
            f"{marker_type}.json",
            payload_text,
        )
        artifact_type = f"runtime_{marker_type}_json"
        self.artifact_repository.create(
            session_id=session.id,
            role_id=role.id,
            stage_name=stage_name,
            artifact_type=artifact_type,
            path=str(artifact_path),
            metadata={
                "role_name": role.role_name,
                "marker_type": marker_type,
                "current_stage": session.current_stage,
            },
        )

    def _append_runtime_marker_event(
        self,
        session: Session,
        role: Role,
        marker_type: str,
        payload: dict,
    ) -> Event:
        if marker_type == "progress":
            event_type = "role_progress_reported"
        elif marker_type == "error":
            event_type = "role_runtime_error_reported"
        else:
            event_type = "role_runtime_marker_reported"
        return self._append_event(
            session_id=session.id,
            event_type=event_type,
            producer_type="role",
            producer_id=role.role_name,
            payload={
                "role_name": role.role_name,
                "marker_type": marker_type,
                "current_stage": session.current_stage,
                **payload,
            },
        )

    def _escalate_runtime_error(
        self,
        session: Session,
        role: Role,
        payload: dict,
    ) -> Session:
        if session.status == SessionStatus.WAITING_FOR_OPERATOR and session.current_owner is None:
            return session
        active_work_item = self._find_active_work_item_for_role(session.id, role.id)
        if active_work_item is not None:
            self.work_item_repository.update_status(
                active_work_item.id,
                WorkItemStatus.WAITING_FOR_OPERATOR,
            )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage=session.current_stage,
            current_owner=None,
        )
        session = self.session_repository.update_status(
            session.id,
            SessionStatus.WAITING_FOR_OPERATOR,
        )
        self._append_event(
            session_id=session.id,
            event_type="session_escalated_to_operator",
            producer_type="coordinator",
            payload={
                "role_name": role.role_name,
                "current_stage": session.current_stage,
                "reason": "runtime_error",
                **payload,
            },
        )
        return session

    def _reconcile_session_dispatch(self, session: Session) -> bool:
        if session.current_owner is None:
            return False

        role = self.role_repository.get_by_name(session.id, session.current_owner)
        if role is None:
            return False

        work_item = self._find_active_work_item_for_role(session.id, role.id)
        if work_item is None:
            work_item = self._reconcile_missing_subtask_assignment(session, role)
            if work_item is None:
                return False

        if self._has_dispatch_event(
            session_id=session.id,
            work_item_id=work_item.id,
            stage_name=session.current_stage,
        ):
            return False

        instruction = self._stage_instruction(
            session.current_stage,
            session.task_key,
            workflow_profile=session.workflow_profile,
            role_name=role.role_name,
            session_policy=session.policy,
        )
        if instruction is None:
            return False

        self._dispatch_role_work(
            session=session,
            role=role,
            work_item=work_item,
            stage_name=session.current_stage,
            instruction=instruction,
        )
        self._append_event(
            session_id=session.id,
            event_type="session_dispatch_reconciled",
            producer_type="coordinator",
            payload={
                "role_name": role.role_name,
                "work_item_id": work_item.id,
                "stage_name": session.current_stage,
            },
        )
        return True

    def _reconcile_missing_subtask_assignment(
        self,
        session: Session,
        role: Role,
    ) -> WorkItem | None:
        if session.current_stage != "subtask_implementation_requested":
            return None
        if role.role_name != IMPLEMENTER_ROLE:
            return None

        next_item = next(
            (
                item
                for item in self.work_item_repository.list_for_session(session.id)
                if item.work_type == "subtask_implementation"
                and item.status == WorkItemStatus.UNASSIGNED
            ),
            None,
        )
        if next_item is None:
            return None

        return self.work_item_repository.update_assignment(
            next_item.id,
            owner_role_id=role.id,
            status=WorkItemStatus.ASSIGNED,
        )

    def _find_active_work_item_for_role(
        self,
        session_id: int,
        role_id: int | None,
    ) -> WorkItem | None:
        if role_id is None:
            return None
        for item in self.work_item_repository.list_for_session(session_id):
            if item.owner_role_id != role_id:
                continue
            if item.status != WorkItemStatus.ASSIGNED:
                continue
            return item
        return None

    def _find_active_primary_coding_work_item(
        self,
        session: Session,
    ) -> WorkItem | None:
        active_role = self._primary_coding_role_for_stage(session)
        if active_role is None:
            return None
        active_item = self._find_active_work_item_for_role(session.id, active_role.id)
        if active_item is None:
            return None
        if active_item.work_type not in {
            "bug_analysis",
            "story_spec",
            "subtask_implementation",
            "implementation",
            "self_review_correction",
            "verification_correction",
            "followup_implementation",
        }:
            return None
        return active_item

    def _complete_active_self_review_work_item(self, session: Session) -> None:
        reviewer_role = self.role_repository.get_by_name(session.id, CODE_REVIEWER_ROLE)
        if reviewer_role is None:
            raise IntakeError("Code reviewer role is missing for the session")
        active_item = self._find_active_work_item_for_role(session.id, reviewer_role.id)
        if active_item is None or active_item.work_type != "self_review":
            raise IntakeError("No active self review work item found for the session")
        self.work_item_repository.update_status(active_item.id, WorkItemStatus.COMPLETED)

    def _previous_self_review_report_paths(self, session_id: int) -> list[str]:
        paths: list[str] = []
        for artifact in self.artifact_repository.list_for_session(session_id):
            if artifact.artifact_type != "self_review_report_markdown":
                continue
            paths.append(artifact.path)
        return paths

    def _latest_artifact_path(
        self,
        session_id: int,
        artifact_type: str,
        *,
        role_name: str | None = None,
    ) -> str | None:
        role_id = None
        if role_name is not None:
            role = self.role_repository.get_by_name(session_id, role_name)
            if role is None:
                return None
            role_id = role.id

        latest_path: str | None = None
        for artifact in self.artifact_repository.list_for_session(session_id):
            if artifact.artifact_type != artifact_type:
                continue
            if role_id is not None and artifact.role_id != role_id:
                continue
            latest_path = artifact.path
        return latest_path

    def _bug_analysis_report_path(self, task_key: str) -> str | None:
        if self.workdir_root is None:
            return None
        return str(self.workdir_root / task_key / "spec" / "bug-analysis.md")

    def _default_extra_hydration_for_dispatch(
        self,
        session: Session,
        role: Role,
        stage_name: str,
    ) -> dict[str, str | int | None]:
        if session.workflow_profile == "story_full":
            story_payload = self._story_context_extra_hydration(session.task_key)
            if role.role_name == PROPOSAL_CONTEXT_WORKER_ROLE and stage_name == "proposal_context_requested":
                return story_payload
            if role.role_name == REQUIREMENTS_CLARIFIER_WORKER_ROLE and stage_name == "requirements_requested":
                payload = dict(story_payload)
                payload["requirements_clarification_mode"] = self._requirements_clarification_mode(session.policy)
                return payload
            if role.role_name in {
                ACCEPTANCE_CRITERIA_WORKER_ROLE,
                CONSTRAINTS_WORKER_ROLE,
                SPEC_VERIFIER_WORKER_ROLE,
                STORY_SPEC_WORKER_ROLE,
                TASK_DECOMPOSER_WORKER_ROLE,
            }:
                return story_payload
            if role.role_name == IMPLEMENTER_ROLE:
                payload = dict(story_payload)
                if stage_name == "boy_scout_correction_requested":
                    payload["issues_file_path"] = self._latest_artifact_path(
                        session.id,
                        "boy_scout_actionable_markdown",
                    )
                if stage_name == "verification_correction_requested":
                    payload["issues_file_path"] = self._latest_artifact_path(
                        session.id,
                        "final_verification_markdown",
                    )
                if stage_name == "self_review_correction_requested":
                    payload["issues_file_path"] = self._latest_artifact_path(
                        session.id,
                        "self_review_report_markdown",
                    )
                return payload
        if role.role_name == REQUIREMENTS_CLARIFIER_WORKER_ROLE and stage_name == "requirements_requested":
            return {
                "requirements_clarification_mode": self._requirements_clarification_mode(session.policy),
            }
        if role.role_name == IMPLEMENTER_ROLE:
            payload: dict[str, str | int | None] = {}
            if stage_name == "boy_scout_correction_requested":
                payload["issues_file_path"] = self._latest_artifact_path(
                    session.id,
                    "boy_scout_actionable_markdown",
                )
            if stage_name == "verification_correction_requested":
                payload["issues_file_path"] = self._latest_artifact_path(
                    session.id,
                    "final_verification_markdown",
                )
            if stage_name == "self_review_correction_requested":
                payload["issues_file_path"] = self._latest_artifact_path(
                    session.id,
                    "self_review_report_markdown",
                )
            if payload:
                return payload
        if session.workflow_profile != "bug_full" or role.role_name != BUG_FIXER_ROLE:
            return {}

        payload: dict[str, str | int | None] = {
            "bug_analysis_report_path": self._bug_analysis_report_path(session.task_key),
        }
        mode_by_stage = {
            "bug_analysis_requested": "analysis-only",
            "implementation_requested": "fix-only",
            "boy_scout_correction_requested": "fix-only",
            "verification_correction_requested": "fix-only",
            "self_review_correction_requested": "fix-only",
            "mr_followup_requested": "fix-only",
            "qa_reopen_requested": "fix-only",
        }
        if stage_name in mode_by_stage:
            payload["bug_mode"] = mode_by_stage[stage_name]
        if stage_name == "bug_analysis_requested":
            payload["primary_bug_inputs"] = "description.md + comments.md"
        if stage_name == "verification_correction_requested":
            payload["issues_file_path"] = self._latest_artifact_path(
                session.id,
                "role_output_summary",
                role_name=VERIFICATION_COORDINATOR_ROLE,
            )
        if stage_name == "self_review_correction_requested":
            payload["issues_file_path"] = self._latest_artifact_path(
                session.id,
                "self_review_report_markdown",
            )
        if stage_name == "boy_scout_correction_requested":
            payload["issues_file_path"] = self._latest_artifact_path(
                session.id,
                "boy_scout_actionable_markdown",
            )
        if stage_name == "mr_followup_requested":
            payload["followup_comments_path"] = self._latest_artifact_path(
                session.id,
                "mr_comments_markdown",
            )
            payload["followup_plan_index_path"] = str(self.workdir_root / session.task_key / "plan" / "index.md") if self.workdir_root is not None else None
            payload["followup_plan_directory_path"] = str(self.workdir_root / session.task_key / "plan") if self.workdir_root is not None else None
        if stage_name == "mr_comments_analysis_requested":
            payload["followup_comments_path"] = self._latest_artifact_path(
                session.id,
                "mr_comments_markdown",
            )
            if self.workdir_root is not None:
                payload["followup_plan_index_path"] = str(self.workdir_root / session.task_key / "plan" / "index.md")
                payload["followup_plan_directory_path"] = str(self.workdir_root / session.task_key / "plan")
        if stage_name == "qa_reopen_requested":
            payload["followup_comments_path"] = self._latest_artifact_path(
                session.id,
                "qa_reopen_comments",
            )
        return payload

    def _requirements_clarification_mode(self, policy: dict[str, str] | None) -> str:
        return (policy or {}).get("requirements_clarification_mode", "ask-selectively")

    def _optional_lane_policy_mode(
        self,
        policy: dict[str, str] | None,
        policy_key: str,
    ) -> str:
        value = str((policy or {}).get(policy_key, "enabled")).strip()
        if value in {"disabled", "enabled", "required"}:
            return value
        return "enabled"

    def _story_context_extra_hydration(
        self,
        task_key: str,
    ) -> dict[str, str | int | None]:
        if self.workdir_root is None:
            return {}
        context_root = self.workdir_root / task_key / "spec" / "context"
        return {
            "proposal_path": str(self.workdir_root / task_key / "spec" / "proposal.md"),
            "context_directory_path": str(context_root),
            "feature_overview_path": str(context_root / "feature-overview.md"),
            "relevant_code_path": str(context_root / "relevant-code.md"),
            "documentation_path": str(context_root / "documentation.md"),
            "implementation_patterns_path": str(context_root / "implementation-patterns.md"),
            "preconditions_path": str(context_root / "preconditions.md"),
        }

    def _find_operator_pending_work_item(self, session_id: int) -> WorkItem | None:
        for item in self.work_item_repository.list_for_session(session_id):
            if item.status != WorkItemStatus.WAITING_FOR_OPERATOR:
                continue
            if item.owner_role_id is None:
                continue
            return item
        return None

    def _retry_work_item_title(self, title: str) -> str:
        if title.startswith("Retry: "):
            return title
        return f"Retry: {title}"

    def _redirect_work_item_title(self, title: str, target_role_name: str) -> str:
        return f"Redirect to {target_role_name}: {title}"

    def _has_dispatch_event(
        self,
        session_id: int,
        work_item_id: int | None,
        stage_name: str,
    ) -> bool:
        if work_item_id is None:
            return False
        for event in self.event_repository.list_for_session(session_id):
            if event.event_type != "role_input_dispatched":
                continue
            if event.payload.get("work_item_id") != work_item_id:
                continue
            if event.payload.get("stage_name") != stage_name:
                continue
            return True
        return False

    def _stage_instruction(
        self,
        stage_name: str,
        task_key: str,
        workflow_profile: str | None = None,
        role_name: str | None = None,
        session_policy: dict[str, str] | None = None,
    ) -> str | None:
        if workflow_profile == "bug_full" and role_name == BUG_FIXER_ROLE:
            if stage_name == "bug_analysis_requested":
                return (
                    f"Mode: analysis-only\n"
                    f"Analyze bug {task_key} before implementation. "
                    "Identify probable root cause, expected fix direction, and whether a regression test should be added."
                )
            if stage_name == "implementation_requested":
                return (
                    f"Mode: fix-only\n"
                    f"Implement the bug fix for {task_key} using your current bug context and the saved bug analysis."
                )
            if stage_name == "verification_correction_requested":
                return (
                    f"Mode: fix-only\n"
                    f"Apply verification corrections for {task_key}. "
                    "Treat the verification report as a narrow bug-fix correction pass."
                )
            if stage_name == "self_review_correction_requested":
                return (
                    f"Mode: fix-only\n"
                    f"Apply self review corrections for {task_key}. "
                    "Treat the review findings as a narrow bug-fix correction pass."
                )
            if stage_name == "mr_followup_requested":
                return (
                    f"Mode: fix-only\n"
                    f"Apply MR follow-up changes for {task_key}. "
                    "Prioritize the latest MR comments as the highest-priority follow-up scope."
                )
            if stage_name == "qa_reopen_requested":
                return (
                    f"Mode: fix-only\n"
                    f"Apply QA reopen follow-up changes for {task_key}. "
                    "Prioritize the latest QA comments as the highest-priority follow-up scope."
                )
        if stage_name == "bug_analysis_requested":
            return (
                f"Analyze bug {task_key} before implementation. "
                "Identify probable root cause, expected fix direction, and whether a regression test should be added."
            )
        if stage_name == "proposal_context_requested":
            return (
                f"Collect proposal and context foundations for story {task_key}. "
                "Read `description.md` and `comments.md`, treat comments as the fresher source when they conflict, "
                "resolve explicit local file references from the snapshot, use Notion MCP for `notion.so` links when needed, "
                "treat other external links as operator-provided context references, "
                "and extract the compact problem statement, key clarifications, and the smallest useful project/context findings for the later story-spec step."
            )
        if stage_name == "requirements_requested":
            clarification_mode = self._requirements_clarification_mode(session_policy)
            return (
                f"Clarify the implementation requirements for story {task_key}. "
                "Resolve assumptions, edge cases, and out-of-scope boundaries before the final story-spec step. "
                f"Clarification mode: {clarification_mode}. "
                "If critical ambiguity remains, ask the operator directly in the live session instead of guessing."
            )
        if stage_name == "boy_scout_requested":
            policy_mode = self._optional_lane_policy_mode(session_policy, "boy_scout_policy")
            if policy_mode == "required":
                return (
                    f"Run a Boy Scout maintainability pass for {task_key}. "
                    "Start from `spec/diff.md`, inspect only the highest-signal changed files, "
                    "write `spec/findings.md` only when real maintainability findings exist, "
                    "and otherwise report a clean result. "
                    "This Boy Scout lane is required for this session, so do not emit skipped_not_needed."
                )
            return (
                f"Run a Boy Scout maintainability pass for {task_key}. "
                "Start from `spec/diff.md`, inspect only the highest-signal changed files, "
                "write `spec/findings.md` only when real maintainability findings exist, "
                "and otherwise report a clean result. "
                "Emit skipped_not_needed when the change surface is too weak to justify a meaningful maintainability pass."
            )
        if stage_name == "acceptance_criteria_requested":
            return (
                f"Prepare explicit acceptance criteria for story {task_key}. "
                "Use independently testable WHEN-THEN-SHALL criteria, cover happy paths, edge cases, and error scenarios from the clarified requirements, "
                "and ensure every meaningful clarified requirement decision is covered before the final story-spec step."
            )
        if stage_name == "constraints_requested":
            return (
                f"Prepare grounded implementation constraints for story {task_key}. "
                "Use `spec/context/project.md` as architectural ground truth, cite it instead of restating generic conventions, "
                "and surface task-specific MUST, MUST NOT, and SHOULD constraints before the final story-spec step."
            )
        if stage_name == "spec_verification_requested":
            return (
                f"Verify the assembled planning package for story {task_key}. "
                "Check for contradictions, missing implementation-shaping details, and planning gaps before the final story-spec step."
            )
        if stage_name == "story_spec_requested":
            return (
                f"Prepare the final implementation-shaping story spec for {task_key} before coding. "
                "Turn the verified planning package into a durable implementation guide that clarifies intended scope, key constraints, implementation approach, "
                "and architecture-sensitive decisions that should guide decomposition and coding."
            )
        if stage_name == "task_decomposition_requested":
            return (
                f"Prepare task decomposition for story {task_key}. "
                "Produce a temporary `plan/index.md` plus self-contained `plan/NN-*.md` task package only for Jira subtask materialization, then hand execution over to the Jira-subtask flow."
            )
        if stage_name == "subtask_implementation_requested":
            return (
                f"Continue sequential subtask implementation for {task_key}. "
                "Use Jira subtasks from the refreshed snapshot as the source of truth, and finish the currently assigned subtask before moving to the next one."
            )
        if stage_name == "implementation_requested":
            return (
                f"Start implementation work for {task_key}. "
                "Read task snapshot inputs such as `description.md`, `comments.md`, and `spec/diff.md` when they exist before deciding that no concrete implementation work is present."
            )
        if stage_name == "boy_scout_correction_requested":
            return f"Apply Boy Scout improvements for {task_key} from the routed findings file as a narrow correction pass."
        if stage_name == "verification_requested":
            return (
                f"Run deterministic verification for {task_key}. "
                "Emit passed when the gate is clean, failed when concrete corrections are needed, "
                "or blocked_verification_cycle when the same verification loop is no longer converging and needs operator intervention."
            )
        if stage_name == "verification_correction_requested":
            return f"Apply verification corrections for {task_key}."
        if stage_name == "self_review_requested":
            policy_mode = self._optional_lane_policy_mode(session_policy, "self_review_policy")
            if policy_mode == "required":
                return (
                    f"Review the current task changes for {task_key}. "
                    "Emit passed if the review is clean, failed if issues still require correction, "
                    "or blocked_review_cycle if the same review loop is no longer converging and needs operator intervention. "
                    "This self-review lane is required for this session, so do not emit skipped_not_needed."
                )
            return (
                f"Review the current task changes for {task_key}. "
                "Emit passed if the review is clean, failed if issues still require correction, "
                "blocked_review_cycle if the same review loop is no longer converging, "
                "or skipped_not_needed if this diff is too small or too low-signal to justify a real review pass."
            )
        if stage_name == "self_review_correction_requested":
            return f"Apply self review corrections for {task_key}."
        if stage_name == "doc_harvest_requested":
            policy_mode = self._optional_lane_policy_mode(session_policy, "doc_harvest_policy")
            if policy_mode == "required":
                return (
                    f"Run documentation harvest for {task_key}. "
                    "Generate or refresh `spec/full-diff.md`, use it as the source of truth, update grounded feature-level README targets only, "
                    "commit only the documentation changes, and report a compact result summary. "
                    "This documentation lane is required for this session, so do not emit skipped_not_needed."
                )
            return (
                f"Run documentation harvest for {task_key}. "
                "Generate or refresh `spec/full-diff.md`, use it as the source of truth, update grounded feature-level README targets only, commit only the documentation changes, and report a compact result summary."
                " Emit skipped_not_needed when the completed change has no grounded README/doc target or does not warrant a documentation update."
            )
        if stage_name == "mr_comments_analysis_requested":
            return (
                f"Analyze unresolved MR comments for {task_key}. "
                "Group them into actionable follow-up themes, write the follow-up plan package under `plan/`, and summarize the implementer-ready next steps."
            )
        if stage_name == "mr_followup_requested":
            return (
                f"Apply MR follow-up changes for {task_key}. "
                "Start from `plan/index.md` when it exists and use the generated follow-up plan files plus the latest MR comments artifact as the highest-priority scope."
            )
        if stage_name == "qa_reopen_requested":
            return f"Apply QA reopen follow-up changes for {task_key}."
        return None

    def _effective_role_names(self, workflow_profile: str, policy: dict[str, str] | None) -> list[str]:
        role_names = list(self.default_roles)
        if MR_COMMENTS_ANALYST_ROLE not in role_names:
            role_names.append(MR_COMMENTS_ANALYST_ROLE)
        if workflow_profile == "bug_full" and BUG_FIXER_ROLE not in role_names:
            role_names.append(BUG_FIXER_ROLE)
        if (policy or {}).get("self_review_policy") != "disabled" and CODE_REVIEWER_ROLE not in role_names:
            role_names.append(CODE_REVIEWER_ROLE)
        if (policy or {}).get("boy_scout_policy") != "disabled" and CODE_SCOUT_ROLE not in role_names:
            role_names.append(CODE_SCOUT_ROLE)
        if (policy or {}).get("doc_harvest_policy") != "disabled" and DOC_HARVEST_ROLE not in role_names:
            role_names.append(DOC_HARVEST_ROLE)
        if workflow_profile == "story_full":
            for role_name in (
                PROPOSAL_CONTEXT_WORKER_ROLE,
                REQUIREMENTS_CLARIFIER_WORKER_ROLE,
                ACCEPTANCE_CRITERIA_WORKER_ROLE,
                CONSTRAINTS_WORKER_ROLE,
                SPEC_VERIFIER_WORKER_ROLE,
                STORY_SPEC_WORKER_ROLE,
                TASK_DECOMPOSER_WORKER_ROLE,
            ):
                if role_name not in role_names:
                    role_names.append(role_name)
        return role_names

    def _primary_coding_role_name_for_work_type(self, session: Session, work_type: str) -> str:
        if work_type == "doc_harvest":
            return DOC_HARVEST_ROLE
        if work_type == "mr_comments_analysis":
            return MR_COMMENTS_ANALYST_ROLE
        if session.workflow_profile != "bug_full":
            return IMPLEMENTER_ROLE
        if work_type in {
            "bug_analysis",
            "implementation",
            "boy_scout_correction",
            "followup_implementation",
            "self_review_correction",
            "verification_correction",
        }:
            return BUG_FIXER_ROLE
        return IMPLEMENTER_ROLE

    def _primary_coding_role_for_work_type(self, session: Session, work_type: str) -> Role:
        role_name = self._primary_coding_role_name_for_work_type(session, work_type)
        role = self.role_repository.get_by_name(session.id, role_name)
        if role is None:
            raise IntakeError(f"{role_name} role is missing for the session")
        return role

    def _primary_coding_role_for_stage(self, session: Session) -> Role | None:
        stage_to_work_type = {
            "bug_analysis_requested": "bug_analysis",
            "proposal_context_requested": "proposal_context",
            "requirements_requested": "requirements",
            "boy_scout_requested": "boy_scout",
            "doc_harvest_requested": "doc_harvest",
            "acceptance_criteria_requested": "acceptance_criteria",
            "constraints_requested": "constraints",
            "spec_verification_requested": "spec_verification",
            "story_spec_requested": "story_spec",
            "task_decomposition_requested": "task_decomposition",
            "subtask_implementation_requested": "subtask_implementation",
            "implementation_requested": "implementation",
            "boy_scout_correction_requested": "boy_scout_correction",
            "mr_comments_analysis_requested": "mr_comments_analysis",
            "self_review_correction_requested": "self_review_correction",
            "verification_correction_requested": "verification_correction",
            "mr_followup_requested": "followup_implementation",
            "qa_reopen_requested": "followup_implementation",
        }
        work_type = stage_to_work_type.get(session.current_stage)
        if work_type is None:
            return None
        try:
            return self._primary_coding_role_for_work_type(session, work_type)
        except IntakeError:
            return None

    def _ensure_on_demand_role(self, session: Session, role_name: str) -> Role:
        existing = self.role_repository.get_by_name(session.id, role_name)
        if existing is not None and existing.status != RoleStatus.STOPPED:
            return existing

        runtime_session = self._runtime_session_handle_for_session(session)
        runtime_role = self._spawn_role_runtime(
            runtime_session=runtime_session,
            task_key=session.task_key,
            role_name=role_name,
            role_config=(session.role_config or {}).get(role_name),
        )
        if existing is not None:
            return self.role_repository.update_runtime(
                existing.id,
                runtime_backend=runtime_role.backend_name,
                runtime_handle=runtime_role.role_id,
                status=RoleStatus.RUNNING,
            )
        return self.role_repository.create(
            session_id=session.id,
            role_name=role_name,
            runtime_backend=runtime_role.backend_name,
            runtime_handle=runtime_role.role_id,
            status=RoleStatus.RUNNING,
        )

    def _stop_on_demand_role(self, session: Session, role_name: str) -> None:
        if role_name in PERSISTENT_SESSION_ROLES:
            return
        role = self.role_repository.get_by_name(session.id, role_name)
        if role is None or role.runtime_handle is None:
            return
        runtime_role = RuntimeRoleHandle(
            role_id=role.runtime_handle,
            session_id=self._runtime_session_handle_for_session(session).session_id,
            backend_name=role.runtime_backend,
        )
        self.session_backend.stop_role(runtime_role)
        self.role_repository.update_status(role.id, RoleStatus.STOPPED)

    def _runtime_session_handle_for_session(self, session: Session) -> RuntimeSessionHandle:
        for role in self.role_repository.list_for_session(session.id):
            if role.runtime_handle and ":" in role.runtime_handle:
                runtime_session_id = role.runtime_handle.split(":", 1)[0]
                return RuntimeSessionHandle(session_id=runtime_session_id)
        raise IntakeError(f"Could not infer runtime session handle for session {session.id}")

    def get_runtime_state_summary(self, session_id: int) -> dict:
        session = self.session_repository.get_by_id(session_id)
        if session is None:
            raise IntakeError(f"Session {session_id} not found")
        roles = self.role_repository.list_for_session(session_id)
        runtime_session_id = None
        try:
            runtime_session_id = self._runtime_session_handle_for_session(session).session_id
        except IntakeError:
            runtime_session_id = None
        tmux_session_visibility = None
        if runtime_session_id is not None and hasattr(self.session_backend, "get_tmux_visibility"):
            tmux_session_visibility = self.session_backend.get_tmux_visibility(runtime_session_id)
        role_summaries = []
        for role in roles:
            role_tmux_visibility = None
            if (
                runtime_session_id is not None
                and role.runtime_handle is not None
                and hasattr(self.session_backend, "get_tmux_visibility")
            ):
                role_tmux_visibility = self.session_backend.get_tmux_visibility(
                    runtime_session_id,
                    role.runtime_handle,
                )
            role_summaries.append(
                {
                    "role_name": role.role_name,
                    "status": role.status.value,
                    "runtime_backend": role.runtime_backend,
                    "runtime_handle": role.runtime_handle,
                    "tmux_attach_command": (
                        role_tmux_visibility.get("tmux_role_attach_command")
                        if isinstance(role_tmux_visibility, dict)
                        else None
                    ),
                    "tmux_capture_command": (
                        role_tmux_visibility.get("tmux_role_capture_command")
                        if isinstance(role_tmux_visibility, dict)
                        else None
                    ),
                }
            )
        last_auto_recovery = None
        for event in reversed(self.event_repository.list_for_session(session_id)):
            if event.event_type == "runtime_role_auto_recovery_attempted":
                last_auto_recovery = {
                    "role_name": event.payload.get("role_name"),
                    "current_stage": event.payload.get("current_stage"),
                    "runtime_handle": event.payload.get("runtime_handle"),
                    "dead_runtime_handle": event.payload.get("dead_runtime_handle"),
                    "event_id": event.id,
                    "created_at": event.created_at,
                }
                break
        return {
            "available": runtime_session_id is not None,
            "runtime_session_id": runtime_session_id,
            "tmux_socket_path": (
                tmux_session_visibility.get("tmux_socket_path")
                if isinstance(tmux_session_visibility, dict)
                else None
            ),
            "tmux_attach_command": (
                tmux_session_visibility.get("tmux_attach_command")
                if isinstance(tmux_session_visibility, dict)
                else None
            ),
            "last_auto_recovery": last_auto_recovery,
            "roles": role_summaries,
        }

    def get_active_runtime_output_summary(self, session_id: int) -> dict:
        session = self.session_repository.get_by_id(session_id)
        if session is None:
            raise IntakeError(f"Session {session_id} not found")

        roles = self.role_repository.list_for_session(session_id)
        candidate_roles: list[Role] = []

        if session.current_owner is not None:
            current_owner_role = self.role_repository.get_by_name(session_id, session.current_owner)
            if current_owner_role is not None:
                candidate_roles.append(current_owner_role)

        owned_role_ids = {
            item.owner_role_id
            for item in self.work_item_repository.list_for_session(session.id)
            if item.owner_role_id is not None and item.status in {WorkItemStatus.ASSIGNED, WorkItemStatus.WAITING_FOR_OPERATOR}
        }
        candidate_roles.extend(
            role
            for role in roles
            if role.id in owned_role_ids and role not in candidate_roles
        )
        candidate_roles.extend(
            role
            for role in roles
            if role.status == RoleStatus.RUNNING and role not in candidate_roles
        )

        active_role = next(
            (role for role in candidate_roles if role.runtime_handle is not None and role.status == RoleStatus.RUNNING),
            None,
        )
        if active_role is None:
            return {
                "available": False,
                "role_name": None,
                "runtime_handle": None,
                "content": "",
            }

        runtime_role = RuntimeRoleHandle(
            role_id=active_role.runtime_handle,
            session_id=self._runtime_session_handle_for_session(session).session_id,
            backend_name=active_role.runtime_backend,
        )
        content = self.session_backend.capture_output_snapshot(runtime_role)
        return {
            "available": True,
            "role_name": active_role.role_name,
            "runtime_handle": active_role.runtime_handle,
            "content": content,
        }

    def stop_runtime_role(self, session_id: int, role_name: str) -> tuple[Session, Event]:
        session = self.session_repository.get_by_id(session_id)
        if session is None:
            raise IntakeError(f"Session {session_id} not found")
        role = self.role_repository.get_by_name(session_id, role_name)
        if role is None or role.runtime_handle is None:
            raise IntakeError(f"Role {role_name} has no live runtime handle")
        runtime_role = RuntimeRoleHandle(
            role_id=role.runtime_handle,
            session_id=self._runtime_session_handle_for_session(session).session_id,
            backend_name=role.runtime_backend,
        )
        self.session_backend.stop_role(runtime_role)
        self.role_repository.update_status(role.id, RoleStatus.STOPPED)
        session = self.session_repository.update_status(session_id, SessionStatus.PAUSED)
        event = self._append_event(
            session_id=session.id,
            event_type="runtime_role_stopped_by_operator",
            producer_type="operator",
            payload={
                "role_name": role_name,
                "runtime_handle": role.runtime_handle,
            },
        )
        return session, event

    def stop_runtime_session(self, session_id: int) -> tuple[Session, Event]:
        session = self.session_repository.get_by_id(session_id)
        if session is None:
            raise IntakeError(f"Session {session_id} not found")
        runtime_session = self._runtime_session_handle_for_session(session)
        self.session_backend.stop_session(runtime_session)
        for role in self.role_repository.list_for_session(session_id):
            self.role_repository.update_status(role.id, RoleStatus.STOPPED)
        session = self.session_repository.update_status(session_id, SessionStatus.PAUSED)
        event = self._append_event(
            session_id=session.id,
            event_type="runtime_session_stopped_by_operator",
            producer_type="operator",
            payload={
                "runtime_session_id": runtime_session.session_id,
            },
        )
        return session, event

    def restart_runtime_role(self, session_id: int, role_name: str) -> tuple[Session, Event, Event | None]:
        session = self._get_session_or_raise(session_id)
        role = self.role_repository.get_by_name(session_id, role_name)
        if role is None:
            raise IntakeError(f"Role {role_name} is missing for session {session_id}")
        if role.status != RoleStatus.STOPPED:
            raise IntakeError(f"Role {role_name} is not stopped")

        runtime_role = self._spawn_role_runtime(
            runtime_session=self._runtime_session_handle_for_session(session),
            task_key=session.task_key,
            role_name=role.role_name,
            role_config=(session.role_config or {}).get(role.role_name),
            resume_mode="native",
        )
        role = self.role_repository.update_runtime(
            role.id,
            runtime_backend=runtime_role.backend_name,
            runtime_handle=runtime_role.role_id,
            status=RoleStatus.RUNNING,
        )
        followup_event = self._reactivate_restarted_owner_work(session, role)
        refreshed = self._get_session_or_raise(session_id)
        event = self._append_event(
            session_id=refreshed.id,
            event_type="runtime_role_restarted_by_operator",
            producer_type="operator",
            payload={
                "role_name": role.role_name,
                "runtime_handle": role.runtime_handle,
                "session_reactivated": followup_event is not None,
            },
        )
        return refreshed, event, followup_event

    def restart_runtime_session(self, session_id: int) -> tuple[Session, Event, Event | None]:
        session = self._get_session_or_raise(session_id)
        runtime_session = self.session_backend.create_task_session(session.task_key)
        updated_owner: Role | None = None
        for role in self.role_repository.list_for_session(session.id):
            runtime_role = self._spawn_role_runtime(
                runtime_session=runtime_session,
                task_key=session.task_key,
                role_name=role.role_name,
                role_config=(session.role_config or {}).get(role.role_name),
                resume_mode="native",
            )
            updated_role = self.role_repository.update_runtime(
                role.id,
                runtime_backend=runtime_role.backend_name,
                runtime_handle=runtime_role.role_id,
                status=RoleStatus.RUNNING,
            )
            if updated_role.role_name == session.current_owner:
                updated_owner = updated_role

        followup_event = self._reactivate_restarted_owner_work(session, updated_owner)
        refreshed = self._get_session_or_raise(session_id)
        event = self._append_event(
            session_id=refreshed.id,
            event_type="runtime_session_restarted_by_operator",
            producer_type="operator",
            payload={
                "runtime_session_id": runtime_session.session_id,
                "session_reactivated": followup_event is not None,
            },
        )
        return refreshed, event, followup_event

    def cleanup_task(
        self,
        session_id: int,
        *,
        cleanup_mode: str,
        force: bool = False,
    ) -> dict:
        session = self._get_session_or_raise(session_id)
        if cleanup_mode not in {"soft", "full", "smart"}:
            raise IntakeError(f"Unsupported cleanup mode: {cleanup_mode}")

        jira_status = self._get_jira_status_name(session.task_key)
        full_cleanup_allowed = (
            jira_status is not None and jira_status.strip().lower() in _CLOSED_JIRA_STATUSES
        )
        effective_cleanup_mode = "full" if cleanup_mode == "smart" and full_cleanup_allowed else cleanup_mode
        if effective_cleanup_mode == "smart":
            effective_cleanup_mode = "soft"
        if effective_cleanup_mode == "full" and not force and not full_cleanup_allowed:
            raise IntakeError(
                f"Full cleanup requires a closed Jira status; current status is {jira_status or 'unknown'}"
            )

        removed_paths: list[str] = []
        removed_paths.extend(self._stop_and_clear_runtime_handles(session))
        removed_paths.extend(self._remove_task_runtime_residue(session.task_key))
        removed_paths.extend(self._remove_runner_private_residue(session.task_key))

        deleted_session = False
        if effective_cleanup_mode == "full":
            removed_paths.extend(self._remove_task_artifacts(session.task_key))
            removed_paths.extend(self._remove_task_worktree_and_directory(session.task_key))
            self.session_repository.delete(session.id)
            deleted_session = True
        else:
            refreshed = self._get_session_or_raise(session_id)
            self._append_event(
                session_id=refreshed.id,
                event_type="task_runtime_cleaned_by_operator",
                producer_type="operator",
                payload={
                    "task_key": refreshed.task_key,
                    "cleanup_mode": effective_cleanup_mode,
                    "removed_paths": removed_paths,
                },
            )

        return {
            "cleaned": True,
            "deleted_session": deleted_session,
            "cleanup_mode": effective_cleanup_mode,
            "task_key": session.task_key,
            "jira_status": jira_status,
            "full_cleanup_allowed": full_cleanup_allowed,
            "removed_paths": removed_paths,
            "session": None if deleted_session else self._get_session_or_raise(session_id),
        }

    def cleanup_closed_tasks(self) -> list[dict]:
        if self.workdir_root is None:
            raise IntakeError("Coordinator is missing workdir root")

        results: list[dict] = []
        candidates: set[str] = set()
        for session in self.session_repository.list_all():
            candidates.add(session.task_key)
        for child in self.workdir_root.iterdir():
            if child.is_dir() and _TASK_KEY_PATTERN.match(child.name):
                candidates.add(child.name)

        for task_key in sorted(candidates):
            jira_status = self._get_jira_status_name(task_key)
            if jira_status is None or jira_status.strip().lower() not in _CLOSED_JIRA_STATUSES:
                continue
            session = self.session_repository.get_by_task_key(task_key)
            if session is None:
                removed_paths: list[str] = []
                removed_paths.extend(self._remove_task_runtime_residue(task_key))
                removed_paths.extend(self._remove_runner_private_residue(task_key))
                removed_paths.extend(self._remove_task_artifacts(task_key))
                removed_paths.extend(self._remove_task_worktree_and_directory(task_key))
                results.append(
                    {
                        "task_key": task_key,
                        "jira_status": jira_status,
                        "deleted_session": False,
                        "removed_paths": removed_paths,
                    }
                )
                continue

            result = self.cleanup_task(session.id, cleanup_mode="full", force=True)
            results.append(
                {
                    "task_key": task_key,
                    "jira_status": jira_status,
                    "deleted_session": bool(result["deleted_session"]),
                    "removed_paths": list(result["removed_paths"]),
                }
            )
        return results

    def _spawn_role_runtime(
        self,
        *,
        runtime_session: RuntimeSessionHandle,
        task_key: str,
        role_name: str,
        role_config: dict[str, str] | None,
        resume_mode: str | None = None,
    ) -> RuntimeRoleHandle:
        if role_config is None:
            role_config = normalize_role_runtime_config(
                repo_root=self._repo_root(),
                role_names=[role_name],
                provided=None,
            ).get(role_name)
        start_directory = None
        launch_command = None
        if self.role_workspace_manager is not None:
            workspace = self.role_workspace_manager.ensure_role_workspace(task_key, role_name)
            start_directory = workspace.directory
            if self.role_launcher_manager is not None:
                launch_plan = self.role_launcher_manager.ensure_launch_plan(
                    task_key=task_key,
                    workspace=workspace,
                    role_config=role_config,
                    resume_mode=resume_mode,
                )
                launch_command = launch_plan.command
        return self.session_backend.spawn_role(
            runtime_session,
            role_name,
            start_directory=start_directory,
            launch_command=launch_command,
        )

    def _reactivate_restarted_owner_work(self, session: Session, role: Role | None) -> Event | None:
        if role is None or session.current_owner != role.role_name:
            return None

        work_item = self._find_active_work_item_for_role(session.id, role.id)
        if work_item is None:
            return None

        instruction = self._resume_stage_instruction(
            session.current_stage,
            session.task_key,
            workflow_profile=session.workflow_profile,
            role_name=role.role_name,
            session_policy=session.policy,
        )
        if instruction is None:
            return None

        session = self.session_repository.update_status(session.id, SessionStatus.ACTIVE)
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage=session.current_stage,
            current_owner=role.role_name,
        )
        return self._dispatch_role_work(
            session=session,
            role=role,
            work_item=work_item,
            stage_name=session.current_stage,
            instruction=instruction,
        )

    def _resume_stage_instruction(
        self,
        stage_name: str,
        task_key: str,
        *,
        workflow_profile: str,
        role_name: str,
        session_policy: dict[str, str] | None = None,
    ) -> str | None:
        base_instruction = self._stage_instruction(
            stage_name,
            task_key,
            workflow_profile=workflow_profile,
            role_name=role_name,
            session_policy=session_policy,
        )
        if base_instruction is None:
            return None
        return (
            f"{base_instruction}\n\n"
            "This task session was restored after a runtime interruption.\n"
            "If this routed work was already in progress, continue and finish the same unfinished work from your existing live session context.\n"
            "Do not restart the whole analysis from scratch unless the current workspace files require a targeted refresh."
        )

    def _read_snapshot_subtasks(self, task_key: str) -> list | None:
        if self.workdir_root is None:
            return None
        statuses_file = self.workdir_root / task_key / "statuses.md"
        if not statuses_file.exists():
            return None
        return read_snapshot_subtasks(statuses_file)

    def _read_snapshot_subtasks_or_raise(self, task_key: str) -> list:
        subtasks = self._read_snapshot_subtasks(task_key)
        if subtasks is None:
            raise IntakeError(f"statuses.md not found for session {task_key}")
        return subtasks

    def _parse_subtask_work_item_title(self, title: str) -> dict[str, str | None]:
        prefix = "Subtask implementation for "
        if not title.startswith(prefix):
            return {"key": None, "title": title}
        payload = title[len(prefix):]
        if ": " not in payload:
            return {"key": payload.strip() or None, "title": title}
        key, item_title = payload.split(": ", 1)
        return {
            "key": key.strip() or None,
            "title": item_title.strip() or title,
        }

    def _refresh_subtask_snapshot(self, session: Session) -> tuple[list | None, bool]:
        if self.snapshot_adapter is None:
            return None, False

        result = self.snapshot_adapter.run(session.task_key)
        if self.artifacts_root is not None:
            stdout_path = write_text_artifact(
                self.artifacts_root,
                session.task_key,
                "subtask-graph",
                "snapshot-refresh.stdout.txt",
                result.stdout,
            )
            self.artifact_repository.create(
                session_id=session.id,
                stage_name="subtask-graph",
                artifact_type="subtask_snapshot_refresh_stdout",
                path=str(stdout_path),
                metadata={"exit_code": result.returncode},
            )
            stderr_path = write_text_artifact(
                self.artifacts_root,
                session.task_key,
                "subtask-graph",
                "snapshot-refresh.stderr.txt",
                result.stderr,
            )
            self.artifact_repository.create(
                session_id=session.id,
                stage_name="subtask-graph",
                artifact_type="subtask_snapshot_refresh_stderr",
                path=str(stderr_path),
                metadata={"exit_code": result.returncode},
            )

        if not result.ok:
            self._append_event(
                session_id=session.id,
                event_type="subtask_snapshot_refresh_failed",
                producer_type="coordinator",
                payload={
                    "task_key": session.task_key,
                    "snapshot_exit_code": result.returncode,
                },
            )
            return None, False

        subtasks = self._read_snapshot_subtasks(session.task_key)
        if subtasks is None:
            return None, True

        self._record_subtask_statuses_artifact(session, subtasks)
        unresolved = unresolved_subtasks(subtasks)
        self._append_event(
            session_id=session.id,
            event_type="subtask_snapshot_refreshed",
            producer_type="coordinator",
            payload={
                "task_key": session.task_key,
                "snapshot_exit_code": result.returncode,
                "subtask_count": len(subtasks),
                "unresolved_count": len(unresolved),
            },
        )
        return subtasks, True

    def _reconcile_subtask_queue_after_refresh(
        self,
        *,
        session: Session,
        source_event: Event,
        queued_items: list[WorkItem],
        unresolved: list,
    ) -> list[WorkItem]:
        if not unresolved:
            for item in queued_items:
                self.work_item_repository.update_status(item.id, WorkItemStatus.COMPLETED)
            return []

        desired_count = len(unresolved)
        normalized_items = queued_items[:desired_count]
        for extra_item in queued_items[desired_count:]:
            self.work_item_repository.update_status(extra_item.id, WorkItemStatus.COMPLETED)

        reconciled: list[WorkItem] = []
        for index, subtask in enumerate(unresolved):
            title = f"Subtask implementation for {subtask.key}: {subtask.title}"
            priority = max(70 - index, 1)
            if index < len(normalized_items):
                reconciled.append(
                    self.work_item_repository.update_shape(
                        normalized_items[index].id,
                        work_type="subtask_implementation",
                        title=title,
                        owner_role_id=None,
                        status=WorkItemStatus.UNASSIGNED,
                    )
                )
                continue
            reconciled.append(
                self.work_item_repository.create(
                    session_id=session.id,
                    work_type="subtask_implementation",
                    title=title,
                    owner_role_id=None,
                    source_event_id=source_event.id,
                    priority=priority,
                    status=WorkItemStatus.UNASSIGNED,
                )
            )
        return reconciled

    def _record_subtask_statuses_artifact(self, session: Session, subtasks: list) -> None:
        if self.artifacts_root is None or self.workdir_root is None:
            raise IntakeError("Coordinator is missing workdir root or artifact root")

        unresolved = unresolved_subtasks(subtasks)
        statuses_file = self.workdir_root / session.task_key / "statuses.md"
        artifact_path = write_text_artifact(
            self.artifacts_root,
            session.task_key,
            "subtask-graph",
            "statuses.md",
            statuses_file.read_text(),
        )
        self.artifact_repository.create(
            session_id=session.id,
            stage_name="subtask-graph",
            artifact_type="subtask_statuses_markdown",
            path=str(artifact_path),
            metadata={
                "subtask_count": len(subtasks),
                "unresolved_count": len(unresolved),
            },
        )

    def _latest_artifact_for_session_type(
        self,
        session_id: int,
        artifact_type: str,
    ) -> Artifact | None:
        for artifact in reversed(self.artifact_repository.list_for_session(session_id)):
            if artifact.artifact_type == artifact_type:
                return artifact
        return None

    def _task_decomposition_markdown(
        self,
        *,
        summary: str,
        task_breakdown: str,
    ) -> str:
        lines = ["# Task Decomposition", ""]
        if summary:
            lines.extend(["## Summary", "", summary, ""])
        if task_breakdown:
            lines.extend(["## Task Breakdown", "", task_breakdown, ""])
        return "\n".join(lines).rstrip() + "\n"

    def _materialize_story_spec_file(
        self,
        *,
        session: Session,
        filename: str,
        artifact_type: str,
        title: str,
        explicit_markdown: str,
        sections: list[tuple[str, str]],
    ) -> None:
        if self.workdir_root is None or self.artifacts_root is None:
            return

        spec_root = self.workdir_root / session.task_key / "spec"
        spec_root.mkdir(parents=True, exist_ok=True)
        target_path = spec_root / filename
        if explicit_markdown:
            content = explicit_markdown.rstrip() + "\n"
        elif target_path.is_file():
            existing_content = target_path.read_text().strip()
            if existing_content:
                content = existing_content.rstrip() + "\n"
            else:
                lines = [f"# {title}", ""]
                for heading, body in sections:
                    normalized = body.strip()
                    if not normalized:
                        continue
                    lines.extend([f"## {heading}", "", normalized, ""])
                content = "\n".join(lines).rstrip() + "\n"
        else:
            lines = [f"# {title}", ""]
            for heading, body in sections:
                normalized = body.strip()
                if not normalized:
                    continue
                lines.extend([f"## {heading}", "", normalized, ""])
            content = "\n".join(lines).rstrip() + "\n"
        target_path.write_text(content)

        artifact_path = write_text_artifact(
            self.artifacts_root,
            session.task_key,
            "planning",
            filename,
            content,
        )
        self.artifact_repository.create(
            session_id=session.id,
            stage_name="planning",
            artifact_type=artifact_type,
            path=str(artifact_path),
            metadata={
                "task_key": session.task_key,
                "source_path": str(target_path),
            },
        )

    def _sync_role_workspace_outputs_to_task_snapshot(
        self,
        *,
        session: Session,
        role_name: str,
        outputs: object,
    ) -> None:
        if self.role_workspace_manager is None or self.workdir_root is None:
            return
        if not isinstance(outputs, list):
            return

        workspace_root = self.role_workspace_manager.role_directory(session.task_key, role_name)
        task_root = self.workdir_root / session.task_key
        for raw_output in outputs:
            relative_path = str(raw_output).strip()
            if not relative_path or relative_path == "RESULT.json":
                continue
            candidate = Path(relative_path)
            if candidate.is_absolute():
                continue
            normalized = Path(*[part for part in candidate.parts if part not in {"", "."}])
            if any(part == ".." for part in normalized.parts):
                continue
            source_path = workspace_root / normalized
            if not source_path.is_file():
                continue
            target_path = task_root / normalized
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, target_path)

    def _materialize_final_verification_file(
        self,
        *,
        session: Session,
        source_event: Event,
    ) -> None:
        if self.workdir_root is None or self.artifacts_root is None:
            return

        spec_root = self.workdir_root / session.task_key / "spec"
        spec_root.mkdir(parents=True, exist_ok=True)
        target_path = spec_root / "final-verification.md"
        explicit_markdown = str(source_event.payload.get("final_verification_markdown") or "").strip()
        if explicit_markdown:
            content = explicit_markdown.rstrip() + "\n"
        elif target_path.is_file():
            existing_content = target_path.read_text().strip()
            content = existing_content.rstrip() + "\n" if existing_content else ""
        else:
            summary = str(source_event.payload.get("summary") or "").strip()
            failures = source_event.payload.get("failures")
            failure_list: list[str] = []
            if isinstance(failures, list):
                failure_list = [str(item).strip() for item in failures if str(item).strip()]
            check_outputs = source_event.payload.get("check_outputs")
            rendered_outputs: list[tuple[str, str]] = []
            if isinstance(check_outputs, dict):
                for name, value in check_outputs.items():
                    rendered_name = str(name).strip()
                    rendered_value = str(value).strip()
                    if rendered_name and rendered_value:
                        rendered_outputs.append((rendered_name, rendered_value))
            passed = source_event.event_type == "verification_passed"
            lines = [f"# Final Verification: {session.task_key}", ""]
            if passed:
                lines.extend(
                    [
                        "## Result",
                        "PASS",
                        "",
                        "## Checks",
                        "- Tests: passed",
                        "- Linter: passed",
                    ]
                )
                if summary:
                    lines.extend(["", "## Summary", "", summary])
            else:
                lines.extend(["## Result", "FAIL"])
                if failure_list:
                    lines.extend(["", "## Failed checks", ""])
                    lines.extend(f"- {item}" for item in failure_list)
                if summary:
                    lines.extend(["", "## Summary", "", summary])
                for check_name, output_text in rendered_outputs:
                    lines.extend(
                        [
                            "",
                            f"## Output: {check_name}",
                            "",
                            "```text",
                            output_text,
                            "```",
                        ]
                    )
            content = "\n".join(lines).rstrip() + "\n"

        target_path.write_text(content)

        artifact_path = write_text_artifact(
            self.artifacts_root,
            session.task_key,
            "verification",
            "final-verification.md",
            content,
        )
        self.artifact_repository.create(
            session_id=session.id,
            stage_name="verification",
            artifact_type="final_verification_markdown",
            path=str(artifact_path),
            metadata={
                "task_key": session.task_key,
                "source_path": str(target_path),
            },
        )

    def _materialize_self_review_report(
        self,
        *,
        session: Session,
        output_type: str,
        payload: dict,
    ) -> None:
        if self.workdir_root is None or self.artifacts_root is None:
            return

        target_path = self._next_self_review_report_target_path(session)
        if target_path is None:
            return
        explicit_markdown = str(payload.get("review_markdown") or "").strip()
        if explicit_markdown:
            content = explicit_markdown.rstrip() + "\n"
        else:
            summary = str(payload.get("summary") or "").strip()
            issues_markdown = str(payload.get("issues_markdown") or "").strip()
            issues = payload.get("issues")
            lines: list[str] = []
            if output_type == "passed":
                lines.extend(["REVIEW_RESULT: clean"])
                if summary:
                    lines.extend(["", "## Summary", "", summary])
            else:
                lines.extend(["REVIEW_RESULT: issues_found"])
                if issues_markdown:
                    lines.extend(["", issues_markdown])
                elif isinstance(issues, list) and issues:
                    lines.extend(["", "## Issues", ""])
                    for raw_issue in issues:
                        if isinstance(raw_issue, dict):
                            severity = str(raw_issue.get("severity") or "warning").strip()
                            file_path = str(raw_issue.get("file") or "unknown").strip()
                            convention = str(raw_issue.get("convention") or "").strip()
                            problem = str(raw_issue.get("problem") or "").strip()
                            required_change = str(raw_issue.get("required_change") or "").strip()
                            lines.extend([f"### [{severity}] {file_path}"])
                            if convention:
                                lines.append(f"- Convention: {convention}")
                            if problem:
                                lines.append(f"- Problem: {problem}")
                            if required_change:
                                lines.append(f"- Required change: {required_change}")
                            lines.append("")
                        else:
                            rendered = str(raw_issue).strip()
                            if rendered:
                                lines.append(f"- {rendered}")
                    if lines and lines[-1] == "":
                        lines.pop()
                elif summary:
                    lines.extend(["", "## Issues", "", f"- {summary}"])
            content = "\n".join(lines).rstrip() + "\n"

        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(content)
        artifact_path = write_text_artifact(
            self.artifacts_root,
            session.task_key,
            "self-review",
            target_path.name,
            content,
        )
        self.artifact_repository.create(
            session_id=session.id,
            stage_name="self-review",
            artifact_type="self_review_report_markdown",
            path=str(artifact_path),
            metadata={
                "task_key": session.task_key,
                "source_path": str(target_path),
                "output_type": output_type,
            },
        )

    def _next_self_review_report_target_path(self, session: Session) -> Path | None:
        if self.workdir_root is None:
            return None
        review_dir = self.workdir_root / session.task_key / "review"
        pass_count = sum(
            1
            for artifact in self.artifact_repository.list_for_session(session.id)
            if artifact.artifact_type == "self_review_report_markdown"
        )
        return review_dir / f"pass-{pass_count + 1:02d}.md"

    def _write_task_decomposition_plan_package(
        self,
        *,
        session: Session,
        plan_index_markdown: str,
        raw_plan_task_files: object,
    ) -> None:
        if self.workdir_root is None:
            raise IntakeError("Coordinator is missing workdir root")

        plan_dir = self.workdir_root / session.task_key / "plan"
        plan_dir.mkdir(parents=True, exist_ok=True)

        index_path = plan_dir / "index.md"
        index_path.write_text(plan_index_markdown.rstrip() + "\n")

        normalized_task_files: list[str] = []
        if isinstance(raw_plan_task_files, list):
            for item in raw_plan_task_files:
                if not isinstance(item, dict):
                    continue
                filename = str(item.get("filename") or "").strip()
                content = str(item.get("content") or "").strip()
                if not filename or not content:
                    continue
                safe_name = Path(filename).name
                if safe_name != filename or not safe_name.endswith(".md"):
                    continue
                file_path = plan_dir / safe_name
                file_path.write_text(content.rstrip() + "\n")
                normalized_task_files.append(safe_name)

        self.artifact_repository.create(
            session_id=session.id,
            stage_name="planning",
            artifact_type="task_decomposition_plan_index",
            path=str(index_path),
            metadata={
                "task_key": session.task_key,
                "task_file_count": len(normalized_task_files),
            },
        )
        self.artifact_repository.create(
            session_id=session.id,
            stage_name="planning",
            artifact_type="task_decomposition_plan_package",
            path=str(plan_dir),
            metadata={
                "task_key": session.task_key,
                "task_files": normalized_task_files,
            },
        )

    def _normalize_task_decomposition_plan_package(
        self,
        *,
        session: Session,
        payload: dict[str, object],
    ) -> tuple[str, list[dict[str, str]]]:
        if self.workdir_root is None:
            raise IntakeError("Coordinator is missing workdir root")

        plan_dir = self.workdir_root / session.task_key / "plan"
        role_plan_dir: Path | None = None
        if self.role_workspace_manager is not None:
            candidate = self.role_workspace_manager.role_directory(
                session.task_key,
                TASK_DECOMPOSER_WORKER_ROLE,
            ) / "plan"
            if candidate.is_dir():
                role_plan_dir = candidate
        source_plan_dir = role_plan_dir if role_plan_dir is not None else (plan_dir if plan_dir.is_dir() else None)
        if source_plan_dir is None:
            raise IntakeError(f"Temporary plan package is missing for session {session.task_key}")

        index_path = source_plan_dir / "index.md"
        if not index_path.is_file():
            raise IntakeError("Task decomposition package is missing plan/index.md")
        plan_index_markdown = index_path.read_text().strip()
        if not plan_index_markdown:
            raise IntakeError("Task decomposition package contains an empty plan/index.md")

        normalized_task_files: list[dict[str, str]] = []
        for file_path in sorted(source_plan_dir.glob("*.md")):
            if file_path.name == "index.md":
                continue
            content = file_path.read_text().strip()
            if not content:
                continue
            normalized_task_files.append(
                {
                    "filename": file_path.name,
                    "content": content,
                }
            )

        if not normalized_task_files:
            raise IntakeError("Task decomposition package must contain at least one task markdown file")

        return plan_index_markdown, normalized_task_files

    def _cleanup_temporary_plan_package(self, session: Session) -> None:
        if self.workdir_root is None:
            raise IntakeError("Coordinator is missing workdir root")

        plan_dir = self.workdir_root / session.task_key / "plan"
        if not plan_dir.exists():
            return
        shutil.rmtree(plan_dir)

    def _jira_subtasks_summary_markdown(self, subtask_keys: list[str]) -> str:
        lines = ["# Created Jira Subtasks", ""]
        for key in subtask_keys:
            lines.append(f"- {key}")
        return "\n".join(lines).rstrip() + "\n"

    def _extract_created_subtask_keys(self, stdout: str) -> list[str]:
        keys: list[str] = []
        for line in stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and "-" in parts[1]:
                candidate = parts[1].strip()
                prefix, _, suffix = candidate.partition("-")
                if prefix.isalpha() and suffix.isdigit():
                    keys.append(candidate)
        return keys

    def _parse_boy_scout_findings(self, session: Session) -> list[dict[str, object]]:
        if self.workdir_root is None:
            return []
        findings_path = self.workdir_root / session.task_key / "spec" / "findings.md"
        if not findings_path.is_file():
            return []
        text = findings_path.read_text(encoding="utf-8")
        sections = [section.strip() for section in text.split("\n---") if section.strip()]
        findings: list[dict[str, object]] = []
        for section in sections:
            if section.startswith("SCOUT_RESULT:"):
                _, _, remainder = section.partition("\n")
                section = remainder.strip()
            if not section:
                continue
            title_match = re.search(r"^## Finding \d+:\s+(.+)$", section, re.MULTILINE)
            if not title_match:
                continue
            files_match = re.search(r"^\*\*Files\*\*:\s+(.+)$", section, re.MULTILINE)
            principle_match = re.search(r"^\*\*Principle\*\*:\s+(.+)$", section, re.MULTILINE)
            problem_match = re.search(r"^\*\*Problem\*\*:\s+(.+)$", section, re.MULTILINE)
            suggestion_match = re.search(r"^\*\*Suggestion\*\*:\s+(.+)$", section, re.MULTILINE)
            raw_files = files_match.group(1).strip() if files_match else ""
            files = [
                item.strip().strip("`")
                for item in raw_files.split(",")
                if item.strip().strip("`")
            ]
            findings.append(
                {
                    "title": title_match.group(1).strip(),
                    "files": files,
                    "principle": principle_match.group(1).strip() if principle_match else "",
                    "problem": problem_match.group(1).strip() if problem_match else "",
                    "suggestion": suggestion_match.group(1).strip() if suggestion_match else "",
                }
            )
        return findings

    def _added_source_paths_from_diff(self, task_key: str) -> set[str]:
        if self.workdir_root is None:
            return set()
        diff_path = self.workdir_root / task_key / "spec" / "diff.md"
        if not diff_path.is_file():
            return set()
        added_paths: set[str] = set()
        in_table = False
        for raw_line in diff_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if line == "## Changed Files":
                in_table = True
                continue
            if in_table and line.startswith("## "):
                break
            if not in_table or not line.startswith("|"):
                continue
            if line.startswith("| Status |") or line.startswith("|---|"):
                continue
            parts = [part.strip() for part in line.strip("|").split("|")]
            if len(parts) < 2:
                continue
            if parts[0] != "added":
                continue
            added_paths.add(parts[1].strip("`"))
        return added_paths

    def _classify_boy_scout_findings(self, session: Session) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        added_paths = self._added_source_paths_from_diff(session.task_key)
        added_basenames = {Path(path).name for path in added_paths}
        implement_now: list[dict[str, object]] = []
        tech_debt: list[dict[str, object]] = []
        for finding in self._parse_boy_scout_findings(session):
            files = [str(item).strip() for item in finding.get("files", []) if str(item).strip()]
            if files and all(file_path in added_paths or Path(file_path).name in added_basenames for file_path in files):
                implement_now.append(finding)
            else:
                tech_debt.append(finding)
        return implement_now, tech_debt

    def _render_boy_scout_findings_markdown(self, findings: list[dict[str, object]]) -> str:
        lines = ["SCOUT_RESULT: findings_found", ""]
        for index, finding in enumerate(findings, start=1):
            title = str(finding.get("title") or f"Finding {index}").strip()
            files = [str(item).strip() for item in finding.get("files", []) if str(item).strip()]
            principle = str(finding.get("principle") or "").strip()
            problem = str(finding.get("problem") or "").strip()
            suggestion = str(finding.get("suggestion") or "").strip()
            lines.append(f"## Finding {index}: {title}")
            lines.append("")
            if files:
                lines.append("**Files**: " + ", ".join(f"`{item}`" for item in files))
            if principle:
                lines.append(f"**Principle**: {principle}")
            if problem:
                lines.append(f"**Problem**: {problem}")
            if suggestion:
                lines.append(f"**Suggestion**: {suggestion}")
            lines.append("")
            lines.append("---")
            lines.append("")
        if lines[-2:] == ["---", ""]:
            lines = lines[:-2]
        return "\n".join(lines).rstrip() + "\n"

    def _materialize_boy_scout_actionable_findings(
        self,
        *,
        session: Session,
        findings: list[dict[str, object]],
        filename: str,
    ) -> Path:
        if self.workdir_root is None:
            raise IntakeError("Coordinator is missing workdir root")
        spec_root = self.workdir_root / session.task_key / "spec"
        spec_root.mkdir(parents=True, exist_ok=True)
        target_path = spec_root / filename
        target_path.write_text(self._render_boy_scout_findings_markdown(findings), encoding="utf-8")
        return target_path

    def _render_boy_scout_issue_description(self, finding: dict[str, object]) -> str:
        title = str(finding.get("title") or "Boy Scout finding").strip()
        files = [str(item).strip() for item in finding.get("files", []) if str(item).strip()]
        principle = str(finding.get("principle") or "").strip()
        problem = str(finding.get("problem") or "").strip()
        suggestion = str(finding.get("suggestion") or "").strip()
        lines = [f"# {title}", ""]
        if files:
            lines.extend(["## Files", ""])
            lines.extend(f"- `{item}`" for item in files)
            lines.append("")
        if principle:
            lines.extend(["## Principle", "", principle, ""])
        if problem:
            lines.extend(["## Problem", "", problem, ""])
        if suggestion:
            lines.extend(["## Suggested change", "", suggestion, ""])
        return "\n".join(lines).rstrip() + "\n"

    def _create_boy_scout_tech_debt_stories(
        self,
        session: Session,
        findings: list[dict[str, object]],
    ) -> list[dict[str, str]]:
        if self.jira_adapter is None or self.workdir_root is None:
            raise IntakeError("Jira adapter is required to create Boy Scout tech-debt stories")
        if not findings:
            return []
        project = session.task_key.split("-", 1)[0]
        tmp_dir = self.workdir_root / session.task_key / "tmp" / "boy-scout-tech-debt"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        created: list[dict[str, str]] = []
        for index, finding in enumerate(findings, start=1):
            title = str(finding.get("title") or f"Boy Scout finding {index}").strip()
            description_path = tmp_dir / f"{index:02d}-description.md"
            description_path.write_text(
                self._render_boy_scout_issue_description(finding),
                encoding="utf-8",
            )
            result = self.jira_adapter.create_issue(
                project=project,
                issue_type="Story",
                summary=f"[Tech debt] {title}",
                description_file=description_path,
            )
            if result.returncode != 0:
                raise IntakeError(f"Failed to create Boy Scout tech-debt story for '{title}'")
            issue_key = ""
            issue_url = ""
            for part in result.stdout.split():
                if _TASK_KEY_PATTERN.match(part.strip()):
                    issue_key = part.strip()
                if part.startswith("http://") or part.startswith("https://"):
                    issue_url = part.strip()
            created.append({"title": title, "issue_key": issue_key, "issue_url": issue_url})
        return created

    def _materialize_boy_scout_deferred_entries(
        self,
        *,
        session: Session,
        created_issues: list[dict[str, str]],
    ) -> None:
        if self.workdir_root is None:
            return
        spec_root = self.workdir_root / session.task_key / "spec"
        spec_root.mkdir(parents=True, exist_ok=True)
        deferred_path = spec_root / "scout-deferred.md"
        existing = deferred_path.read_text(encoding="utf-8").rstrip() + "\n" if deferred_path.is_file() else ""
        additions = [
            f"- {issue['title']} ({issue['issue_key']})"
            for issue in created_issues
            if issue.get("title")
        ]
        deferred_path.write_text(existing + "\n".join(additions).rstrip() + ("\n" if additions else ""), encoding="utf-8")
        if self.artifacts_root is not None:
            artifact_path = write_text_artifact(
                self.artifacts_root,
                session.task_key,
                "boy-scout",
                "scout-deferred.md",
                deferred_path.read_text(encoding="utf-8"),
            )
            self.artifact_repository.create(
                session_id=session.id,
                stage_name="boy-scout",
                artifact_type="boy_scout_deferred_markdown",
                path=str(artifact_path),
                metadata={"entry_count": len(created_issues)},
            )

    def _count_mr_discussions(self, markdown: str) -> int:
        return sum(1 for line in markdown.splitlines() if line.startswith("## Discussion "))

    def _extract_mr_url(self, stdout: str) -> str | None:
        for line in stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith("http://") or stripped.startswith("https://"):
                return stripped
            marker = "MR already exists: "
            if stripped.startswith(marker):
                return stripped.removeprefix(marker).strip() or None
        return None

    def _extract_snapshot_explicit_links(self, task_key: str) -> list[str]:
        if self.workdir_root is None:
            return []
        task_root = self.workdir_root / task_key
        links: list[str] = []
        seen: set[str] = set()
        for relative_path in ("description.md", "comments.md"):
            candidate = task_root / relative_path
            if not candidate.is_file():
                continue
            for match in _EXPLICIT_URL_PATTERN.findall(candidate.read_text(encoding="utf-8")):
                if match in seen:
                    continue
                seen.add(match)
                links.append(match)
        return links

    def _emit_proposal_context_link_warning(self, session: Session) -> None:
        if self.artifacts_root is None:
            return
        explicit_links = self._extract_snapshot_explicit_links(session.task_key)
        non_notion_links = [link for link in explicit_links if "notion.so" not in link]
        if not non_notion_links:
            return

        artifact_body = "\n".join(
            [
                "# Proposal Context External Links Warning",
                "",
                "The snapshot includes external links whose contents are not automatically fetched into `spec/proposal.md`.",
                "Treat them as operator-provided references unless they are manually incorporated later.",
                "",
                "## Links",
                "",
                *[f"- {link}" for link in non_notion_links],
                "",
            ]
        )
        artifact_path = write_text_artifact(
            self.artifacts_root,
            session.task_key,
            "story-planning",
            "proposal-external-links-warning.md",
            artifact_body,
        )
        self.artifact_repository.create(
            session_id=session.id,
            stage_name="story-planning",
            artifact_type="proposal_external_links_warning",
            path=str(artifact_path),
            metadata={"link_count": len(non_notion_links)},
        )
        self._append_event(
            session_id=session.id,
            event_type="proposal_external_links_detected",
            producer_type="coordinator",
            payload={
                "task_key": session.task_key,
                "link_count": len(non_notion_links),
                "summary": (
                    "External links were found in the snapshot; their contents are not automatically included "
                    "in the proposal unless they are Notion pages handled through MCP."
                ),
            },
        )

    def _materialize_boy_scout_deferred(self, *, session: Session, reason: str) -> None:
        if self.workdir_root is None or self.artifacts_root is None:
            return

        spec_root = self.workdir_root / session.task_key / "spec"
        findings_path = spec_root / "findings.md"
        if not findings_path.is_file():
            return

        deferred_path = spec_root / "scout-deferred.md"
        deferred_titles = self._read_boy_scout_deferred_titles(deferred_path)
        for title in self._extract_boy_scout_finding_titles(findings_path.read_text()):
            if title not in deferred_titles:
                deferred_titles.append(title)
        if not deferred_titles:
            return

        lines = [
            "# Deferred Boy Scout Findings",
            "",
            f"Deferred after operator decision: {reason}",
            "",
            "## Deferred Titles",
            "",
        ]
        lines.extend(f"- {title}" for title in deferred_titles)
        content = "\n".join(lines).rstrip() + "\n"
        deferred_path.parent.mkdir(parents=True, exist_ok=True)
        deferred_path.write_text(content)

        artifact_path = write_text_artifact(
            self.artifacts_root,
            session.task_key,
            "boy-scout",
            "scout-deferred.md",
            content,
        )
        self.artifact_repository.create(
            session_id=session.id,
            stage_name="boy-scout",
            artifact_type="boy_scout_deferred_markdown",
            path=str(artifact_path),
            metadata={
                "task_key": session.task_key,
                "source_path": str(deferred_path),
                "deferred_count": len(deferred_titles),
            },
        )

    def _extract_boy_scout_finding_titles(self, markdown: str) -> list[str]:
        titles: list[str] = []
        for line in markdown.splitlines():
            normalized = line.strip()
            if not normalized.startswith("## Finding"):
                continue
            if ":" not in normalized:
                continue
            title = normalized.split(":", 1)[1].strip()
            if title and title not in titles:
                titles.append(title)
        return titles

    def _read_boy_scout_deferred_titles(self, deferred_path: Path) -> list[str]:
        if not deferred_path.is_file():
            return []
        titles: list[str] = []
        for line in deferred_path.read_text().splitlines():
            normalized = line.strip()
            if not normalized.startswith("- "):
                continue
            title = normalized[2:].strip()
            if title and title not in titles:
                titles.append(title)
        return titles

    def _platform_for_task_key(self, task_key: str) -> str:
        if task_key.startswith("IOS-"):
            return "ios"
        if task_key.startswith("ANDR-"):
            return "android"
        return "unknown"

    def _dispatch_role_work(
        self,
        session: Session,
        role: Role,
        work_item: WorkItem,
        stage_name: str,
        instruction: str,
        extra_hydration: dict[str, str | int | None] | None = None,
    ) -> None:
        merged_hydration = self._default_extra_hydration_for_dispatch(
            session,
            role,
            stage_name,
        )
        if work_item.work_type == "subtask_implementation" and "subtask_key" not in merged_hydration:
            merged_hydration["subtask_key"] = self._parse_subtask_work_item_title(work_item.title)["key"]
        if extra_hydration:
            merged_hydration.update(extra_hydration)
        prompt_mode = self._prompt_mode_for_dispatch(session, role)
        hydration = build_role_hydration(
            role_name=role.role_name,
            task_key=session.task_key,
            current_stage=session.current_stage,
            active_work_item=work_item,
            extra_payload=merged_hydration or None,
        )
        prompt_text = role_handoff_prompt(
            role_name=role.role_name,
            instruction=instruction,
            hydration_payload=hydration,
            prompt_mode=prompt_mode,
        )
        hydration_path = write_text_artifact(
            self.artifacts_root,
            session.task_key,
            stage_name,
            f"{role.role_name}.hydration.json",
            json.dumps(hydration, indent=2, sort_keys=True),
        )
        workspace = self.role_workspace_manager.ensure_role_workspace(session.task_key, role.role_name)
        workspace_hydration_path = workspace.directory / "HYDRATION.json"
        workspace_hydration_path.write_text(json.dumps(hydration, indent=2, sort_keys=True))
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
                "prompt_mode": prompt_mode,
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
                "prompt_mode": prompt_mode,
            },
        )
        runtime_role = RuntimeRoleHandle(
            role_id=role.runtime_handle or f"{role.runtime_backend}:{role.role_name}",
            session_id=self._runtime_session_id_for_role(role, session),
            backend_name=role.runtime_backend,
        )
        self.session_backend.send_input(runtime_role, prompt_text)
        return self._append_event(
            session_id=session.id,
            event_type="role_input_dispatched",
            producer_type="coordinator",
            payload={
                "role_name": role.role_name,
                "work_item_id": work_item.id,
                "stage_name": stage_name,
                "hydration_version": updated_role.last_hydration_version,
                "prompt_mode": prompt_mode,
            },
        )

    def _runtime_session_id_for_role(self, role: Role, session: Session) -> str:
        runtime_handle = role.runtime_handle
        if runtime_handle and ":" in runtime_handle:
            return runtime_handle.split(":", 1)[0]
        return f"session:{session.id}"

    def _prompt_mode_for_dispatch(self, session: Session, role: Role) -> str:
        role_runtime_config = (session.role_config or {}).get(role.role_name, {})
        is_live_launcher_role = role.runtime_backend == "tmux" and role_runtime_config.get("runner") in {
            "claude",
            "codex",
        }
        if role.role_name in {IMPLEMENTER_ROLE, BUG_FIXER_ROLE, VERIFICATION_COORDINATOR_ROLE}:
            if is_live_launcher_role:
                return "live_bootstrap" if role.last_hydration_version == 0 else "live_continuation"
            return "bootstrap" if role.last_hydration_version == 0 else "continuation"
        return "full"

    def _get_jira_status_name(self, task_key: str) -> str | None:
        if self.jira_adapter is None:
            return None
        result = self.jira_adapter.get_issue_status(task_key)
        if result.returncode != 0 or not result.stdout.strip():
            return None
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None
        return payload.get("fields", {}).get("status", {}).get("name")

    def _stop_and_clear_runtime_handles(self, session: Session) -> list[str]:
        removed_paths: list[str] = []
        runtime_session_id = None
        try:
            runtime_session_id = self._runtime_session_handle_for_session(session).session_id
        except IntakeError:
            runtime_session_id = None

        if runtime_session_id is not None:
            self.session_backend.stop_session(RuntimeSessionHandle(session_id=runtime_session_id))
            removed_paths.append(f"runtime-session:{runtime_session_id}")

        updated_any = False
        for role in self.role_repository.list_for_session(session.id):
            if role.runtime_handle is not None or role.status != RoleStatus.STOPPED:
                self.role_repository.update_runtime(
                    role.id,
                    runtime_backend=role.runtime_backend,
                    runtime_handle=None,
                    status=RoleStatus.STOPPED,
                )
                updated_any = True

        if updated_any and session.status in {
            SessionStatus.ACTIVE,
            SessionStatus.WAITING_FOR_OPERATOR,
        }:
            self.session_repository.update_status(session.id, SessionStatus.PAUSED)
        return removed_paths

    def _remove_task_runtime_residue(self, task_key: str) -> list[str]:
        if self.workdir_root is None:
            return []
        removed: list[str] = []
        for path in (
            self.workdir_root / task_key / "runtime",
            self.workdir_root / task_key / "tmp",
        ):
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
                removed.append(str(path))
        return removed

    def _remove_task_artifacts(self, task_key: str) -> list[str]:
        if self.workdir_root is None:
            return []
        path = self.workdir_root / "factory-artifacts" / task_key
        if not path.exists():
            return []
        shutil.rmtree(path, ignore_errors=True)
        return [str(path)]

    def _remove_runner_private_residue(self, task_key: str) -> list[str]:
        removed: list[str] = []
        task_key_lower = task_key.lower()
        claude_projects_root = Path.home() / ".claude" / "projects"
        if claude_projects_root.exists() and claude_projects_root.is_dir():
            for child in claude_projects_root.iterdir():
                if task_key_lower not in child.name.lower():
                    continue
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
                removed.append(str(child))

        codex_sessions_root = Path.home() / ".codex" / "sessions"
        if codex_sessions_root.exists() and codex_sessions_root.is_dir():
            for session_file in codex_sessions_root.rglob("*.jsonl"):
                if not self._codex_session_file_matches_task(session_file, task_key_lower):
                    continue
                session_file.unlink(missing_ok=True)
                removed.append(str(session_file))
                self._prune_empty_parents(session_file.parent, stop_root=codex_sessions_root)
        return removed

    def _codex_session_file_matches_task(self, session_file: Path, task_key_lower: str) -> bool:
        try:
            with session_file.open("r", encoding="utf-8") as handle:
                for _ in range(20):
                    line = handle.readline()
                    if not line:
                        break
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    cwd = (
                        payload.get("payload", {}).get("cwd")
                        if isinstance(payload, dict)
                        else None
                    )
                    if isinstance(cwd, str) and task_key_lower in cwd.lower():
                        return True
                    session_text = json.dumps(payload).lower()
                    if task_key_lower in session_text:
                        return True
        except OSError:
            return False
        return False

    def _prune_empty_parents(self, path: Path, *, stop_root: Path) -> None:
        current = path
        while current != stop_root and current.is_dir():
            try:
                next(current.iterdir())
                break
            except StopIteration:
                current.rmdir()
                current = current.parent
            except OSError:
                break

    def _remove_task_worktree_and_directory(self, task_key: str) -> list[str]:
        if self.workdir_root is None:
            return []
        removed: list[str] = []
        task_root = self.workdir_root / task_key
        repo_dir = task_root / "repo"

        if repo_dir.exists():
            git_file = repo_dir / ".git"
            if git_file.is_file():
                try:
                    common_git_dir = (
                        subprocess.run(
                            ["git", "-C", str(repo_dir), "rev-parse", "--git-common-dir"],
                            check=True,
                            capture_output=True,
                            text=True,
                        )
                        .stdout.strip()
                    )
                    main_repo = Path(common_git_dir).resolve().parent
                    subprocess.run(
                        ["git", "-C", str(main_repo), "worktree", "remove", "--force", str(repo_dir)],
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    for branch in (f"feature/{task_key}", f"bugfix/{task_key}"):
                        branch_exists = subprocess.run(
                            ["git", "-C", str(main_repo), "rev-parse", "--verify", branch],
                            check=False,
                            capture_output=True,
                            text=True,
                        )
                        if branch_exists.returncode == 0:
                            subprocess.run(
                                ["git", "-C", str(main_repo), "branch", "-D", branch],
                                check=False,
                                capture_output=True,
                                text=True,
                            )
                except subprocess.CalledProcessError:
                    pass
            if repo_dir.exists():
                shutil.rmtree(repo_dir, ignore_errors=True)
            removed.append(str(repo_dir))

        if task_root.exists():
            shutil.rmtree(task_root, ignore_errors=True)
            removed.append(str(task_root))
        return removed

    def _repo_root(self) -> Path:
        if self.workdir_root is not None:
            return self.workdir_root.parent
        return Path(__file__).resolve().parents[2]

    def _append_event(
        self,
        session_id: int,
        event_type: str,
        producer_type: str,
        payload: dict,
        producer_id: str | None = None,
        correlation_id: str | None = None,
    ) -> Event:
        event = self.event_repository.append(
            session_id=session_id,
            event_type=event_type,
            producer_type=producer_type,
            producer_id=producer_id,
            payload=payload,
            correlation_id=correlation_id,
        )
        if self.event_bus is not None:
            self.event_bus.publish(event)
        return event
