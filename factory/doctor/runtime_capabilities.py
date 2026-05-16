#!/usr/bin/env python3
"""Live runtime capability discovery for factory runners."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import json
import re
import shutil
import subprocess
from typing import Any, Callable


WhichFunc = Callable[[str], str | None]
CommandRunner = Callable[[list[str]], tuple[int, str]]

CLAUDE_MODEL_ALIASES: tuple[tuple[str, str], ...] = (
    ("default", "Default"),
    ("sonnet", "Sonnet"),
    ("opus", "Opus"),
    ("haiku", "Haiku"),
    ("sonnet[1m]", "Sonnet 1M"),
    ("opusplan", "Opus Plan"),
)


@dataclass(frozen=True)
class RuntimeModelCapability:
    id: str
    label: str
    supported_efforts: list[str]
    default_effort: str | None
    visibility: str
    supported_in_api: bool
    source: str


@dataclass(frozen=True)
class RunnerCapability:
    runner: str
    available: bool
    source: str
    path: str | None
    supports_custom_model: bool
    models: list[RuntimeModelCapability]


@dataclass(frozen=True)
class LegacyRoleDefault:
    role_name: str
    model: str | None
    effort: str | None
    mcp_servers: list[str]
    source: str


def _run_command(command: list[str]) -> tuple[int, str]:
    completed = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
        timeout=10,
    )
    return completed.returncode, completed.stdout.strip()


def _parse_claude_efforts(help_text: str) -> list[str]:
    match = re.search(r"--effort <level>.*?\(([^)]+)\)", help_text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ["low", "medium", "high", "xhigh", "max"]
    efforts = [value.strip() for value in match.group(1).split(",")]
    return [value for value in efforts if value]


def _build_claude_capability(
    *,
    which_func: WhichFunc,
    command_runner: CommandRunner,
) -> RunnerCapability:
    claude_path = which_func("claude")
    if claude_path is None:
        return RunnerCapability(
            runner="claude",
            available=False,
            source="local cli probe",
            path=None,
            supports_custom_model=True,
            models=[],
        )

    return_code, output = command_runner(["claude", "--help"])
    efforts = _parse_claude_efforts(output) if return_code == 0 else ["low", "medium", "high", "xhigh", "max"]
    models = [
        RuntimeModelCapability(
            id=model_id,
            label=label,
            supported_efforts=list(efforts),
            default_effort="medium" if "medium" in efforts else (efforts[0] if efforts else None),
            visibility="list",
            supported_in_api=True,
            source="anthropic alias catalog",
        )
        for model_id, label in CLAUDE_MODEL_ALIASES
    ]
    return RunnerCapability(
        runner="claude",
        available=True,
        source="local cli probe + curated alias catalog",
        path=claude_path,
        supports_custom_model=True,
        models=models,
    )


def _build_codex_capability(
    *,
    which_func: WhichFunc,
    command_runner: CommandRunner,
) -> RunnerCapability:
    codex_path = which_func("codex")
    if codex_path is None:
        return RunnerCapability(
            runner="codex",
            available=False,
            source="local cli probe",
            path=None,
            supports_custom_model=True,
            models=[],
        )

    return_code, output = command_runner(["codex", "debug", "models"])
    if return_code != 0:
        return RunnerCapability(
            runner="codex",
            available=True,
            source="local cli probe",
            path=codex_path,
            supports_custom_model=True,
            models=[],
        )

    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        payload = {}

    models: list[RuntimeModelCapability] = []
    for entry in payload.get("models", []):
        if entry.get("visibility", "list") == "hide":
            continue
        models.append(
            RuntimeModelCapability(
                id=entry.get("slug") or entry.get("id") or entry.get("name") or "unknown",
                label=entry.get("display_name") or entry.get("label") or entry.get("slug") or "unknown",
                supported_efforts=[
                    level.get("effort")
                    for level in entry.get("supported_reasoning_levels", [])
                    if isinstance(level, dict) and isinstance(level.get("effort"), str)
                ],
                default_effort=entry.get("default_reasoning_level"),
                visibility=entry.get("visibility", "list"),
                supported_in_api=bool(entry.get("supported_in_api", False)),
                source="codex debug models",
            )
        )

    return RunnerCapability(
        runner="codex",
        available=True,
        source="local cli probe + codex model catalog",
        path=codex_path,
        supports_custom_model=True,
        models=models,
    )


def _parse_agent_frontmatter(agent_path: Path) -> LegacyRoleDefault:
    in_frontmatter = False
    current_list_key: str | None = None
    model: str | None = None
    effort: str | None = None
    mcp_servers: list[str] = []

    for raw_line in agent_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if line.strip() == "---":
            if not in_frontmatter:
                in_frontmatter = True
                continue
            break
        if not in_frontmatter:
            continue
        stripped = line.strip()
        if current_list_key == "mcpServers" and stripped.startswith("- "):
            mcp_servers.append(stripped[2:].strip())
            continue
        current_list_key = None
        if stripped.startswith("model:"):
            value = stripped.split(":", 1)[1].strip()
            model = value or None
        elif stripped.startswith("effort:"):
            value = stripped.split(":", 1)[1].strip()
            effort = value or None
        elif stripped.startswith("mcpServers:"):
            value = stripped.split(":", 1)[1].strip()
            if value == "[]":
                mcp_servers = []
            else:
                current_list_key = "mcpServers"

    return LegacyRoleDefault(
        role_name=agent_path.stem,
        model=model,
        effort=effort,
        mcp_servers=mcp_servers,
        source=str(agent_path),
    )


def _build_legacy_role_defaults(repo_root: Path) -> list[LegacyRoleDefault]:
    agent_dir = repo_root / ".claude" / "agents"
    if not agent_dir.is_dir():
        return []
    return sorted(
        (_parse_agent_frontmatter(path) for path in agent_dir.glob("*.md")),
        key=lambda item: item.role_name,
    )


def build_runtime_capabilities(
    *,
    repo_root: Path,
    which_func: WhichFunc = shutil.which,
    command_runner: CommandRunner = _run_command,
) -> dict[str, Any]:
    runners = [
        _build_claude_capability(which_func=which_func, command_runner=command_runner),
        _build_codex_capability(which_func=which_func, command_runner=command_runner),
    ]
    available_runners = [runner.runner for runner in runners if runner.available]
    default_runner = "claude" if "claude" in available_runners else (available_runners[0] if available_runners else None)
    return {
        "available_runners": available_runners,
        "default_runner": default_runner,
        "runners": [asdict(runner) for runner in runners],
        "legacy_role_defaults": [asdict(item) for item in _build_legacy_role_defaults(repo_root)],
    }
