---
description: >
  Fetch unresolved GitLab MR review comments, group related ones, and create Jira subtasks for each group.
  TRIGGER when: (1) the user says that review comments were added to an MR and asks to process, group, or create subtasks for them;
  (2) the user pastes a bare GitLab MR URL (e.g. https://gitlab.com/.../merge_requests/2971) with no additional context — treat it as a request to process that MR's comments.
  Examples: "new comments on MR for IOS-1234", "13 review comments on MR !2942", "create subtasks for MR comments", "https://gitlab.com/M69/mobile/ios/finomcommon/-/merge_requests/2971".
  DO NOT TRIGGER for QA Jira comments — those should be handled inside the task's normal reopened/follow-up implementation path.
---

Process GitLab MR review comments and create Jira subtasks. Arguments: `$ARGUMENTS`

This skill defines the deprecated slash-command MR follow-up surface. The current primary product flow handles MR follow-up through backend session stages, MR comment ingestion, analysis, and follow-up execution.

## Step 1 — Parse arguments

Extract from `$ARGUMENTS`:
- **MR ID** — the GitLab MR number (e.g. `2942`); extract from URL if a full URL was given; ask if missing
- **Jira key** (e.g. `IOS-12300`) — optional; if not provided, auto-detect from the MR (see below)

Determine platform from Jira key prefix or MR URL:
- `IOS-` prefix or URL contains `finomcommon` → `ios`
- `ANDR-` prefix or URL contains `android` → `android`

If no Jira key was provided, detect it from the MR title/description:

```bash
KEY="$(bash scripts/get-mr-jira-key.sh <ios|android> <MR_ID>)"
```

If the script fails (exit code 1), stop and ask the user to provide the Jira key manually.

Resolve the Jira key to the parent issue before proceeding:

```bash
KEY="$(bash scripts/get-issue-parent.sh <KEY>)"
```

All subsequent paths and commands must use the resolved parent key.

## Step 2 — Validate local workspace

This flow requires an existing task workspace because the analyst reads:
- `$SDD_WORKDIR/<KEY>/repo/`
- `$SDD_WORKDIR/<KEY>/spec/context/` (if present)
- `$SDD_WORKDIR/<KEY>/plan/`

If `$SDD_WORKDIR/<KEY>/repo/` does not exist, stop and tell the user to run `/snapshot <KEY>` first.

## Step 3 — Fetch unresolved discussions

```bash
bash scripts/fetch-mr-comments.sh <ios|android> <MR_ID>
```

The script prints a Markdown document listing all unresolved discussion threads with file/line locations and comment text.

- Exit code `2` means all discussions are resolved — inform the user and stop.
- Exit code `1` means a fatal error — surface the error and stop.

Capture the full output — it is passed to the agent in the next step.

## Step 4 — Delegate to mr-comments-analyst

Invoke the `mr-comments-analyst` agent with:

```
Jira key: <KEY>

MR comments:
<full output from fetch-mr-comments.sh, pasted verbatim>
```

The agent will:
- Read `$SDD_WORKDIR/<KEY>/spec/context/` for task context (if it exists)
- Read source files from `$SDD_WORKDIR/<KEY>/repo/` to understand terse reviewer comments
- Group discussions by theme, enrich each group with actionable descriptions, and write plan files to `$SDD_WORKDIR/<KEY>/plan/`
- Return a summary of the groups created

## Step 5 — Create Jira subtasks

Show the agent summary to the user, then proceed immediately to create subtasks.

## Step 6 — Create subtasks

```bash
bash scripts/create-subtasks-batch.sh --parent <KEY>
```

The script reads `plan/index.md`, creates one Jira subtask per task file, and skips any that already exist.

If the analyst appended only a few new MR follow-up artifacts into an already populated `plan/` directory, create only those new files with repeated `--task-file` flags instead of recreating the whole backlog. Relative task-file paths are resolved against `$SDD_WORKDIR/<KEY>/plan/`.

## Step 7 — Report

Show the script output verbatim, then summarise:

```
Created or updated MR-review subtasks for <KEY>.
```

## Rules

- MUST use `scripts/fetch-mr-comments.sh` — never use `WebFetch` or `glab` directly for reading MR comments.
- MUST auto-detect the Jira key via `scripts/get-mr-jira-key.sh` when not provided in arguments; only ask the user if the script fails.
- MUST resolve the input key to the parent issue with `bash scripts/get-issue-parent.sh <KEY>` before using workdir paths.
- MUST require an existing `$SDD_WORKDIR/<KEY>/repo/` workspace; if missing, stop and instruct the user to run `/snapshot <KEY>` first.
- MUST delegate grouping, enrichment, and plan-file writing to the `mr-comments-analyst` agent — do not do this work directly.
- MUST create Jira subtasks automatically after the agent writes plan files — no confirmation needed.
- MUST use `scripts/create-subtasks-batch.sh` for subtask creation — never call `create-subtask.sh` in a loop.
- MUST use repeated `--task-file` flags when only a subset of newly written `plan/` files should become Jira subtasks.
- MUST NOT fix code directly — only create subtasks.
- MUST NOT create subtasks for already-resolved discussions (the script filters them out automatically).
