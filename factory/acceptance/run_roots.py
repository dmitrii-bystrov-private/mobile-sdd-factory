#!/usr/bin/env python3
"""Helpers for project-scoped acceptance run roots."""

from __future__ import annotations

from contextlib import contextmanager
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


def create_run_root(repo_root: Path, prefix: str) -> Path:
    cleanup_stale_run_roots(repo_root)
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
