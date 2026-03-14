## Scripts

This directory contains small shell scripts used by the assistant and as standalone CLI helpers.

### Prerequisites

- `glab` (GitLab CLI)
- `jq`
- `acli` (Atlassian/Jira CLI) — only for `standup.sh`

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
```

Otherwise run them from the repo root:

```bash
bash scripts/standup.sh
bash scripts/gitlab.sh
bash scripts/request-review.sh android 1234
```

### Scripts

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

It prints 2–3 lines:
- Jira link + summary (if a Jira key is present in the MR title)
- MR diffs link
- diff stats (files/additions/deletions) when available

#### `check-updates.sh`

Used by `standup.sh` (on Mondays) to check for tool updates.

