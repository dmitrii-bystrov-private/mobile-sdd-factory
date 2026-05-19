---
description: >
  Commit changes, push, open a GitLab merge request to master, and prepare the Slack-ready review message.
  TRIGGER when the user asks to create/open/push an MR, merge request, or PR — or says "push and create MR", "open MR", "submit MR".
  DO NOT TRIGGER for reviewing MRs or checking MR status.
---

Commit staged changes, push the branch, and open a merge request on GitLab. Arguments: `$ARGUMENTS`

This skill defines the deprecated slash-command MR handoff surface. In the current primary product flow, delivery normally performs MR handoff automatically and surfaces only failures for operator recovery.

## Step 1 — Determine project and working directory

Identify the Jira key from `$ARGUMENTS` or the current branch name.

If a Jira key is known, check for a worktree first:
- Worktree path: `$SDD_WORKDIR/<TASK-KEY>/repo`
- If it exists → use it as `<project_dir>`

If no worktree found, fall back to the main project directory:
- `IOS-` → `$IOS_DIR`
- `ANDR-` → `$ANDROID_DIR`

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

## Step 4 — Push and create merge request

```
bash scripts/create-mr.sh <JIRA-KEY>
```

The script resolves the project directory from the task worktree, pushes the branch, and opens the MR to master. It prints the created MR URL on success.

If the script fails (e.g. push rejected, already on master), surface the error to the user and stop. Do NOT force-push without explicit confirmation.

## Step 5 — Prepare review message

After MR creation succeeds:

1. Read the created MR URL from the script output.
2. Extract the numeric MR ID from the URL.
3. Infer platform:
   - `IOS-` task key or MR URL containing `finomcommon`/`/ios/` → `ios`
   - `ANDR-` task key or MR URL containing `/android/` → `android`
4. Run:

```bash
bash scripts/request-review-message.sh <platform> <mr_id>
```

5. Show the generated review message to the user together with the MR URL.

If review-message generation fails, still surface the MR URL and report the review-message error separately.
