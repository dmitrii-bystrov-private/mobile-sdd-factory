#!/usr/bin/env python3
"""Minimal interactive fixture for launcher-backed PTY driver tests."""

from __future__ import annotations

import sys


def main() -> None:
    sys.stdout.write(
        "SDD_FACTORY_ROLE_LAUNCHER_READY role=implementer task=IOS-50004 lifecycle=persistent\n"
    )
    sys.stdout.write(
        "SDD_FACTORY_AGENT_BOOTSTRAP launcher=claude role=implementer task=IOS-50004 lifecycle=persistent\n"
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
                sys.stdout.flush()
            continue
        if not line:
            continue
        sys.stdout.write(f"ROUTED:{line}\n")
        sys.stdout.write(
            'SDD_OUTPUT: {"output_type":"completed","payload":{"summary":"interactive round done"}}\n'
        )
        sys.stdout.flush()


if __name__ == "__main__":
    main()
