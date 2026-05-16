#!/usr/bin/env python3
"""Run plan-based Jira subtask creation acceptance through the operator route layer."""

from __future__ import annotations

from pathlib import Path
import tempfile

from backend.api.routes_artifacts import list_artifacts
from backend.api.routes_operator import create_subtasks_from_plan
from backend.api.routes_sessions import create_session, prepare_session
from backend.api.schemas import (
    CreateSessionRequest,
    CreateSubtasksFromPlanRequest,
    PrepareSessionRequest,
)

from importlib.util import module_from_spec, spec_from_file_location


def load_story_acceptance_module():
    module_path = Path(__file__).resolve().parent / "run-story-subtasks-acceptance.py"
    spec = spec_from_file_location("story_subtasks_acceptance", module_path)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    story_acceptance = load_story_acceptance_module()
    with tempfile.TemporaryDirectory(prefix="sdd-factory-plan-subtasks-acceptance.") as temp_dir:
        temp_root = Path(temp_dir)
        deps = story_acceptance.build_acceptance_dependencies(repo_root=repo_root, temp_root=temp_root)

        create_response = create_session(
            CreateSessionRequest(
                task_key="IOS-ACCEPT-PLAN-001",
                workflow_profile="story_full",
                policy={
                    "self_review_policy": "disabled",
                    "boy_scout_policy": "disabled",
                    "doc_harvest_policy": "disabled",
                },
            ),
            dependencies=deps,
        )
        session_id = create_response.session.id
        prepare_session(
            PrepareSessionRequest(task_key="IOS-ACCEPT-PLAN-001"),
            dependencies=deps,
        )

        plan_dir = temp_root / "workdir" / "IOS-ACCEPT-PLAN-001" / "plan"
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / "index.md").write_text(
            "# Execution Task List\n\n| # | Task | Depends on | Status |\n|---|------|------------|--------|\n| 01 | [Build data source](./01-build-data-source.md) | — | ☐ |\n"
        )
        (plan_dir / "01-build-data-source.md").write_text(
            "# Build data source\n\n## What to implement\nCreate the feature data source.\n"
        )

        response = create_subtasks_from_plan(
            CreateSubtasksFromPlanRequest(session_id=session_id),
            dependencies=deps,
        )
        assert response.created
        assert response.event_type == "jira_subtasks_created"

        artifacts_response = list_artifacts(session_id=session_id, dependencies=deps)
        artifact_types = [item.artifact_type for item in artifacts_response.items]
        assert "jira_subtasks_stdout" in artifact_types
        assert "jira_subtasks_stderr" in artifact_types
        assert "subtasks_snapshot_stdout" in artifact_types
        assert "subtasks_snapshot_stderr" in artifact_types

        print(f"Plan-based Jira subtask acceptance passed for session {session_id}.")


if __name__ == "__main__":
    main()
