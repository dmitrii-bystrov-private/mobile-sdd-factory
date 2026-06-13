# Dual Review Lanes Migration Plan

## Goal

Replace the current `code-reviewer` + `code-scout` quality model with two focused review lanes:

- `convention-reviewer` checks whether the diff follows the local project conventions.
- `requirements-reviewer` checks whether the diff implements the routed task requirements and meaningful edge cases.

The existing self-review correction loop is the implementation baseline. Its useful behavior must be preserved:

- structured review report artifact;
- `failed -> correction_requested -> implementer -> re-review`;
- `blocked_review_cycle` operator escalation;
- operator guidance after a blocked cycle;
- previous reports scoped to the immediate correction chain only.

`code-scout` should be removed from new-session routing once dual review lanes are implemented. The legacy `code-scout` and `code-reviewer` roles should be physically removed only after old sessions that may depend on legacy stages have completed.

## Target Role Split

### Convention Reviewer

Purpose: local consistency review.

Primary project guidance:

- Read `CLAUDE.md` when present.
- Read `README.md` when present.
- Follow their links to relevant local convention docs/templates for the touched diff.

Review scope:

- architecture and ownership boundaries;
- dependency direction;
- module/component shape;
- naming and file layout;
- local API/data mapping patterns;
- async, lifecycle, cancellation, and cleanup conventions;
- UI/component/layout conventions when grounded in local project guidance;
- test naming, structure, fixtures, mocks, and deterministic style;
- abstraction boundaries and helper ergonomics.

Rules:

- Start from the current diff.
- Read only convention sources relevant to the touched files.
- Use nearest similar code/tests only to clarify conventions not covered by docs/templates.
- Report only issues grounded in local docs, templates, or stable nearby precedent.
- Do not review requirements completeness or business edge cases.
- Do not review documentation hygiene; that belongs to Documentation Reviewer.
- Do not run build/test/lint/simulator commands.

### Requirements Reviewer

Purpose: behavioral completeness review.

Primary inputs:

- `statuses.md` as the canonical task/subtask ordering source;
- root task `description.md` and `comments.md`;
- per-key Jira task/subtask `description.md` and `comments.md` read in `statuses.md` order;
- proposal/context package when present;
- acceptance criteria when present;
- current diff;
- relevant existing behavior and tests.

Review scope:

- all requested behavior is implemented;
- fresh comments/clarifications are respected;
- important edge cases are covered;
- existing behavior is not accidentally broken;
- tests cover meaningful behavior, not only implementation details;
- missing or ambiguous verification evidence is called out without running verification.

Rules:

- Start from the routed task/spec inputs before judging the diff.
- Treat requirements as cumulative across the ordered Jira task/subtask list.
- Treat newer Jira follow-up tasks/subtasks as higher authority than the original task description, older specs, and earlier follow-ups only where they explicitly conflict.
- Earlier accepted subtasks remain part of the regression contract unless a later follow-up clearly overrides them.
- Use `statuses.md` as the source of truth for Jira task/subtask order and follow-up precedence.
- Do not rely on `plan/index.md` or `plan/NN-*.md` as authoritative follow-up inputs because those are temporary decomposition artifacts.
- When inputs conflict, follow the newest applicable Jira follow-up rather than synthesizing a compromise across old and new requirements.
- When reporting a regression against an earlier subtask, cite the earlier Jira key and state that no later follow-up overrides that requirement.
- Report behavior gaps and edge-case risks.
- Do not report local style/convention issues unless they directly change behavior.
- Do not run build/test/lint/simulator commands.

## Target Flow

```text
implementation
  -> convention_review_requested
  -> convention_review_correction_requested? -> convention_review_requested
  -> requirements_review_requested
  -> requirements_review_correction_requested? -> convention_review_requested -> requirements_review_requested
  -> verification_requested
  -> doc_harvest_requested?
  -> documentation_review_requested?
  -> completed
```

Correction loops stay lane-specific:

- convention findings route back as convention corrections;
- requirements findings route back as requirements corrections;
- every code-changing correction re-enters the full review gate from convention review, regardless of which lane requested the correction;
- each lane has its own report artifacts and blocked-cycle history.

