#!/usr/bin/env python3
"""Helpers for project-scoped acceptance run roots."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import os
import shutil
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
    root = runtime_root(repo_root) / "tmux-sockets"
    root.mkdir(parents=True, exist_ok=True)
    return root


def create_run_root(repo_root: Path, prefix: str) -> Path:
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
            shutil.rmtree(root, ignore_errors=True)
        elif keep_root:
            print(f"[debug] kept temp_root={root}")
