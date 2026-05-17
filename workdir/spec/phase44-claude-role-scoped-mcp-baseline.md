# Phase 44 Slice: Claude Role-Scoped MCP Baseline

## Goal

Make Claude-backed roles receive only the MCP servers implied by their role contract, while keeping Codex MCP explicitly global.

## Required Outcomes

- `Claude` launcher path no longer relies on one broad shared MCP-enabled settings surface
- each Claude role gets an effective scoped settings file plus scoped MCP config
- the source of truth for allowed Claude MCP servers comes from legacy role contracts
- `Codex` behavior is left unchanged and documented as global-by-design

## Notes

- this slice is about runtime isolation, not user-configurable MCP editing
- it should preserve non-MCP Claude settings and only filter MCP-related settings
