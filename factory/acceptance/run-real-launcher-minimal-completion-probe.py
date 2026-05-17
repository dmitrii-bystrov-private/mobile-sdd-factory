#!/usr/bin/env python3
"""Probe minimal terminal completion from a real launcher-backed Claude session."""

from __future__ import annotations

import os
import pty
import select
import subprocess
import time
from pathlib import Path

from backend.roles.launcher import RoleLauncherManager
from backend.roles.workspace import RoleWorkspaceManager


PROMPT = (
    "Read ROUTED_WORK.md in the current directory, read HYDRATION.json too if it exists, follow the routed instructions exactly, "
    "and reply only through the SDD_* protocol described in AGENTS.md."
)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    workdir_root = repo_root / "workdir"
    task_key = "IOS-ACCEPT-REAL-LAUNCHER-MINIMAL-COMPLETION-001"

    workspace_manager = RoleWorkspaceManager(
        runtime_root=workdir_root,
        repo_root=repo_root,
        workdir_root=workdir_root,
    )
    launcher_manager = RoleLauncherManager(
        repo_root=repo_root,
        workdir_root=workdir_root,
        launcher_command=["auto"],
    )
    workspace = workspace_manager.ensure_role_workspace(task_key, "implementer")
    launcher_manager.ensure_launch_plan(task_key=task_key, workspace=workspace)

    routed_work_path = workspace.directory / "ROUTED_WORK.md"
    routed_work_path.write_text(
        'Reply with exactly one line:\n'
        'SDD_OUTPUT: {"output_type":"completed","payload":{"summary":"ok"}}\n'
    )

    master_fd, slave_fd = pty.openpty()
    process = subprocess.Popen(
        [str(workspace.directory / "launch-role.sh")],
        cwd=workspace.directory,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
    )
    os.close(slave_fd)
    os.set_blocking(master_fd, False)

    output = ""
    trusted = False
    sent = False
    start = time.time()
    try:
        while time.time() - start < 45.0:
            ready, _, _ = select.select([master_fd], [], [], 0.5)
            if not ready:
                continue
            try:
                data = os.read(master_fd, 65536)
            except BlockingIOError:
                continue
            if not data:
                break
            chunk = data.decode(errors="replace")
            output += chunk
            normalized = output.lower()
            if not trusted and "quick safety check" in normalized and "trust this folder" in normalized:
                os.write(master_fd, b"1\n")
                trusted = True
            if not sent and ("✻" in output or "auto mode on" in normalized or "❯" in output):
                os.write(master_fd, PROMPT.encode())
                time.sleep(0.25)
                os.write(master_fd, b"\r")
                sent = True
            if "SDD_OUTPUT:" in output:
                break
        assert "SDD_OUTPUT:" in output, output[-12000:]
        print("Real launcher minimal completion probe passed.")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        os.close(master_fd)


if __name__ == "__main__":
    main()
