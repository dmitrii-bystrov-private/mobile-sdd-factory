---
description: >
  Route a Jira task to the appropriate skill based on issue type (Story → /jira-story, Bug → /jira-bug).
  Also accepts bare Jira URLs. This skill only routes — it takes no other action.
  TRIGGER when the user provides a Jira key or URL and wants to start working on it.
  Examples: "IOS-1234", "/jira-task IOS-1234", "https://pnlfintech.atlassian.net/browse/IOS-1234".
---

Route Jira task `$ARGUMENTS` to the appropriate skill.

This skill defines the deprecated slash-command router surface. The current primary product flow starts from the operator UI and backend session runtime.

## Step 1 — Detect bare URL

Before parsing `$ARGUMENTS` as a key, check if the raw input matches:
```
https://pnlfintech.atlassian.net/browse/(IOS|ANDR)-\d+
```

If matched: extract the Jira key from the URL (the `(IOS|ANDR)-\d+` capture group) and treat it as `<KEY>`.

Otherwise: use `$ARGUMENTS` as `<KEY>` directly.

## Step 2 — Resolve to parent key

```bash
KEY="$(bash scripts/get-issue-parent.sh <KEY>)"
```

If the input was a subtask or sub-bug, `<KEY>` is now replaced with the parent story/bug key. All subsequent steps use the resolved `<KEY>`.

## Step 3 — Fetch issue type

```bash
bash scripts/get-issue-type.sh <KEY>
```

The script prints the issue type name (e.g. `Story`, `Bug`) to stdout.

## Step 4 — Route

- If type is `Story` → delegate to `/jira-story <KEY>`. Do nothing else.
- If type is `Bug` → delegate to `/jira-bug <KEY>`. Do nothing else.
- If type is anything else → print an error and exit without delegating:
  > "Unrecognized issue type: '<type>'. This workflow only supports Story and Bug. Please handle this task manually."

## Rules

- MUST apply the bare URL regex before parsing as a key.
- MUST fetch issue type via `bash scripts/get-issue-type.sh <KEY>`.
- MUST delegate to `/jira-story` for Story and `/jira-bug` for Bug.
- MUST print the unrecognized type name and exit without delegating for any other type.
- MUST NOT perform any action beyond routing (no code inspection, no file writing, no subagent calls).
- MUST run Step 2 and Step 3 as separate Bash tool calls — do NOT combine them with && or pipe.
