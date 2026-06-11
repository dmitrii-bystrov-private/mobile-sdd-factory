from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from backend.config import load_config
from backend.state.db import Database
from backend.state.role_repository import RoleRepository
from backend.state.session_repository import SessionRepository
from backend.state.work_item_repository import WorkItemRepository


CODING_ROLES = {"implementer", "bug-fixer", "mr-comments-analyst-worker"}
PLANNING_ROLES = {
    "proposal-context-worker",
    "requirements-clarifier-worker",
    "acceptance-criteria-worker",
    "constraints-worker",
    "task-decomposer-worker",
}
SUPPORTED_ROLES = {
    "code-scout",
    "verification-coordinator",
    "code-reviewer",
    "spec-verifier-worker",
    "doc-harvest-worker",
    *CODING_ROLES,
    *PLANNING_ROLES,
}
OUTPUT_TYPE_CHOICES = {
    "completed",
    "passed",
    "failed",
    "skipped_not_needed",
    "blocked_review_cycle",
    "blocked_verification_cycle",
}


class ResultWriterError(ValueError):
    """Raised when CLI input cannot be converted into a deterministic result."""


@dataclass(frozen=True)
class SubmissionContext:
    role_name: str
    output_path: Path
    task_key: str


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be a non-negative integer")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Write deterministic RESULT.json files for routed role outcomes."
    )
    parser.add_argument("--work-item-id", required=True, type=_positive_int)
    parser.add_argument("--output-type", default="completed", choices=sorted(OUTPUT_TYPE_CHOICES))
    parser.add_argument("--result")
    parser.add_argument("--findings-count", type=_non_negative_int)
    parser.add_argument("--findings-path")
    parser.add_argument("--summary")
    parser.add_argument("--details")
    parser.add_argument("--failure", action="append", default=[])
    parser.add_argument("--issues-markdown")
    parser.add_argument("--issues-markdown-file")
    parser.add_argument("--subtask-key")
    parser.add_argument("--needs-operator-input", action="store_true")
    parser.add_argument("--missing-input", action="append", default=[])
    parser.add_argument("--pending-decision", action="append", default=[])
    parser.add_argument("--blocker-question", action="append", default=[])
    parser.add_argument("--conflict-point")
    parser.add_argument("--reviewer-premise")
    parser.add_argument("--preferred-direction")
    parser.add_argument("--requested-decision")
    parser.add_argument("--supporting-evidence")
    parser.add_argument("--next-step")
    parser.add_argument("--verified-focus")
    return parser


def _clean_optional_text(payload: dict[str, object], key: str, value: str | None) -> None:
    if value is None:
        return
    rendered = value.strip()
    if rendered:
        payload[key] = rendered


def _normalized_list(values: Sequence[str]) -> list[str]:
    return [item.strip() for item in values if item.strip()]


def _read_text_file_argument(path_value: str | None, label: str) -> str | None:
    if path_value is None:
        return None
    path_text = path_value.strip()
    if not path_text:
        return None
    path = Path(path_text)
    if not path.is_file():
        raise ResultWriterError(f"{label} file does not exist: {path}")
    return path.read_text(encoding="utf-8")


def _resolve_optional_text_or_file(
    *,
    inline_value: str | None,
    file_value: str | None,
    label: str,
) -> str | None:
    if inline_value is not None and inline_value.strip() and file_value is not None and file_value.strip():
        raise ResultWriterError(f"Use either --{label} or --{label}-file, not both")
    file_text = _read_text_file_argument(file_value, label)
    if file_text is not None:
        return file_text
    return inline_value


def _load_database() -> Database:
    configured_path = os.environ.get("SDD_FACTORY_DB_PATH")
    if configured_path:
        return Database(Path(configured_path))
    return Database(load_config().database_path)


