# Internal Review Lanes Improvement Plan

## Context

The factory currently has two internal review lanes after implementation:

- `code-reviewer` for self-review
- `code-scout` for Code Scout maintainability review

They already catch useful issues, but the two lanes are not equally mature.

Observed gaps from live tasks:

1. `code-reviewer` usually detects real regressions, but some blocked-cycle outputs are too terse.
   - Example pattern: "unresolved X regression" without enough technical direction for the operator or implementer.
2. `code-scout` uses a weaker artifact/process model than `code-reviewer`.
   - It often emits only a short outcome JSON.
   - Findings are not materialized and persisted as cleanly as self-review findings.
3. Reviewer and scout findings do not share one consistent structure.
   - Reviewer has a more mature review trail.
   - Scout findings are less reusable in correction loops.
4. External MR-review follow-up subtasks are often much better written than internal findings.
   - They typically include:
     - the finding
     - why it matters
     - desired design direction
     - scope boundaries
     - tests / acceptance criteria

This plan is meant to raise the internal lanes closer to that bar without adding a third review worker yet.

## Goals

1. Make `code-reviewer` findings consistently actionable.
2. Make `code-scout` findings first-class artifacts, not lightweight side outputs.
3. Align the storage, rendering, and correction flow of both lanes.
4. Improve operator experience during escalation and blocked cycles.
5. Reduce wasted correction iterations caused by underspecified findings.

## Non-goals

1. Do not add a third internal review worker in this phase.
2. Do not broaden review scope into dynamic verification or test execution.
3. Do not make every finding verbose by default when the pass is clean.
4. Do not redesign the full session workflow unless required by the review-lane work.

## Current State Summary

### `code-reviewer`

Strengths:

- already integrated with correction loops
- has durable artifacts:
  - `self_review_report_markdown`
  - `self_review_outcome_json`
- participates in blocked-cycle escalation
- findings usually point to real regressions or contract mismatches

Weaknesses:

- blocked-cycle summaries can be too compressed
- repeated-cycle reports often carry only a diagnosis, not correction direction
- operator payloads can lose reviewer context if not explicitly materialized

### `code-scout`

Strengths:

- useful for maintainability and structural cleanliness
- can explain clean / skipped passes reasonably well
- catches a different class of issues than correctness review

Weaknesses:

- findings are not persisted in a reviewer-grade report format
- outcome shape is less consistent than self-review
- correction-loop semantics are weaker
- history is harder to inspect and reuse

## Target State

After this plan:

1. Both review lanes produce a first-class durable report.
2. Both lanes use a common finding schema.
3. Corrections consume structured findings rather than short summaries.
4. Blocked-cycle escalation always includes meaningful technical context.
5. Operator replies can be routed against clearly identified findings, not generic issue labels.

## Progress Checkpoint

Last synchronized: 2026-06-03

### Completed

1. User-facing rename from `Boy Scout` to `Code Scout`
   - user-facing UI/runtime labels switched to `Code Scout`
   - internal ids remain backward compatible (`boy_scout_*`)
2. `Code Scout` durable report trail
   - `boy_scout_report_markdown` is now first-class and materialized for clean/finding passes
3. Structured finding contract for `code-scout`
   - findings now carry:
     - title
     - why it matters
     - required direction
     - non-goals
   - actionable findings materialize in correction-ready markdown
4. Structured finding contract for `code-reviewer`
   - reviewer findings now preserve the same richer shape in report materialization
5. Reviewer blocked-cycle payload improvement
   - operator-facing blocker details now preserve:
     - short summary
     - structured unresolved finding body
6. `Code Scout` operator-detail improvement
   - operator-facing scout escalation now shows:
     - implement-now findings
     - tech-debt candidates
     - why it matters / required direction / non-goals
7. Unified implementer correction hydration
   - implementer correction rounds now receive a common payload shape across:
     - self-review corrections
     - Code Scout corrections
     - verification corrections
8. Review-family metadata alignment
   - reviewer and Code Scout reports now share:
     - `report_family = internal_review`
     - `review_lane`
     - `status`
     - `work_item_id`
   - reviewer and Code Scout outcomes now share the same family contract
9. Metadata-first correction/history lookup started
   - self-review history lookup can resolve via internal-review metadata
   - Code Scout correction lookup can resolve via internal-review metadata
   - Code Scout escalation now carries explicit `review_report_paths`
