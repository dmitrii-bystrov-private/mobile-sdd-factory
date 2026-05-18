"""Role launcher contract for persistent runtime roles."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
import re
import shlex

from backend.role_runtime_config import resolve_role_mcp_servers
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
        "acceptance-criteria-worker",
        "constraints-worker",
        "spec-verifier-worker",
        "task-decomposer-worker",
        "code-scout",
        "mr-comments-analyst-worker",
        "doc-harvest-worker",
    }:
        return "one-shot"
    return "persistent"


class RoleLauncherManager:
    """Create explicit launcher scripts for persistent role runtimes."""

    def __init__(
        self,
        repo_root: Path,
        workdir_root: Path | None = None,
        launcher_command: list[str] | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.workdir_root = workdir_root or (repo_root / "workdir")
        if launcher_command is None or launcher_command == ["auto"]:
            self.launcher_command = [str(repo_root / "factory" / "scripts" / "run-role-agent.sh")]
        else:
            self.launcher_command = list(launcher_command)

    def ensure_launch_plan(
        self,
        *,
        task_key: str,
        workspace: RoleWorkspace,
        role_config: dict[str, str] | None = None,
        resume_mode: str | None = None,
    ) -> RoleLaunchPlan:
        claude_runtime_files = self._ensure_claude_runtime_files(
            task_key=task_key,
            workspace=workspace,
            role_config=role_config,
        )
        launcher_script = workspace.directory / "launch-role.sh"
        launcher_script.write_text(
            self._build_launcher_script(
                task_key=task_key,
                role_name=workspace.role_name,
                workspace=workspace,
                role_config=role_config,
                resume_mode=resume_mode,
                claude_runtime_files=claude_runtime_files,
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
        role_config: dict[str, str] | None = None,
        resume_mode: str | None = None,
        claude_runtime_files: dict[str, Path] | None = None,
    ) -> str:
        launcher_exec = " ".join(_shell_escape(part) for part in self.launcher_command)
        runner = (role_config or {}).get("runner", "")
        model = (role_config or {}).get("model", "")
        effort = (role_config or {}).get("effort", "")
        claude_settings = str((claude_runtime_files or {}).get("settings", ""))
        claude_mcp_config = str((claude_runtime_files or {}).get("mcp_config", ""))
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
                f'export SDD_FACTORY_WORKDIR_ROOT={_shell_escape(str(self.workdir_root))}',
                f'export SDD_FACTORY_TASK_REPO_ROOT={_shell_escape(str(self.workdir_root / task_key / "repo"))}',
                f'export SDD_FACTORY_ROLE_LIFECYCLE={_shell_escape(_role_lifecycle_mode(role_name))}',
                f'export SDD_FACTORY_ROLE_RUNNER={_shell_escape(runner)}',
                f'export SDD_FACTORY_ROLE_MODEL={_shell_escape(model)}',
                f'export SDD_FACTORY_ROLE_EFFORT={_shell_escape(effort)}',
                f'export SDD_FACTORY_ROLE_RESUME_MODE={_shell_escape(resume_mode or "")}',
                f'export SDD_FACTORY_CLAUDE_SETTINGS={_shell_escape(claude_settings)}',
                f'export SDD_FACTORY_CLAUDE_MCP_CONFIG={_shell_escape(claude_mcp_config)}',
                f"cd {_shell_escape(str(workspace.directory))}",
                'printf "SDD_FACTORY_ROLE_LAUNCHER_READY role=%s task=%s lifecycle=%s\\n" "$SDD_FACTORY_ROLE_NAME" "$SDD_FACTORY_TASK_KEY" "$SDD_FACTORY_ROLE_LIFECYCLE"',
                f"exec {launcher_exec}",
                "",
            ]
        )

    def _ensure_claude_runtime_files(
        self,
        *,
        task_key: str,
        workspace: RoleWorkspace,
        role_config: dict[str, str] | None,
    ) -> dict[str, Path]:
        runner = (role_config or {}).get("runner")
        if runner != "claude":
            return {}

        allowed_servers = resolve_role_mcp_servers(
            repo_root=self.repo_root,
            role_name=workspace.role_name,
            runner=runner,
        )
        settings_payload = self._build_scoped_claude_settings(
            task_key=task_key,
            allowed_servers=allowed_servers,
        )
        mcp_payload = self._build_scoped_mcp_config(
            task_key=task_key,
            allowed_servers=allowed_servers,
        )

        settings_path = workspace.directory / "claude.settings.role.json"
        settings_path.write_text(json.dumps(settings_payload, indent=2, sort_keys=True) + "\n")
        mcp_config_path = workspace.directory / "claude.mcp.role.json"
        mcp_config_path.write_text(json.dumps(mcp_payload, indent=2, sort_keys=True) + "\n")
        return {
            "settings": settings_path,
            "mcp_config": mcp_config_path,
        }

    def _build_scoped_claude_settings(
        self,
        *,
        task_key: str,
        allowed_servers: list[str],
    ) -> dict:
        payload = self._load_json_file(self._resolve_settings_source(task_key)) or {}
        enabled_servers = list(allowed_servers)
        payload["enabledMcpjsonServers"] = enabled_servers

        permissions = payload.get("permissions")
        if isinstance(permissions, dict):
            allow_entries = permissions.get("allow")
            if isinstance(allow_entries, list):
                permissions["allow"] = [
                    entry
                    for entry in allow_entries
                    if self._is_allowed_tool_entry(entry, enabled_servers)
                ]
        return payload

    def _build_scoped_mcp_config(
        self,
        *,
        task_key: str,
        allowed_servers: list[str],
    ) -> dict:
        payload = self._load_json_file(self._resolve_mcp_source(task_key)) or {}
        servers = payload.get("mcpServers")
        if not isinstance(servers, dict):
            return {"mcpServers": {}}
        return {
            "mcpServers": {
                server_name: server_config
                for server_name, server_config in servers.items()
                if server_name in allowed_servers
            }
        }

    def _resolve_settings_source(self, task_key: str) -> Path | None:
        task_repo_root = self.workdir_root / task_key / "repo"
        task_candidates = [
            task_repo_root / ".claude" / "settings.local.json",
            task_repo_root / ".claude" / "settings.json",
        ]
        repo_candidates = [
            self.repo_root / ".claude" / "settings.local.json",
            self.repo_root / ".claude" / "settings.json",
        ]
        for candidate in [*task_candidates, *repo_candidates]:
            if candidate.is_file():
                return candidate
        return None

    def _resolve_mcp_source(self, task_key: str) -> Path | None:
        task_repo_root = self.workdir_root / task_key / "repo"
        candidates = [
            task_repo_root / ".mcp.json",
            self.repo_root / ".mcp.json",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None

    @staticmethod
    def _load_json_file(path: Path | None) -> dict | None:
        if path is None or not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _is_allowed_tool_entry(entry: object, allowed_servers: list[str]) -> bool:
        if not isinstance(entry, str):
            return True
        match = re.match(r"mcp__([^_]+(?:-[^_]+)*)__", entry)
        if match is None:
            return True
        return match.group(1) in set(allowed_servers)
