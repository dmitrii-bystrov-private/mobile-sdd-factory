---
description: Prepare a Jira workspace - fetch issue data, create a git worktree, and write snapshot artifacts (description.md, comments.md, statuses.md). Run this before starting or resuming implementation on a task.

TRIGGER when: an agent needs to set up or refresh a workspace for a Jira task — i.e., before starting implementation on a new task or when resuming work on an existing task.
DO NOT TRIGGER when: the workspace already exists and snapshot files are up to date.
---

Prepare a Jira workspace for a parent issue and its subtasks. Argument: Jira issue key (parent or subtask — always resolved to parent before proceeding).

This skill defines the deprecated slash-command snapshot surface. The current primary product flow normally prepares the task workspace from the operator UI and backend session runtime.

## Step 0 — Resolve to parent key

Before anything else, resolve the input key to its parent:

```bash
KEY="$(bash scripts/get-issue-parent.sh <INPUT-KEY>)"
```

`get-issue-parent.sh` returns the parent key if the input is a subtask, or the key itself if it is already a parent. All subsequent steps use `<KEY>` (the resolved value).

**MUST NOT skip this step.** Running snapshot directly on a subtask key creates a spurious worktree and branch — always resolve first.

## Invocation

```bash
bash scripts/snapshot.sh <KEY>
```

Example: `bash scripts/snapshot.sh IOS-12345`

## Required environment

| Variable     | Description                                        |
|--------------|----------------------------------------------------|
| `SDD_WORKDIR` | Root directory for task workspaces                |
| `IOS_DIR`     | Path to iOS repo (required for `IOS-*` keys)      |
| `ANDROID_DIR` | Path to Android repo (required for `ANDR-*` keys) |

`acli` and `jq` must be available on `PATH`. `acli` requires active Jira authentication.

## What the script does

1. **Validates** environment variables and required CLI tools.
2. **Fetches Jira data**: parent core fields, parent comments, subtask list, each subtask's core fields and comments.
3. **Renders ADF** description and comment bodies to Markdown.
4. **Creates git worktree** at `$SDD_WORKDIR/<KEY>/repo/` on branch `feature/<KEY>` (or `bugfix/<KEY>` for Bug type). Skips creation if the worktree already exists.
5. **Platform bootstrap** (new worktree only):
   - **iOS** (`IOS_DIR`): symlinks `swift_format`, runs `mise trust`, `mise install`, `tuist install`, `tuist generate`, `pod install`.
   - **Android** (`ANDROID_DIR`): copies `.gradle`, symlinks `local.properties`, and runs `./gradlew clean`.
6. **Creates directory structure** and **writes snapshot artifacts** (see layout below):
   - **Story**: creates `spec/context/` and `plan/` directories, symlinks `spec/context/project.md` → platform `CLAUDE.md`.
   - **Bug**: creates `spec/` directory only.
7. **Transitions Bugs to In Progress** only when the Jira status is currently `To Do`.

## Output layout

**Story type:**
```
$SDD_WORKDIR/<PARENT-KEY>/
├── description.md          # parent issue: metadata + rendered description
├── comments.md             # parent issue: all comments in chronological order
├── statuses.md             # Markdown table: parent + all subtasks
├── spec/
│   └── context/
│       └── project.md      # symlink → platform CLAUDE.md
├── plan/                   # empty, ready for task-decomposer
├── repo/                   # git worktree on feature/<PARENT-KEY>
└── <SUBTASK-KEY>/
    ├── description.md      # subtask: metadata + rendered description
    └── comments.md         # subtask: all comments
```

**Bug type:**
```
$SDD_WORKDIR/<PARENT-KEY>/
├── description.md
├── comments.md
├── statuses.md
├── spec/                   # empty, ready for downstream analysis/spec artifacts
└── repo/                   # git worktree on bugfix/<PARENT-KEY>
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
| `IOS_DIR` / `ANDROID_DIR` error  | Set the platform directory that matches the Jira key prefix |
| `acli` command not found         | Install acli: `brew tap atlassian/homebrew-acli && brew install acli` |
| `acli` auth failure              | Run `acli jira auth login`                         |
| Network timeout                  | Connect to VPN                                     |
| Git worktree error               | Check that `master` branch is up to date and the branch name does not already exist |
