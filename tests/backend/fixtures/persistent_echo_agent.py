#!/usr/bin/env python3
"""Small persistent test agent for local process-mode runtime validation."""

from __future__ import annotations

import json
import select
import sys


def _iter_messages() -> list[str]:
    pending: list[str] = []
    while True:
        ready, _, _ = select.select([sys.stdin], [], [], 0.1)
        if not ready:
            if pending:
                yield "\n".join(pending).strip()
                pending = []
            continue
        line = sys.stdin.readline()
        if line == "":
            if pending:
                yield "\n".join(pending).strip()
            return
        pending.append(line.rstrip("\n"))


def main() -> None:
    print("AGENT_READY", flush=True)
    round_number = 0
    for text in _iter_messages():
        if not text:
            continue
        round_number += 1
        print(
            f'SDD_PROGRESS: {json.dumps({"status": "in_progress", "message": f"round {round_number}", "progress": 50})}',
            flush=True,
        )
        print(
            f'SDD_OUTPUT: {json.dumps({"output_type": "completed", "payload": {"summary": f"round {round_number} done"}})}',
            flush=True,
        )


if __name__ == "__main__":
    main()
