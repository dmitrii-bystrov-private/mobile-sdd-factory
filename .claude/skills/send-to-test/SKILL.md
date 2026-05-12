---
description: >
  Commit uncommitted changes and transition a Jira task to Ready for test.
  TRIGGER when the user asks to send/submit/move a task to testing, QA, or test.
  Examples: "send to test", "submit to QA", "move to QA", "ready for testing".
  DO NOT TRIGGER for general task questions or code changes unrelated to QA handoff.
---

Send a Jira task to QA. Arguments: `$ARGUMENTS`

## Step 1 — Collect parameters

Parse `<KEY>` from `$ARGUMENTS`. If missing, ask for it.

## Step 2 — Run commit-and-resolve

```bash
bash scripts/commit-and-resolve.sh <KEY>
```

The script:
1. Commits all uncommitted changes with message `<KEY>: <TASK-TITLE>` (title fetched from Jira).
2. Transitions the task to **Ready for test**.
