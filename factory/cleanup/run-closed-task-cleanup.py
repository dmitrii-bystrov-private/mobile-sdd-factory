#!/usr/bin/env python3
"""Project-scoped cleanup for definitely closed Jira tasks."""

from __future__ import annotations

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.dependencies import build_dependencies  # noqa: E402


def main() -> int:
    dependencies = build_dependencies()
    results = dependencies.coordinator_service.cleanup_closed_tasks()

    cleaned = 0
    for item in results:
        task_key = str(item["task_key"])
        jira_status = str(item["jira_status"])
        removed_paths = list(item["removed_paths"])
        print(f"{task_key}  ->  {jira_status}")
        for path in removed_paths:
            print(f"  removed {path}")
        cleaned += 1

    print("")
    print(f"Done. Cleaned: {cleaned}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
