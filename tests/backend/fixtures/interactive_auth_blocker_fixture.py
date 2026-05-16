#!/usr/bin/env python3
"""Interactive fixture that reaches ready state and then asks for auth."""

from __future__ import annotations

import sys


def main() -> None:
    sys.stdout.write(
        "SDD_FACTORY_ROLE_LAUNCHER_READY role=implementer task=IOS-50005 lifecycle=persistent\n"
    )
    sys.stdout.write(
        "SDD_FACTORY_AGENT_BOOTSTRAP launcher=claude role=implementer task=IOS-50005 lifecycle=persistent\n"
    )
    sys.stdout.write(
        "Quick safety check: Is this a project you created or one you trust?\n"
        "❯ 1. Yes, I trust this folder\n"
        "  2. No, exit\n"
        "Enter to confirm · Esc to cancel\n"
    )
    sys.stdout.flush()

    trusted = False
    for raw_line in sys.stdin:
        line = raw_line.rstrip("\r\n")
        if not trusted:
            if line == "1":
                trusted = True
                sys.stdout.write(
                    "⏵⏵ auto mode on (shift+tab to cycle)          ctrl+g to edit in Vim\n"
                )
                sys.stdout.write("1 claude.ai connector needs auth · /mcp\n")
                sys.stdout.flush()
            continue


if __name__ == "__main__":
    main()
