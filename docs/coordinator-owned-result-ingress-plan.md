# Coordinator-Owned Result Ingress Plan

## Goal

Move terminal role-result submission from runtime-authored `RESULT.json` files
to a coordinator-owned ingest path, while still materializing canonical disk
artifacts for observability, debugging, and recovery.

## Why

The current model is better than before, but it still trusts the runtime role
workspace as the authoritative source of truth for terminal outcomes.

That leaves a few remaining failure modes:

- the runtime can overwrite or corrupt `RESULT.json`
- stale runtimes can write after ownership has already moved elsewhere
- partial file writes can race with collection
- the coordinator validates only after reading a runtime-authored file

The target model is:

- role submits a structured terminal payload to the coordinator-owned ingress
- coordinator validates it immediately against the role/work-item contract
- coordinator stores the accepted payload as the authoritative result
- coordinator materializes the canonical `RESULT.json` artifact on disk

This preserves the disk trail without making the runtime-local file the source
of truth.

## Scope

This rollout only changes terminal outcome submission.

Out of scope for the first pass:

- replacing runtime console telemetry markers like `SDD_PROGRESS`
- replacing runtime output capture logs
- changing story-planning or verification business rules
- changing the task/session state machine semantics

## Principles

1. `work_item_id` remains the only required context key for roles.
2. The coordinator, not the runtime, owns authoritative acceptance/rejection.
3. Canonical disk artifacts stay in place for forensics and operator support.
4. Rollout should be phased and reversible.
5. During migration, protocol safety matters more than minimizing code churn.

## Target Contract

### Runtime-facing contract

Roles should submit terminal outcomes through a single shell-facing helper,
not by writing `RESULT.json` directly.

Target shape:

```bash
bash "$SDD_FACTORY_REPO_ROOT/scripts/submit-result.sh" \
  --work-item-id 123 \
  --result passed \
  --summary "short summary"
```

The helper should:

- resolve coordinator connection details deterministically
- send the structured payload to the coordinator-owned ingress
- exit non-zero when submission is rejected

### Coordinator-owned ingest contract

The ingest path should:

- resolve session, role, stage, and schema from `work_item_id`
- validate role-specific required fields before accepting the payload
- reject stale or mismatched submissions before they affect state
- persist the accepted canonical payload
- materialize canonical `RESULT.json` and accepted-result artifacts on disk

### Disk artifacts after ingest

After successful ingest, the coordinator should write:

- canonical `runtime/role-workspaces/<role>/RESULT.json`
- accepted-result artifact under `factory-artifacts/...`

On rejection, the coordinator should optionally retain:

- rejected raw payload artifact
- protocol-violation artifact with reason

## Rollout Phases

### Phase 1: Document and shape the ingress contract

Deliverables:

- final runtime-facing CLI shape
- final coordinator ingest payload shape
- role-specific required fields by role family

Exit criteria:

- no ambiguity about what stays file-based and what moves to ingest

### Phase 2: Add coordinator-owned ingest endpoint/service

Deliverables:

- coordinator service method for terminal result submission
- role/work-item/schema resolution by `work_item_id`
- canonical acceptance/rejection path

Exit criteria:

- unit tests prove accepted and rejected submissions behave deterministically

### Phase 3: Keep disk materialization, but move authority to ingest

Deliverables:

- canonical artifact materialization after accepted ingress
- rejection artifact materialization for failed ingress

Exit criteria:

- no accepted result depends on a runtime-authored `RESULT.json`
- disk evidence still exists after every accepted or rejected submission

### Phase 4: Add shell wrapper for roles

Deliverables:

- `scripts/submit-result.sh`
- worker prompts updated to call only the shell wrapper

Exit criteria:

- worker-facing contract no longer references direct file writing

### Phase 5: Migration and compatibility window

Deliverables:

- temporary compatibility with current `write-result.sh` / file-based collection
- explicit metrics/logging showing which path was used

Exit criteria:

- live runs show the new ingress path is stable across key roles

### Phase 6: Remove runtime-authored authority

Deliverables:

- file collector downgraded from authoritative source to compatibility path
- runtime-local file write no longer required for normal operation

Exit criteria:

- normal production flow uses coordinator-owned ingest only

## Implementation Order

1. Introduce coordinator service API for terminal-result submission.
2. Add persistence/materialization for accepted and rejected payloads.
3. Add shell `submit-result.sh` wrapper.
4. Migrate the highest-risk roles first:
   - `verification-coordinator`
   - `code-scout`
   - `code-reviewer`
   - story-planning workers
5. Keep file-based collector as migration fallback.
6. Remove fallback only after live confidence is high.

## Risks

### Risk: losing disk evidence

Mitigation:

- accepted submissions always materialize canonical artifacts on disk
- rejected submissions can store raw/rejected payload artifacts

### Risk: transport failures replace file failures

Mitigation:

- helper exits non-zero on transport failure
- coordinator emits protocol/runtime recovery actions as today
- retain compatibility fallback during migration

### Risk: stale runtime submits after ownership changed

Mitigation:

- reject by `work_item_id` ownership/state validation at ingest time
- store rejection reason explicitly

### Risk: rollout complexity across many roles

Mitigation:

- migrate highest-value roles first
- keep old path as compatibility layer briefly

## Tests

Need coverage for:

- accepted submission for verifier/scout/reviewer/planning roles
- rejected submission with missing required fields
- rejected submission for stale/mismatched `work_item_id`
- canonical artifact materialization after accepted ingress
- rejected artifact materialization after failed ingress
- end-to-end coordinator transition after accepted ingress

## Expected Effort

This is medium-to-large work, not a one-line patch.

Why:

- it touches worker contract, coordinator intake, artifact semantics, and tests
- it benefits from a compatibility window rather than a one-shot cutover

But it is still tractable because:

- `work_item_id`-centric resolution is already in place
- strict role-result schemas already exist
- shell helper rollout already reduced runtime variance

## Definition of Done

This effort is done when:

- authoritative terminal result acceptance is coordinator-owned
- roles submit via a single shell helper
- canonical disk artifacts still exist after accepted submissions
- key live roles complete runs without relying on runtime-authored `RESULT.json`
