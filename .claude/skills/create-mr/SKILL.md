---
description: >
  Commit changes, push, and open a GitLab merge request to master.
  TRIGGER when the user asks to create/open/push an MR, merge request, or PR — or says "push and create MR", "open MR", "submit MR".
  DO NOT TRIGGER for reviewing MRs, checking MR status, or posting to Slack (that is /request-review).
---

Commit staged changes, push the branch, and open a merge request on GitLab. Arguments: `$ARGUMENTS`

## Step 1 — Determine project

Identify the project from the current git branch or `$ARGUMENTS`:
- If currently in a mobile project directory, use that
- If a Jira key is provided: `IOS-` → `~/Projects/Finom/finomcommon`, `ANDR-` → `~/Projects/Finom/finom`
- If ambiguous, ask

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

## Step 4 — Push

```
git -C <project_dir> push -u origin <branch-name>
```

If the push fails (e.g. rejected), explain the error and suggest a fix. Do NOT force-push without explicit confirmation.

## Step 5 — Create merge request

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

## Step 6 — Offer next steps

After the MR is created, ask:

"MR создан: <URL>. Отправить на ревью в Slack?"

If the user confirms, invoke the `/request-review` skill with the MR URL.
