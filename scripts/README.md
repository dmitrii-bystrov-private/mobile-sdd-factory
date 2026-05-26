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
- `JIRA_BASE_URL` — optional Jira browse URL override used in generated links
- `DEFAULT_JIRA_ASSIGNEE` — optional default assignee email for `create-issue.sh`

Scripts that use `IOS_DIR` / `ANDROID_DIR` will fail fast if the variable is not set or does not point to an existing directory.

### Scripts

#### `dev.sh`

Convenience entrypoint for the most common supported local developer actions:

```bash
bash scripts/dev.sh help
bash scripts/dev.sh ui
bash scripts/dev.sh backend-start
bash scripts/dev.sh backend-status
bash scripts/dev.sh stack
bash scripts/dev.sh test
bash scripts/dev.sh test-live
bash scripts/dev.sh doctor
bash scripts/dev.sh bootstrap
```

It is a thin wrapper over the supported launcher, doctor, bootstrap, and test-rail scripts so contributors do not need to remember multiple entrypoints.

#### `run-supported-tests.sh`

Runs the supported Constellation: Agent Runtime test rail from the repository root:

```bash
bash scripts/run-supported-tests.sh
bash scripts/run-supported-tests.sh --live
```

Default coverage:

- backend regression suite
- UI production build
- shell regression tests under `scripts/tests/`
- supported operator acceptance harnesses

Optional `--live` additionally runs the high-signal live runtime acceptance harnesses.

Use this as the primary single entry point when you want broad validation of the supported platform.

#### `snapshot.sh`

Prepares a Jira workspace for a parent issue and its subtasks:

```bash
bash scripts/snapshot.sh <PARENT-KEY>
```

1. Fetches Jira data (parent + subtasks) and renders ADF descriptions/comments to Markdown.
2. Creates a git worktree at `$SDD_WORKDIR/<KEY>/repo/` on `feature/<KEY>` (or `bugfix/<KEY>` for Bug type). Skips creation if the worktree already exists.
3. Runs platform bootstrap for new worktrees:
   - **iOS** (`IOS_DIR`): symlinks `swift_format`, runs `mise trust`, `mise install`, `tuist install`, `tuist generate`, `pod install`.
   - **Android** (`ANDROID_DIR`): copies `.gradle`, symlinks `local.properties`, then runs `./gradlew clean`.
4. Transitions the task to **In Progress** only for Bugs currently in **To Do**.
5. Writes snapshot artifacts:

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

#### `create-subtask.sh`

Creates a single Jira subtask under a parent story:

```bash
scripts/create-subtask.sh --parent <KEY> --title <title> --description <file.md>
```

- Reads the parent story's assignee from Jira and assigns the new subtask to them.
- Passes the markdown description file directly to `acli` (no ADF conversion needed).
- Prints the created subtask key to stdout on success.
- Exits non-zero with an error message on failure.

#### `create-subtasks-batch.sh`

Creates all Jira subtasks from a decomposition plan in one batch:

```bash
scripts/create-subtasks-batch.sh --parent <KEY> --plan-dir <plan/>
scripts/create-subtasks-batch.sh --parent <KEY> --plan-dir <plan/> \
  --task-file ./10-follow-up-a.md \
  --task-file ./11-follow-up-b.md
```

- If `--plan-dir` is omitted, defaults to `$SDD_WORKDIR/<KEY>/plan/`.
- If `--task-file` is omitted, reads `<plan-dir>/index.md` to determine creation order.
- If one or more `--task-file` flags are provided, creates only those files in the order passed on the command line.
- Relative `--task-file` paths are resolved against `<plan-dir>`; absolute paths are also accepted.
- Calls `create-subtask.sh` for each task file in that order.
- Skips tasks whose titles already exist as subtasks under the same parent.
- Stops on first failure and reports which task failed and why.
- Already-created subtasks are NOT rolled back on partial failure.
- Prints a summary table of created subtask keys and any skipped titles.

This selective mode is useful when `plan/` contains a broader backlog but you only want to create newly added review findings or MR follow-up tasks without rebuilding a temporary plan directory.

#### `request-review-message.sh`

Generates a Slack-ready message for requesting review of a merge request:

```bash
bash scripts/request-review-message.sh ios <mr_iid>
bash scripts/request-review-message.sh android <mr_iid>
```

Prints 2–3 lines:
- Jira link + summary (if a Jira key is present in the MR title)
- MR diffs link
- diff stats (files/additions/deletions) when available

Optional flag:
- `--open` / `-o` — open a browser tab with rich text preselected for copy/paste into Slack

#### `adf-to-md.sh`

Library sourced by `snapshot.sh`. Provides `render_adf_to_markdown` — converts Jira ADF (Atlassian Document Format) JSON to Markdown. Not intended to be run directly.

#### `snapshot-formatters.sh`

