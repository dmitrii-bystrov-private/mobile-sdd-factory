# Runtime Model

This document describes the supported runtime model of SDD Factory.

## Core Principles

The supported platform is built around:

- backend-owned session state
- persistent tmux-backed role runtimes
- operator UI as the primary control surface
- long-running quality lanes instead of repeated stateless one-shot passes

The runtime model is intentionally different from the deprecated slash-command orchestration surface.

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
- `code-reviewer`
- `code-scout`
- `verification-coordinator`
- planning workers such as `proposal-context-worker`, `requirements-clarifier-worker`, `spec-verifier-worker`, and `task-decomposer-worker`
- follow-up workers such as `mr-comments-analyst-worker` and `doc-harvest-worker`

Some roles are short planning lanes.
Some roles are persistent long-runners.

## Persistent Long-Runners

The most important supported long-running roles are:

- `implementer`
- `code-reviewer`
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

- self-review
- Boy Scout
- doc harvest

## Follow-Up Flows

The supported platform routes follow-up work back into the same runtime model instead of branching into disconnected side paths.

Important follow-up inputs:

- MR comments
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
- redirect parked work to another allowed role
- runtime input for interactive blockers
- runtime stop / restart at role or session level
- automatic runtime recovery after owner-runtime death

The supported rule is:

- happy path should be automatic
- operator involvement should happen only when the workflow cannot safely proceed

## Cleanup Model

Task cleanup is explicit and lifecycle-aware.

Supported cleanup actions:

- runtime residue cleanup
- full task cleanup when closed-task rules allow it
- forced full cleanup for exceptional operator use

Acceptance/test runtime cleanup is isolated separately under project-scoped runtime roots.

## Deprecated Surface

The deprecated slash-command surface is not the source of truth for this runtime model.

See:

- [deprecated-surface.md](deprecated-surface.md)
