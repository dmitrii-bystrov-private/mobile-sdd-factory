#!/usr/bin/env python3
"""Interactive fixture that requires two operator replies before completion."""

from __future__ import annotations

import sys


def main() -> None:
    sys.stdout.write(
        "SDD_FACTORY_ROLE_LAUNCHER_READY role=implementer task=IOS-50007 lifecycle=persistent\n"
    )
    sys.stdout.write(
        "SDD_FACTORY_AGENT_BOOTSTRAP launcher=claude role=implementer task=IOS-50007 lifecycle=persistent\n"
    )
    sys.stdout.write(
        "Quick safety check: Is this a project you created or one you trust?\n"
        "❯ 1. Yes, I trust this folder\n"
        "  2. No, exit\n"
        "Enter to confirm · Esc to cancel\n"
    )
    sys.stdout.flush()

    trusted = False
    auth_blocked = False
    confirm_blocked = False
    for raw_line in sys.stdin:
        line = raw_line.rstrip("\r\n")
        if not trusted:
            if line == "1":
                trusted = True
                auth_blocked = True
                sys.stdout.write(
                    "⏵⏵ auto mode on (shift+tab to cycle)          ctrl+g to edit in Vim\n"
                )
                sys.stdout.write("1 claude.ai connector needs auth · /mcp\n")
                sys.stdout.flush()
            continue

        if auth_blocked:
            if line.startswith("/"):
                auth_blocked = False
                confirm_blocked = True
                sys.stdout.write(f"AUTH_CONTINUED:{line}\n")
                sys.stdout.write(
                    "Confirm tool execution?\n"
                    "1. Continue\n"
                    "2. Cancel\n"
                    "Enter to confirm · Esc to cancel\n"
                )
                sys.stdout.flush()
            continue

        if confirm_blocked:
            if line == "1":
                confirm_blocked = False
                sys.stdout.write("CONFIRM_CONTINUED:1\n")
                sys.stdout.write(
                    'SDD_OUTPUT: {"output_type":"completed","payload":{"summary":"interactive multi-step recovery completed"}}\n'
                )
                sys.stdout.flush()
            continue


if __name__ == "__main__":
    main()
