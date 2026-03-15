## Scripts

This directory contains shell scripts used by the assistant and as standalone CLI helpers.

### Prerequisites

- `glab` (GitLab CLI)
- `jq`
- `acli` (Atlassian/Jira CLI)

### Required environment variables

- `IOS_DIR` — path to the iOS repository
- `ANDROID_DIR` — path to the Android repository
- `SDD_WORKDIR` — path to the per-task workdir root

Optional:
- `JIRA_BASE_URL` — default: `https://pnlfintech.atlassian.net/browse/` (used by `request-review.sh`)

Scripts that use `IOS_DIR` / `ANDROID_DIR` will fail fast if the variable is not set or does not point to an existing directory.

### Usage

If `scripts/` is on your `$PATH`, you can call scripts by name:

```bash
standup.sh
gitlab.sh
request-review.sh ios 2867
bash scripts/snapshot.sh IOS-12345
```

Otherwise run them from the repo root:

```bash
bash scripts/standup.sh
bash scripts/gitlab.sh
bash scripts/request-review.sh android 1234
```

### Scripts

#### `snapshot.sh`

Prepares a Jira workspace for a parent issue and its subtasks:

```bash
bash scripts/snapshot.sh <PARENT-KEY>
```

1. Fetches Jira data (parent + subtasks) and renders ADF descriptions/comments to Markdown.
2. Creates a git worktree at `$SDD_WORKDIR/<KEY>/repo/` on `feature/<KEY>` (or `bugfix/<KEY>` for Bug type). Skips creation if the worktree already exists.
3. Runs iOS bootstrap (symlinks `swift_format`, runs `mise trust`, `tuist generate`, `pod install`) for new worktrees when `IOS_DIR` is set.
4. Writes snapshot artifacts:

```
$SDD_WORKDIR/<PARENT-KEY>/
├── description.md      # parent metadata + rendered description
├── comments.md         # parent comments in chronological order
├── statuses.md         # Markdown table: parent + all subtasks
├── repo/               # git worktree
└── <SUBTASK-KEY>/
    ├── description.md
    └── comments.md
```

Safe to re-run — worktree and bootstrap are skipped if the worktree already exists; snapshot files are overwritten with fresh Jira data.

Exit codes: `0` = success, `1` = fatal error, `2` = partial success (some subtask retrievals failed).

#### `standup.sh`

Builds a daily standup summary by querying:
- GitLab merge requests (iOS + Android)
- Jira backlog (via `acli`)

Output is printed to stdout.

#### `gitlab.sh`

Prints:
- merge requests awaiting your approval/review
- your open merge requests

Output is printed to stdout.

#### `request-review.sh`

Generates a Slack-ready message for requesting review of a merge request:

```bash
request-review.sh ios <mr_iid>
request-review.sh android <mr_iid>
```

Prints 2–3 lines:
- Jira link + summary (if a Jira key is present in the MR title)
- MR diffs link
- diff stats (files/additions/deletions) when available

#### `adf_to_md.sh`

Library sourced by `snapshot.sh`. Provides `render_adf_to_markdown` — converts Jira ADF (Atlassian Document Format) JSON to Markdown. Not intended to be run directly.

#### `snapshot_formatters.sh`

Library sourced by `snapshot.sh`. Provides `write_description_md`, `write_comments_md`, and `write_statuses_md` — formats and writes snapshot artifact files. Not intended to be run directly.

#### `check-updates.sh`

Used by `standup.sh` (on Mondays) to check for tool updates.

#### `acli-dump-issue.sh`

Debug helper — dumps raw Jira issue JSON for a given key. Useful when investigating acli output format.

### Tests

Test scripts live in `scripts/tests/`:

- `test_adf_to_md.sh` — unit tests for `adf_to_md.sh`
- `test_snapshot_formatters.sh` — unit tests for `snapshot_formatters.sh` (uses golden files in `tests/golden/`)
- `test_snapshot_errors.sh` — integration tests for error handling in `snapshot.sh`
- `gen_golden.sh` — regenerates golden files in `tests/golden/` from current script output
