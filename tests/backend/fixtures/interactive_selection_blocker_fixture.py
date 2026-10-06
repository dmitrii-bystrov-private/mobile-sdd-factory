#!/usr/bin/env python3
"""Interactive fixture that reaches ready state and then asks for selection."""

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
                    "❯ .\n"
                    "✻ Brewed for 1s\n"
                )
                sys.stdout.write(
                    "☐ Action\n"
                    "What would you like to do?\n"
                    "❯ 1. Option 1\n"
                    "  2. Option 2\n"
                    "Enter to select · ↑/↓ to navigate · Esc to cancel\n"
                )
                sys.stdout.flush()
            continue


if __name__ == "__main__":
    main()