def resolve_submission_context(
    *,
    work_item_id: int,
) -> SubmissionContext:
    database = _load_database()
    work_items = WorkItemRepository(database)
    sessions = SessionRepository(database)
    roles = RoleRepository(database)

    work_item = work_items.get_by_id(work_item_id)
    if work_item is None:
        raise ResultWriterError(f"unknown work_item_id: {work_item_id}")
    session = sessions.get_by_id(work_item.session_id)
    if session is None:
        raise ResultWriterError(f"work item {work_item_id} references a missing session")
    if work_item.owner_role_id is None:
        raise ResultWriterError(
            f"work item {work_item_id} has no assigned owner role; cannot resolve RESULT.json target"
        )
    role = roles.get_by_id(work_item.owner_role_id)
    if role is None:
        raise ResultWriterError(
            f"work item {work_item_id} references a missing owner role; cannot resolve RESULT.json target"
        )

    runtime_role_name = str(os.environ.get("SDD_FACTORY_ROLE_NAME", "")).strip()
    if runtime_role_name and runtime_role_name != role.role_name:
        raise ResultWriterError(
            f"work item {work_item_id} belongs to role {role.role_name}, not current runtime {runtime_role_name}"
        )

    workdir_root_env = str(os.environ.get("SDD_FACTORY_WORKDIR_ROOT", "")).strip()
    if workdir_root_env:
        workdir_root = Path(workdir_root_env)
    else:
        config = load_config()
        workdir_root = config.workdir_root
    output_path = workdir_root / session.task_key / "runtime" / "role-workspaces" / role.role_name / "RESULT.json"
    return SubmissionContext(role_name=role.role_name, output_path=output_path, task_key=session.task_key)


def _validate_role_output_type(role_name: str, output_type: str) -> None:
    allowed: dict[str, set[str]] = {
        "code-scout": {"completed", "passed", "skipped_not_needed"},
        "verification-coordinator": {
            "completed",
            "passed",
            "failed",
            "blocked_verification_cycle",
        },
        "code-reviewer": {
            "completed",
            "passed",
            "failed",
            "blocked_review_cycle",
            "skipped_not_needed",
        },
        "spec-verifier-worker": {"completed", "passed", "failed"},
        "doc-harvest-worker": {"completed", "passed", "skipped_not_needed"},
    }
    if role_name in CODING_ROLES:
        allowed_types = {"completed", "failed"}
    elif role_name in PLANNING_ROLES:
        allowed_types = {"completed", "passed", "failed"}
    else:
        allowed_types = allowed.get(role_name, set())
    if output_type not in allowed_types:
        raise ResultWriterError(f"{role_name} does not support output_type={output_type}")


def _build_code_scout_payload(args: argparse.Namespace) -> dict[str, object]:
    result = str(args.result or "").strip()
    if result not in {"clean", "findings_found"}:
        raise ResultWriterError("code-scout requires --result clean|findings_found")
    payload: dict[str, object] = {
        "work_item_id": args.work_item_id,
        "result": result,
    }
    _clean_optional_text(payload, "summary", args.summary)
    _clean_optional_text(payload, "details", args.details)

    if result == "findings_found":
        findings_path = str(args.findings_path or "").strip()
        if not findings_path:
            raise ResultWriterError("code-scout findings results require --findings-path")
        if args.findings_count is None:
            raise ResultWriterError("code-scout findings results require --findings-count")
        if args.findings_count <= 0:
            raise ResultWriterError("code-scout findings results require a positive --findings-count")
        payload["findings_count"] = args.findings_count
        payload["findings_path"] = findings_path
    return payload


def _build_verification_payload(args: argparse.Namespace) -> dict[str, object]:
    payload: dict[str, object] = {
        "work_item_id": args.work_item_id,
    }
    _clean_optional_text(payload, "summary", args.summary)
    _clean_optional_text(payload, "details", args.details)

    if args.output_type == "blocked_verification_cycle":
        return payload

    result = str(args.result or "").strip()
    if result not in {"passed", "failed"}:
        raise ResultWriterError("verification-coordinator requires --result passed|failed")
    payload["result"] = result

    failures = _normalized_list(args.failure)
    if failures:
        payload["failures"] = failures

    if result == "failed" and "failures" not in payload and "summary" not in payload:
        raise ResultWriterError(
            "failed verification results require at least --failure or --summary"
        )
    return payload


def _build_code_reviewer_payload(args: argparse.Namespace) -> dict[str, object]:
    payload: dict[str, object] = {
        "work_item_id": args.work_item_id,
    }
    issues_markdown = _resolve_optional_text_or_file(
        inline_value=args.issues_markdown,
        file_value=args.issues_markdown_file,
        label="issues-markdown",
    )
    _clean_optional_text(payload, "summary", args.summary)
    _clean_optional_text(payload, "details", args.details)
    _clean_optional_text(payload, "issues_markdown", issues_markdown)
    return payload


