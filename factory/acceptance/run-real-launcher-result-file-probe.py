#!/usr/bin/env python3
"""Probe RESULT.json creation by a real launcher-backed Claude session."""

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
    "and reply only through the file protocol described there."
)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    workdir_root = repo_root / "workdir"
    task_key = "IOS-ACCEPT-REAL-LAUNCHER-RESULT-FILE-001"

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

    result_path = workspace.directory / "RESULT.json"
    routed_work_path = workspace.directory / "ROUTED_WORK.md"
    result_path.unlink(missing_ok=True)
    routed_work_path.write_text(
        "Write RESULT.json in the current directory with exactly this JSON object:\n"
        '{"output_type":"completed","payload":{"summary":"ok-from-result-file"}}\n'
        "Do not print SDD_OUTPUT for this task.\n"
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
            if ready:
                try:
                    data = os.read(master_fd, 65536)
                except BlockingIOError:
                    data = b""
                if data:
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
            if result_path.is_file():
                break

        assert result_path.is_file(), output[-12000:]
        result_text = result_path.read_text().strip()
        assert '"output_type":"completed"' in result_text.replace(" ", "")
        assert "ok-from-result-file" in result_text
        assert "SDD_OUTPUT:" not in output
        print("Real launcher result file probe passed.")
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
