# Phase 44 Blocker: Codex MCP Isolation Seam

## Problem

`Role-Scoped MCP Baseline` needs a reliable way to restrict MCP availability per role for both:

- `claude`
- `codex`

For Claude, the launcher already has a clear settings seam.

For Codex, the local CLI currently exposes:

- global/shared MCP configuration
- `codex mcp list`
- config overrides via `-c`

but the local probes so far do not show a reliable per-session MCP filtering path.

## What Was Tested

- `codex mcp list`
- `codex mcp get ios-rag`
- `codex mcp list -c 'mcp_servers={}'`
- `codex mcp list -c 'mcp_servers={\"ios-rag\"={url=\"https://mcp.finom.world/mcp/swift\"}}'`

## Observation

The override probes did not change the active MCP list in the expected way.

That means we do not yet have a trustworthy implementation seam for:

- runner-agnostic role MCP isolation
- or a Codex-specific per-launch filtered MCP set

## Decision

Do not ship a fake "role-scoped MCP" implementation that only truly isolates Claude.

Treat this as a real blocker until the Codex config/runtime seam is understood well enough to implement the feature honestly.

## Safe Next Step

Before coding `Role-Scoped MCP Baseline`, reconcile the actual Codex MCP configuration model and identify one of:

1. a supported per-session override mechanism
2. a supported project-local config mechanism
3. an explicit decision that Codex MCP isolation is unsupported and must remain deferred
