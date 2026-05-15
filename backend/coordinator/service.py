"""Top-level coordinator facade."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
from pathlib import Path

from backend.api.sse import SessionEventBus
from backend.coordinator.artifacts import write_text_artifact
from backend.coordinator.intake import IntakeError, classify_task_readiness
from backend.knowledge.store import KnowledgeStore
from backend.coordinator.subtasks import read_snapshot_subtasks, unresolved_subtasks
from backend.coordinator.hydration import build_role_hydration
from backend.models.event import Event
from backend.models.enums import RoleStatus, SessionStatus, WorkItemStatus
from backend.models.session import Session
from backend.models.role import Role
from backend.models.work_item import WorkItem
from backend.roles.prompts import role_handoff_prompt
from backend.roles.launcher import RoleLauncherManager
from backend.roles.workspace import RoleWorkspaceManager
from backend.roles.contracts import (
    ALLOWED_STAGE_ROLE_TARGETS,
    BUG_FIXER_ROLE,
    CODE_REVIEWER_ROLE,
    IMPLEMENTER_ROLE,
    STORY_SPEC_WORKER_ROLE,
    TASK_COORDINATOR_ROLE,
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
    knowledge_root: Path | None = None
    event_bus: SessionEventBus | None = None
    role_workspace_manager: RoleWorkspaceManager | None = None
    role_launcher_manager: RoleLauncherManager | None = None

    def create_task_session(
        self,
        task_key: str,
        workflow_profile: str,
        policy: dict[str, str] | None = None,
    ) -> tuple[Session, Event, bool]:
        """Create or reuse a task session and emit the initial session event."""

        normalized_policy = normalize_session_policy(workflow_profile, policy)
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
            event = self._append_event(
                session_id=existing.id,
                event_type="task_session_reused",
                producer_type="coordinator",
                payload={
                    "task_key": task_key,
                    "current_stage": existing.current_stage,
                    "workflow_profile": existing.workflow_profile,
                    "policy": existing.policy or {},
                },
            )
            return existing, event, False

        session = self.session_repository.create(
            task_key=task_key,
            current_stage="intake",
            workflow_profile=normalized_policy.workflow_profile,
            policy=normalized_policy.policy,
        )
        runtime_session = self.session_backend.create_task_session(task_key)
        effective_roles = self._effective_role_names(
            normalized_policy.workflow_profile,
            normalized_policy.policy,
        )
        for role_name in effective_roles:
            start_directory = None
            launch_command = None
            if self.role_workspace_manager is not None:
                workspace = self.role_workspace_manager.ensure_role_workspace(task_key, role_name)
                start_directory = workspace.directory
                if self.role_launcher_manager is not None:
                    launch_plan = self.role_launcher_manager.ensure_launch_plan(
                        task_key=task_key,
                        workspace=workspace,
                    )
                    launch_command = launch_plan.command
            runtime_role = self.session_backend.spawn_role(
                runtime_session,
                role_name,
                start_directory=start_directory,
                launch_command=launch_command,
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
                "runtime_session_id": runtime_session.session_id,
                "roles": effective_roles,
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
        existing = self.session_repository.get_by_task_key(resolved_task_key)
        session, _, created = self.create_task_session(
            resolved_task_key,
            workflow_profile=(
                existing.workflow_profile
                if existing is not None
                else infer_workflow_profile(issue_type)
            ),
            policy=existing.policy if existing is not None else None,
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
                details["followup_event_type"] = self._enqueue_story_spec(
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
        if event_type == "story_spec_completed":
            session, followup_event = self._handle_story_spec_completed(session, accepted_event)
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
        followup_event = self._enqueue_mr_followup(
            session=session,
            source_event=event,
            mr_id=mr_id,
            discussion_count=discussion_count,
        )
        refreshed = self._get_session_or_raise(session.id)
        return refreshed, event, followup_event, discussion_count

    def create_mr_handoff(
        self,
        session_id: int,
    ) -> tuple[Session, Event, str | None]:
        if self.gitlab_adapter is None or self.artifacts_root is None:
            raise IntakeError("Coordinator is missing GitLab adapter or artifact root")

        session = self._get_session_or_raise(session_id)
        if session.status != SessionStatus.COMPLETED:
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
        if (session.policy or {}).get("doc_harvest_policy") == "disabled":
            raise IntakeError(f"Session {session_id} has doc harvest disabled by policy")

        artifact_path = write_text_artifact(
            self.artifacts_root,
            session.task_key,
            "doc-harvest",
            "doc-harvest-summary.md",
            normalized_summary,
        )
        self.artifact_repository.create(
            session_id=session.id,
            stage_name="doc-harvest",
            artifact_type="doc_harvest_summary",
            path=str(artifact_path),
            metadata={"summary_length": len(normalized_summary)},
        )
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="doc_harvest_completed",
            current_owner=None,
        )
        session = self.session_repository.update_status(session.id, SessionStatus.COMPLETED)
        event = self._append_event(
            session_id=session.id,
            event_type="doc_harvest_completed",
            producer_type="coordinator",
            payload={
                "task_key": session.task_key,
                "summary_length": len(normalized_summary),
                "current_stage": session.current_stage,
                "status": session.status.value,
            },
        )
        return session, event

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
        if (session.policy or {}).get("self_review_policy") == "disabled":
            raise IntakeError(f"Session {session_id} has self review disabled by policy")

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
        if session.status != SessionStatus.COMPLETED:
            raise IntakeError(
                f"Session {session_id} must be completed before send-to-test handoff can run"
            )
        if session.current_stage != "mr_handoff_completed":
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
        followup_event = self._enqueue_qa_followup(
            session=session,
            source_event=event,
        )
        refreshed = self._get_session_or_raise(session.id)
        return refreshed, event, followup_event

    def create_knowledge(
        self,
        session_id: int,
        title: str,
        guidance: str,
        scope: str | None = None,
    ) -> tuple[Session, Event]:
        session = self._get_session_or_raise(session_id)
        knowledge_store = self._knowledge_store_or_raise()
        item = knowledge_store.create_item(
            title=title,
            platform=self._platform_for_task_key(session.task_key),
            workflow_profiles=[session.workflow_profile],
            task_key=session.task_key,
            guidance=guidance,
            scope=scope,
        )
        self.artifact_repository.create(
            session_id=session.id,
            stage_name="knowledge",
            artifact_type="knowledge_reference_markdown",
            path=str(item.path),
            metadata={
                "knowledge_id": item.id,
                "scope": item.scope,
            },
        )
        event = self._append_event(
            session_id=session.id,
            event_type="knowledge_created",
            producer_type="operator",
            payload={
                "knowledge_id": item.id,
                "title": item.title,
                "scope": item.scope,
                "path": str(item.path),
            },
        )
        return session, event

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
        if session.status != SessionStatus.ACTIVE:
            raise IntakeError(
                f"Session {session_id} must be active before starting subtask graph"
            )
        if session.current_stage != "implementation_requested":
            raise IntakeError(
                f"Session {session_id} must be at implementation_requested before starting subtask graph"
            )
        active_item = self._find_active_primary_coding_work_item(session)
        if active_item is None or active_item.work_type != "implementation":
            raise IntakeError("No active implementation work item found for subtask graph start")

        statuses_file = self.workdir_root / session.task_key / "statuses.md"
        try:
            subtasks = read_snapshot_subtasks(statuses_file)
        except FileNotFoundError as exc:
            raise IntakeError(f"statuses.md not found for session {session.task_key}") from exc

        unresolved = unresolved_subtasks(subtasks)
        if not unresolved:
            raise IntakeError(f"No unresolved subtasks found for session {session.task_key}")

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

        event = self._append_event(
            session_id=session.id,
            event_type="subtask_graph_requested",
            producer_type="operator",
            payload={
                "subtask_count": len(subtasks),
                "unresolved_count": len(unresolved),
            },
        )
        followup_event = self._enqueue_subtask_graph(
            session=session,
            source_event=event,
            subtasks=subtasks,
            initial_work_item=active_item,
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
        elif mapped_event_type == "story_spec_completed":
            session, followup_event = self._handle_story_spec_completed(session, accepted_event)
        elif mapped_event_type == "subtask_completed":
            session, followup_event = self._handle_subtask_completed(session, accepted_event)
        elif mapped_event_type == "implementation_completed":
            session, followup_event = self._handle_implementation_completed(session, accepted_event)
        elif mapped_event_type == "verification_failed":
            session, followup_event = self._handle_verification_failed(session, accepted_event)
        elif mapped_event_type == "verification_passed":
            session, followup_event = self._handle_verification_passed(session, accepted_event)
        elif mapped_event_type == "self_review_passed":
            session, followup_event = self._handle_self_review_passed(session, accepted_event)
        elif mapped_event_type == "self_review_issues_found":
            session, followup_event = self._handle_self_review_issues_found(session, accepted_event)
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
        session = self._apply_runtime_output_markers(session, role, chunks)
        event = self._append_event(
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
            session = self._apply_runtime_output_markers(session, role, chunks)
            total_chunks += len(chunks)

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

    def run_loop_once(self) -> tuple[Event | None, int, int]:
        active_sessions = self.session_repository.list_by_status(SessionStatus.ACTIVE)
        total_chunks = 0
        polled_sessions = 0
        reconciled_sessions = 0

        for session in active_sessions:
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

    def resume_session(self, session_id: int) -> tuple[Session, Event, Event]:
        session = self._get_session_or_raise(session_id)
        if session.status == SessionStatus.WAITING_FOR_OPERATOR:
            return self._resume_waiting_session(session)
        if session.status == SessionStatus.PAUSED:
            return self._resume_paused_session(session)
        raise IntakeError(
            f"Session {session_id} is not resumable; current status is {session.status.value}"
        )

    def _resume_waiting_session(self, session: Session) -> tuple[Session, Event, Event]:
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
        instruction = self._stage_instruction(
            session.current_stage,
            session.task_key,
            workflow_profile=session.workflow_profile,
            role_name=role.role_name,
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
        if target_role_name == TASK_COORDINATOR_ROLE:
            raise IntakeError("Redirecting active work to task-coordinator is not supported")
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
            f"Prepare a concise implementation spec for story {session.task_key} before coding. "
            "Clarify the intended scope, key constraints, and an implementation approach that will guide the next coding step."
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

        summary = str(source_event.payload.get("summary") or "").strip()
        constraints = str(source_event.payload.get("constraints") or "").strip()
        context_lines: list[str] = []
        if summary:
            context_lines.append(f"Story spec summary: {summary}")
        if constraints:
            context_lines.append(f"Key constraints: {constraints}")
        additional_context = "\n".join(context_lines) if context_lines else None

        event = self._enqueue_initial_implementation(
            session=session,
            resolved_task_key=session.task_key,
            source_event=source_event,
            additional_context=additional_context,
        )
        session = self._get_session_or_raise(session.id)
        return session, event

    def _enqueue_subtask_graph(
        self,
        session: Session,
        source_event: Event,
        subtasks: list,
        initial_work_item: WorkItem,
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
            },
        )

    def _handle_subtask_completed(
        self,
        session: Session,
        source_event: Event,
    ) -> tuple[Session, Event]:
        active_item = self._find_active_primary_coding_work_item(session)
        if active_item is None or active_item.work_type != "subtask_implementation":
            raise IntakeError("No active subtask implementation work item found for the session")

        self.work_item_repository.update_status(active_item.id, WorkItemStatus.COMPLETED)
        implementer_role = self.role_repository.get_by_name(session.id, IMPLEMENTER_ROLE)
        if implementer_role is None:
            raise IntakeError("Implementer role is missing for the session")

        remaining_items = [
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "subtask_implementation"
            and item.status == WorkItemStatus.UNASSIGNED
        ]
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
                },
            )

        return self._advance_after_coding_completion(
            session=session,
            source_event=source_event,
            completed_work_type="subtask_implementation",
        )

    def _handle_implementation_completed(
        self,
        session: Session,
        source_event: Event,
    ) -> tuple[Session, Event]:
        active_item = self._find_active_primary_coding_work_item(session)
        if active_item is None:
            raise IntakeError("No active coding work item found for the session")
        self.work_item_repository.update_status(active_item.id, WorkItemStatus.COMPLETED)

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
            and (session.policy or {}).get("self_review_policy") == "required"
        ):
            return self._enqueue_self_review(session=session, source_event=source_event)

        return self._enqueue_verification(session=session, source_event=source_event)

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
        self._dispatch_role_work(
            session=session,
            role=reviewer_role,
            work_item=review_item,
            stage_name="self_review_requested",
            instruction=(
                f"Review the current task changes for {session.task_key}. "
                "Report a clean pass or remaining issues."
            ),
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
        doc_harvest_policy = (session.policy or {}).get("doc_harvest_policy")
        if doc_harvest_policy == "required":
            session = self.session_repository.update_stage_and_owner(
                session.id,
                current_stage="doc_harvest_requested",
                current_owner=None,
            )
            session = self.session_repository.update_status(session.id, SessionStatus.ACTIVE)
            event = self._append_event(
                session_id=session.id,
                event_type="doc_harvest_requested",
                producer_type="coordinator",
                payload={
                    "task_key": session.task_key,
                    "source_event_id": source_event.id,
                    "current_stage": session.current_stage,
                    "status": session.status.value,
                },
            )
            return session, event
        session = self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="completed",
            current_owner=None,
        )
        session = self.session_repository.update_status(session.id, SessionStatus.COMPLETED)
        event = self._append_event(
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

    def _enqueue_mr_followup(
        self,
        session: Session,
        source_event: Event,
        mr_id: str,
        discussion_count: int,
    ) -> Event:
        return self._enqueue_followup_implementation(
            session=session,
            source_event=source_event,
            stage_name="mr_followup_requested",
            event_type="mr_followup_requested",
            title=f"MR follow-up for {session.task_key} from !{mr_id}",
            instruction=(
                f"Apply MR follow-up changes for {session.task_key} from MR !{mr_id}. "
                f"There are {discussion_count} unresolved discussion groups recorded in artifacts."
            ),
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

    def _handle_self_review_passed(
        self,
        session: Session,
        source_event: Event,
    ) -> tuple[Session, Event]:
        self._complete_active_self_review_work_item(session)
        return self._enqueue_verification(
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
        self._dispatch_role_work(
            session=session,
            role=verification_role,
            work_item=verification_item,
            stage_name="verification_requested",
            instruction=f"Run deterministic verification for {session.task_key}.",
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
        if role_name in {IMPLEMENTER_ROLE, BUG_FIXER_ROLE} and output_type == "completed":
            if session.current_stage == "bug_analysis_requested":
                return "bug_analysis_completed"
            if session.current_stage == "story_spec_requested":
                return "story_spec_completed"
            if session.current_stage == "subtask_implementation_requested":
                return "subtask_completed"
            if session.current_stage in {
                "implementation_requested",
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
        if role_name == CODE_REVIEWER_ROLE and session.current_stage == "self_review_requested":
            if output_type in {"passed", "completed"}:
                return "self_review_passed"
            if output_type == "failed":
                return "self_review_issues_found"
        if role_name == STORY_SPEC_WORKER_ROLE and session.current_stage == "story_spec_requested":
            if output_type in {"passed", "completed"}:
                return "story_spec_completed"
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
                    output_type = payload.get("output_type")
                    output_payload = payload.get("payload", {})
                    if not isinstance(output_type, str) or not isinstance(output_payload, dict):
                        continue
                    current_session, _, _ = self.handle_role_output(
                        session_id=current_session.id,
                        role_name=role.role_name,
                        output_type=output_type,
                        payload=output_payload,
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
        for line in text.splitlines():
            marker_type = self._line_marker_type(line)
            if marker_type is None:
                continue
            raw_payload = line.split(":", 1)[1].strip()
            try:
                parsed = json.loads(raw_payload)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                results.append((marker_type, parsed))
        return results

    def _line_marker_type(self, line: str) -> str | None:
        if line.startswith("SDD_OUTPUT:"):
            return "output"
        if line.startswith("SDD_PROGRESS:"):
            return "progress"
        if line.startswith("SDD_ERROR:"):
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
        if stage_name == "story_spec_requested":
            return (
                f"Prepare a concise implementation spec for story {task_key} before coding. "
                "Clarify the intended scope, key constraints, and an implementation approach that will guide the next coding step."
            )
        if stage_name == "subtask_implementation_requested":
            return (
                f"Continue sequential subtask implementation for {task_key}. "
                "Finish the currently assigned subtask before moving to the next one."
            )
        if stage_name == "implementation_requested":
            return f"Start implementation work for {task_key}."
        if stage_name == "verification_requested":
            return f"Run deterministic verification for {task_key}."
        if stage_name == "verification_correction_requested":
            return f"Apply verification corrections for {task_key}."
        if stage_name == "self_review_requested":
            return (
                f"Review the current task changes for {task_key}. "
                "Emit passed if the review is clean, or failed if issues still require correction."
            )
        if stage_name == "self_review_correction_requested":
            return f"Apply self review corrections for {task_key}."
        if stage_name == "mr_followup_requested":
            return f"Apply MR follow-up changes for {task_key}."
        if stage_name == "qa_reopen_requested":
            return f"Apply QA reopen follow-up changes for {task_key}."
        return None

    def _effective_role_names(self, workflow_profile: str, policy: dict[str, str] | None) -> list[str]:
        role_names = list(self.default_roles)
        if workflow_profile == "bug_full" and BUG_FIXER_ROLE not in role_names:
            role_names.append(BUG_FIXER_ROLE)
        if (policy or {}).get("self_review_policy") != "disabled" and CODE_REVIEWER_ROLE not in role_names:
            role_names.append(CODE_REVIEWER_ROLE)
        return role_names

    def _primary_coding_role_name_for_work_type(self, session: Session, work_type: str) -> str:
        if session.workflow_profile != "bug_full":
            return IMPLEMENTER_ROLE
        if work_type in {
            "bug_analysis",
            "implementation",
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
            "story_spec_requested": "story_spec",
            "subtask_implementation_requested": "subtask_implementation",
            "implementation_requested": "implementation",
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
        start_directory = None
        launch_command = None
        if self.role_workspace_manager is not None:
            workspace = self.role_workspace_manager.ensure_role_workspace(session.task_key, role_name)
            start_directory = workspace.directory
            if self.role_launcher_manager is not None:
                launch_plan = self.role_launcher_manager.ensure_launch_plan(
                    task_key=session.task_key,
                    workspace=workspace,
                )
                launch_command = launch_plan.command

        runtime_role = self.session_backend.spawn_role(
            runtime_session,
            role_name,
            start_directory=start_directory,
            launch_command=launch_command,
        )
        if existing is not None:
            return self.role_repository.create(
                session_id=session.id,
                role_name=role_name,
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

    def _knowledge_store_or_raise(self) -> KnowledgeStore:
        if self.knowledge_root is None:
            raise IntakeError("Coordinator is missing knowledge root")
        return KnowledgeStore(self.knowledge_root)

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
    ) -> None:
        prompt_mode = self._prompt_mode_for_dispatch(role)
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
            prompt_mode=prompt_mode,
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
            session_id=f"session:{session.id}",
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

    def _prompt_mode_for_dispatch(self, role: Role) -> str:
        if role.role_name in {IMPLEMENTER_ROLE, BUG_FIXER_ROLE, VERIFICATION_COORDINATOR_ROLE}:
            return "bootstrap" if role.last_hydration_version == 0 else "continuation"
        return "full"

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
