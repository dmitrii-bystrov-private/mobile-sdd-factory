# Phase 44 Next Slice

## Question

What should be the next concrete slice inside `Phase 44` after the runtime-management and Claude MCP isolation groundwork?

## Candidate Slices

### Option 1. Runtime Restart And Recovery Baseline

Add explicit operator restart flows after manual runtime stop actions.

### Option 2. More Realistic Live Runtime Contract

Reduce the gap between the current transitional routed prompt packet and the intended role model:

- keep `AGENTS.md` as the durable role contract
- move toward shorter live trigger text instead of repeating the full role framing in every routed work packet
- validate that launcher-backed roles still complete correctly under that more realistic contract

### Option 3. Codex Parity Validation Baseline

Deepen live validation on Codex until runtime expectations are symmetric enough with Claude.

### Option 4. Runtime Crash Auto-Recovery Baseline

Move beyond manual restart into health-check and respawn behavior for killed persistent roles.

## Decision

Choose `More Realistic Live Runtime Contract`.

## Why

### 1. Current live tests still prove a transitional contract

The system currently works with a routed `ROUTED_WORK.md` packet that still repeats:

- role name
- role-specific rules
- output protocol instructions

That is practical for stabilization, but it is not yet the most realistic end-state for persistent roles that should primarily rely on `AGENTS.md` plus a short per-round trigger.

### 2. This makes the next live proofs more meaningful

If we do not tighten the role contract now, later Codex parity work may prove the wrong thing: compatibility with an over-specified transitional prompt rather than the intended persistent-role model.

### 3. Codex parity should come immediately after this tightening

Once the live contract becomes more realistic for Claude, the same contract should be used to validate Codex end-to-end rather than leaving Codex on a shallower proof path.

### 4. Restart/recovery still matters, but it can follow runtime-contract realism

Explicit restart semantics remain important, but they do not change the core question of what exactly we are proving in live runner validation.
