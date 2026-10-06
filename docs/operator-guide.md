# Operator Guide

This guide describes the supported day-to-day workflow for the current Constellation: Agent Runtime platform.

Use this document for the backend/UI runtime model.

## Primary Entry Point

The normal entry point is the operator UI.

From the UI you can:

- create a session for a Jira key
- choose `story_full` or `oneshot`
- adjust per-role runtime config for this session
- manage runtime state, recovery, and cleanup
- inspect live runtime handles and tmux commands

## Session Creation

When starting a new task:

1. Enter the Jira key.
2. Choose the workflow profile:
   - `story_full` for full planning + decomposition + execution
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
- convention review
- requirements review
- verification
- MR handoff
- send-to-test

## When Operator Input Is Expected

Launcher confirmation menus with an affirmative option are accepted automatically, including permission to run a Claude dynamic workflow. These confirmations do not require `Send Runtime Input` or move the session to `waiting_for_operator`.

Operator input is expected only when the workflow genuinely cannot continue safely on its own.

Typical cases:

- requirements clarification
- blocked review cycles
- blocked verification cycles

When this happens the session moves to `waiting_for_operator`.

If the interactive state explicitly requires a direct reply in the same live role session, use `Send Runtime Input`.
Use `Resume Session` or `Retry Current Stage` only for recovery-style blockers after the underlying problem has been fixed.

## Runtime Visibility

An active Codex model-capacity error is retried automatically on the configured model. Recovery events
record `recovery_reason=model_capacity`. Persistent failures retry after cooldown; the Codex shortcut
and warning footer does not prevent detection. Working output and pending terminal results prevent pokes.

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

QA/e2e tasks accept QA Jira links in the normal start form. The QA/E2E settings control smoke inclusion,
fresh installs, selected-test limits, time budgets and failure retries. Machine paths/devices/ports use
ENV instead. See [e2e-workflow.md](e2e-workflow.md). Failed test regressions use the correction loop;
environment failures require recovery. Evidenced baseline failures also allow an explicit operator
decision. Retry Current Stage starts a new gate after recovery.
QA native verdicts govern this routing even when a worker submits a blocked-cycle outcome. A legacy
"Verification cycle resolution" item can also be retried after recovery; retry replaces it with a fresh
verification work item and strategy.
With a configured dedicated iOS pool, verification uses a free factory simulator independently of
workspace runs. When every pool slot is occupied, the gate waits while it remains active; the total
verification time limit still applies. The selected simulator is shut down after tests, retries and
baseline comparisons. Its cleanup outcome and any errors remain in the native verification report.
The recovery card says "E2E verification is blocked" and includes a "Retry verification" button directly
below its explanation. The separated footer describes when to retry. Infrastructure or baseline failures
do not require a text reply to the verifier. Baseline failures identify the scenario and retain the task
and baseline error messages separately; they do not claim that a broken baseline proves an SDK problem.
For actual failures on both test revisions, select the findings you accept and choose "Continue with
findings". Add an optional comment or linked issue. The factory retains the failures and operator
decision, runs every remaining scenario and platform, and records accepted_with_warnings if those
checks pass. "Request corrections" sends the problem to implementation; "Retry verification" starts
a fresh gate and does not inherit accepted findings. Setup/teardown failures cannot be accepted through
baseline findings, even when both test revisions fail; correct the execution recipe/environment and retry.
Missing builds, occupied devices and other
preflight failures cannot be accepted through this action. Changing the source, execution strategy, task support files or app
build invalidates the decision. Acceptance is specific to this gate, not a global quarantine.
After fixing an environment failure during continuation, "Retry continuation" resumes the same gate
with your decisions. It keeps the reviewed build even if a newer master build becomes available.
The verifier derives project execution commands from the current checkout and records them in the
common verification strategy. Older QA sessions using the retired separate-plan contract need a fresh
verification retry; their former operator decisions remain in history and do not approve new execution.

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
