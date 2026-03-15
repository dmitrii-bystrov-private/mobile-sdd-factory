---
description: >
  Fix QA review issues for a Reopened Jira task — read QA comments, fix in the existing worktree, commit, and send back to test.
  TRIGGER when the user mentions a task was returned from QA, has QA comments to fix, or is in "Reopened" status and needs to be fixed.
  Examples: "fix QA comments", "task was reopened", "fix review for IOS-12035".
  DO NOT TRIGGER for implementing new tasks (use /implement), or for sending to test without prior QA feedback.
---

Fix QA review issues for a Jira task. Argument: Jira key (e.g. `/fix-review IOS-12035`).

## Steps

### 1. Resolve parent key

Parse the task key from `$ARGUMENTS`. If missing, ask for it.

Run a minimal Jira fetch to determine issue type and parent:

```bash
acli jira workitem view <KEY> --fields 'issuetype,parent' --json
```

- If `fields.issuetype.subtask == true` → extract `<STORY-KEY>` from `fields.parent.key`
- Otherwise → `<STORY-KEY>` = `<KEY>`

### 2. Run snapshot

```bash
bash scripts/snapshot.sh <STORY-KEY>
```

This refreshes all Jira data (including the latest QA comments) and ensures the worktree exists.

If the script exits with code 1, stop and report the error to the user.

### 3. Extract QA feedback

Determine which `comments.md` to read:
- If `<KEY>` is a subtask → `$SDD_WORKDIR/<STORY-KEY>/<KEY>/comments.md`
- If `<KEY>` is the story itself → `$SDD_WORKDIR/<STORY-KEY>/comments.md`

Parse the file: find the **last** comment block whose body starts with the exact prefix `[QA_HANDOFF]` (case-sensitive, must be the first character of the first line). Extract all comment blocks that appear **after** that marker block — these are the QA feedback comments.

If **no `[QA_HANDOFF]` marker** is found, treat the entire comment history as QA feedback.

Show the user a clean summary:
```
QA feedback on <KEY>:
1. <issue from comment>
2. <issue from comment>
...
```

Ask: "Это все замечания, или есть что добавить?" — wait for confirmation or additions before proceeding.

### 4. Locate the worktree and save QA feedback to file

```bash
ls "$SDD_WORKDIR/<STORY-KEY>/repo"
```

If the worktree does not exist, tell the user and stop — it must have been set up during the original implementation.

Save the confirmed QA issues to `$SDD_WORKDIR/<STORY-KEY>/qa-<KEY>.md`:

```markdown
# QA Feedback for <KEY>

Source: comments.md (after last [QA_HANDOFF] marker)

## Issues

1. <issue>
2. <issue>
...

## Status

- [ ] <issue 1>
- [ ] <issue 2>
...
```

### 5. Assess complexity and decide on approach

Review the confirmed QA issues and classify each one:
- **Straightforward** — clear fix, no design decisions (e.g. wrong color, wrong text, missing constraint, simple layout fix)
- **Non-trivial** — requires choosing an approach, touching multiple files, understanding a non-obvious pattern, or redesigning a part of the UI/logic

If **any** issue is non-trivial, tell the user:
```
Есть нетривиальные замечания: <list them>. Запущу qa-spec-writer, чтобы подготовить детальный план перед имплементацией.
```
Then go to Step 5a. Otherwise go to Step 5b.

### 5a. Non-trivial path — launch qa-spec-writer first

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

### 5b. Straightforward path — launch the implementer directly

```
Fix QA review issues for <KEY>.

QA feedback file: $SDD_WORKDIR/<STORY-KEY>/qa-<KEY>.md
Spec file (for context): $SDD_WORKDIR/<STORY-KEY>/spec-<KEY>.md
Project directory: $SDD_WORKDIR/<STORY-KEY>/repo

Read the QA feedback file first, then the spec to understand the original implementation.
Fix only the issues listed in the QA feedback. Do not make unrelated changes.
```

Wait for the agent to complete.

### 6. Review the fixes

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

### 7. Commit

```bash
git -C "$SDD_WORKDIR/<STORY-KEY>/repo" add -A
git -C "$SDD_WORKDIR/<STORY-KEY>/repo" commit -m "<KEY>: Fix QA review issues"
```

### 8. Send back to test

Run the `send-to-test` skill:
```
/send-to-test <KEY>
```

The QA comment should briefly describe what was fixed in response to the review.
