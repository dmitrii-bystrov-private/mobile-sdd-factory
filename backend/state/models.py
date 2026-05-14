"""Row-to-domain conversion helpers for the SQLite layer."""

from __future__ import annotations

import json
import sqlite3

from backend.models.artifact import Artifact
from backend.models.checkpoint import Checkpoint
from backend.models.enums import RoleStatus, SessionStatus, VerificationStatus, WorkItemStatus
from backend.models.event import Event
from backend.models.role import Role
from backend.models.session import Session
from backend.models.verification import VerificationRun
from backend.models.work_item import WorkItem


def session_from_row(row: sqlite3.Row) -> Session:
    return Session(
        id=row["id"],
        task_key=row["task_key"],
        status=SessionStatus(row["status"]),
        current_stage=row["current_stage"],
        current_owner=row["current_owner"],
        workflow_profile=row["workflow_profile"],
        policy=json.loads(row["policy_json"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        ended_at=row["ended_at"],
    )


def role_from_row(row: sqlite3.Row) -> Role:
    return Role(
        id=row["id"],
        session_id=row["session_id"],
        role_name=row["role_name"],
        status=RoleStatus(row["status"]),
        runtime_backend=row["runtime_backend"],
        runtime_handle=row["runtime_handle"],
        last_hydration_version=row["last_hydration_version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def event_from_row(row: sqlite3.Row) -> Event:
    return Event(
        id=row["id"],
        session_id=row["session_id"],
        event_type=row["event_type"],
        producer_type=row["producer_type"],
        producer_id=row["producer_id"],
        payload=json.loads(row["payload_json"]),
        correlation_id=row["correlation_id"],
        created_at=row["created_at"],
    )


def work_item_from_row(row: sqlite3.Row) -> WorkItem:
    return WorkItem(
        id=row["id"],
        session_id=row["session_id"],
        work_type=row["work_type"],
        title=row["title"],
        status=WorkItemStatus(row["status"]),
        owner_role_id=row["owner_role_id"],
        source_event_id=row["source_event_id"],
        priority=row["priority"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def artifact_from_row(row: sqlite3.Row) -> Artifact:
    return Artifact(
        id=row["id"],
        session_id=row["session_id"],
        role_id=row["role_id"],
        stage_name=row["stage_name"],
        artifact_type=row["artifact_type"],
        path=row["path"],
        metadata=json.loads(row["metadata_json"]),
        created_at=row["created_at"],
    )


def checkpoint_from_row(row: sqlite3.Row) -> Checkpoint:
    return Checkpoint(
        id=row["id"],
        session_id=row["session_id"],
        checkpoint_type=row["checkpoint_type"],
        label=row["label"],
        metadata=json.loads(row["metadata_json"]),
        created_at=row["created_at"],
    )


def verification_run_from_row(row: sqlite3.Row) -> VerificationRun:
    return VerificationRun(
        id=row["id"],
        session_id=row["session_id"],
        attempt_number=row["attempt_number"],
        status=VerificationStatus(row["status"]),
        command_profile=row["command_profile"],
        artifact_group_id=row["artifact_group_id"],
        created_at=row["created_at"],
    )
