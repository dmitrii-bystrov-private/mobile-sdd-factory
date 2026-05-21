"""Verification strategy planning for workflow-level verifier runs."""

from __future__ import annotations

from pathlib import Path
import json


def detect_verification_platform(task_repo_root: Path) -> str:
    if (task_repo_root / "Tools" / "buildscripts").is_dir():
        return "ios"
    return "android"


def build_verification_strategy(*, task_key: str, workdir_root: Path) -> dict[str, object]:
    task_root = workdir_root / task_key
    repo_root = task_root / "repo"
    platform = detect_verification_platform(repo_root)
    strategy: dict[str, object] = {
        "task_key": task_key,
        "platform": platform,
        "mode": "broad_safe_gate",
        "confidence": "high",
        "reason": (
            "Use the safe workflow-level verification gate first while targeted "
            "verification strategy is introduced incrementally."
        ),
        "commands": [
            f"bash scripts/run-test.sh {task_key}",
            f"bash scripts/run-lint.sh {task_key}",
        ],
        "phases": ["test", "lint"],
        "reporting": {
            "final_verification_path": str(task_root / "spec" / "final-verification.md"),
        },
    }
    if platform == "ios":
        context_root = task_root / "tmp" / "verification" / "ios"
        strategy["prepare"] = {
            "tuist_generate": "required",
            "pod_install": "required",
        }
        strategy["phases"] = [
            "prepare",
            "build_for_testing",
            "test_without_building",
            "lint",
        ]
        strategy["phase_commands"] = {
            "prepare": f"bash scripts/ios-prepare.sh {task_key}",
            "build_for_testing": f"bash scripts/ios-build-for-testing.sh {task_key}",
            "test_without_building": f"bash scripts/ios-test-without-building.sh {task_key}",
            "lint": f"bash scripts/run-lint.sh {task_key}",
        }
        strategy["ios_context"] = {
            "context_root": str(context_root),
            "derived_data_path": str(context_root / "derived-data"),
            "xcresult_root": str(context_root / "xcresult"),
            "cloned_source_packages_path": str(context_root / "cloned-source-packages"),
            "logs_path": str(context_root / "logs"),
        }
    return strategy


def materialize_verification_strategy(*, task_key: str, workdir_root: Path) -> tuple[dict[str, object], Path]:
    strategy = build_verification_strategy(task_key=task_key, workdir_root=workdir_root)
    spec_root = workdir_root / task_key / "spec"
    spec_root.mkdir(parents=True, exist_ok=True)
    strategy_path = spec_root / "verification-strategy.json"
    strategy_path.write_text(json.dumps(strategy, indent=2, sort_keys=True), encoding="utf-8")
    return strategy, strategy_path
