"""Role launcher contract for persistent runtime roles."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import shlex

from backend.roles.workspace import RoleWorkspace


@dataclass(frozen=True, slots=True)
class RoleLaunchPlan:
    role_name: str
    workspace_dir: Path
    launcher_script: Path
    command: list[str]


def _shell_escape(value: str) -> str:
    return shlex.quote(value)


def _role_lifecycle_mode(role_name: str) -> str:
    if role_name in {
        "story-spec-worker",
        "proposal-context-worker",
        "requirements-clarifier-worker",
    }:
        return "one-shot"
    return "persistent"


class RoleLauncherManager:
    """Create explicit launcher scripts for persistent role runtimes."""

    def __init__(self, repo_root: Path, launcher_command: list[str] | None = None) -> None:
        self.repo_root = repo_root
        if launcher_command is None or launcher_command == ["auto"]:
            self.launcher_command = [str(repo_root / "scripts" / "run-role-agent.sh")]
        else:
            self.launcher_command = list(launcher_command)

    def ensure_launch_plan(
        self,
        *,
        task_key: str,
        workspace: RoleWorkspace,
    ) -> RoleLaunchPlan:
        launcher_script = workspace.directory / "launch-role.sh"
        launcher_script.write_text(
            self._build_launcher_script(
                task_key=task_key,
                role_name=workspace.role_name,
                workspace=workspace,
            )
        )
        launcher_script.chmod(0o755)
        return RoleLaunchPlan(
            role_name=workspace.role_name,
            workspace_dir=workspace.directory,
            launcher_script=launcher_script,
            command=[str(launcher_script)],
        )

    def _build_launcher_script(
        self,
        *,
        task_key: str,
        role_name: str,
        workspace: RoleWorkspace,
    ) -> str:
        launcher_exec = " ".join(_shell_escape(part) for part in self.launcher_command)
        return "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                "",
                f'export SDD_FACTORY_TASK_KEY={_shell_escape(task_key)}',
                f'export SDD_FACTORY_ROLE_NAME={_shell_escape(role_name)}',
                f'export SDD_FACTORY_ROLE_WORKSPACE={_shell_escape(str(workspace.directory))}',
                f'export SDD_FACTORY_ROLE_AGENTS_MD={_shell_escape(str(workspace.agents_path))}',
                f'export SDD_FACTORY_REPO_ROOT={_shell_escape(str(self.repo_root))}',
                f'export SDD_FACTORY_WORKDIR_ROOT={_shell_escape(str(self.repo_root / "workdir"))}',
                f'export SDD_FACTORY_ROLE_LIFECYCLE={_shell_escape(_role_lifecycle_mode(role_name))}',
                f"cd {_shell_escape(str(workspace.directory))}",
                'printf "SDD_FACTORY_ROLE_LAUNCHER_READY role=%s task=%s lifecycle=%s\\n" "$SDD_FACTORY_ROLE_NAME" "$SDD_FACTORY_TASK_KEY" "$SDD_FACTORY_ROLE_LIFECYCLE"',
                f"exec {launcher_exec}",
                "",
            ]
        )
