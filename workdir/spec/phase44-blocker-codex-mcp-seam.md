# Phase 44 Note: Codex MCP Policy

## Clarification

`Role-Scoped MCP Baseline` no longer treats Codex as a blocker.

The product policy is now:

- `Claude` requires role-scoped MCP isolation
- `Codex` keeps MCP global by design

## Result

The old assumption that role-scoped MCP had to work identically for both runners was wrong.

The practical implication is simple:

- do not spend more implementation effort trying to fake Codex role-scoped MCP
- keep Codex launcher behavior unchanged
- scope `Phase 44` MCP isolation work to `Claude` only
