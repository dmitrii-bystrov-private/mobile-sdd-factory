from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence


class ResultWriterError(ValueError):
    """Raised when CLI input cannot be converted into a deterministic result."""


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def _non_empty(value: str) -> str:
    rendered = value.strip()
    if not rendered:
        raise argparse.ArgumentTypeError("value must not be empty")
    return rendered


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Write deterministic RESULT.json files for routed role outcomes."
    )
    subparsers = parser.add_subparsers(dest="role", required=True)

    scout = subparsers.add_parser("code-scout")
    scout.add_argument("--output", required=True)
    scout.add_argument("--work-item-id", required=True, type=_positive_int)
    scout.add_argument(
        "--output-type",
        default="completed",
        choices=["completed", "passed", "skipped_not_needed"],
    )
    scout.add_argument("--result", required=True, choices=["clean", "findings_found"])
    scout.add_argument("--findings-count", type=_positive_int)
    scout.add_argument("--findings-path")
    scout.add_argument("--summary")
    scout.add_argument("--details")

    verifier = subparsers.add_parser("verification-coordinator")
    verifier.add_argument("--output", required=True)
    verifier.add_argument("--work-item-id", required=True, type=_positive_int)
    verifier.add_argument(
        "--output-type",
        default="completed",
        choices=["completed", "passed", "failed", "blocked_verification_cycle"],
    )
    verifier.add_argument("--result", choices=["passed", "failed"])
    verifier.add_argument("--summary")
    verifier.add_argument("--details")
    verifier.add_argument("--failure", action="append", default=[])

    reviewer = subparsers.add_parser("code-reviewer")
    reviewer.add_argument("--output", required=True)
    reviewer.add_argument("--work-item-id", required=True, type=_positive_int)
    reviewer.add_argument(
        "--output-type",
        default="completed",
        choices=["completed", "passed", "failed", "blocked_review_cycle", "skipped_not_needed"],
    )
    reviewer.add_argument("--summary")
    reviewer.add_argument("--details")
    reviewer.add_argument("--issues-markdown")

    coding_roles = ["implementer", "bug-fixer", "mr-comments-analyst-worker"]
    for role_name in coding_roles:
        coding = subparsers.add_parser(role_name)
        coding.add_argument("--output", required=True)
        coding.add_argument("--work-item-id", required=True, type=_positive_int)
        coding.add_argument("--output-type", default="completed", choices=["completed"])
        coding.add_argument("--summary")
        coding.add_argument("--details")
        coding.add_argument("--subtask-key")

    planning_roles = [
        "proposal-context-worker",
        "requirements-clarifier-worker",
        "acceptance-criteria-worker",
        "constraints-worker",
        "task-decomposer-worker",
    ]
    for role_name in planning_roles:
        planning = subparsers.add_parser(role_name)
        planning.add_argument("--output", required=True)
        planning.add_argument("--work-item-id", required=True, type=_positive_int)
        planning.add_argument(
            "--output-type",
            default="completed",
            choices=["completed", "passed", "failed"],
        )
        planning.add_argument("--summary")
        planning.add_argument("--details")
        planning.add_argument("--needs-operator-input", action="store_true")
        planning.add_argument("--failure", action="append", default=[])
        planning.add_argument("--missing-input", action="append", default=[])
        planning.add_argument("--pending-decision", action="append", default=[])
        planning.add_argument("--blocker-question", action="append", default=[])
        planning.add_argument("--next-step")

    spec_verifier = subparsers.add_parser("spec-verifier-worker")
    spec_verifier.add_argument("--output", required=True)
    spec_verifier.add_argument("--work-item-id", required=True, type=_positive_int)
    spec_verifier.add_argument(
        "--output-type",
        default="completed",
        choices=["completed", "passed", "failed"],
    )
    spec_verifier.add_argument("--summary")
    spec_verifier.add_argument("--details")
    spec_verifier.add_argument("--blocker-question", action="append", default=[])
    spec_verifier.add_argument("--verified-focus")

    doc_harvest = subparsers.add_parser("doc-harvest-worker")
    doc_harvest.add_argument("--output", required=True)
    doc_harvest.add_argument("--work-item-id", required=True, type=_positive_int)
    doc_harvest.add_argument(
        "--output-type",
        default="completed",
        choices=["completed", "passed", "skipped_not_needed"],
    )
    doc_harvest.add_argument("--summary")
    doc_harvest.add_argument("--details")

    return parser