def _build_coding_payload(args: argparse.Namespace) -> dict[str, object]:
    payload: dict[str, object] = {
        "work_item_id": args.work_item_id,
    }
    _clean_optional_text(payload, "summary", args.summary)
    _clean_optional_text(payload, "details", args.details)
    _clean_optional_text(payload, "subtask_key", args.subtask_key)
    _clean_optional_text(payload, "conflict_point", args.conflict_point)
    _clean_optional_text(payload, "reviewer_premise", args.reviewer_premise)
    _clean_optional_text(payload, "preferred_direction", args.preferred_direction)
    _clean_optional_text(payload, "requested_decision", args.requested_decision)
    _clean_optional_text(payload, "supporting_evidence", args.supporting_evidence)
    if args.needs_operator_input:
        payload["needs_operator_input"] = True
    return payload


def _build_story_planning_payload(args: argparse.Namespace) -> dict[str, object]:
    payload: dict[str, object] = {
        "work_item_id": args.work_item_id,
    }
    _clean_optional_text(payload, "summary", args.summary)
    _clean_optional_text(payload, "details", args.details)
    _clean_optional_text(payload, "next_step", args.next_step)

    failures = _normalized_list(args.failure)
    if failures:
        payload["failures"] = failures
    missing_inputs = _normalized_list(args.missing_input)
    if missing_inputs:
        payload["missing_inputs"] = missing_inputs
    pending_decisions = _normalized_list(args.pending_decision)
    if pending_decisions:
        payload["pending_decisions"] = pending_decisions
    blocker_questions = _normalized_list(args.blocker_question)
    if blocker_questions:
        payload["blocker_questions"] = blocker_questions
    if args.needs_operator_input:
        payload["needs_operator_input"] = True
    return payload


def _build_spec_verifier_payload(args: argparse.Namespace) -> dict[str, object]:
    payload: dict[str, object] = {
        "work_item_id": args.work_item_id,
    }
    _clean_optional_text(payload, "summary", args.summary)
    _clean_optional_text(payload, "details", args.details)
    _clean_optional_text(payload, "verified_focus", args.verified_focus)
    blocker_questions = _normalized_list(args.blocker_question)
    if blocker_questions:
        payload["blocker_questions"] = blocker_questions
    return payload


def _build_doc_harvest_payload(args: argparse.Namespace) -> dict[str, object]:
    payload: dict[str, object] = {
        "work_item_id": args.work_item_id,
    }
    _clean_optional_text(payload, "summary", args.summary)
    _clean_optional_text(payload, "details", args.details)
    return payload


def build_result_document(
    args: argparse.Namespace,
    role_name: str | None = None,
) -> dict[str, object]:
    resolved_role_name = role_name or str(getattr(args, "role", "") or getattr(args, "legacy_role", "")).strip()
    if not resolved_role_name:
        raise ResultWriterError("role name is required to build a terminal result document")
    _validate_role_output_type(resolved_role_name, args.output_type)

    if resolved_role_name == "code-scout":
        payload = _build_code_scout_payload(args)
    elif resolved_role_name == "verification-coordinator":
        payload = _build_verification_payload(args)
    elif resolved_role_name == "code-reviewer":
        payload = _build_code_reviewer_payload(args)
    elif resolved_role_name in CODING_ROLES:
        payload = _build_coding_payload(args)
    elif resolved_role_name in PLANNING_ROLES:
        payload = _build_story_planning_payload(args)
    elif resolved_role_name == "spec-verifier-worker":
        payload = _build_spec_verifier_payload(args)
    elif resolved_role_name == "doc-harvest-worker":
        payload = _build_doc_harvest_payload(args)
    else:
        raise ResultWriterError(f"unsupported role: {resolved_role_name}")

    return {
        "output_type": args.output_type,
        "payload": payload,
    }


def write_result_file(output_path: Path, document: dict[str, object]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        context = resolve_submission_context(
            work_item_id=args.work_item_id,
        )
        document = build_result_document(args, context.role_name)
        write_result_file(context.output_path, document)
    except ResultWriterError as exc:
        parser.exit(2, f"error: {exc}\n")
    return 0


__all__ = [
    "ResultWriterError",
    "SubmissionContext",
    "build_parser",
    "build_result_document",
    "main",
    "resolve_submission_context",
    "write_result_file",
]
