# Smart Verification Agent

This note captures the intended design for `IOS-12535`:

- Jira: `IOS-12535`
- Title: `Smart Verification Agent for targeted mobile verification`

It is a product/design note for the current Constellation runtime, not an implementation-complete spec.

## Problem

The current verification lane is too coarse.

Today `verification-coordinator` is effectively:

- one shared role for both iOS and Android
- one broad workflow-level gate
- one default strategy: run heavy wrappers

In practice this means:

- no platform-specific intelligence
- no target/module-aware verification
- no selective test execution
- no explanation of why a particular path was chosen
- no safe parallel verification across several worktrees

Current implementation seams that reflect this:

- `backend/coordinator/service.py`
- `backend/tools/verification_adapter.py`
- `backend/roles/prompts.py`
- `backend/roles/workspace.py`
- `scripts/run-test.sh`
- `scripts/run-lint.sh`
- platform-native build scripts under the mobile repos

## Goals

The verification agent should:

- choose the cheapest correct verification path for the current task
- treat iOS and Android as separate first-class verification paths
- explain why a strategy was selected
- use broad wrappers as a fallback, not as the default for everything
- support safe parallel execution for multiple task worktrees

## Non-Goals

- replacing wrappers entirely
- making unsafe guesses when confidence is low
- forcing a single cross-platform strategy contract when the platforms differ materially
- blocking current workflow progress on a full verifier rewrite

## Core Decision

The current single generic verifier should evolve into a strategy-driven verifier with platform-specific execution paths.

The model should be:

1. detect platform and changed surface
2. inspect repo signals
3. choose the narrowest safe verification plan
4. explain the choice
5. execute
6. fall back to broader verification when confidence is insufficient

## Current Weaknesses

### 1. Shared role contract for iOS and Android

The current `verification-coordinator` prompt is workflow-level and generic.

That is too weak because:

- iOS verification constraints are dominated by Xcode, DerivedData, simulator state, Tuist, CocoaPods
- Android verification constraints are dominated by Gradle module graph, test task selection, build cache, variants

These should not be treated as one generic command-selection problem.

### 2. Broad wrappers as the only real strategy

Right now the contract says, effectively:

- run `bash scripts/run-test.sh "$SDD_FACTORY_TASK_KEY"`
- run `bash scripts/run-lint.sh "$SDD_FACTORY_TASK_KEY"`

This is stable, but too expensive and too opaque.

### 3. No worktree-local build isolation

This is especially painful for iOS.

Without task-local verification state:

- concurrent verification runs can conflict
- cleanup is harder
- build/test artifacts are harder to inspect and reuse

### 4. No prepare/build/test separation

The future smart verifier must be able to distinguish:

- environment/project preparation
- compile/build verification
- test execution

If those are always glued together, there is no real room for “smart” verification.

## Target Architecture

## A. Strategy-Driven Verification Lane

Keep one workflow-level verification lane in orchestration terms, but make its internal execution strategy explicit.

The lane should produce a structured verification plan with fields like:

- `platform`
- `confidence`
- `prepare_required`
- `selected_scope`
- `selected_commands`
- `fallback_reason`
- `report_paths`

That plan should be reflected in `spec/final-verification.md` and optionally in a machine-readable verification artifact.

## B. Platform-Specific Specialists

Two concrete execution paths should exist behind the same coordinator lane:

- `ios_verification_strategy`
- `android_verification_strategy`

This does not necessarily require two top-level runtime roles on day one.

A pragmatic first step is:

- keep `verification-coordinator` as the routed role
- split strategy selection and command generation internally by platform

Later, if needed, those can become separate long-running roles.

## C. Explicit Verification Strategy Selection

The verifier should decide among several safe strategy classes, for example:

- `broad_wrappers`
- `targeted_build_only`
- `targeted_build_plus_selected_tests`
- `test_without_building`
- `platform_prepare_then_targeted_verification`

Each chosen strategy must be explainable.

## D. Worktree-Local Verification State

Verification must become task-local and disposable.

Each task should get a verification state root under its worktree, for example:

```text
$SDD_WORKDIR/<KEY>/.verification/
```

For iOS this should hold things like:

- `DerivedData`
- `xcresult`
- logs
- cloned source packages

For Android this should hold things like:

- logs
- task-local temp outputs when needed
- optional redirected Gradle-local state where practical

This is important for:

- safe parallel runs
- deterministic cleanup
- artifact reuse
- post-failure inspection

## iOS Path

The iOS path is the clearest immediate win.

### Required Direction

Introduce a task-local build context, for example:

```text
$SDD_WORKDIR/<KEY>/.verification/ios/
```

It should own:

- `DerivedData`
- `xcresult`
- logs
- `clonedSourcePackages`

### Required Command-Level Changes

The verifier should stop relying on implicit shared Xcode state.

Where targeted iOS commands are used, they should explicitly pass:

- `-derivedDataPath`
- `-resultBundlePath`
- `-clonedSourcePackagesDirPath`

### iOS Prepare Policy

The verifier should decide whether prepare steps are needed by repo signals.

Examples:

- if `Tuist.swift` or `Tuist/` changes: regeneration may be required
- if `Podfile` or `Podfile.lock` changes: dependency install may be required
- if only Swift/test/resource files change within existing targets: regeneration is usually unnecessary

### iOS Efficient Test Policy

The verifier should support:

