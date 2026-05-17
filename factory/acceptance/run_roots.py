#!/usr/bin/env python3
"""Helpers for project-scoped acceptance run roots."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
from typing import Iterator

from backend.session_backend.runtime_models import RuntimeSessionHandle


def runtime_root(repo_root: Path) -> Path:
    root = repo_root / ".runtime"
    root.mkdir(parents=True, exist_ok=True)
    return root


def acceptance_runs_root(repo_root: Path) -> Path:
    root = runtime_root(repo_root) / "test-runs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def tmux_socket_root(repo_root: Path) -> Path:
    root = repo_root / ".ts" / "runtime"
    root.mkdir(parents=True, exist_ok=True)
    return root


def run_tmux_socket_root(run_root: Path) -> Path:
    run_suffix = run_root.name.split(".")[-1]
    root = run_root.parents[2] / ".ts" / "tests" / run_suffix
    root.mkdir(parents=True, exist_ok=True)
    return root


def cleanup_stale_run_roots(repo_root: Path) -> None:
    runs_root = acceptance_runs_root(repo_root)
    for run_root in runs_root.iterdir():
        if not run_root.is_dir():
            continue
        socket_root = run_tmux_socket_root(run_root)
        if socket_root.exists():
            for sock in socket_root.glob("*.sock"):
                try:
                    if sock.exists():
                        subprocess.run(
                            ["tmux", "-S", str(sock), "kill-server"],
                            check=False,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                finally:
                    sock.unlink(missing_ok=True)
            shutil.rmtree(socket_root, ignore_errors=True)
        shutil.rmtree(run_root, ignore_errors=True)


def _iter_claude_test_project_dirs(*, run_suffix: str | None = None) -> list[Path]:
    root = Path.home() / ".claude" / "projects"
    if not root.exists() or not root.is_dir():
        return []
    matches: list[Path] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        name = child.name.lower()
        is_test_dir = (
            "runtime-test-runs" in name
            or "workdir-ios-accept" in name
            or "workdir-ios-debug" in name
        )
        if not is_test_dir:
            continue
        if run_suffix is not None and run_suffix.lower() not in name:
            continue
        matches.append(child)
    return matches


def _codex_session_matches(session_file: Path, *, cwd_predicate) -> bool:
    try:
        with session_file.open("r", encoding="utf-8") as handle:
            for _ in range(20):
                line = handle.readline()
                if not line:
                    break
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                cwd = payload.get("payload", {}).get("cwd") if isinstance(payload, dict) else None
                if isinstance(cwd, str) and cwd_predicate(cwd.lower()):
                    return True
    except OSError:
        return False
    return False


def _iter_codex_test_session_files(*, repo_root: Path, run_root: Path | None = None) -> list[Path]:
    root = Path.home() / ".codex" / "sessions"
    if not root.exists() or not root.is_dir():
        return []
    runtime_runs_root = str(repo_root / ".runtime" / "test-runs").lower()
    specific_run_root = str(run_root).lower() if run_root is not None else None

    def predicate(cwd: str) -> bool:
        if specific_run_root is not None:
            return specific_run_root in cwd
        return runtime_runs_root in cwd or "/workdir/ios-accept" in cwd or "/workdir/ios-debug" in cwd

    matches: list[Path] = []
    for session_file in root.rglob("*.jsonl"):
        if _codex_session_matches(session_file, cwd_predicate=predicate):
            matches.append(session_file)
    return matches


def _prune_empty_codex_session_dirs() -> None:
    root = Path.home() / ".codex" / "sessions"
    if not root.exists() or not root.is_dir():
        return
    for path in sorted(root.rglob("*"), reverse=True):
        if not path.is_dir():
            continue
        try:
            next(path.iterdir())
        except StopIteration:
            path.rmdir()
        except OSError:
            continue


def cleanup_stale_runner_test_residue(repo_root: Path) -> None:
    for path in _iter_claude_test_project_dirs():
        shutil.rmtree(path, ignore_errors=True)
    for session_file in _iter_codex_test_session_files(repo_root=repo_root):
        session_file.unlink(missing_ok=True)
    _prune_empty_codex_session_dirs()


def cleanup_runner_test_residue_for_run_root(repo_root: Path, run_root: Path) -> None:
    run_suffix = run_root.name.split(".")[-1]
    for path in _iter_claude_test_project_dirs(run_suffix=run_suffix):
        shutil.rmtree(path, ignore_errors=True)
    for session_file in _iter_codex_test_session_files(repo_root=repo_root, run_root=run_root):
        session_file.unlink(missing_ok=True)
    _prune_empty_codex_session_dirs()


def create_run_root(repo_root: Path, prefix: str) -> Path:
    cleanup_stale_run_roots(repo_root)
    cleanup_stale_runner_test_residue(repo_root)
    return Path(tempfile.mkdtemp(prefix=f"{prefix}.", dir=acceptance_runs_root(repo_root)))


def shutdown_dependencies(dependencies) -> None:
    seen_runtime_sessions: set[str] = set()
    for session in dependencies.session_repository.list_all():
        runtime_session_id = None
        for role in dependencies.role_repository.list_for_session(session.id):
            if role.runtime_handle and ":" in role.runtime_handle:
                runtime_session_id = role.runtime_handle.split(":", 1)[0]
                break
        if runtime_session_id is None or runtime_session_id in seen_runtime_sessions:
            continue
        seen_runtime_sessions.add(runtime_session_id)
        try:
            dependencies.session_backend.stop_session(
                RuntimeSessionHandle(session_id=runtime_session_id)
            )
        except Exception:
            pass


@contextmanager
def managed_run_root(
    repo_root: Path,
    prefix: str,
    *,
    keep_env_var: str = "SDD_FACTORY_KEEP_TEMP",
) -> Iterator[Path]:
    root = create_run_root(repo_root, prefix)
    keep_root = os.environ.get(keep_env_var, "").strip().lower() in {"1", "true", "yes"}
    success = False
    try:
        yield root
        success = True
    finally:
        if success and not keep_root:
            cleanup_runner_test_residue_for_run_root(repo_root, root)
            shutil.rmtree(root, ignore_errors=True)
        elif keep_root:
            print(f"[debug] kept temp_root={root}")