Review artifacts use lane-specific directories:

```text
review/convention/pass-01.md
review/convention/outcome.json
review/requirements/pass-01.md
review/requirements/outcome.json
```

Legacy `code-reviewer` / `self_review_requested` may keep using `review/pass-NN.md` for active-session compatibility. New dual-review lanes should use the lane-specific paths above. Artifact repository lookups should still rely on `review_lane` metadata, not path parsing.

## Compatibility Strategy

- Keep legacy `self_review_requested` / `code-reviewer` handling during migration so active sessions are not broken.
- Keep legacy `boy_scout_requested` / `code-scout` handling during migration so active sessions are not broken.
- Reuse `self_review_policy` as the compatibility backing field for the new dual-review gate during the first implementation slice.
- Display that policy as `Review Gate` in operator-facing UI/docs once it controls convention + requirements review.
- Postpone any storage/API rename to `review_policy` to a later cleanup slice.
- New sessions should use the dual review flow once it is implemented.
- Stop routing new sessions to `code-scout` once dual review is active.
- Remove legacy `code-reviewer` and `code-scout` only after old sessions using legacy review/scout stages have drained.
- Avoid database migrations unless a schema change becomes clearly necessary; prefer new stage/work-item names over changing persisted old rows.

## Implementation Checklist

### 1. Review Lane Abstraction

- [ ] Introduce lane-aware review configuration for coordinator helpers.
- [ ] Parameterize role name, review lane, review work type, correction work type, requested stage, correction stage, artifact names, and display labels.
- [ ] Reuse existing self-review report materialization where possible.
- [ ] Store new dual-review artifacts under lane-specific directories: `review/convention/` and `review/requirements/`.
- [ ] Preserve immediate-correction-chain report scoping.
- [ ] Preserve blocked-cycle operator escalation.
- [ ] Preserve operator guidance replay after blocked-cycle resolution.

### 2. New Roles

- [x] Add `convention-reviewer` role contract.
- [x] Add `requirements-reviewer` role contract.
- [x] Add role baselines.
- [x] Add both new reviewer roles to persistent session roles.
- [x] Add launcher/workspace support.
- [x] Add role prompt rules.
- [x] Encode Requirements Reviewer input precedence: newer Jira follow-up tasks/subtasks override the original description, older specs, and earlier follow-ups only on explicit conflict.
- [x] Encode cumulative Requirements Reviewer semantics: earlier accepted subtasks remain active regression requirements unless explicitly overridden.
- [x] Route `statuses.md` to Requirements Reviewer as the canonical task/subtask order input.
- [x] Ensure Requirements Reviewer does not treat `plan/index.md` or `plan/NN-*.md` as authoritative follow-up inputs.
- [x] Add deterministic result writer support.
- [x] Add UI role labels and descriptions.

### 3. Coordinator Routing

- [x] Route implementation completion to convention review when review policy is enabled/required.
- [x] Route convention pass to requirements review.
- [x] Route requirements pass to verification or the next existing quality gate.
- [x] Route convention failure to convention correction.
- [x] Route requirements failure to requirements correction.
- [x] Route convention correction completion back to convention review.
- [x] Route requirements correction completion back to convention review, then requirements review.
- [x] Keep legacy `self_review_requested` behavior for already-running sessions.

### 4. Policies and UI

- [x] Reuse `self_review_policy` as the compatibility backing field for the dual-review gate.
- [x] Rename operator-facing `Self Review` policy labels to `Review Gate`.
- [x] Document that `review_policy` storage/API rename is deferred.
- [x] Add readable stage labels:
  - `Convention Review`
  - `Convention Review Correction`
  - `Requirements Review`
  - `Requirements Review Correction`
- [x] Update runtime/session role ordering in the UI.
- [x] Ensure on-demand/default dashboard visibility stays intentional.
- [ ] Keep legacy Code Scout controls available only for active legacy sessions until old sessions drain.

### 5. Tests

