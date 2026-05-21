# Smart Verification Agent Backlog

## Goal

Incrementally replace the current generic verification worker with a platform-aware verification system that:

- chooses the cheapest safe verification path,
- supports parallel worktrees cleanly,
- keeps workflow-level verification authority inside the verifier lane,
- and blocks delivery when verification has not actually converged.

This backlog is local planning only. It is not a Jira decomposition.

## Workstream 1: Verification Contract

### 1.1 Split platform responsibilities

- Introduce explicit iOS and Android verification paths instead of one generic verifier behavior.
- Keep one orchestration entrypoint, but make the execution strategy platform-specific.

### 1.2 Define a verification strategy object

- Add a machine-readable strategy structure selected before verification starts.
- Strategy should capture:
  - platform,
  - confidence level,
  - selected verification mode,
  - exact commands,
  - fallback path,
  - human-readable reason.

### 1.3 Tighten role boundaries

- Verifier owns workflow-level build/test/lint decisions.
- `implementer`, `bug-fixer`, and other non-verifier roles must not run broad verification gates.
- Narrow task-local checks remain allowed only when explicitly routed.

## Workstream 2: iOS Task-Local Build Context

### 2.1 Isolated verification workspace

- Add task-local paths for:
  - `DerivedData`
  - `xcresult`
  - build logs
  - test logs
  - cloned source packages

### 2.2 Parallel-safe execution

- Ensure two worktrees can verify concurrently without colliding through shared Xcode state.
- Remove implicit dependence on global machine-wide build directories where possible.

### 2.3 Explicit cleanup policy

- Define what is retained between verification rounds and what is disposable.
- Prefer cheap local cleanup over destructive global cleanup.

## Workstream 3: Verification Pipeline Decomposition

### 3.1 Separate prepare / build / test / lint phases

- Stop treating verification as one opaque wrapper call.
- Represent phases explicitly so the verifier can choose a cheaper safe route.

### 3.2 Add repo-signal based preparation rules

- Decide when `tuist generate` is needed.
- Decide when dependency/bootstrap refresh is needed.
- Avoid unconditional heavy prepare steps.

### 3.3 Support build-for-testing / test-without-building

- Reuse build products when safe.
- Avoid recompiling when only the test execution phase must be repeated.

## Workstream 4: Targeted Verification Decisions

### 4.1 Changed-file aware routing

- Use changed files plus repo signals to choose between:
  - targeted test,
  - targeted build,
  - broad test,
  - broad build + test.

### 4.2 Confidence-based fallback

- When confidence is low, prefer the broader safe path.
- Do not pretend to be smart when the verifier lacks enough signal.

### 4.3 Human-readable verification report

- Record:
  - chosen strategy,
  - why it was chosen,
  - what was intentionally skipped,
  - why fallback happened,
  - exact commands that ran.

## Workstream 5: Orchestration Audit

### 5.1 Delivery gating

- Verify that failed verification cannot proceed to MR handoff or send-to-test.
- Verify that verifier output cannot be misclassified as passed when checks failed.

### 5.2 Deterministic correction loops

- Ensure verification failure always re-enters the correction loop cleanly.
- Ensure correction rounds do not silently degrade into delivery.

### 5.3 Runtime/session consistency

- Ensure session state, active work item, verifier runtime, and follow-up dispatch remain aligned across retries and restarts.

## Recommended Implementation Order

1. iOS task-local verification context
2. Verification strategy object and reporting contract
3. Prepare/build/test phase split
4. Targeted iOS decision engine with safe fallback
5. Orchestration audit and delivery-gate hardening
6. Android-specific strategy parity

## Likely Code Touchpoints

- `backend/roles/prompts.py`
- `backend/roles/workspace.py`
- `backend/coordinator/service.py`
- `backend/session_policy.py`
- `scripts/run-build.sh`
- `scripts/run-test.sh`
- `scripts/run-lint.sh`
- new iOS-specific verification helpers under `scripts/`
- verifier result/report materialization under `spec/final-verification.md`

## First Practical Slice

The first slice should deliver real user value without requiring the full smart verifier:

- introduce task-local iOS verification paths,
- make verifier output explain the chosen route,
- separate prepare from build/test,
- and keep the current broad fallback available.

That gives:

- safer parallel worktrees,
- lower average verification cost,
- better observability,
- and a stable base for later targeting logic.