- `build-for-testing`
- `test-without-building`

This allows:

- build once
- test many
- cheaper reruns
- more practical shard/retry behavior

### iOS Parallel-Safety Rules

To support several worktrees on one machine:

- every task gets its own `DerivedData`
- every task gets its own `xcresult`
- every task gets its own source packages directory
- simulator allocation must avoid shared mutable state collisions

## Android Path

Android needs the same strategic shape, even if the concrete mechanics differ.

The verifier should learn to inspect:

- affected Gradle modules
- affected build variants
- whether targeted module tasks are safe
- whether broad fallback is required

The main requirement is symmetry of design intent:

- Android must not remain “generic fallback forever” while only iOS gets a smart path

## Decision Inputs

Before selecting commands, the verifier should inspect signals such as:

- changed file paths
- platform ownership of changed files
- module/target ownership heuristics
- manifest/build configuration changes
- dependency definition changes
- test file changes
- generated/project-layout affecting files

These signals should be documented and conservative.

When confidence is low, the verifier must fall back.

## Fallback Policy

The broad wrapper path remains necessary.

It should be used when:

- affected platform cannot be determined confidently
- target/module mapping is uncertain
- prepare-state confidence is low
- targeted command selection would be too risky

The key difference is:

- fallback becomes an explicit decision
- not the silent default

## Reporting Contract

`spec/final-verification.md` should evolve from a plain pass/fail report into a verification decision report.

At minimum it should capture:

- selected platform
- selected strategy
- repo signals that influenced the choice
- commands actually run
- whether fallback occurred
- why fallback occurred
- key outputs and artifact paths

This is required for trust and debuggability.

## Proposed Implementation Slices

### Slice 1: Verification Strategy Contract

Goal:

- introduce an internal strategy model without changing platform command behavior yet

Repo areas:

- `backend/tools/verification_adapter.py`
- `backend/coordinator/service.py`
- `backend/roles/prompts.py`
- `backend/roles/workspace.py`

Deliverables:

- structured verification plan object
- report format for chosen strategy
- explicit fallback semantics

### Slice 2: iOS Worktree-Local Verification Context

Goal:

- isolate iOS verification state per task

Repo areas:

- verification adapter layer
- wrapper scripts or new helper scripts
- docs for task-local verification artifacts

Deliverables:

- task-local verification root
- explicit `DerivedData` / `xcresult` / logs paths
- cleanup-safe behavior

### Slice 3: iOS Prepare / Build / Test Separation

Goal:

- stop treating every verification run as a full expensive preflight

Deliverables:

- explicit prepare step
- prepare decision rules
- targeted build-only path
- targeted test path

### Slice 4: iOS Targeted Verification

Goal:

- choose narrower safe commands where confidence is high

Deliverables:

- target/module-aware path selection
- selected test execution where safe
- `build-for-testing -> test-without-building` flow

### Slice 5: Android Strategy Parity

Goal:

- provide the same decision-model architecture for Android

Deliverables:

- Android module/variant-aware strategy path
- Android broad fallback rules
- matching reporting contract

### Slice 6: Parallel Verification Support

Goal:

- make concurrent verification for multiple worktrees safe and intentional

Deliverables:

- verified task-local state isolation
- resource-allocation policy
- documented concurrency constraints

## Recommended First Implementation Order

For this repo, the safest order is:

1. strategy contract and reporting
2. iOS task-local verification state
3. iOS prepare/build/test separation
4. iOS targeted command selection
5. Android parity
6. cross-worktree concurrency hardening

This order gives useful progress early without forcing a full cross-platform redesign up front.

## Concrete Repo Changes To Expect

Likely code changes will concentrate around:

- `backend/tools/verification_adapter.py`
  - evolve from fixed wrapper calls to strategy-aware command selection
- `backend/coordinator/service.py`
  - route/report verification strategy decisions
- `backend/roles/prompts.py`
  - teach verifier to justify command choice, not just run wrappers
- `backend/roles/workspace.py`
  - expose task-local verification paths and strategy contract
- `scripts/run-test.sh`, `scripts/run-lint.sh`
  - keep as broad fallback path
- new helper scripts
  - likely platform-specific prepare/build/test helpers

## Orchestration Audit Required

This initiative should explicitly include an orchestration audit for verification failure handling.

Observed risk:

- tasks with failing tests can still progress to MR handoff
- failures then surface only in CI instead of being corrected inside the task session

This is a workflow bug, not only a verifier-quality issue.

The audit should confirm:

- verification failure always blocks delivery progression
- failing verification cannot silently transition into MR handoff
- correction loops are re-entered deterministically after failed verification
- session state, work items, and runtime dispatch stay aligned after verification failure
- no stale or malformed verifier output can be misclassified as `verification_passed`

Specific repo areas to inspect during implementation:

- `backend/coordinator/service.py`
- verification event mapping and acceptance logic
- delivery gating before `mr_handoff_completed`
- retry / resume / reopen semantics after failed verification

Expected outcome:

- a task with red tests or red lint should be corrected inside the orchestration loop
- MR creation should remain downstream of a genuinely green verification outcome

## Recommendation

Do not implement this as:

- “same verifier, but with more if-statements around wrapper execution”

Implement it as:

- explicit strategy selection
- explicit task-local verification state
- explicit platform-aware execution paths
- explicit fallback reasoning

That is the minimum shape that deserves the name “Smart Verification Agent”.
