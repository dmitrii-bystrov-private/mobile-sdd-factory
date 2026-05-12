---
description: >
  Clean up resolved Jira task workspaces from $SDD_WORKDIR.
  Scans all directories with a git worktree, checks Jira status,
  and removes worktree + directory for tasks that are Resolved.
  TRIGGER when the user asks to clean up, prune, or remove finished tasks from workdir.
  Examples: "cleanup workdir", "prune resolved tasks", "clean up finished tasks".
---

Clean up resolved task workspaces. Arguments: `$ARGUMENTS`

## Step 1 — Run cleanup script

```bash
bash scripts/cleanup.sh
```

The script will:
- Scan all directories in `$SDD_WORKDIR` that contain a `repo/` worktree
- Fetch the current Jira status for each task key
- For tasks with status `Resolved`: remove the git worktree, delete the local branch, and delete the entire task directory
- Print a summary of what was cleaned and what was skipped

## Step 2 — Report results

Show the script output to the user verbatim.
