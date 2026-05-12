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
- **raw_context** — everything the user said about the task: what, why, how, affected files, fix ideas
- **priority** — Highest / High / Medium / Low / Lowest (default: `Medium`)

If **summary** or **type** or **platform** is missing or ambiguous, ask before proceeding.
If there is not enough context to write a meaningful description, ask for more details before proceeding.

## Step 2 — Compose description

Using `raw_context`, write a full structured description in **Markdown**. The script converts it to Jira ADF automatically. Do not truncate or summarise — include all relevant detail.

**For Bug:**
```
## Description
[What goes wrong and when. Include any error messages or observable symptoms.]

## Root Cause
[Technical explanation of why it happens. Reference specific files/methods/lines if known.]

## Consequences
[List all impact points — broken UI, security bypass, data loss, etc.]

## Steps to Reproduce
1. ...
2. ...

## Expected Behavior
[What should happen.]

## Actual Behavior
[What actually happens.]

## Fix
[Proposed fix approach with file names, method names, line numbers if known.]
```

**For Story:**
```
## Background
[Why this is needed. Business or technical motivation.]

## Goal
[What should be achieved when done.]

## Implementation Notes
[Technical approach, affected files, constraints, edge cases if known.]

## Acceptance Criteria
- [ ] ...
- [ ] ...
```

Omit sections that have no relevant information. Keep language precise and technical.

## Step 3 — Show preview and confirm

Show the full description so the user can review it:
```
Project:     <IOS|ANDR>
Type:        <Bug|Story>
Summary:     <summary>
Priority:    <priority>

--- Description ---
<full description>
---
```

Ask: "Create a task?" — wait for explicit confirmation before proceeding.

## Step 4 — Create via script

Run `scripts/create-issue.sh` in a single Bash call:

```bash
scripts/create-issue.sh \
  --project <IOS|ANDR> \
  --type <Bug|Story> \
  --summary "<summary>" \
  --description "<description>" \
  --priority "<priority>"
```

Omit `--description` if none was provided.

The script prints two lines: the issue key and the URL.

## Step 5 — Show result

On success, show:
```
✓ Created: <KEY-123>
  https://pnlfintech.atlassian.net/browse/<KEY-123>
```

On error, show the raw error and suggest what to fix.
