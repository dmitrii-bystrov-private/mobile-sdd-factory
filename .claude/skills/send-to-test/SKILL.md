---
description: >
  Send a Jira task to testing: post a QA comment and transition status to "Ready for test".
  TRIGGER when the user asks to send/submit/move a task to testing, QA, or test.
  Examples: "send to test", "submit to QA", "move to QA", "ready for testing".
  DO NOT TRIGGER for general task questions or code changes unrelated to QA handoff.
---

Send a Jira task to QA. Arguments: `$ARGUMENTS`

## Combined invocation

If the message also contains an intent to post an MR for review (e.g. "send to test and request review"), execute **both** skills sequentially:
1. Complete all steps of this skill first.
2. Then execute the `request-review` skill for the MR part.

Collect all required parameters for both upfront, show a combined preview, confirm once, then execute both.

## Step 1 — Collect parameters

Parse `$ARGUMENTS`. Extract:
- **task key** (required) — e.g. `IOS-12005` or `ANDR-10874`
- **what was done** (optional) — brief description of the change in plain language
- **QA hint** (optional) — what to pay attention to, or that testing is straightforward

If the task key is missing, ask for it.

## Step 2 — Fetch task context

Run:
```
acli jira workitem view <KEY>
```

Read the task summary and description to understand what it's about. You'll use this to draft the comment if the user didn't provide enough context.

Also check what MR (if any) is referenced in the task or was mentioned by the user.

## Step 3 — Draft the comment

Write a short QA comment in English. Structure:

```
**What was done**
<1–3 sentences in plain language, no technical jargon. What changed from the user's perspective.>

**QA notes**
<What the tester should focus on. If there are side effects or adjacent areas touched — call them out.
If the change is trivial, say so: "No edge cases expected — just verify the app launches and requests complete successfully.">
```

Keep it short and practical. No implementation details, no code references.

## Step 4 — Preview and confirm

Show the full comment text and the target task key. Ask: "Добавить комментарий и перевести в Ready for test?" — wait for explicit confirmation.

## Step 5 — Post comment and transition

Run sequentially:

1. Post the comment:
```
acli jira workitem comment --key <KEY> --body "<comment text>"
```

2. Transition the task:
```
acli jira workitem transition --key <KEY> --status "Ready for test"
```

On success, confirm:
```
✓ <KEY> → Ready for test
  Comment posted.
```

On error, show the error and suggest what to fix.
