# Phase 44 Next Slice

## Question

What should be the next concrete slice inside `Phase 44` after `Role Runtime Configuration Baseline`?

## Candidate Slices

### Option 1. Role-Scoped MCP Baseline

Stop using one broad shared MCP settings surface and generate effective MCP settings per role.

### Option 2. Runtime Session Management Surface

Add explicit operator visibility and stop controls for live runtime sessions and roles.

### Option 3. Codex Parity Validation Baseline

Deepen live validation on Codex until runtime expectations are symmetric enough with Claude.

## Decision

Choose `Role-Scoped MCP Baseline`.

## Why

### 1. Runtime config without MCP isolation is still incomplete

The product can now choose runner/model/effort, but each role still receives MCP availability too broadly.

### 2. MCP isolation is part of role correctness, not a later nicety

It directly affects:

- context cleanliness
- predictability
- role boundary discipline

### 3. It stays bounded

The launcher already has a settings injection seam.

The next step is to make that seam role-specific instead of global.
