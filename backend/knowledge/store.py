"""Repo-visible knowledge item storage and matching."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re


SOURCE_DIRECTORY = {
    "review_feedback": "review",
    "session_insight": "session-insights",
}


@dataclass(frozen=True, slots=True)
class KnowledgeItem:
    id: str
    title: str
    source_type: str
    platform: str
    workflow_profiles: tuple[str, ...]
    task_key: str
    guidance: str
    scope: str | None
    source_summary: str | None
    created_at: str
    path: Path


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "knowledge-item"


def _parse_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    if not raw.startswith("---\n"):
        return {}, raw
    end_index = raw.find("\n---\n", 4)
    if end_index == -1:
        return {}, raw
    frontmatter_block = raw[4:end_index]
    body = raw[end_index + 5 :]
    metadata: dict[str, str] = {}
    for line in frontmatter_block.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()
    return metadata, body


def _format_item_markdown(
    *,
    item_id: str,
    title: str,
    source_type: str,
    platform: str,
    workflow_profiles: list[str],
    task_key: str,
    scope: str | None,
    source_summary: str | None,
    created_at: str,
    guidance: str,
) -> str:
    metadata_lines = [
        "---",
        f"id: {item_id}",
        f"title: {title}",
        f"source_type: {source_type}",
        f"platform: {platform}",
        f"workflow_profiles: {', '.join(workflow_profiles)}",
        f"task_key: {task_key}",
        f"created_at: {created_at}",
    ]
    if scope:
        metadata_lines.append(f"scope: {scope}")
    if source_summary:
        metadata_lines.append(f"source_summary: {source_summary}")
    metadata_lines.append("---")
    metadata = "\n".join(metadata_lines)
    return (
        f"{metadata}\n\n"
        "## Guidance\n\n"
        f"{guidance.strip()}\n"
    )


class KnowledgeStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def ensure_structure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        for directory_name in SOURCE_DIRECTORY.values():
            (self.root / directory_name).mkdir(parents=True, exist_ok=True)

    def create_item(
        self,
        *,
        title: str,
        source_type: str,
        platform: str,
        workflow_profiles: list[str],
        task_key: str,
        guidance: str,
        scope: str | None = None,
        source_summary: str | None = None,
    ) -> KnowledgeItem:
        if source_type not in SOURCE_DIRECTORY:
            raise ValueError(f"Unsupported knowledge source type: {source_type}")
        self.ensure_structure()
        created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        slug = _slugify(title)
        item_id = f"{platform}-{workflow_profiles[0]}-{slug}"
        target_dir = self.root / SOURCE_DIRECTORY[source_type]
        filename = f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{slug}.md"
        path = target_dir / filename
        path.write_text(
            _format_item_markdown(
                item_id=item_id,
                title=title,
                source_type=source_type,
                platform=platform,
                workflow_profiles=workflow_profiles,
                task_key=task_key,
                scope=scope,
                source_summary=source_summary,
                created_at=created_at,
                guidance=guidance,
            )
        )
        return self.load_item(path)

    def load_item(self, path: Path) -> KnowledgeItem:
        raw = path.read_text()
        metadata, body = _parse_frontmatter(raw)
        profiles = tuple(
            value.strip()
            for value in metadata.get("workflow_profiles", "").split(",")
            if value.strip()
        )
        guidance = body.replace("## Guidance", "", 1).strip()
        return KnowledgeItem(
            id=metadata.get("id", path.stem),
            title=metadata.get("title", path.stem),
            source_type=metadata.get("source_type", "session_insight"),
            platform=metadata.get("platform", "unknown"),
            workflow_profiles=profiles,
            task_key=metadata.get("task_key", ""),
            guidance=guidance,
            scope=metadata.get("scope") or None,
            source_summary=metadata.get("source_summary") or None,
            created_at=metadata.get("created_at", ""),
            path=path,
        )

    def list_items(self) -> list[KnowledgeItem]:
        if not self.root.exists():
            return []
        items: list[KnowledgeItem] = []
        for path in sorted(self.root.rglob("*.md")):
            if path.name == "README.md":
                continue
            items.append(self.load_item(path))
        return items

    def match(
        self,
        *,
        platform: str,
        workflow_profile: str,
        limit: int = 3,
    ) -> list[KnowledgeItem]:
        matches = [
            item
            for item in self.list_items()
            if item.platform == platform and workflow_profile in item.workflow_profiles
        ]
        return matches[:limit]
