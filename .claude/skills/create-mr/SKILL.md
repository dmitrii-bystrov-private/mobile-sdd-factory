---
description: >
  Commit changes, push, and open a GitLab merge request to master.
  TRIGGER when the user asks to create/open/push an MR, merge request, or PR — or says "push and create MR", "open MR", "submit MR".
  DO NOT TRIGGER for reviewing MRs, checking MR status, or posting to Slack (that is /request-review).
---

Commit staged changes, push the branch, and open a merge request on GitLab. Arguments: `$ARGUMENTS`

## Step 1 — Determine project and working directory

Identify the Jira key from `$ARGUMENTS` or the current branch name.

If a Jira key is known, check for a worktree first:
- Worktree path: `~/Projects/Finom/workdir/<TASK-KEY>/repo`
- If it exists → use it as `<project_dir>`

If no worktree found, fall back to the main project directory:
- `IOS-` → `~/Projects/Finom/finomcommon`
- `ANDR-` → `~/Projects/Finom/finom`

If ambiguous, ask.

Set `<project_dir>` accordingly.

## Step 2 — Check git state

```
git -C <project_dir> status
git -C <project_dir> branch --show-current
git -C <project_dir> log master..HEAD --oneline
```

Verify:
- Not on `master` (refuse to push directly to master)
- There are changes to commit OR commits ahead of master

## Step 3 — Commit (if uncommitted changes exist)

If there are staged or unstaged changes:

1. Show a summary of changed files
2. Stage relevant files (prefer explicit file names over `git add -A`)
3. Draft a concise commit message based on the diff
4. Show the proposed commit message and ask for confirmation
5. Commit

If all changes are already committed, skip this step.

## Step 4 — Run linter (Android only)

**iOS: skip this step** — linting is not enforced at this stage.

**Android:** run detekt and ktlint before pushing:

```
cd <project_dir> && ./gradlew detekt ktlint 2>&1 | tail -40
```

If either fails:
1. Show the errors to the user
2. Fix them (magic numbers → named constants, unused imports, formatting, etc.)
3. Re-run to confirm both pass
4. Commit the fixes

Do NOT push if the linter fails.

## Step 5 — Push

```
git -C <project_dir> push -u origin <branch-name>
```

If the push fails (e.g. rejected), explain the error and suggest a fix. Do NOT force-push without explicit confirmation.

## Step 6 — Create merge request

Extract a Jira key from the branch name if possible (e.g. `feature/ANDR-12345` → `ANDR-12345`).

Build the title: `<JIRA-KEY>: <task summary>` (use the Jira task summary if known, otherwise derive from commits).

Build the description:
- One-line summary of what was done
- Jira link: `https://pnlfintech.atlassian.net/browse/<JIRA-KEY>` (if key is available)
- List of key changes (files/components touched)

Run:
```
cd <project_dir> && glab mr create \
  --fill \
  --title "<JIRA-KEY>: <summary>" \
  --description "<description>" \
  --target-branch master \
  --remove-source-branch \
  --yes
```

Note: `--fill` and `--title` must both be present — `--yes` alone without `--fill` will error.

Show the created MR URL.

## Step 7 — Offer next steps

After the MR is created, ask:

"MR создан: <URL>. Отправить на ревью в Slack?"

If the user confirms, invoke the `/request-review` skill with the MR URL.