Library sourced by `snapshot.sh`. Provides `write_description_md`, `write_comments_md`, and `write_statuses_md` — formats and writes snapshot artifact files. Not intended to be run directly.

#### `get-issue-type.sh`

Returns the Jira issue type name (e.g. `Story`, `Bug`) for a given key:

```bash
bash scripts/get-issue-type.sh <KEY>
```

Prints the type name to stdout. Used by skills to route tasks.

#### `get-issue-parent.sh`

Resolves the story/bug key for a given issue:

```bash
bash scripts/get-issue-parent.sh <KEY>
```

Prints the parent key if `<KEY>` is a subtask/sub-bug, or `<KEY>` itself otherwise. Used by skills to handle subtask inputs gracefully.

#### `run-build.sh` / `run-test.sh` / `run-lint.sh`

Platform-aware wrappers for building, testing, and linting a task worktree. Detect the platform automatically (iOS vs Android) and `cd` into the repo before running the appropriate script.

```bash
bash scripts/run-test.sh  <KEY>   # default workflow verification gate
bash scripts/run-lint.sh  <KEY>   # default workflow verification gate
bash scripts/run-build.sh <KEY>   # legacy/manual wrapper, not part of the default workflow gate
```

Platform is detected by checking for `Tools/buildscripts/` in `$SDD_WORKDIR/<KEY>/repo/`:
- Present → **iOS** (task-local orchestration scripts `scripts/ios-*.sh`)
- Absent → **Android** (task-local orchestration scripts `scripts/android-*.sh`)

Output is already filtered by the underlying scripts — on success a single `✅ ...` line is printed; on failure a `❌ ...` line followed by only the relevant error lines. **Do not pipe through `grep`, `tail`, or any other filter.**

Requires `SDD_WORKDIR` to be set.

#### `generate-diff.sh`

Generates a structured git diff artifact for a task worktree:

```bash
bash scripts/generate-diff.sh <KEY>
bash scripts/generate-diff.sh <KEY> --mode docs
bash scripts/generate-diff.sh <KEY> --mode full
```

- Compares `origin/master...HEAD` and writes a structured artifact with:
  - scope metadata
  - agent notes describing `+` / `-` semantics
  - changed-file status table
  - line-count table
  - raw patch section
- Modes:
  - `source` (default) → source files (`.swift`, `.kt`, `.kts`, `.xml`) written to `$SDD_WORKDIR/<KEY>/spec/diff.md`
  - `docs` → documentation files (`.md`, `.adoc`, `.rst`, `.txt`) written to `$SDD_WORKDIR/<KEY>/spec/doc-diff.md`
  - `full` → source + documentation files written to `$SDD_WORKDIR/<KEY>/spec/full-diff.md`
- Excludes generated files and dependency directories such as `Pods/` and `node_modules/`.
- Used by review/scout/documentation workflows that need a safer diff artifact than a raw patch alone.

Requires `SDD_WORKDIR` to be set.

#### `create-mr.sh`

Pushes the task branch and opens a GitLab merge request targeting `master`:

```bash
bash scripts/create-mr.sh <TASK-KEY>
```

- Resolves the repo from `$SDD_WORKDIR/<PARENT-OR-TASK-KEY>/repo` first, then falls back to `IOS_DIR` / `ANDROID_DIR`.
- Refuses to push directly from `master`.
- Reuses an existing MR for the same source branch if one already exists.
- Builds the MR title as `<KEY>: <TASK-TITLE>` and includes the Jira link in the description.

Requires `SDD_WORKDIR`, plus `IOS_DIR` or `ANDROID_DIR` when no worktree exists.

#### `send-to-test.sh`

Transitions the task to the appropriate testing-ready Jira status without creating a git commit:

```bash
bash scripts/send-to-test.sh <TASK-KEY>
```

- Workflow checkpoint commits should already exist before this step; this script only performs the Jira transition.
- Non-bug tasks transition to **Ready for test**.
- If the task is in **To Do**, transitions through **In Progress** first.

Requires `acli` and `jq`.

#### `fetch-mr-comments.sh`

Fetches unresolved GitLab review discussions and renders them as Markdown:

```bash
bash scripts/fetch-mr-comments.sh <ios|android> <mr_iid>
```

- Paginates through all MR discussions using the GitLab API.
- Filters to unresolved resolvable notes only.
- Prints grouped Markdown sections with file path and line number when available.
- Exits with code `2` when no unresolved discussions exist.

Useful for turning review feedback into Jira subtasks or QA follow-up items.

This script is the first half of the `/handle-mr-comments` workflow:
- `fetch-mr-comments.sh` exports unresolved MR discussions
- the `mr-comments-analyst` agent groups them into `plan/` files under `$SDD_WORKDIR/<KEY>/plan/`
- `create-subtasks-batch.sh --parent <KEY>` creates Jira subtasks from those generated plan files
- when only a subset of new plan files should become Jira subtasks, pass them explicitly with repeated `--task-file`

