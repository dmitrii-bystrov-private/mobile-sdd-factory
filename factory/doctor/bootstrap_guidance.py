#!/usr/bin/env python3
"""Generate actionable setup guidance from the doctor report."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any


@dataclass(frozen=True)
class GuidanceItem:
    id: str
    label: str
    status: str
    details: str
    hint: str | None


def build_bootstrap_guidance(report: dict[str, Any]) -> dict[str, Any]:
    checks = report.get("checks", [])
    required_actions = [
        GuidanceItem(
            id=item["id"],
            label=item["label"],
            status=item["status"],
            details=item["details"],
            hint=item.get("hint"),
        )
        for item in checks
        if item.get("required") and item.get("status") != "ok"
    ]
    optional_actions = [
        GuidanceItem(
            id=item["id"],
            label=item["label"],
            status=item["status"],
            details=item["details"],
            hint=item.get("hint"),
        )
        for item in checks
        if not item.get("required") and item.get("status") != "ok"
    ]

    next_step = "Environment is ready."
    if required_actions:
        next_step = "Resolve required setup issues first."
    elif optional_actions:
        next_step = "Required setup is ready; optional improvements remain."

    return {
        "overall_status": report.get("overall_status", "warn"),
        "required_action_count": len(required_actions),
        "optional_action_count": len(optional_actions),
        "next_step": next_step,
        "required_actions": [item.__dict__ for item in required_actions],
        "optional_actions": [item.__dict__ for item in optional_actions],
    }


def format_bootstrap_guidance(guidance: dict[str, Any]) -> str:
    lines = [
        "SDD Factory Bootstrap Guidance",
        f"Overall doctor status: {guidance['overall_status']}",
        f"Next step: {guidance['next_step']}",
    ]

    required_actions = guidance["required_actions"]
    optional_actions = guidance["optional_actions"]

    if required_actions:
        lines.append("")
        lines.append("Required actions:")
        for item in required_actions:
            lines.append(f"- {item['label']} [{item['status']}]: {item['details']}")
            if item.get("hint"):
                lines.append(f"  do: {item['hint']}")

    if optional_actions:
        lines.append("")
        lines.append("Optional improvements:")
        for item in optional_actions:
            lines.append(f"- {item['label']} [{item['status']}]: {item['details']}")
            if item.get("hint"):
                lines.append(f"  do: {item['hint']}")

    if not required_actions and not optional_actions:
        lines.append("")
        lines.append("No setup actions are currently required.")

    return "\n".join(lines)


def json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2)
