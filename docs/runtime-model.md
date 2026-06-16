# Runtime Model

This document describes the supported runtime model of Constellation: Agent Runtime.

## Core Principles

The supported platform is built around:

- backend-owned session state
- persistent tmux-backed role runtimes
- operator UI as the primary control surface
- long-running quality lanes instead of repeated stateless one-shot passes

## Sessions

A session is the top-level unit of execution for a Jira task.

A session includes:

- task key
- workflow profile
- policy values
- current stage
- current owner
- work items
- artifacts
- runtime session state

Supported workflow profiles:

- `story_full`
- `bug_full`
- `oneshot`

## Roles

The platform routes work to specialized roles.

Important roles include:

- `implementer`
- `bug-fixer`
- `convention-reviewer`
- `requirements-reviewer`
- `verification-coordinator`
- planning workers such as `proposal-context-worker`, `requirements-clarifier-worker`, `spec-verifier-worker`, and `task-decomposer-worker`
- follow-up workers such as `doc-harvest-worker`

Some roles are short planning lanes.
Some roles are persistent long-runners.

## Persistent Long-Runners

The most important supported long-running roles are:

- `implementer`
- `convention-reviewer`
- `requirements-reviewer`
- `verification-coordinator`

The platform intentionally keeps these roles alive across rounds so they retain context.

This supports:

- native continuation after restart
- correction loops without stateless drift
- explicit blocked-cycle outcomes such as:
  - `blocked_review_cycle`
  - `blocked_verification_cycle`

## Runtime Host

The supported operational host is `tmux`.

The platform no longer treats older host variants as supported operational modes.

`tmux` is used for:

- persistent role windows
- runtime visibility
- manual attach/capture for debugging
- restart and continuation
- automatic recovery

## Runtime Defaults

Runtime defaults are project-local and stored in:

```text
.sdd-factory/settings.local.json
```

They define:

- default runner
- per-role runner/model/effort defaults
- per-workflow policy defaults

These defaults are surfaced and edited through the UI.

They are distinct from `.claude/settings.json` or `.claude/settings.local.json`, which remain Claude-specific launcher source material for scoped permissions and MCP visibility rather than the supported runtime-defaults store.
The launcher filters those Claude settings per role and does not copy `env` values into worker-local settings.

MCP visibility is role-scoped for Claude sessions. Current built-in baselines expose `ios-rag`, `android-rag`, and `frontend-rag` to `implementer`, `bug-fixer`, and `proposal-context-worker`; other roles receive an empty scoped MCP config by default.

## Policy Semantics

Optional lanes follow this model:

- `disabled`
- `enabled`
- `required`

`enabled` means:

- the lane auto-starts
- the agent may emit `skipped_not_needed`

`required` means:

- the lane auto-starts
- `skipped_not_needed` is not allowed

This applies to optional quality/documentation lanes such as:

- review gate
- doc harvest

## Follow-Up Flows

The supported platform routes follow-up work back into the same runtime model instead of branching into disconnected side paths.

Important follow-up inputs:

- QA reopen comments
- refreshed Jira subtasks

These can materialize new follow-up subtasks and re-enter execution through the subtask graph.

## Delivery Model

Delivery is part of the workflow, not a separate manual phase.

The normal supported path is:

- verification passes
- task completes
- MR handoff runs automatically
- send-to-test runs automatically

Manual delivery actions remain as recovery tools only when automatic delivery fails.

## Recovery Model

Recovery is first-class in the runtime model.

The platform supports:

- pause / resume
- retry current stage
- runtime input for interactive blockers
- runtime stop / restart at role or session level
- automatic runtime recovery after owner-runtime death

For live runtime escalations, roles should distinguish between:

- interactive blockers that need a direct operator reply in the same live session
- runtime/tooling/recovery blockers that need retry, resume, or external repair instead

Use `SDD_ERROR` for both, but set `needs_operator_input: true` only for the first case.

The supported rule is:

- happy path should be automatic
- operator involvement should happen only when the workflow cannot safely proceed

## Cleanup Model

Task cleanup is explicit and lifecycle-aware.

Supported cleanup actions:

- runtime residue cleanup
- full task cleanup when closed-task rules allow it

Acceptance/test runtime cleanup is isolated separately under project-scoped runtime roots.
Forced full cleanup remains an internal emergency seam rather than part of the normal supported operator model.