- [x] `implementation -> convention_review_requested`.
- [x] `convention_review passed -> requirements_review_requested`.
- [x] `requirements_review passed -> verification_requested`.
- [x] `convention_review failed -> convention_review_correction_requested`.
- [x] `requirements_review failed -> requirements_review_correction_requested`.
- [x] Convention correction completion returns to convention review.
- [x] Requirements correction completion returns to convention review before requirements review.
- [ ] Blocked review cycle works independently per lane.
- [ ] Previous review reports are scoped to the immediate correction chain per lane.
- [x] Convention and requirements review artifacts are written to separate lane directories.
- [ ] Operator guidance after blocked-cycle reply is replayed to the correct lane.
- [ ] Requirements Reviewer follows newest Jira follow-up precedence when inputs conflict.
- [ ] Requirements Reviewer catches regressions against earlier subtasks that were not overridden by later follow-ups.
- [ ] Requirements Reviewer uses `statuses.md` ordering to resolve task/subtask precedence.
- [ ] Requirements Reviewer ignores temporary plan/decomposition numbering as follow-up authority.
- [x] Result writer accepts both new reviewer roles.
- [x] UI/API display new stages and roles correctly.

### 6. Documentation

- [x] Update `README.md` workflow diagrams and role table.
- [x] Update `docs/runtime-model.md`.
- [x] Update `docs/operator-guide.md`.
- [x] Update `docs/terminal-result-contract.md`.
- [ ] Update `DEVELOPERS_GUIDE.md` if supported-platform behavior is described there.
- [ ] Remove Code Scout from default/current-flow documentation once new sessions no longer route to it; document it only as legacy compatibility until old sessions drain.

### 7. Code Scout Removal

Do this after dual review lanes are implemented and verified, and after old sessions that may depend on legacy `boy_scout_*` stages have completed.

Remove Code Scout completely. Do not preserve or migrate its deferred tech-debt, implement-now, or operator-decision behavior into Convention Reviewer or Requirements Reviewer.

- [ ] Remove `code-scout` role baseline and contracts.
- [ ] Remove `boy_scout_policy`.
- [ ] Remove `boy_scout_requested` and `boy_scout_correction_requested` routing.
- [ ] Remove Code Scout operator actions:
  - skip;
  - implement-now;
  - create tech debt.
- [ ] Remove scout artifact materialization and deferred registry logic.
- [ ] Remove scout UI labels, buttons, and styles.
- [ ] Remove scout tests or replace them with dual-review tests.
- [ ] Remove scout documentation references.
- [ ] Verify no Code Scout deferred tech-debt or operator-decision behavior remains under another role name.

### 8. Legacy Code Reviewer Removal

Do this after old sessions that may depend on legacy `self_review_*` stages have completed.

- [ ] Remove `code-reviewer` role baseline and contracts.
- [ ] Remove `self_review_requested` and `self_review_correction_requested` legacy routing.
- [ ] Remove legacy self-review artifact paths such as `review/pass-NN.md`.
- [ ] Remove legacy self-review tests or replace them with dual-review tests.
- [ ] Remove legacy self-review documentation references.
- [ ] Verify no new session can route to `code-reviewer`.

## Acceptance Criteria

- New task sessions use convention review followed by requirements review.
- Each reviewer has a narrower, non-overlapping prompt.
- Corrections are created from the lane that reported findings, and any code-changing correction then re-enters the full review gate from convention review.
- `blocked_review_cycle` is not triggered by old findings returning after unrelated follow-up/subtask/implementation work.
- Existing active sessions using legacy self-review or Code Scout are still recoverable during migration.
- Legacy Code Reviewer and Code Scout are removed only after old sessions have drained and dual review behavior is covered by tests.

## Role Runtime Decision

Both new review lanes should be persistent roles.

Rationale:

- correction loops benefit from retained local context;
- previous correction rounds and operator guidance remain available inside the role session;
- the existing runtime model already supports persistent quality lanes;
- token consumption is not the bottleneck compared with review quality.

Guardrails:

- Convention Reviewer treats current diff plus local project guidance as authoritative.
- Requirements Reviewer treats the current routed Jira context and `statuses.md` order as authoritative.
- Requirements Reviewer may use persistent memory only as background; memory loses to current routed inputs.
- Earlier subtasks remain regression requirements unless a later Jira follow-up explicitly overrides them.
