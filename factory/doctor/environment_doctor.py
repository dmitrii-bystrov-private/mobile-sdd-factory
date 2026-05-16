#!/usr/bin/env python3
"""Baseline environment doctor for the SDD Factory."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import sys
from typing import Callable


CheckStatus = str
WhichFunc = Callable[[str], str | None]
CommandRunner = Callable[[list[str]], tuple[int, str]]


@dataclass(frozen=True)
class CheckResult:
    id: str
    category: str
    label: str
    required: bool
    status: CheckStatus
    details: str
    value: str | None = None
    source: str | None = None
    hint: str | None = None


def _load_dotenv(dotenv_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not dotenv_path.is_file():
        return values
    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip("'").strip('"')
    return values


def _load_enabled_mcp_servers(repo_root: Path) -> tuple[set[str], list[str]]:
    server_names: set[str] = set()
    sources: list[str] = []
    for candidate in (
        repo_root / ".claude" / "settings.json",
        repo_root / ".claude" / "settings.local.json",
    ):
        if not candidate.is_file():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for server_name in payload.get("enabledMcpjsonServers", []):
            if isinstance(server_name, str):
                server_names.add(server_name)
        sources.append(str(candidate.relative_to(repo_root)))
    return server_names, sources


def _run_command(command: list[str]) -> tuple[int, str]:
    completed = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    return completed.returncode, completed.stdout.strip()


def _path_check(
    *,
    variable_name: str,
    label: str,
    required: bool,
    env: dict[str, str],
    dotenv: dict[str, str],
) -> CheckResult:
    if variable_name in env and env[variable_name]:
        value = env[variable_name]
        source = "process env"
    elif variable_name in dotenv and dotenv[variable_name]:
        value = dotenv[variable_name]
        source = ".claude/.env"
    else:
        return CheckResult(
            id=f"env.{variable_name}",
            category="environment",
            label=label,
            required=required,
            status="missing",
            details=f"{variable_name} is not set.",
            hint=f"Set {variable_name} in your shell or .claude/.env.",
        )

    path = Path(value).expanduser()
    if path.is_dir():
        return CheckResult(
            id=f"env.{variable_name}",
            category="environment",
            label=label,
            required=required,
            status="ok",
            details=f"{variable_name} points to an existing directory.",
            value=str(path),
            source=source,
        )
    return CheckResult(
        id=f"env.{variable_name}",
        category="environment",
        label=label,
        required=required,
        status="invalid",
        details=f"{variable_name} does not point to an existing directory.",
        value=str(path),
        source=source,
        hint=f"Create or correct the directory referenced by {variable_name}.",
    )


def _command_presence_check(
    *,
    command_name: str,
    label: str,
    required: bool,
    which_func: WhichFunc,
) -> CheckResult:
    command_path = which_func(command_name)
    if command_path:
        return CheckResult(
            id=f"cli.{command_name}",
            category="cli",
            label=label,
            required=required,
            status="ok",
            details=f"{command_name} is installed.",
            value=command_path,
        )
    return CheckResult(
        id=f"cli.{command_name}",
        category="cli",
        label=label,
        required=required,
        status="missing",
        details=f"{command_name} is not installed or not on PATH.",
        hint=f"Install {command_name} and ensure it is available on PATH.",
    )


def _runner_presence_check(which_func: WhichFunc) -> CheckResult:
    available = [name for name in ("claude", "codex") if which_func(name)]
    if available:
        return CheckResult(
            id="runner.any",
            category="runtime",
            label="At least one live role runner",
            required=True,
            status="ok",
            details=f"Available runners: {', '.join(available)}.",
            value=", ".join(available),
        )
    return CheckResult(
        id="runner.any",
        category="runtime",
        label="At least one live role runner",
        required=True,
        status="missing",
        details="Neither claude nor codex is available on PATH.",
        hint="Install Claude Code or Codex CLI.",
    )


def _auth_check(
    *,
    check_id: str,
    label: str,
    required: bool,
    command_name: str,
    command: list[str],
    which_func: WhichFunc,
    command_runner: CommandRunner,
    success_predicate: Callable[[str], bool],
    success_formatter: Callable[[str], str] | None,
    hint: str,
) -> CheckResult:
    if not which_func(command_name):
        return CheckResult(
            id=check_id,
            category="auth",
            label=label,
            required=required,
            status="unavailable",
            details=f"{command_name} is not installed, so auth could not be checked.",
            hint=hint,
        )

    return_code, output = command_runner(command)
    normalized = output.lower()
    if return_code == 0 and success_predicate(output):
        if success_formatter is None:
            details = output.splitlines()[0] if output else f"{command_name} auth looks healthy."
        else:
            details = success_formatter(output)
        return CheckResult(
            id=check_id,
            category="auth",
            label=label,
            required=required,
            status="ok",
            details=details,
        )
    if "unauthor" in normalized or "not logged in" in normalized or "login" in normalized:
        status = "unauthorized"
    else:
        status = "invalid"
    return CheckResult(
        id=check_id,
        category="auth",
        label=label,
        required=required,
        status=status,
        details=output or f"{command_name} auth check failed.",
        hint=hint,
    )


def _any_runner_auth_check(
    claude_auth: CheckResult,
    codex_auth: CheckResult,
) -> CheckResult:
    good = [item.label for item in (claude_auth, codex_auth) if item.status == "ok"]
    if good:
        return CheckResult(
            id="auth.runner_any",
            category="auth",
            label="At least one live role runner authenticated",
            required=True,
            status="ok",
            details=f"Authenticated runners: {', '.join(good)}.",
        )
    statuses = ", ".join(
        f"{item.label}={item.status}"
        for item in (claude_auth, codex_auth)
        if item.status != "unavailable"
    )
    if not statuses:
        statuses = "no runner auth checks available"
    return CheckResult(
        id="auth.runner_any",
        category="auth",
        label="At least one live role runner authenticated",
        required=True,
        status="unauthorized",
        details=statuses,
        hint="Authenticate Claude Code or Codex before running live launcher-backed roles.",
    )


def _format_claude_auth(output: str) -> str:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return output.splitlines()[0] if output else "Claude auth looks healthy."
    email = payload.get("email")
    auth_method = payload.get("authMethod")
    if email and auth_method:
        return f"Logged in as {email} via {auth_method}."
    if email:
        return f"Logged in as {email}."
    return "Claude auth looks healthy."


def _format_glab_auth(output: str) -> str:
    for line in output.splitlines():
        stripped = line.strip()
        if "Logged in to" in stripped:
            return stripped
    return output.splitlines()[0] if output else "glab auth looks healthy."


def _mcp_server_check(
    *,
    server_name: str,
    required: bool,
    enabled_servers: set[str],
    sources: list[str],
) -> CheckResult:
    if server_name in enabled_servers:
        return CheckResult(
            id=f"mcp.{server_name}",
            category="mcp",
            label=f"MCP server {server_name}",
            required=required,
            status="ok",
            details=f"{server_name} is enabled in Claude settings.",
            source=", ".join(sources) if sources else None,
        )
    return CheckResult(
        id=f"mcp.{server_name}",
        category="mcp",
        label=f"MCP server {server_name}",
        required=required,
        status="missing",
        details=f"{server_name} is not enabled in Claude settings.",
        source=", ".join(sources) if sources else None,
        hint=f"Add {server_name} to enabledMcpjsonServers in your Claude settings.",
    )


def _tmux_check(which_func: WhichFunc) -> CheckResult:
    path = which_func("tmux")
    if path:
        return CheckResult(
            id="runtime.tmux",
            category="runtime",
            label="tmux host backend",
            required=False,
            status="ok",
            details="tmux is installed.",
            value=path,
        )
    return CheckResult(
        id="runtime.tmux",
        category="runtime",
        label="tmux host backend",
        required=False,
        status="missing",
        details="tmux is not installed; the system will fall back to local process hosting.",
        hint="Install tmux if you want tmux-backed persistent sessions.",
    )


def build_report(
    *,
    repo_root: Path,
    env: dict[str, str] | None = None,
    which_func: WhichFunc = shutil.which,
    command_runner: CommandRunner = _run_command,
) -> dict[str, object]:
    active_env = dict(os.environ) if env is None else dict(env)
    dotenv = _load_dotenv(repo_root / ".claude" / ".env")
    enabled_mcp_servers, mcp_sources = _load_enabled_mcp_servers(repo_root)

    checks = [
        _path_check(
            variable_name="SDD_WORKDIR",
            label="Task workdir root",
            required=True,
            env=active_env,
            dotenv=dotenv,
        ),
        _path_check(
            variable_name="IOS_DIR",
            label="iOS project root",
            required=True,
            env=active_env,
            dotenv=dotenv,
        ),
        _path_check(
            variable_name="ANDROID_DIR",
            label="Android project root",
            required=True,
            env=active_env,
            dotenv=dotenv,
        ),
        _command_presence_check(
            command_name="python3",
            label="Python 3",
            required=True,
            which_func=which_func,
        ),
        _command_presence_check(
            command_name="jq",
            label="jq",
            required=True,
            which_func=which_func,
        ),
        _command_presence_check(
            command_name="acli",
            label="Atlassian CLI",
            required=True,
            which_func=which_func,
        ),
        _command_presence_check(
            command_name="glab",
            label="GitLab CLI",
            required=True,
            which_func=which_func,
        ),
        _command_presence_check(
            command_name="claude",
            label="Claude Code",
            required=False,
            which_func=which_func,
        ),
        _command_presence_check(
            command_name="codex",
            label="Codex CLI",
            required=False,
            which_func=which_func,
        ),
        _runner_presence_check(which_func),
        _tmux_check(which_func),
        _mcp_server_check(
            server_name="ios-rag",
            required=True,
            enabled_servers=enabled_mcp_servers,
            sources=mcp_sources,
        ),
        _mcp_server_check(
            server_name="android-rag",
            required=True,
            enabled_servers=enabled_mcp_servers,
            sources=mcp_sources,
        ),
        _mcp_server_check(
            server_name="frontend-rag",
            required=False,
            enabled_servers=enabled_mcp_servers,
            sources=mcp_sources,
        ),
    ]

    claude_auth = _auth_check(
        check_id="auth.claude",
        label="Claude Code auth",
        required=False,
        command_name="claude",
        command=["claude", "auth", "status"],
        which_func=which_func,
        command_runner=command_runner,
        success_predicate=lambda output: '"loggedIn": true' in output or '"loggedIn":true' in output,
        success_formatter=_format_claude_auth,
        hint="Run `claude auth login` if you want Claude-backed live roles.",
    )
    codex_auth = _auth_check(
        check_id="auth.codex",
        label="Codex CLI auth",
        required=False,
        command_name="codex",
        command=["codex", "login", "status"],
        which_func=which_func,
        command_runner=command_runner,
        success_predicate=lambda output: "logged in" in output.lower(),
        success_formatter=None,
        hint="Run `codex login` if you want Codex-backed live roles.",
    )
    checks.extend(
        [
            _auth_check(
                check_id="auth.acli_jira",
                label="Atlassian CLI Jira auth",
                required=True,
                command_name="acli",
                command=["acli", "jira", "auth", "status"],
                which_func=which_func,
                command_runner=command_runner,
                success_predicate=lambda output: "authenticated" in output.lower(),
                success_formatter=None,
                hint="Run `acli jira auth login`.",
            ),
            _auth_check(
                check_id="auth.glab",
                label="GitLab CLI auth",
                required=True,
                command_name="glab",
                command=["glab", "auth", "status"],
                which_func=which_func,
                command_runner=command_runner,
                success_predicate=lambda output: "logged in" in output.lower(),
                success_formatter=_format_glab_auth,
                hint="Run `glab auth login`.",
            ),
            claude_auth,
            codex_auth,
            _any_runner_auth_check(claude_auth, codex_auth),
        ]
    )

    required_checks = [check for check in checks if check.required]
    required_failures = [check for check in required_checks if check.status != "ok"]
    optional_warnings = [check for check in checks if not check.required and check.status != "ok"]
    overall = "ok" if not required_failures else "warn"

    return {
        "overall_status": overall,
        "repo_root": str(repo_root),
        "required_ok": len(required_checks) - len(required_failures),
        "required_total": len(required_checks),
        "optional_warnings": len(optional_warnings),
        "checks": [asdict(check) for check in checks],
    }


def format_human_report(report: dict[str, object]) -> str:
    lines = [
        "SDD Factory Environment Doctor",
        f"Overall status: {report['overall_status']}",
        f"Required checks: {report['required_ok']}/{report['required_total']} OK",
    ]
    optional_warnings = int(report["optional_warnings"])
    if optional_warnings:
        lines.append(f"Optional warnings: {optional_warnings}")

    category_order = ("environment", "cli", "runtime", "mcp", "auth")
    checks = report["checks"]
    for category in category_order:
        category_checks = [item for item in checks if item["category"] == category]
        if not category_checks:
            continue
        lines.append("")
        lines.append(f"{category.upper()}:")
        for item in category_checks:
            prefix = "OK" if item["status"] == "ok" else "WARN"
            line = f"- [{prefix}] {item['label']}: {item['details']}"
            if item.get("value"):
                line += f" ({item['value']})"
            lines.append(line)
            if item.get("hint") and item["status"] != "ok":
                lines.append(f"  hint: {item['hint']}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    json_mode = "--json" in argv
    repo_root = Path(__file__).resolve().parents[2]
    report = build_report(repo_root=repo_root)
    if json_mode:
        json.dump(report, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(format_human_report(report))
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
