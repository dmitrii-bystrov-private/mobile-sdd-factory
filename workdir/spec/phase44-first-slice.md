# Phase 44 First Slice

## Question

What should be the first concrete slice inside `Phase 44. Runtime Management, Role Configuration, And MCP Isolation`?

## Candidate Slices

### Option 1. Runtime Session Management Surface

Add an explicit operator surface for:

- live runtime sessions
- live role handles
- stop session
- stop role

### Option 2. Role Runtime Configuration Baseline

Add role-level runner/model/effort configuration backed by real runtime capabilities.

### Option 3. Role-Scoped MCP Baseline

Stop using one broad MCP settings surface and generate role-scoped effective MCP settings.

### Option 4. Codex Parity Validation Baseline

Deepen live Codex validation until it reaches the same confidence level as Claude for the supported runtime path.

## Decision

Choose `Role Runtime Configuration Baseline`.

## Why

### 1. It depends directly on the capabilities work already queued in Phase 43

Once the runtime capability surface exists, the next valuable move is to let the operator configure roles against that real capability set.

### 2. It makes later runtime-management decisions safer

If the product already knows what runner/model/effort each role should use, later stop/restart/recovery semantics become more deterministic.

### 3. It is the natural bridge to MCP isolation

Role-scoped MCP policy becomes much cleaner once each role already has an explicit runtime configuration object.
