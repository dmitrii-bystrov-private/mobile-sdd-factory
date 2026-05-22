"""Verification strategy planning for workflow-level verifier runs."""

from __future__ import annotations

from pathlib import Path
import json
import subprocess


_IOS_PREPARE_SENSITIVE_MARKERS = (
    "Podfile",
    "Podfile.lock",
    ".podspec",
    "Project.swift",
    "Workspace.swift",
    "Tuist/",
    ".xcodeproj/",
    ".xcworkspace/",
    "Package.swift",
    ".mise",
    ".tool-versions",
)


def _read_changed_files_from_git(task_repo_root: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(task_repo_root), "diff", "--name-only", "origin/master...HEAD"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _read_changed_files_from_diff_artifact(task_root: Path) -> list[str]:
    diff_path = task_root / "spec" / "diff.md"
    if not diff_path.is_file():
        return []
    changed_files: list[str] = []
    in_table = False
    for raw_line in diff_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line == "| Status | Path |":
            in_table = True
            continue
        if not in_table:
            continue
        if line == "" or not line.startswith("|"):
            break
        if line == "|---|---|":
            continue
        parts = [part.strip() for part in line.strip("|").split("|")]
        if len(parts) != 2:
            continue
        path = parts[1]
        if path:
            changed_files.append(path)
    return changed_files


def _read_changed_files(task_root: Path, task_repo_root: Path) -> list[str]:
    changed_files = _read_changed_files_from_git(task_repo_root)
    if changed_files:
        return changed_files
    return _read_changed_files_from_diff_artifact(task_root)


def _is_doc_path(path: str) -> bool:
    return path.endswith((".md", ".adoc", ".rst", ".txt"))


def _is_ios_test_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return (
        "/Tests/" in normalized
        or normalized.endswith("Tests.swift")
        or normalized.endswith("Test.swift")
    )


def _is_ios_prepare_sensitive_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return any(marker in normalized for marker in _IOS_PREPARE_SENSITIVE_MARKERS)


def detect_verification_platform(task_repo_root: Path) -> str:
    if (task_repo_root / "Tools" / "buildscripts").is_dir():
        return "ios"
    return "android"


def build_verification_strategy(*, task_key: str, workdir_root: Path) -> dict[str, object]:
    task_root = workdir_root / task_key
    repo_root = task_root / "repo"
    platform = detect_verification_platform(repo_root)
    changed_files = _read_changed_files(task_root, repo_root)
    non_doc_files = [path for path in changed_files if not _is_doc_path(path)]
    docs_only = bool(changed_files) and not non_doc_files
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
        "changed_files": changed_files,
        "signals": {
            "changed_file_count": len(changed_files),
            "docs_only": docs_only,
        },
    }
    if platform == "ios":
        context_root = task_root / "tmp" / "verification" / "ios"
        tests_only = bool(non_doc_files) and all(_is_ios_test_path(path) for path in non_doc_files)
        prepare_sensitive = any(_is_ios_prepare_sensitive_path(path) for path in non_doc_files)
        prepare_policy = "required" if prepare_sensitive else "reuse_if_available"
        mode = "ios_broad_safe_gate"
        confidence = "high"
        reason = (
            "Use the iOS workflow-level verification gate with task-local build state "
            "for safe parallel verification."
        )
        if tests_only and not prepare_sensitive:
            mode = "ios_test_scope_gate"
            confidence = "medium"
            reason = (
                "The diff is limited to iOS test code, so the verifier can keep the "
                "same safe gate while preferring reusable task-local prepare state."
            )
        elif prepare_sensitive:
            reason = (
                "The diff touches build or dependency configuration, so iOS prepare "
                "steps must run freshly before verification."
            )
        strategy["mode"] = mode
        strategy["confidence"] = confidence
        strategy["reason"] = reason
        strategy["prepare"] = {
            "tuist_generate": prepare_policy,
            "pod_install": prepare_policy,
            "policy": prepare_policy,
        }
        strategy["build_products_policy"] = (
            "reuse_if_same_head" if tests_only and not prepare_sensitive else "rebuild"
        )
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
        strategy["signals"] = {
            "changed_file_count": len(changed_files),
            "docs_only": docs_only,
            "tests_only": tests_only,
            "prepare_sensitive": prepare_sensitive,
        }
    return strategy


def materialize_verification_strategy(*, task_key: str, workdir_root: Path) -> tuple[dict[str, object], Path]:
    strategy = build_verification_strategy(task_key=task_key, workdir_root=workdir_root)
    spec_root = workdir_root / task_key / "spec"
    spec_root.mkdir(parents=True, exist_ok=True)
    strategy_path = spec_root / "verification-strategy.json"
    strategy_path.write_text(json.dumps(strategy, indent=2, sort_keys=True), encoding="utf-8")
    return strategy, strategy_path
