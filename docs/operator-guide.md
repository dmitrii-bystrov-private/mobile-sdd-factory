# Operator Guide

This guide describes the supported day-to-day workflow for the current Constellation: Agent Runtime platform.

Use this document for the backend/UI runtime model.

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
  Refreshes the task snapshot while a session is active, or reopens a completed `story_full` session when new subtasks appear after delivery.
- `Refresh Subtask State`
  Pulls the latest Jira subtask state while story execution is active and reconciles the remaining subtask queue around the currently active subtask.

Most of the time the workflow should progress automatically through:

- planning
- decomposition
- implementation
- self-review
- Code Scout
- verification
- MR handoff
- send-to-test

## When Operator Input Is Expected

Operator input is expected only when the workflow genuinely cannot continue safely on its own.

Typical cases:

- requirements clarification
- Code Scout findings that include old-code candidates and need a tech-debt decision
- blocked review cycles
- blocked verification cycles

When this happens the session moves to `waiting_for_operator`.

If the interactive state explicitly requires a direct reply in the same live role session, use `Send Runtime Input`.
Use `Resume Session` or `Retry Current Stage` only for recovery-style blockers after the underlying problem has been fixed.

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

Manage them from the `Runtime Defaults` panel in the operator sidebar.

This is the supported place for:

- default runner
- per-role runner/model/effort defaults
- per-workflow policy defaults

This is not the same thing as `.claude/settings.json` or `.claude/settings.local.json`.
Those Claude files are only used as Claude-specific permission/MCP source material for scoped launcher sessions.
The launcher filters MCP servers and MCP permissions per role, and it does not copy `env` values into worker-local Claude settings.

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

## Cleanup

There are two supported cleanup levels in the UI:

- `Clean Runtime Residue`
  Stops runtime and removes task-local runtime residue while keeping the task snapshot and worktree.
- `Full Cleanup`
  Removes the full task snapshot and worktree when the closed-task gate allows it.

There is also project-level closed-task cleanup automation for definitely closed tasks.
Forced full cleanup remains an internal emergency seam rather than a normal supported operator action.
