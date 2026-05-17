# Phase 44 Slice: Runtime Restart And Recovery Baseline

## Goal

Make manual runtime stop actions reversible through explicit operator restart flows.

## Required Outcomes

- operator can restart one stopped role runtime
- operator can restart a full stopped runtime session
- restarted runtimes reuse the same launch plan and role workspace contract
- if the restarted role is the current owner, the current routed work is dispatched again automatically

## Non-Goals

- this slice does not attempt generic crash health-checking yet
- this slice does not try to make Codex and Claude runtime behavior fully symmetric yet
