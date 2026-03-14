---
description: >
  Fix QA review issues for a Reopened Jira task — read QA comments, fix in the existing worktree, commit, and send back to test.
  TRIGGER when the user mentions a task was returned from QA, has QA comments to fix, or is in "Reopened" status and needs to be fixed.
  Examples: "fix QA comments", "task was reopened", "fix review for IOS-12035".
  DO NOT TRIGGER for implementing new tasks (use /implement), or for sending to test without prior QA feedback.
---

Fix QA review issues for a Jira task. Argument: Jira key (e.g. `/fix-review IOS-12035`).

## Steps

### 1. Load task and QA feedback

Parse the task key from `$ARGUMENTS`. If missing, ask for it.

Fetch the task:
```bash
acli jira workitem view <KEY> --fields '*all' --json
```

Read:
- Task summary and description
- All comments — QA feedback is written as regular comments, typically the most recent ones after the last "Ready for test" transition
- Parent key (if subtask)

Determine `<STORY-KEY>`:
- If subtask → use parent key
- If story → use task key itself

Show the user a clean summary of the QA comments:
```
QA feedback on <KEY>:
1. <issue from comment>
2. <issue from comment>
...
```

Ask: "Это все замечания, или есть что добавить?" — wait for confirmation or additions before proceeding.

### 2. Locate the worktree and save QA feedback to file

```bash
ls "$SDD_WORKDIR/<STORY-KEY>/repo"
```

If the worktree does not exist, tell the user and stop — the worktree must exist from the original implementation.

Save the confirmed QA issues to `$SDD_WORKDIR/<STORY-KEY>/qa-<KEY>.md`:

```markdown
# QA Feedback for <KEY>

Source: Jira comments (Reopened <date>)

## Issues

1. <issue>
2. <issue>
...

## Status

- [ ] <issue 1>
- [ ] <issue 2>
...
```

### 3. Assess complexity and decide on approach

Review the confirmed QA issues and classify each one:
- **Straightforward** — clear fix, no design decisions (e.g. wrong color, wrong text, missing constraint, simple layout fix)
- **Non-trivial** — requires choosing an approach, touching multiple files, understanding a non-obvious pattern, or redesigning a part of the UI/logic

If **any** issue is non-trivial, tell the user:
```
Есть нетривиальные замечания: <list them>. Запущу qa-spec-writer, чтобы подготовить детальный план перед имплементацией.
```
Then go to Step 3a. Otherwise go to Step 3b.

### 3a. Non-trivial path — launch qa-spec-writer first

Launch the `qa-spec-writer` agent:

```
Write a fix spec for QA review issues on <KEY>.

QA feedback file: $SDD_WORKDIR/<STORY-KEY>/qa-<KEY>.md
Original spec file: $SDD_WORKDIR/<STORY-KEY>/spec-<KEY>.md
Project directory: $SDD_WORKDIR/<STORY-KEY>/repo
Output spec path: $SDD_WORKDIR/<STORY-KEY>/spec-qa-<KEY>.md
```

Wait for the agent to complete. Show the user a brief summary of what the spec contains. Then launch the implementer agent:

```
Fix QA review issues for <KEY>.

Fix spec: $SDD_WORKDIR/<STORY-KEY>/spec-qa-<KEY>.md
QA feedback file: $SDD_WORKDIR/<STORY-KEY>/qa-<KEY>.md
Project directory: $SDD_WORKDIR/<STORY-KEY>/repo

Read the fix spec first — it contains the full plan. Follow it step by step.
Fix only the issues listed. Do not make unrelated changes.
```

### 3b. Straightforward path — launch the implementer directly

```
Fix QA review issues for <KEY>.

QA feedback file: $SDD_WORKDIR/<STORY-KEY>/qa-<KEY>.md
Spec file (for context): $SDD_WORKDIR/<STORY-KEY>/spec-<KEY>.md
Project directory: $SDD_WORKDIR/<STORY-KEY>/repo

Read the QA feedback file first, then the spec to understand the original implementation.
Fix only the issues listed in the QA feedback. Do not make unrelated changes.
```

Wait for the agent to complete.

### 4. Review the fixes

1. **iOS only — always regenerate Xcode project after implementation:**
   ```bash
   mise exec -- tuist generate --no-open --path "$SDD_WORKDIR/<STORY-KEY>/repo"
   pod install --project-directory "$SDD_WORKDIR/<STORY-KEY>/repo"
   ```
   Run this unconditionally for any iOS task — SourceKit errors like "No such module" are caused by a stale project, not by bad code.

2. Read each modified file and verify:
   - Each QA issue is addressed
   - No unrelated changes were introduced
   - No new obvious bugs

If issues remain, launch the implementer again with specific fix instructions. Repeat until satisfied.

### 5. Commit

```bash
git -C "$SDD_WORKDIR/<STORY-KEY>/repo" add -A
git -C "$SDD_WORKDIR/<STORY-KEY>/repo" commit -m "<KEY>: Fix QA review issues"
```

### 6. Send back to test

Run the `send-to-test` skill:
```
/send-to-test <KEY>
```

The QA comment should briefly describe what was fixed in response to the review.