10. UI presentation cleanup
   - correction-family labels are clearer in worker/session UI
   - operator wording across review lanes is more consistent
   - artifact log now surfaces internal-review family context

### Partially Completed

1. Artifact/history lookup migration
   - some downstream flows now use metadata-first lookup
   - other code paths still depend on concrete artifact types
2. UI/operator review-family presentation
   - artifact panel and operator wording are improved
   - broader review-family navigation/filtering is still pending

### Not Started

1. Unified `Evidence` / `Suggested approach` / `Test expectations` handling
   - current structured contract covers the most important fields
   - optional sections are not yet standardized across both lanes
2. Shared correction/operator flow for multi-lane findings
   - reviewer and scout are closer, but not yet fully abstracted as one review subsystem
3. Metrics / rollout instrumentation for review-lane quality
   - no explicit counters yet for:
     - repeat blocked cycles
     - correction-loop convergence
     - finding reuse quality

### Current Recommended Next Steps

1. Finish metadata-first review-family lookup
   - remove more direct dependency on:
     - `self_review_report_markdown`
     - `boy_scout_report_markdown`
     - `boy_scout_actionable_markdown`
   - keep compatibility fallbacks until old history can be ignored
2. Standardize optional structured sections
   - `Evidence`
   - `Suggested approach`
   - `Test expectations`
3. Unify operator/correction handling further
   - continue reducing lane-specific branching where reviewer and Code Scout now share equivalent semantics
4. Add explicit success metrics
   - repeated-cycle rate
   - operator-escalation clarity
   - correction convergence after first reroute

## Unified Finding Contract

Both `code-reviewer` and `code-scout` should use the same finding structure when issues exist.

### Required sections

1. `Finding`
   - what is wrong
   - where it is wrong
   - what behavior/structure is affected
2. `Why it matters`
   - regression, contract break, maintainability hazard, or future-risk explanation
3. `Required direction`
   - what must change
   - what invariant must hold after the fix
4. `Non-goals`
   - what should not be broadened in this pass
5. `Evidence`
   - file(s), call path(s), or concrete code-area references

### Optional sections

1. `Suggested approach`
   - when the lane can propose a strong implementation direction
2. `Test expectations`
   - when the fix should be accompanied by specific verification evidence

### Clean / skipped output rules

When the pass is clean or skipped, the lane should stay concise:

- one summary line
- optional short details paragraph explaining why the area is clean or why the pass is not needed

We only want the full structure when there is a real finding.

## Reviewer Lane Improvements

### 1. Upgrade finding quality

Change `code-reviewer` prompt/workspace contract so findings are not just labels.

Expected behavior:

- if there is one real issue, reviewer writes a structured finding
- if the same issue repeats across cycles, reviewer still emits:
  - the unresolved invariant
  - the affected code area
  - why the previous correction did not satisfy the requirement

### 2. Strengthen blocked-cycle output

Blocked cycles should stop emitting only a compressed summary like:

- `unresolved X regression`

They should instead include:

- the repeated unresolved finding
- why this is a repeat rather than a new issue
- what authoritative direction is currently expected

### 3. Preserve structured context end-to-end

The following surfaces should all preserve the same content:

- self-review report markdown
- role output payload
- session escalation event
- interactive operator state
- next correction hydration

There should be no lossy conversion from structured finding to one-line blocker unless explicitly required for compact UI labels.

## Code Scout Lane Improvements

### 1. Introduce a durable report artifact

Add a new first-class artifact, symmetric to reviewer:

- `boy_scout_report_markdown`

This should exist whenever the lane runs, with:

- a clean report for `clean`
- a structured findings report when issues exist
- a concise explanation when skipped

### 2. Raise finding quality

Code Scout findings should describe:

- structural smell or maintainability problem
- why it is not just style preference
- what cleanup direction is expected
- what not to expand in the current pass

The scout should not just say:

- "maintainability issue found"

It should produce a minimal design note.

### 3. Make correction semantics reviewer-grade

Scout findings should feed the correction lane with the same seriousness as self-review findings:

- structured finding report attached to the correction pass
- durable history
- operator-visible context if the cycle stalls

### 4. Keep clean passes compact

Most scout passes are clean.
We should not inflate them.

Clean output can remain:

- short summary
- short explanation when useful

