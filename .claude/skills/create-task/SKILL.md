---
description: >
  Create a Jira task (Bug or Story) in the iOS or Android project.
  TRIGGER when the user asks to create, add, log, or track a task, bug, issue, story, or ticket —
  even in free-form phrasing. Extract all available fields (summary, type, platform, priority, description)
  from the message. Ask only for what's missing.
  DO NOT TRIGGER for general questions or code changes unrelated to task creation.
---

Create a Jira task. Arguments: `$ARGUMENTS`

## Step 1 — Collect parameters

Parse `$ARGUMENTS` as a free-form description. Extract:
- **summary** — short title (required)
- **type** — `Bug` or `Story` (required; ask if unclear)
- **platform** — `iOS` → project `IOS`, `Android` → project `ANDR` (required; ask if not specified)
- **description** — longer description. Extract from the user's message even if not explicitly labelled — any context about what needs to be done, why, or how counts as description. If the message is too brief to infer a meaningful description, ask for details before proceeding.
- **priority** — Highest / High / Medium / Low / Lowest (default: `Medium`)

If **summary** or **type** or **platform** is missing or ambiguous, ask before proceeding.
If there is not enough context for a meaningful **description**, ask for more details before proceeding.

## Step 2 — Show preview and confirm

Show a concise preview:
```
Project:     <IOS|ANDR>
Type:        <Bug|Story>
Summary:     <summary>
Priority:    <priority>
Assignee:    d.bystrov@pnlfin.tech
Team:        common-mobile
Description: <first 120 chars or "none">
```

Ask: "Создать задачу?" — wait for explicit confirmation before proceeding.

## Step 3 — Build JSON and create

Write a JSON file to `/tmp/jira_create.json`.

**For both Bug and Story:**
```json
{
  "additionalAttributes": {
    "priority": {"name": "<priority>"},
    "customfield_10625": {"id": "11914"}
  },
  "assignee": "d.bystrov@pnlfin.tech",
  "summary": "<summary>",
  "description": "<description_adf_or_omit>",
  "projectKey": "<IOS|ANDR>",
  "type": "<Bug|Story>"
}
```

If description is provided, format it as ADF:
```json
{
  "type": "doc",
  "version": 1,
  "content": [{"type": "paragraph", "content": [{"type": "text", "text": "<description>"}]}]
}
```

If no description — omit the `"description"` key entirely.

Run:
```
acli jira workitem create --from-json /tmp/jira_create.json --json
```

## Step 4 — Show result

On success, show:
```
✓ Created: <KEY-123>
  https://finom.atlassian.net/browse/<KEY-123>
```

On error, show the raw error and suggest what to fix.
