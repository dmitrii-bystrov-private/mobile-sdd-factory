# iOS Verification Target Mapping

## Goal

Add a conservative target/module mapping layer for the iOS verifier so it can narrow verification scope safely when confidence is high, and fall back to the current broad-safe path when confidence is low.

This is the next layer above the current iOS verification foundation:

- task-local Xcode context,
- phase-based execution,
- strategy materialization,
- docs-only skip,
- test-only selectors,
- prepare/build artifact reuse,
- delivery gating on passed verification.

## Current State

The iOS verifier already distinguishes:

- docs-only changes,
- test-only changes,
- prepare-sensitive changes,
- reuse vs rebuild for prepare/build products.

But it still treats most production-code diffs broadly:

- one general app-level verification path,
- one broad test/lint gate,
- conservative fallback to whole-task verification.

What is still missing is a reliable answer to:

- which module changed,
- which targets/schemes are affected,
- which test bundles are relevant,
- whether a narrower verification scope is actually safe.

## What “Target Mapping” Means

Target mapping is a machine-readable layer that maps:

- changed files
- to modules/areas
- to build targets/schemes
- to likely relevant test bundles
- with an explicit confidence level

The verifier should use that mapping only when it is strong enough to justify a narrower path.

## Target Outcomes

For a given iOS task, the mapping layer should eventually be able to answer:

- impacted modules
- impacted schemes
- impacted test targets
- optional `only-testing` selectors
- whether broad fallback is still required

## Principles

### 1. Conservative by default

- Narrow only when confidence is high.
- If mapping is incomplete or ambiguous, keep the current broad-safe verification path.

### 2. Explainable decisions

The verifier report must explain:

- why a narrow path was chosen,
- what was considered impacted,
- what was intentionally not run,
- why fallback happened.

### 3. Stable machine-readable input

Do not make the model invent target mappings from scratch in every run.
Materialize repo-specific mapping data into a deterministic input first.

### 4. Incremental rollout

Start with simple path-prefix mapping and only later consider deeper graph-aware inference.

## Proposed Mapping Layers

### Layer 1: Path Prefix Mapping

Use repo path conventions to infer impacted areas.

Example shape:

```json
{
  "areas": [
    {
      "name": "FinomCore",
      "path_prefixes": ["FinomCore/"],
      "schemes": ["Finom"],
      "test_targets": ["FinomTests"]
    }
  ]
}
```

This is the cheapest and safest first step because:

- it is explainable,
- easy to audit,
- easy to patch when repo structure changes.

### Layer 2: Test Target Inference

After path mapping identifies impacted areas, infer the most relevant test bundles.

Examples:

- `FinomCore/...` -> `FinomTests`
- UI-layer changes -> UI/integration test bundles
- pure test-file changes -> direct `only-testing` selectors

### Layer 3: Scheme Narrowing

Where the repo structure safely allows it, choose:

- narrower scheme,
- narrower test plan,
- or narrower verification command set.

This should be introduced only after Layer 1 and Layer 2 are trustworthy.

### Layer 4: Graph-Aware Mapping

Later, optionally use generated project metadata or Tuist graph information to infer:

- transitive dependencies,
- target inclusion,
- shared scheme impact.

This is higher value but also higher complexity and fragility.
It should not be the first implementation step.

## Signals to Use

### File-level signals

- changed file paths
- file extensions
- test-file naming
- docs-only vs source-code change

### Repo structure signals

- folder prefixes
- colocated tests
- naming conventions for modules/features

### Build-system signals

- `Project.swift`
- `Workspace.swift`
- Tuist-specific structure
- optional generated metadata if stable enough

### Confidence signals

- all changed files map cleanly to one known area
- matching test target exists
- no cross-cutting config/build files changed
- no repo-wide/shared infra paths changed

## Proposed Strategy Output Extension

The current `verification-strategy.json` should eventually include an optional section like:

```json
{
  "impact_mapping": {
    "confidence": "high",
    "impacted_areas": ["FinomCore"],
    "impacted_schemes": ["Finom"],
    "impacted_test_targets": ["FinomTests"],
    "targeted_selectors": ["FinomTests/ObservationListServiceTests"],
    "fallback_required": false
  }
}
```

If confidence is low:

```json
{
  "impact_mapping": {
    "confidence": "low",
    "fallback_required": true,
    "reason": "Cross-cutting configuration and shared code changed together."
  }
}
```

## Suggested iOS Implementation Plan

### Step 1: Static mapping file

Add a repo-local machine-readable mapping file for iOS verification.

Example future location:

- `config/ios-verification-map.json`

It should define:

- area names
- path prefixes
- relevant schemes
- relevant test targets

### Step 2: Build a mapper

Create a deterministic mapper that:

- reads changed files
- matches them to path prefixes
- emits impacted areas + confidence

### Step 3: Extend strategy generation

Teach `backend/coordinator/verification_strategy.py` to:

- include impacted areas
- include target/test mapping
- choose narrow path only when confidence is high

### Step 4: Narrow test execution

Use mapping output to drive:

- `only-testing`
- selected test bundle focus
- optional narrower scheme usage

### Step 5: Report decisions

Ensure `spec/final-verification.md` records:

- impacted areas
- chosen scheme/test scope
- why narrow mode was safe
- why broad fallback was used when applicable

## Fallback Policy

Always fall back to the broader safe iOS path when:

- multiple unrelated areas changed,
- mapping confidence is low,
- build/config/dependency files changed,
- generated project shape may have changed,
- test target coverage is unclear.

The verifier should prefer safe broad verification over risky underscoping.

## Risks

### False narrowing

The main risk is underscoping verification and missing regressions.

Mitigation:

- confidence gating,
- explicit fallback rules,
- human-readable reporting,
- gradual rollout.

### Mapping drift

Repo structure evolves and path-based mapping can go stale.

Mitigation:

- keep mapping file explicit and reviewable,
- prefer simple rules over opaque inference,
- audit mismatches with real tasks.

### Over-complexity too early

Jumping directly to graph-aware mapping would slow delivery and increase fragility.

Mitigation:

- start with path-prefix mapping,
- add graph-aware inference only if path mapping proves insufficient.

## Recommended Next Slice

The next iOS-specific implementation slice should be:

1. add a static `ios-verification-map.json`
2. implement path-prefix impacted-area inference
3. extend `verification-strategy.json` with `impact_mapping`
4. keep broad fallback as default unless confidence is explicitly high

That gives real narrowing value without overcommitting to a brittle graph-analysis system.