def _clean_optional_text(payload: dict[str, object], key: str, value: str | None) -> None:
    if value is None:
        return
    rendered = value.strip()
    if rendered:
        payload[key] = rendered


def _build_code_scout_payload(args: argparse.Namespace) -> dict[str, object]:
    payload: dict[str, object] = {
        "work_item_id": args.work_item_id,
        "result": args.result,
    }
    _clean_optional_text(payload, "summary", args.summary)
    _clean_optional_text(payload, "details", args.details)

    if args.result == "findings_found":
        findings_path = str(args.findings_path or "").strip()
        if not findings_path:
            raise ResultWriterError("code-scout findings results require --findings-path")
        if args.findings_count is None:
            raise ResultWriterError("code-scout findings results require --findings-count")
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

    if args.result not in {"passed", "failed"}:
        raise ResultWriterError("verification-coordinator requires --result passed|failed")
    payload["result"] = args.result

    failures = [item.strip() for item in args.failure if item.strip()]
    if failures:
        payload["failures"] = failures

    if args.result == "failed" and "failures" not in payload and "summary" not in payload:
        raise ResultWriterError(
            "failed verification results require at least --failure or --summary"
        )
    return payload


def _build_code_reviewer_payload(args: argparse.Namespace) -> dict[str, object]:
    payload: dict[str, object] = {
        "work_item_id": args.work_item_id,
    }
    _clean_optional_text(payload, "summary", args.summary)
    _clean_optional_text(payload, "details", args.details)
    _clean_optional_text(payload, "issues_markdown", args.issues_markdown)
    return payload


def _build_coding_payload(args: argparse.Namespace) -> dict[str, object]:
    payload: dict[str, object] = {
        "work_item_id": args.work_item_id,
    }
    _clean_optional_text(payload, "summary", args.summary)
    _clean_optional_text(payload, "details", args.details)
    _clean_optional_text(payload, "subtask_key", args.subtask_key)
    return payload


def _normalized_list(values: Sequence[str]) -> list[str]:
    return [item.strip() for item in values if item.strip()]


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


def build_result_document(args: argparse.Namespace) -> dict[str, object]:
    if args.role == "code-scout":
        payload = _build_code_scout_payload(args)
    elif args.role == "verification-coordinator":
        payload = _build_verification_payload(args)
    elif args.role == "code-reviewer":
        payload = _build_code_reviewer_payload(args)
    elif args.role in {"implementer", "bug-fixer", "mr-comments-analyst-worker"}:
        payload = _build_coding_payload(args)
    elif args.role in {
        "proposal-context-worker",
        "requirements-clarifier-worker",
        "acceptance-criteria-worker",
        "constraints-worker",
        "task-decomposer-worker",
    }:
        payload = _build_story_planning_payload(args)
    elif args.role == "spec-verifier-worker":
        payload = _build_spec_verifier_payload(args)
    elif args.role == "doc-harvest-worker":
        payload = _build_doc_harvest_payload(args)
    else:
        raise ResultWriterError(f"unsupported role: {args.role}")

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
        document = build_result_document(args)
        write_result_file(Path(args.output), document)
    except ResultWriterError as exc:
        parser.exit(2, f"error: {exc}\n")
    return 0


__all__ = [
    "ResultWriterError",
    "build_parser",
    "build_result_document",
    "main",
    "write_result_file",
]
