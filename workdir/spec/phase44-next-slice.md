# Phase 44 Next Slice

## Question

What should be the next concrete slice inside `Phase 44` after runtime management, Claude MCP isolation, the more realistic live role contract, Codex live parity, and task/runtime cleanup work?

## Candidate Slices

### Option 1. Native Session Continuation Baseline

Make operator restart/resume actions continue the previous runner session natively instead of recreating a fresh live session and redispatching work.

### Option 2. Runtime Crash Auto-Recovery Baseline

Add health-check and respawn behavior for unexpectedly dead persistent role sessions.

### Option 3. Permanent Documentation Start

Begin moving temporary knowledge from `workdir/spec/` into permanent project docs.

## Decision

Choose `Native Session Continuation Baseline`.

## Why

### 1. The restart path is operationally useful but architecturally transitional

The current restart flow works, but it is still:

- recreate runtime
- rehydrate context
- redispatch current work

That is useful as a safety net, but it is not the desired end-state for persistent live sessions.

### 2. The user-facing expectation is continuation, not reconstruction

When an operator resumes a previously interrupted role, the right behavior is:

- continue the previous native runner session
- send a short continuation instruction if needed
- avoid cold-starting a new session unless native continuation is impossible

### 3. The older blockers are already behind us

The next slice is no longer:

- AGENTS-first realism
- Codex two-round parity
- MCP policy clarification
- task/test cleanup

Those are already complete enough to stop driving the phase.

### 4. Crash recovery should follow true continuation semantics

Automatic respawn/recovery is easier to design cleanly once the explicit operator-driven continuation model is correct.
