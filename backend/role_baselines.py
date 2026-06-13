"""Supported runtime role baselines for the backend/UI platform."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class RoleBaseline:
    role_name: str
    model: str | None
    effort: str | None
    mcp_servers: list[str]
    source: str


_BASELINE_SOURCE = "backend.role_baselines"

ROLE_BASELINES: tuple[RoleBaseline, ...] = (
    RoleBaseline("implementer", "sonnet", "medium", ["ios-rag", "android-rag", "frontend-rag"], _BASELINE_SOURCE),
    RoleBaseline("verification-coordinator", "sonnet", "medium", [], _BASELINE_SOURCE),
    RoleBaseline("bug-fixer", "sonnet", "high", ["ios-rag", "android-rag", "frontend-rag"], _BASELINE_SOURCE),
    RoleBaseline("convention-reviewer", "sonnet", "medium", [], _BASELINE_SOURCE),
    RoleBaseline("requirements-reviewer", "sonnet", "medium", [], _BASELINE_SOURCE),
    RoleBaseline("code-reviewer", "sonnet", "medium", [], _BASELINE_SOURCE),
    RoleBaseline("code-scout", "sonnet", "medium", [], _BASELINE_SOURCE),
    RoleBaseline("mr-comments-analyst-worker", "sonnet", "high", [], _BASELINE_SOURCE),
    RoleBaseline("doc-harvest-worker", "sonnet", "medium", [], _BASELINE_SOURCE),
    RoleBaseline("documentation-reviewer", "sonnet", "medium", [], _BASELINE_SOURCE),
    RoleBaseline(
        "proposal-context-worker",
        "sonnet",
        "high",
        ["ios-rag", "android-rag", "frontend-rag"],
        _BASELINE_SOURCE,
    ),
    RoleBaseline("requirements-clarifier-worker", "sonnet", "high", [], _BASELINE_SOURCE),
    RoleBaseline("acceptance-criteria-worker", "sonnet", "medium", [], _BASELINE_SOURCE),
    RoleBaseline("constraints-worker", "sonnet", "high", [], _BASELINE_SOURCE),
    RoleBaseline("spec-verifier-worker", "opus", "high", [], _BASELINE_SOURCE),
    RoleBaseline("task-decomposer-worker", "sonnet", "high", [], _BASELINE_SOURCE),
)


def known_role_names() -> list[str]:
    return sorted(item.role_name for item in ROLE_BASELINES)


def role_baselines_by_name() -> dict[str, RoleBaseline]:
    return {item.role_name: item for item in ROLE_BASELINES}


def role_baselines_report() -> list[dict[str, object]]:
    return [asdict(item) for item in ROLE_BASELINES]
