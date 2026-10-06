#!/usr/bin/env python3
"""Interactive fixture that blocks, receives operator input, then completes."""

from __future__ import annotations

import json
from pathlib import Path
import sys


def main() -> None:
    sys.stdout.write(
        "SDD_FACTORY_ROLE_LAUNCHER_READY role=implementer task=IOS-50006 lifecycle=persistent\n"
    )
    sys.stdout.write(
        "SDD_FACTORY_AGENT_BOOTSTRAP launcher=claude role=implementer task=IOS-50006 lifecycle=persistent\n"
    )
    sys.stdout.write(
        "Quick safety check: Is this a project you created or one you trust?\n"
        "❯ 1. Yes, I trust this folder\n"
        "  2. No, exit\n"
        "Enter to confirm · Esc to cancel\n"
    )
    sys.stdout.flush()

    trusted = False
    blocked = False
    for raw_line in sys.stdin:
        line = raw_line.rstrip("\r\n")
        if not trusted:
            if line == "1":
                trusted = True
                blocked = True
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

        if blocked:
            if line:
                blocked = False
                sys.stdout.write(f"AUTH_CONTINUED:{line}\n")
                (Path.cwd() / "RESULT.json").write_text(
                    json.dumps(
                        {
                            "output_type": "completed",
                            "payload": {"summary": "interactive recovery completed"},
                        }
                    ),
                    encoding="utf-8",
                )
                sys.stdout.flush()
            continue


if __name__ == "__main__":
    main()
