"""Manage local agent workspace trust entries for temporary role workspaces."""

from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile


_ROLE_WORKSPACE_SEGMENT = "/runtime/role-workspaces/"
_CODEX_PROJECT_HEADER_RE = re.compile(r'^\[projects\."((?:[^"\\]|\\.)*)"\]\s*$')


def trust_role_workspace(
    workspace_dir: Path,
    *,
    runner: str,
    home: Path | None = None,
) -> list[str]:
    """Persist trust for a role workspace before launching an interactive agent."""

    normalized_runner = runner.strip().lower()
    target_home = home or Path.home()
    workspace = str(workspace_dir.resolve())
    updated: list[str] = []

    if normalized_runner == "claude":
        if _trust_claude_workspace(target_home, workspace):
            updated.append(f"{target_home / '.claude.json'}:{workspace}")
    if normalized_runner == "codex":
        if _trust_codex_workspace(target_home, workspace):
            updated.append(f"{target_home / '.codex' / 'config.toml'}:{workspace}")
    return updated


def remove_task_role_workspace_trust(
    task_key: str,
    *,
    workdir_root: Path,
    home: Path | None = None,
) -> list[str]:
    """Remove agent trust entries for temporary role workspaces of one task."""

    target_home = home or Path.home()
    prefix = str((workdir_root / task_key / "runtime" / "role-workspaces").resolve())
    removed: list[str] = []

    removed.extend(_remove_claude_project_entries(target_home, lambda path: _is_path_under(path, prefix)))
    removed.extend(_remove_codex_project_entries(target_home, lambda path: _is_path_under(path, prefix)))
    return removed


def remove_stale_role_workspace_trust(
    *,
    workdir_root: Path,
    home: Path | None = None,
) -> list[str]:
    """Remove trust entries for temporary role workspaces that no longer exist."""

    target_home = home or Path.home()
    resolved_workdir = str(workdir_root.resolve())

    def stale_role_workspace(path: str) -> bool:
        return (
            path.startswith(resolved_workdir + "/")
            and _ROLE_WORKSPACE_SEGMENT in path
            and not Path(path).exists()
        )

    removed: list[str] = []
    removed.extend(_remove_claude_project_entries(target_home, stale_role_workspace))
    removed.extend(_remove_codex_project_entries(target_home, stale_role_workspace))
    return removed


def _trust_claude_workspace(home: Path, workspace: str) -> bool:
    config_path = home / ".claude.json"
    payload = _read_json_object(config_path)
    projects = payload.setdefault("projects", {})
    if not isinstance(projects, dict):
        projects = {}
        payload["projects"] = projects

    project_payload = projects.get(workspace)
    if not isinstance(project_payload, dict):
        project_payload = {}
        projects[workspace] = project_payload

    if project_payload.get("hasTrustDialogAccepted") is True:
        return False
    project_payload["hasTrustDialogAccepted"] = True
    _write_json(config_path, payload)
    return True


def _trust_codex_workspace(home: Path, workspace: str) -> bool:
    config_path = home / ".codex" / "config.toml"
    text = config_path.read_text() if config_path.is_file() else ""
    header = f'[projects.{_toml_quote(workspace)}]'
    lines = text.splitlines()
    start, end = _find_codex_project_section(lines, workspace)

    if start is None:
        block = [header, 'trust_level = "trusted"']
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(block)
        _write_text(config_path, "\n".join(lines) + "\n")
        return True

    for index in range(start + 1, end):
        if lines[index].strip().startswith("trust_level"):
            if lines[index].strip() == 'trust_level = "trusted"':
                return False
            lines[index] = 'trust_level = "trusted"'
            _write_text(config_path, "\n".join(lines) + "\n")
            return True

    lines.insert(end, 'trust_level = "trusted"')
    _write_text(config_path, "\n".join(lines) + "\n")
    return True


def _remove_claude_project_entries(home: Path, predicate) -> list[str]:
    config_path = home / ".claude.json"
    if not config_path.is_file():
        return []
    payload = _read_json_object(config_path)
    projects = payload.get("projects")
    if not isinstance(projects, dict):
        return []

    removed = [path for path in projects if predicate(path)]
    if not removed:
        return []
    for path in removed:
        projects.pop(path, None)
    _write_json(config_path, payload)
    return [f"{config_path}:{path}" for path in removed]


def _remove_codex_project_entries(home: Path, predicate) -> list[str]:
    config_path = home / ".codex" / "config.toml"
    if not config_path.is_file():
        return []

    lines = config_path.read_text().splitlines()
    kept: list[str] = []
    removed: list[str] = []
    index = 0
    changed = False
    while index < len(lines):
        match = _CODEX_PROJECT_HEADER_RE.match(lines[index])
        if match is None:
            kept.append(lines[index])
            index += 1
            continue

        path = _toml_unquote(match.group(1))
        section_end = index + 1
        while section_end < len(lines) and not lines[section_end].startswith("["):
            section_end += 1

        if predicate(path):
            removed.append(path)
            changed = True
        else:
            kept.extend(lines[index:section_end])
        index = section_end

    if changed:
        _write_text(config_path, "\n".join(kept).rstrip() + "\n")
    return [f"{config_path}:{path}" for path in removed]


def _find_codex_project_section(lines: list[str], workspace: str) -> tuple[int | None, int]:
    for index, line in enumerate(lines):
        match = _CODEX_PROJECT_HEADER_RE.match(line)
        if match is None or _toml_unquote(match.group(1)) != workspace:
            continue
        end = index + 1
        while end < len(lines) and not lines[end].startswith("["):
            end += 1
        return index, end
    return None, len(lines)


def _read_json_object(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict) -> None:
    _write_text(path, json.dumps(payload, indent=2) + "\n")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def _toml_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _toml_unquote(value: str) -> str:
    return value.replace('\\"', '"').replace("\\\\", "\\")


def _is_path_under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")