Only finding paths need the heavier structure.

## Artifact and Persistence Plan

### New / improved artifacts

1. Keep:
   - `self_review_report_markdown`
   - `self_review_outcome_json`
2. Add:
   - `boy_scout_report_markdown`
3. Ensure both lanes have durable:
   - outcome JSON
   - report markdown
   - role output JSON

### Storage invariants

1. Every finding-producing pass must materialize a report.
2. Every correction pass must be able to recover the exact structured finding that triggered it.
3. Every blocked cycle must be able to recover the most recent authoritative unresolved finding.
4. UI/operator surfaces must not depend on transient runtime output when a durable artifact exists.

## Operator Experience Improvements

### 1. Better blocker payloads

Operator-facing blocker state should show:

- the finding body, not only the short summary
- preserved formatting
- issue context first, boilerplate second

### 2. Better correction routing

When operator guidance is supplied:

- the reply should attach to the exact structured finding lineage
- the implementer should receive the guidance
- the subsequent reviewer/scout pass should also receive that authoritative resolution context

### 3. Better distinction between lanes

UI and artifacts should make it obvious:

- this is a correctness/self-review finding
- this is a maintainability/Code Scout finding

That will reduce confusion when multiple lanes have comments on the same task.

## Prompt and Contract Work

### `code-reviewer`

Update contract to require:

1. structured findings on issue paths
2. concise but explicit repeat-cycle explanations
3. stronger explanation of expected correction direction
4. no test/build execution

### `code-scout`

Update contract to require:

1. structured findings on issue paths
2. explicit distinction between:
   - real maintainability finding
   - deferred known debt
   - no actionable finding
   - skipped-not-needed
3. writing the report artifact whenever the pass runs

## Workflow Changes

### Phase 1: Contract and artifact parity

Deliverables:

1. reviewer findings upgraded to the unified structure
2. `boy_scout_report_markdown` introduced
3. scout outcome materialization aligned with reviewer

Success criteria:

- fresh tasks produce durable reviewer and scout reports
- finding paths are readable without opening runtime logs

### Phase 2: Correction-flow integration

Deliverables:

1. correction hydration consumes structured reviewer findings
2. correction hydration consumes structured scout findings
3. blocked-cycle escalation carries structured unresolved finding context

Success criteria:

- operator can understand the issue from interactive state alone
- correction loops require fewer "what exactly is wrong?" interventions

### Phase 3: Quality tightening

Deliverables:

1. repeated-cycle reviewer findings are more explicit
2. scout findings distinguish debt from preference
3. UI renders both report types cleanly

Success criteria:

- fewer ambiguous blocked cycles
- easier comparison between internal findings and external review follow-ups

## Metrics to Watch

1. Average number of self-review correction cycles per task
2. Average number of operator escalations caused by unclear findings
3. Percentage of scout runs with:
   - clean
   - skipped
   - findings
4. Percentage of blocked cycles whose operator state is understandable without opening runtime logs
5. Number of external-review follow-up subtasks whose scope could have been derived from internal findings

## Risks

1. Over-verbose findings may create noise.
   - Mitigation: only use the full structure for issue paths.
2. Reviewer and scout may start over-prescribing implementation details.
   - Mitigation: require `Required direction`, not mandatory exact patch designs.
3. Too much structured text may bloat operator UI.
   - Mitigation: keep summary compact and render details progressively.

## Recommended Implementation Order

1. Add `boy_scout_report_markdown`.
2. Upgrade reviewer finding contract.
3. Upgrade scout finding contract.
4. Align persistence and artifact creation.
5. Align correction hydration for both lanes.
6. Align operator blocker payloads and UI rendering.
7. Reassess whether a third review worker is still needed.

## Recommendation on Additional Review Workers

Do not add a third internal review worker yet.

Reevaluate only after the improvements above are live and measured.

If a major gap still remains after reviewer/scout parity, only then consider a dedicated third lane for a clearly separate concern such as:

- concurrency review
- architecture boundary review
- performance review

## Definition of Done

This plan is complete when:

1. reviewer and scout findings share one structured contract
2. both lanes materialize durable reports
3. operator-facing blocked-cycle states preserve the actual finding body
4. correction flows consume structured findings from either lane
5. live tasks show fewer ambiguous review loops
6. internal findings are closer in usefulness to external-review follow-up subtasks
