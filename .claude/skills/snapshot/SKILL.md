---
description: Prepare a Jira workspace - fetch issue data, create a git worktree, and write snapshot artifacts (description.md, comments.md, statuses.md). Run this before starting or resuming implementation on a task.

TRIGGER when: an agent needs to set up or refresh a workspace for a Jira task — i.e., before starting implementation on a new task or when resuming work on an existing task.
DO NOT TRIGGER when: the workspace already exists and snapshot files are up to date.
---

Prepare a Jira workspace for a parent issue and its subtasks. Argument: Jira parent issue key.

## Invocation

```bash
bash scripts/snapshot.sh <PARENT-KEY>
```

Example: `bash scripts/snapshot.sh IOS-12345`

## Required environment

| Variable     | Description                                        |
|--------------|----------------------------------------------------|
| `SDD_WORKDIR` | Root directory for task workspaces                |
| `IOS_DIR`     | Path to iOS repo (set exactly one of these two)   |
| `ANDROID_DIR` | Path to Android repo (set exactly one of these two) |

`acli` and `jq` must be available on `PATH`. `acli` requires active Jira authentication.

## What the script does

1. **Validates** environment variables and required CLI tools.
2. **Fetches Jira data**: parent core fields, parent comments, subtask list, each subtask's core fields and comments.
3. **Renders ADF** description and comment bodies to Markdown.
4. **Creates git worktree** at `$SDD_WORKDIR/<KEY>/repo/` on branch `feature/<KEY>` (or `bugfix/<KEY>` for Bug type). Skips creation if the worktree already exists.
5. **iOS bootstrap** (new worktree only, when `IOS_DIR` is set): symlinks `swift_format`, runs `mise trust`, `tuist generate`, `pod install`.
6. **Writes snapshot artifacts** (see layout below).

## Output layout

```
$SDD_WORKDIR/<PARENT-KEY>/
├── description.md          # parent issue: metadata + rendered description
├── comments.md             # parent issue: all comments in chronological order
├── statuses.md             # Markdown table: parent + all subtasks
├── repo/                   # git worktree on feature/<PARENT-KEY>
└── <SUBTASK-KEY>/
    ├── description.md      # subtask: metadata + rendered description
    └── comments.md         # subtask: all comments
```

## Idempotency

Safe to re-run. An existing worktree is preserved as-is (bootstrap is skipped). Snapshot files are overwritten with fresh Jira data on every run.

## Exit codes

| Code | Meaning                                                       |
|------|---------------------------------------------------------------|
| 0    | All stages succeeded                                          |
| 1    | Fatal error (env validation or parent retrieval failed); no artifacts written |
| 2    | Partial success: one or more subtask retrievals failed; parent artifacts and successful subtask artifacts are still written |

## Troubleshooting

| Symptom                          | Check                                              |
|----------------------------------|----------------------------------------------------|
| `SDD_WORKDIR` error              | Export `SDD_WORKDIR` before running                |
| `IOS_DIR` / `ANDROID_DIR` error  | Set exactly one platform directory                 |
| `acli` command not found         | Install acli: `brew tap atlassian/homebrew-acli && brew install acli` |
| `acli` auth failure              | Run `acli jira auth login`                         |
| Network timeout                  | Connect to VPN                                     |
| Git worktree error               | Check that `master` branch is up to date and the branch name does not already exist |