That workflow assumes an existing task workspace at `$SDD_WORKDIR/<KEY>/repo/`, typically prepared via `bash scripts/snapshot.sh <KEY>`.

#### `get-mr-jira-key.sh`

Extracts the Jira key from a GitLab MR title or description:

```bash
bash scripts/get-mr-jira-key.sh <ios|android> <mr_iid>
```

- Fetches the MR via the GitLab API.
- Searches the title first, then the description, for the first `IOS-XXXX` or `ANDR-XXXX` pattern.
- Prints the key to stdout.
- Exits with code `1` if no key is found.

Used by the `/handle-mr-comments` skill to auto-detect the Jira key when the user provides only an MR URL.

#### `create-issue.sh`

Creates a Jira Story or Bug from CLI input:

```bash
bash scripts/create-issue.sh \
  --project <IOS|ANDR> \
  --type <Bug|Story> \
  --summary "<text>" \
  [--description "<markdown>"] \
  [--description-file path/to/file.md] \
  [--priority <Highest|High|Medium|Low|Lowest>] \
  [--assignee <email>]
```

- Converts Markdown descriptions to Jira ADF via `md-to-adf.sh`.
- Applies the shared team custom field automatically.
- Uses `DEFAULT_JIRA_ASSIGNEE` when `--assignee` is omitted.
- Prints both the created Jira key and browse URL.

#### `update-issue.sh`

Updates fields of an existing Jira issue:

```bash
scripts/update-issue.sh \
  --key <KEY> \
  [--summary "<text>"] \
  [--description "<markdown>"] \
  [--description-file path/to/file.md] \
  [--assignee <email>]
```

- At least one optional field is required; exits with an error otherwise.
- Converts Markdown descriptions to Jira ADF via `md-to-adf.sh`.
- Prints `✓ Updated: <KEY>` and the browse URL on success.

Note: `acli` does not support updating priority via CLI — change it in the Jira UI.

#### `md-to-adf.sh`

Library sourced by `create-issue.sh`, `update-issue.sh`, and `create-subtask.sh`. Provides `render_markdown_to_adf`, which converts Markdown to Jira ADF JSON. It can read either a file path or stdin.

#### `gitlab.sh`

Shows a compact GitLab dashboard across both mobile repos:

```bash
bash scripts/gitlab.sh
```

- Lists MRs assigned to you for review that you have not yet approved.
- Lists your own open MRs and marks already approved ones.
- Aggregates iOS and Android output into one terminal view.

#### `standup.sh`

Prints a standup-oriented status snapshot:

```bash
bash scripts/standup.sh
```

- Lists your open iOS and Android MRs.
- Lists MRs waiting on your review, including whether you already commented.
- Dumps a Jira backlog filter result (`acli jira workitem search --filter 10494 ...`).
- Runs `check-updates.sh` automatically on Mondays.

The script is user-specific as committed today:
- GitLab username is hardcoded as `dapper.chita`
- Jira filter ID is hardcoded as `10494`

#### `check-updates.sh`

Checks local developer tooling for updates:

```bash
bash scripts/check-updates.sh
```

- Checks Homebrew-installed tools used by this workflow.
- Compares the installed Claude Code CLI version to the latest npm release.
- Prints outdated global npm packages, when any exist.

#### `cleanup.sh`

Removes resolved task workspaces from `$SDD_WORKDIR`:

```bash
bash scripts/cleanup.sh
```

- Scans all subdirectories of `$SDD_WORKDIR` that contain a `repo/` git worktree.
- Fetches the current Jira status for each directory name (treated as a task key).
- For tasks with status `Resolved`: removes the git worktree, deletes the matching local branch, then deletes the task directory.
- Prints a one-line status per task and a final summary (`Cleaned / Skipped / Errors`).
- Invoked automatically by the `/cleanup` skill.

#### `acli-dump-issue.sh`

Debug helper — dumps raw Jira issue JSON for a given key. Useful when investigating acli output format.

```bash
bash scripts/acli-dump-issue.sh <ISSUE-KEY> [output-dir]
```

- Writes parent issue payloads plus per-subtask payloads.
- Defaults output to `tmp/acli-dumps/<ISSUE-KEY>/`.

### Tests

Test scripts live in `scripts/tests/`:

- `test_adf_to_md.sh` — unit tests for `adf-to-md.sh`
- `test_snapshot-formatters.sh` — unit tests for `snapshot-formatters.sh` (uses golden files in `tests/golden/`)
- `test_snapshot_errors.sh` — integration tests for error handling in `snapshot.sh`
- `gen_golden.sh` — regenerates golden files in `tests/golden/` from current script output
