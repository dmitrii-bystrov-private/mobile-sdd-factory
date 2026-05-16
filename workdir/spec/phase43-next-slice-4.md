# Phase 43 Next Slice 4

## Question

What should be the next concrete slice inside `Phase 43` after:

- doctor baseline
- bootstrap guidance baseline
- doctor and guidance product surfaces
- local toolchain doctor expansion

## Candidate Slices

### Option 1. Runtime Capabilities Baseline

Expose the live runner capability surface needed for real operator/runtime configuration:

- available runners
- selectable models per runner
- selectable reasoning/effort levels per runner
- source of truth separation between:
  - runtime-discovered options
  - legacy role defaults

### Option 2. Setup Automation Baseline

Begin bounded repair helpers for the most common missing prerequisites.

### Option 3. Permanent Documentation Baseline

Start the first reconciled permanent docs package.

## Decision

Choose `Runtime Capabilities Baseline`.

## Why

### 1. It unlocks real runtime configuration

The next practical operator gap is no longer only setup diagnosis.

The system now needs a trustworthy source for:

- real models
- real effort/reasoning levels
- runner-specific option sets

### 2. It avoids hardcoding stale UI choices

Legacy `.claude/agents/*.md` values are useful as old defaults, but they are not a reliable runtime catalog.

The UI should not present imaginary or outdated values.

### 3. It creates the factual base for later per-role runtime config

Before adding role-level model/effort controls, we need a bounded capability surface that says what each runner actually supports.
