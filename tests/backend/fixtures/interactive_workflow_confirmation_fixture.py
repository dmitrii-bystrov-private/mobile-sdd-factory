#!/usr/bin/env python3
"""A launcher that asks for workflow consent twice in the same live role."""

import sys


for attempt in range(2):
    sys.stdout.write(
        "\033[2J\033[H"
        "Run a dynamic workflow?\n"
        "This dynamic workflow will spin up multiple subagents.\n"
        "  ❯ 1. Yes, run it\n"
        "    2. View raw script\n"
        "    3. No\n\n"
        "Esc to cancel · Tab to amend\n"
        "ctrl+g to edit script in $EDITOR\n"
    )
    sys.stdout.flush()
    answer = sys.stdin.readline().strip()
    if answer != "1":
        raise RuntimeError(f"Unexpected answer: {answer!r}")
    sys.stdout.write("\033[2J\033[HWorkflow running\n❯ \n")
    sys.stdout.flush()

sys.stdout.write('SDD_PROGRESS: {"message":"both workflows accepted"}\n')
sys.stdout.flush()
for _ in sys.stdin:
    pass
