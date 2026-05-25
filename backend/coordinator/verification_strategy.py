"""Verification strategy planning for workflow-level verifier runs."""

from __future__ import annotations

import json
from pathlib import Path
import re
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
_IOS_VERIFICATION_MAP_PATH = Path(__file__).resolve().parents[2] / "config" / "ios-verification-map.json"
_ANDROID_PREPARE_SENSITIVE_MARKERS = (
    "settings.gradle",
    "settings.gradle.kts",
    "build.gradle",
    "build.gradle.kts",
    "gradle.properties",
    "gradle/libs.versions.toml",
    "gradle-wrapper.properties",
    "gradlew",
    "gradlew.bat",
)
_ANDROID_VERIFICATION_MAP_PATH = Path(__file__).resolve().parents[2] / "config" / "android-verification-map.json"


def _normalize_repo_path(path: str) -> str:
    normalized = path.replace("\\", "/").strip()
    normalized = normalized.lstrip("./")
    return normalized.lstrip("/")


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        value = str(raw_value).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _load_ios_verification_map() -> list[dict[str, object]]:
    try:
        payload = json.loads(_IOS_VERIFICATION_MAP_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    areas = payload.get("areas")
    if not isinstance(areas, list):
        return []
    return [item for item in areas if isinstance(item, dict)]


def _load_android_verification_map() -> list[dict[str, object]]:
    try:
        payload = json.loads(_ANDROID_VERIFICATION_MAP_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    areas = payload.get("areas")
    if not isinstance(areas, list):
        return []
    return [item for item in areas if isinstance(item, dict)]


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
    normalized = _normalize_repo_path(path).lower()
    return normalized.endswith((".md", ".adoc", ".rst", ".txt"))


def _is_ios_test_path(path: str) -> bool:
    normalized = _normalize_repo_path(path)
    return (
        "/Tests/" in normalized
        or normalized.endswith("Tests.swift")
        or normalized.endswith("Test.swift")
    )


def _is_ios_prepare_sensitive_path(path: str) -> bool:
    normalized = _normalize_repo_path(path)
    return any(marker in normalized for marker in _IOS_PREPARE_SENSITIVE_MARKERS)


def _is_android_test_path(path: str) -> bool:
    normalized = _normalize_repo_path(path)
    lowered = normalized.lower()
    return (
        "/src/test/" in lowered
        or "/src/androidtest/" in lowered
        or lowered.endswith(("test.kt", "test.java", "tests.kt", "tests.java"))
    )


def _is_android_prepare_sensitive_path(path: str) -> bool:
    normalized = _normalize_repo_path(path)
    return any(marker in normalized for marker in _ANDROID_PREPARE_SENSITIVE_MARKERS)


def _extract_ios_test_selectors(task_repo_root: Path, changed_files: list[str]) -> list[str]:
    selectors: list[str] = []
    seen: set[str] = set()
    class_pattern = re.compile(r"\b(?:final\s+)?class\s+(\w+Tests?)\s*:\s*(?:\w+\.)?XCTestCase\b")
    for changed_path in changed_files:
        if not _is_ios_test_path(changed_path):
            continue
        candidate = task_repo_root / changed_path
        class_names: list[str] = []
        if candidate.is_file():
            try:
                text = candidate.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = candidate.read_text(encoding="utf-8", errors="ignore")
            class_names = [match.group(1) for match in class_pattern.finditer(text)]
        if not class_names:
            stem = Path(changed_path).stem
            if stem.endswith(("Test", "Tests")):
                class_names = [stem]
        for class_name in class_names:
            selector = f"FinomTests/{class_name}"
            if selector not in seen:
                seen.add(selector)
                selectors.append(selector)
    return selectors


def _match_ios_area(changed_path: str, areas: list[dict[str, object]]) -> dict[str, object] | None:
    normalized_path = _normalize_repo_path(changed_path).lower()
    best_match: dict[str, object] | None = None
    best_length = -1
    for area in areas:
        prefixes = area.get("path_prefixes")
        if not isinstance(prefixes, list):
            continue
        for raw_prefix in prefixes:
            prefix = _normalize_repo_path(str(raw_prefix)).lower()
            if not prefix:
                continue
            if normalized_path.startswith(prefix) and len(prefix) > best_length:
                best_match = area
                best_length = len(prefix)
    return best_match


def _build_ios_impact_mapping(
    *,
    changed_files: list[str],
    non_doc_files: list[str],
    prepare_sensitive: bool,
    targeted_selectors: list[str],
) -> dict[str, object]:
    areas = _load_ios_verification_map()
    impacted_area_names: list[str] = []
    impacted_schemes: list[str] = []
    impacted_test_targets: list[str] = []
    unmapped_files: list[str] = []

    for changed_path in non_doc_files:
        matched_area = _match_ios_area(changed_path, areas)
        if matched_area is None:
            unmapped_files.append(changed_path)
            continue
        area_name = str(matched_area.get("name") or "").strip()
        if area_name:
            impacted_area_names.append(area_name)
        schemes = matched_area.get("schemes")
        if isinstance(schemes, list):
            impacted_schemes.extend(str(item).strip() for item in schemes)
        test_targets = matched_area.get("test_targets")
        if isinstance(test_targets, list):
            impacted_test_targets.extend(str(item).strip() for item in test_targets)

    impacted_area_names = _dedupe_preserving_order(impacted_area_names)
    impacted_schemes = _dedupe_preserving_order(impacted_schemes)
    impacted_test_targets = _dedupe_preserving_order(impacted_test_targets)

    confidence = "low"
    fallback_required = True
    reason = "The changed files could not be mapped to a stable iOS verification area, so the broad safe gate remains required."
    preferred_scheme = impacted_schemes[0] if len(impacted_schemes) == 1 else ""

    if changed_files and not non_doc_files:
        confidence = "high"
        fallback_required = False
        reason = "Only documentation files changed, so no code-impact mapping is required."
    elif prepare_sensitive:
        confidence = "low"
        fallback_required = True
        reason = "Build or dependency configuration changed, so even mapped iOS areas must fall back to the broad safe gate."
    elif non_doc_files and not unmapped_files and len(impacted_area_names) == 1:
        confidence = "high"
        fallback_required = False
        reason = f"All changed code maps cleanly to the single impacted iOS area `{impacted_area_names[0]}`."
    elif non_doc_files and not unmapped_files and len(impacted_area_names) > 1:
        confidence = "medium"
        fallback_required = True
        reason = "The diff spans multiple mapped iOS areas, so narrowing further would be unsafe."
    elif non_doc_files and unmapped_files:
        confidence = "low"
        fallback_required = True
        reason = "Some changed files did not match the static iOS verification map, so the broad safe gate remains required."

    impact_mapping: dict[str, object] = {
        "confidence": confidence,
        "fallback_required": fallback_required,
        "reason": reason,
        "impacted_areas": impacted_area_names,
        "impacted_schemes": impacted_schemes,
        "impacted_test_targets": impacted_test_targets,
        "targeted_selectors": targeted_selectors,
        "mapped_file_count": len(non_doc_files) - len(unmapped_files),
        "unmapped_files": unmapped_files,
    }
    if preferred_scheme:
        impact_mapping["preferred_scheme"] = preferred_scheme
    return impact_mapping


def _match_android_area(changed_path: str, areas: list[dict[str, object]]) -> dict[str, object] | None:
    normalized_path = _normalize_repo_path(changed_path).lower()
    best_match: dict[str, object] | None = None
    best_length = -1
    for area in areas:
        prefixes = area.get("path_prefixes")
        if not isinstance(prefixes, list):
            continue
        for raw_prefix in prefixes:
            prefix = _normalize_repo_path(str(raw_prefix)).lower()
            if not prefix:
                continue
            if normalized_path.startswith(prefix) and len(prefix) > best_length:
                best_match = area
                best_length = len(prefix)
    return best_match


def _infer_android_module(task_repo_root: Path, changed_path: str) -> str | None:
    candidate = task_repo_root / _normalize_repo_path(changed_path)
    current = candidate.parent if candidate.suffix else candidate
    try:
        repo_root_resolved = task_repo_root.resolve()
        current_resolved = current.resolve()
    except OSError:
        return None
    while True:
        if (current_resolved / "build.gradle").is_file() or (current_resolved / "build.gradle.kts").is_file():
            try:
                relative = current_resolved.relative_to(repo_root_resolved)
            except ValueError:
                return None
            if str(relative) in {"", "."}:
                return None
            parts = [part for part in relative.parts if part not in {"", "."}]
            if not parts:
                return None
            return ":" + ":".join(parts)
        if current_resolved == repo_root_resolved:
            return None
        parent = current_resolved.parent
        if parent == current_resolved:
            return None
        current_resolved = parent


def _default_android_tasks_for_module(module_name: str) -> tuple[list[str], list[str], list[str]]:
    normalized = module_name.strip()
    if not normalized:
        return ([], [], [])
    return ([f"{normalized}:assemble"], [f"{normalized}:test"], [f"{normalized}:lint"])


def _build_android_impact_mapping(
    *,
    task_repo_root: Path,
    changed_files: list[str],
    non_doc_files: list[str],
    prepare_sensitive: bool,
) -> dict[str, object]:
    areas = _load_android_verification_map()
    impacted_area_names: list[str] = []
    impacted_modules: list[str] = []
    impacted_build_tasks: list[str] = []
    impacted_test_tasks: list[str] = []
    impacted_lint_tasks: list[str] = []
    unmapped_files: list[str] = []

    for changed_path in non_doc_files:
        matched_area = _match_android_area(changed_path, areas)
        if matched_area is not None:
            area_name = str(matched_area.get("name") or "").strip()
            if area_name:
                impacted_area_names.append(area_name)
            gradle_modules = matched_area.get("gradle_modules")
            if isinstance(gradle_modules, list):
                impacted_modules.extend(str(item).strip() for item in gradle_modules)
            build_tasks = matched_area.get("build_tasks")
            if isinstance(build_tasks, list):
                impacted_build_tasks.extend(str(item).strip() for item in build_tasks)
            test_tasks = matched_area.get("test_tasks")
            if isinstance(test_tasks, list):
                impacted_test_tasks.extend(str(item).strip() for item in test_tasks)
            lint_tasks = matched_area.get("lint_tasks")
            if isinstance(lint_tasks, list):
                impacted_lint_tasks.extend(str(item).strip() for item in lint_tasks)
            continue

        inferred_module = _infer_android_module(task_repo_root, changed_path)
        if inferred_module is None:
            unmapped_files.append(changed_path)
            continue
        impacted_area_names.append(inferred_module.lstrip(":").replace(":", "/"))
        impacted_modules.append(inferred_module)
        default_build_tasks, default_test_tasks, default_lint_tasks = _default_android_tasks_for_module(
            inferred_module
        )
        impacted_build_tasks.extend(default_build_tasks)
        impacted_test_tasks.extend(default_test_tasks)
        impacted_lint_tasks.extend(default_lint_tasks)

    impacted_area_names = _dedupe_preserving_order(impacted_area_names)
    impacted_modules = _dedupe_preserving_order(impacted_modules)
    impacted_build_tasks = _dedupe_preserving_order(impacted_build_tasks)
    impacted_test_tasks = _dedupe_preserving_order(impacted_test_tasks)
    impacted_lint_tasks = _dedupe_preserving_order(impacted_lint_tasks)

    confidence = "low"
    fallback_required = True
    reason = (
        "The changed files could not be mapped to a stable Android module boundary, so the broad safe gate remains required."
    )

    if changed_files and not non_doc_files:
        confidence = "high"
        fallback_required = False
        reason = "Only documentation files changed, so no code-impact mapping is required."
    elif prepare_sensitive:
        confidence = "low"
        fallback_required = True
        reason = "Gradle or build configuration changed, so Android verification must fall back to the broad safe gate."
    elif non_doc_files and not unmapped_files and len(impacted_modules) == 1:
        confidence = "high"
        fallback_required = False
        reason = f"All changed code maps cleanly to the single impacted Android module `{impacted_modules[0]}`."
    elif non_doc_files and not unmapped_files and len(impacted_modules) > 1:
        confidence = "medium"
        fallback_required = True
        reason = "The diff spans multiple mapped Android modules, so narrowing further would be unsafe."
    elif non_doc_files and unmapped_files:
        confidence = "low"
        fallback_required = True
        reason = "Some changed files did not map cleanly to Android modules, so the broad safe gate remains required."

    return {
        "confidence": confidence,
        "fallback_required": fallback_required,
        "reason": reason,
        "impacted_areas": impacted_area_names,
        "impacted_modules": impacted_modules,
        "impacted_build_tasks": impacted_build_tasks,
        "impacted_test_tasks": impacted_test_tasks,
        "impacted_lint_tasks": impacted_lint_tasks,
        "mapped_file_count": len(non_doc_files) - len(unmapped_files),
        "unmapped_files": unmapped_files,
    }


def detect_verification_platform(task_repo_root: Path) -> str:
    if (task_repo_root / "Tools" / "buildscripts").is_dir():
        return "ios"
    return "android"


def build_verification_strategy(*, task_key: str, workdir_root: Path, repo_root: Path) -> dict[str, object]:
    task_root = workdir_root / task_key
    task_repo_root = task_root / "repo"
    platform = detect_verification_platform(task_repo_root)
    changed_files = _read_changed_files(task_root, task_repo_root)
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
        targeted_selectors = _extract_ios_test_selectors(repo_root, non_doc_files) if tests_only else []
        impact_mapping = _build_ios_impact_mapping(
            changed_files=changed_files,
            non_doc_files=non_doc_files,
            prepare_sensitive=prepare_sensitive,
            targeted_selectors=targeted_selectors,
        )
        prepare_policy = "required" if prepare_sensitive else "reuse_if_available"
        mode = "ios_broad_safe_gate"
        confidence = str(impact_mapping.get("confidence") or "high")
        reason = (
            "Use the iOS workflow-level verification gate with task-local build state "
            "for safe parallel verification."
        )
        if docs_only:
            mode = "ios_docs_only_skip"
            confidence = "high"
            reason = "Only documentation files changed, so code verification can be skipped safely for this iOS task."
        elif tests_only and not prepare_sensitive:
            mode = "ios_test_scope_gate"
            confidence = "medium"
            reason = (
                "The diff is limited to iOS test code, so the verifier can keep the "
                "same safe gate while preferring reusable task-local prepare state."
            )
            if targeted_selectors:
                reason += f" Targeted test selectors were inferred for {len(targeted_selectors)} changed test file(s)."
        elif not prepare_sensitive and not bool(impact_mapping.get("fallback_required")):
            impacted_areas = impact_mapping.get("impacted_areas")
            rendered_area = ""
            if isinstance(impacted_areas, list) and impacted_areas:
                rendered_area = str(impacted_areas[0]).strip()
            mode = "ios_impacted_area_gate"
            confidence = "high"
            if rendered_area:
                reason = (
                    f"All changed iOS code maps to the single impacted area `{rendered_area}`, "
                    "so the verifier can keep the safe task-local gate while reporting a narrower impact boundary."
                )
            else:
                reason = (
                    "All changed iOS code maps to a single impacted area, so the verifier can "
                    "keep the safe task-local gate while reporting a narrower impact boundary."
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
        strategy["test_selection"] = {
            "mode": "only_testing" if targeted_selectors else "broad",
            "selectors": targeted_selectors,
            "test_targets": list(impact_mapping.get("impacted_test_targets") or []),
        }
        strategy["impact_mapping"] = impact_mapping
        strategy["phases"] = [] if docs_only else [
            "prepare",
            "build_for_testing",
            "test_without_building",
            "lint",
        ]
        scripts_root = repo_root / "scripts"
        strategy["commands"] = [
            f"bash {scripts_root / 'ios-verify.sh'} {task_key}",
        ]
        strategy["phase_commands"] = {
            "prepare": f"bash {scripts_root / 'ios-prepare.sh'} {task_key}",
            "build_for_testing": f"bash {scripts_root / 'ios-build-for-testing.sh'} {task_key}",
            "test_without_building": f"bash {scripts_root / 'ios-test-without-building.sh'} {task_key}",
            "lint": f"bash {scripts_root / 'run-lint.sh'} {task_key}",
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
            "targeted_selector_count": len(targeted_selectors),
            "mapped_area_count": len(list(impact_mapping.get("impacted_areas") or [])),
            "unmapped_file_count": len(list(impact_mapping.get("unmapped_files") or [])),
        }
    elif platform == "android":
        context_root = task_root / "tmp" / "verification" / "android"
        tests_only = bool(non_doc_files) and all(_is_android_test_path(path) for path in non_doc_files)
        prepare_sensitive = any(_is_android_prepare_sensitive_path(path) for path in non_doc_files)
        impact_mapping = _build_android_impact_mapping(
            task_repo_root=task_repo_root,
            changed_files=changed_files,
            non_doc_files=non_doc_files,
            prepare_sensitive=prepare_sensitive,
        )
        prepare_policy = "required" if prepare_sensitive else "reuse_if_available"
        mode = "android_broad_safe_gate"
        confidence = str(impact_mapping.get("confidence") or "high")
        reason = (
            "Use the Android workflow-level verification gate with task-local Gradle state "
            "for safe parallel verification."
        )
        phases = ["prepare", "build", "test", "lint"]
        if docs_only:
            mode = "android_docs_only_skip"
            confidence = "high"
            reason = "Only documentation files changed, so code verification can be skipped safely for this Android task."
            phases = []
        elif tests_only and not prepare_sensitive and not bool(impact_mapping.get("fallback_required")):
            mode = "android_test_scope_gate"
            confidence = "high"
            reason = (
                "The diff is limited to Android test code inside a single impacted module, "
                "so the verifier can run a narrower task-local test+lint gate."
            )
        elif not prepare_sensitive and not bool(impact_mapping.get("fallback_required")):
            impacted_modules = impact_mapping.get("impacted_modules")
            rendered_module = ""
            if isinstance(impacted_modules, list) and impacted_modules:
                rendered_module = str(impacted_modules[0]).strip()
            mode = "android_impacted_module_gate"
            confidence = "high"
            phases = ["prepare", "build", "test", "lint"]
            if rendered_module:
                reason = (
                    f"All changed Android code maps to the single impacted module `{rendered_module}`, "
                    "so the verifier can keep a task-local module-scoped gate."
                )
            else:
                reason = (
                    "All changed Android code maps to a single impacted module, so the verifier can "
                    "keep a task-local module-scoped gate."
                )
        elif prepare_sensitive:
            reason = (
                "The diff touches Gradle or build configuration, so Android verification "
                "must refresh task-local Gradle state before running the broad safe gate."
            )
        build_tasks = list(impact_mapping.get("impacted_build_tasks") or [])
        test_tasks = list(impact_mapping.get("impacted_test_tasks") or [])
        if mode == "android_broad_safe_gate":
            test_tasks = ["test"]
            build_tasks = []
        elif mode == "android_test_scope_gate":
            build_tasks = []
        strategy["mode"] = mode
        strategy["confidence"] = confidence
        strategy["reason"] = reason
        strategy["prepare"] = {
            "gradle_state": prepare_policy,
            "policy": prepare_policy,
        }
        strategy["build_products_policy"] = (
            "reuse_if_same_head" if tests_only and not prepare_sensitive else "rebuild"
        )
        strategy["test_selection"] = {
            "mode": "targeted_tasks" if test_tasks and mode != "android_broad_safe_gate" else "broad",
            "gradle_test_tasks": [str(item).strip() for item in test_tasks if str(item).strip()],
            "gradle_lint_tasks": [],
        }
        strategy["build_selection"] = {
            "mode": "targeted_tasks" if build_tasks and mode == "android_impacted_module_gate" else "skip",
            "gradle_build_tasks": [str(item).strip() for item in build_tasks if str(item).strip()],
        }
        strategy["impact_mapping"] = impact_mapping
        strategy["phases"] = phases
        scripts_root = repo_root / "scripts"
        strategy["commands"] = [
            f"bash {scripts_root / 'android-verify.sh'} {task_key}",
        ]
        strategy["phase_commands"] = {
            "prepare": f"bash {scripts_root / 'android-prepare.sh'} {task_key}",
            "build": f"bash {scripts_root / 'android-build.sh'} {task_key}",
            "test": f"bash {scripts_root / 'android-test.sh'} {task_key}",
            "lint": f"bash {scripts_root / 'android-lint.sh'} {task_key}",
        }
        strategy["android_context"] = {
            "context_root": str(context_root),
            "gradle_user_home_path": str(context_root / "gradle-user-home"),
            "logs_path": str(context_root / "logs"),
        }
        strategy["signals"] = {
            "changed_file_count": len(changed_files),
            "docs_only": docs_only,
            "tests_only": tests_only,
            "prepare_sensitive": prepare_sensitive,
            "mapped_module_count": len(list(impact_mapping.get("impacted_modules") or [])),
            "unmapped_file_count": len(list(impact_mapping.get("unmapped_files") or [])),
        }
    return strategy


def materialize_verification_strategy(*, task_key: str, workdir_root: Path, repo_root: Path) -> tuple[dict[str, object], Path]:
    strategy = build_verification_strategy(task_key=task_key, workdir_root=workdir_root, repo_root=repo_root)
    spec_root = workdir_root / task_key / "spec"
    spec_root.mkdir(parents=True, exist_ok=True)
    strategy_path = spec_root / "verification-strategy.json"
    strategy_path.write_text(json.dumps(strategy, indent=2, sort_keys=True), encoding="utf-8")
    return strategy, strategy_path
