# SDD Factory Project Charter

## Purpose

Transform the current `SDD Assistant` orchestration model into `SDD Factory`: a task-scoped, persistent-session control plane for mobile delivery workflows.

## Core Hypothesis

The project succeeds if one Jira task can be handled by a persistent session that:

- survives repeated implementation, review, and verification iterations
- keeps explicit state outside the model
- uses deterministic orchestration wherever ambiguity is absent
- reuses long-lived role terminals instead of cold-starting short-lived agents

## Problem Statement

The current workflow repeatedly restarts agent roles across loops such as:

- implementation
- self-review fixes
- verification fixes
- MR feedback
- QA reopen cycles

This causes repeated context rereads, token waste, latency, and orchestration drift.

## V1 Goal

Deliver a local system built on `Python + FastAPI + SQLite + tmux` that proves task-scoped persistent execution for one Jira task using:

- `task-coordinator`
- `implementer`
- `verification-coordinator`

## V1 Success Criteria

- one task session is persisted in SQLite
- one implementer session survives implementation and multiple fix rounds without restart
- deterministic verification runs independently from agent claims
- coordinator routes explicit events and records artifacts
- operator can inspect and control a session through an API, with UI following after the control plane exists

## Non-Goals For V1

- workflow editor
- semantic/vector memory
- multi-backend runtime support beyond the abstraction seam
- generalized multi-repo / multi-tracker platform
- terminal-first or chat-first operator UX
- broad multi-agent society

## Constraints

- temporary specs and planning artifacts live under `workdir/spec/`
- existing `scripts/` should be reused as deterministic adapters where possible
- `tmux` is runtime infrastructure, not product UX
- coordinator control must remain deterministic and auditable

## Current Status

Backend MVP, the first stable operator UI milestone, lifecycle extension, delivery/handoff, workflow-control, workflow-coverage, and the shared knowledge base foundation are now complete.

The system now includes:

- explicit bug-analysis coverage
- explicit story planning/spec coverage
- sequential subtask-graph orchestration
- repo-visible knowledge from review feedback and session insights
- repo-visible QA knowledge and operator-visible knowledge browsing

The next missing proof is no longer basic orchestration, delivery completion, workflow coverage, or the first curated knowledge/governance loop.

The active productizing gaps are now:

- environment setup and diagnosis
- runtime capability discovery for real runner/model/effort options
- runtime session management
- per-role runtime configuration
- role-scoped MCP isolation
- codex parity depth

Permanent documentation remains intentionally deferred until those operational/runtime surfaces stabilize and can be reconciled against the final implementation.
