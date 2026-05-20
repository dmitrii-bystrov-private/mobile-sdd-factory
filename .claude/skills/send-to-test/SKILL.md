---
description: >
  Transition a Jira task to Ready for test after workflow commits and MR handoff have already completed.
  TRIGGER when the user asks to send/submit/move a task to testing, QA, or test.
  Examples: "send to test", "submit to QA", "move to QA", "ready for testing".
  DO NOT TRIGGER for general task questions or code changes unrelated to QA handoff.
---

Send a Jira task to QA. Arguments: `$ARGUMENTS`

This skill defines the deprecated slash-command send-to-test surface. In the current primary product flow, send-to-test normally runs automatically after delivery succeeds and only failed delivery needs manual recovery.

## Step 1 — Collect parameters

Parse `<KEY>` from `$ARGUMENTS`. If missing, ask for it.

## Step 2 — Run send-to-test

```bash
bash scripts/send-to-test.sh <KEY>
```

The script:
1. Transitions the task to **Ready for test**.
2. Does not create any git commit; workflow commits should already exist before this step.
