# Operator Guide

This guide describes the supported day-to-day workflow for the current SDD Factory platform.

Use this document for the backend/UI runtime model.
Do not use the deprecated slash-command skill surface as the primary operational reference.

## Primary Entry Point

The normal entry point is the operator UI.

From the UI you can:

- create a session for a Jira key
- choose `story_full`, `bug_full`, or `oneshot`
- adjust per-role runtime config for this session
- manage runtime state, recovery, and cleanup
- inspect live runtime handles and tmux commands

## Session Creation

When starting a new task:

1. Enter the Jira key.
2. Choose the workflow profile:
   - `story_full` for full planning + decomposition + execution
   - `bug_full` for bug analysis/fix flow
   - `oneshot` for small direct implementation work
3. Review the policy defaults.
4. Override role runner/model/effort only if this session needs something different from project defaults.
5. Use `Create And Prepare`.

The backend prepares the snapshot and routes the first workflow step automatically.

## Daily Flow

The normal happy path should require little or no operator input.

The main daily actions are:

- `Process Updates`
  Refreshes the task snapshot and lets the coordinator decide whether to continue active work or reopen from new follow-up signals.
- `Refresh Subtask State`
  Pulls the latest Jira subtask state while story execution is active.
- `Create Knowledge Entry`
  Records a reusable project convention, hidden constraint, or non-obvious implementation finding in the shared knowledge base for future sessions.

Most of the time the workflow should progress automatically through:

- planning
- decomposition
- implementation
- self-review
- Boy Scout
- verification
- MR handoff
- send-to-test

## When Operator Input Is Expected

Operator input is expected only when the workflow genuinely cannot continue safely on its own.

Typical cases:

- requirements clarification
- MCP/authentication/VPN blockers
- Boy Scout findings that include old-code candidates and need a tech-debt decision
- blocked review cycles
- blocked verification cycles
- manual cleanup decisions

When this happens the session moves to `waiting_for_operator`.

## Runtime Visibility

Each session exposes runtime visibility in the UI:

- runtime session id
- tmux socket path
- session-level attach command
- per-role attach command
- per-role capture-pane command
- last automatic recovery information, when applicable

Use these only when the UI-level session state is not enough and you need direct runtime inspection.

The same runtime panel also exposes supported runtime controls for:

- stopping a single role runtime
- restarting a single role runtime
- stopping the whole runtime session
- restarting the whole runtime session

These are recovery tools, not part of the normal happy path.

## Runtime Defaults

Project-local defaults are stored in:

```text
.sdd-factory/settings.local.json
```

Manage them from `Settings → Runtime Defaults`.

This is the supported place for:

- default runner
- per-role runner/model/effort defaults
- per-workflow policy defaults

These defaults apply to future sessions.
Per-session overrides in the session creation form only affect the session being created.

## Recovery Actions

Use recovery actions only when the workflow is blocked, paused, or failed at a specific operational seam.

Recovery actions include:

- `Resume Session`
- `Retry Current Stage`
- `Create Jira Subtasks`
- `Start Subtask Graph`
- `Retry MR Handoff`
- `Retry Send To Test`
- direct runtime input for interactive blockers

These are not normal day-to-day buttons.
If they are needed frequently, treat that as a product/runtime quality issue rather than standard operator practice.

## Shared Knowledge

The UI also supports manual knowledge capture for reusable project guidance.

Use it when a task reveals something future sessions should not rediscover from scratch, for example:

- a project convention that should be followed again
- a hidden implementation constraint
- a non-obvious reuse rule or integration seam

This is a supported operator action, but it is not part of the normal recovery path.

## Cleanup

There are two supported cleanup levels in the UI:

- `Clean Runtime Residue`
  Stops runtime and removes task-local runtime residue while keeping the task snapshot and worktree.
- `Full Cleanup`
  Removes the full task snapshot and worktree when the closed-task gate allows it.
- `Force Full Cleanup`
  Bypasses the closed-task gate and should be treated as an exceptional operator action.

There is also project-level closed-task cleanup automation for definitely closed tasks.

## Deprecated Surface

The old slash-command skills remain in the repository only as deprecated compatibility surface and migration reference.

See:

- [deprecated-surface.md](deprecated-surface.md)

Do not use the deprecated surface as the source of truth for current backend/UI runtime behavior.
