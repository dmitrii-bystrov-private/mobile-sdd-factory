# Phase 44 Direction

## Question

What should become the next named phase after the current setup/doctor track?

## Decision

Reserve `Phase 44. Runtime Management, Role Configuration, And MCP Isolation` as the next productizing phase after the active `Phase 43` setup/doctor work.

## Why This Must Become A Real Phase

### 1. Runtime sessions are not yet a first-class operator surface

Today the operator can inspect task sessions and lifecycle state, but cannot yet reliably:

- see live runtime handles as first-class runtime objects
- stop a persistent runtime role intentionally
- stop a full task runtime session intentionally
- restart or recover a killed persistent role through an explicit product flow

### 2. Per-role runtime configuration is still missing

The system does not yet expose real role-level runtime configuration for:

- runner type
- model
- reasoning/effort

Legacy `.claude/agents/*.md` values exist, but they are not yet the runtime contract.

### 3. Role-scoped MCP isolation is not implemented

The current launcher path still uses broad shared settings rather than a role-scoped effective MCP set.

That means:

- MCP availability is too coarse
- role isolation is weaker than intended
- runtime behavior is less predictable than the old role contracts implied

### 4. Codex parity is still shallower than Claude parity

The code path exists, but the live validation depth is still stronger for Claude than for Codex.

That makes runtime configuration and product expectations incomplete.

## Phase 44 Target

This phase should produce four durable outcomes:

1. a real runtime-session management surface
2. explicit stop/restart/recovery semantics
3. per-role runtime configuration with real runner/model/effort options
4. role-scoped MCP settings instead of global launcher-wide MCP exposure

## Non-Goal

This phase should not write permanent docs first.

The work here is still operational/runtime productization and may still move the final documentation shape.
