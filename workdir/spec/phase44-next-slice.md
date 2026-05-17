# Phase 44 Next Slice

## Question

What should be the next concrete slice inside `Phase 44` after `Claude Role-Scoped MCP Baseline`?

## Candidate Slices

### Option 1. Runtime Restart And Recovery Baseline

Add explicit operator restart flows after manual runtime stop actions.

### Option 2. Codex Parity Validation Baseline

Deepen live validation on Codex until runtime expectations are symmetric enough with Claude.

### Option 3. Runtime Crash Auto-Recovery Baseline

Move beyond manual restart into health-check and respawn behavior for killed persistent roles.

## Decision

Choose `Runtime Restart And Recovery Baseline`.

## Why

### 1. Manual stop without restart semantics is still incomplete

The operator can now stop runtime roles and sessions, but cannot yet bring them back through an explicit product flow.

### 2. Restart is a direct follow-up to the new runtime-management surface

Without restart, stop control is only half of the operational story.

### 3. It stays bounded

The launch plan, role workspace, and runtime-state surfaces already exist.

The next step is to reconnect those existing pieces into an explicit restart path.
