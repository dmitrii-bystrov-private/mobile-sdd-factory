# Terminal Result Contract

This document fixes the minimum deterministic contract for routed role terminal results.

The goal is simple:
- orchestration must depend only on a small structured payload
- markdown reports, summaries, and console output stay human-facing
- roles should not hand-assemble JSON objects when only a few fields drive state transitions
- `work_item_id` should be the only coordinator-owned context key a role needs for terminal submission

## General Rules

Model-capacity recovery is runtime retry handling, not a worker terminal result. Retries preserve the
work item and configured model. A pending submitted result prevents recovery input; capacity errors
must not be interpreted as a completed task or an operator requirements question.

Roles submit terminal outcomes through the deterministic helper:

```bash
bash "$SDD_FACTORY_REPO_ROOT/scripts/write-result.sh" --work-item-id <work_item_id> ...
```

The helper builds the structured result document, validates the role-specific contract, resolves the canonical role/workspace context from `work_item_id`, and submits it to the backend `/roles/submit-result` ingress.
The backend records the accepted document as a `role_result_json` artifact.
Worker-local `runtime/role-workspaces/<role>/RESULT.json` files are local recovery inputs for interrupted helper submissions; roles should not create them manually.

The canonical submitted document has this shape:

```json
{
  "output_type": "completed",
  "payload": {
    "work_item_id": 123
  }
}
```

Universal required fields:
- `output_type`
- `payload`
- `payload.work_item_id`

Universal rules:
- `scripts/write-result.sh` is the supported terminal submission path.
- roles must not write `RESULT.json` manually or call `scripts/write-result.py` directly.
- Free-form console output, `summary`, markdown files, and telemetry never decide state transitions.
- Role-specific reports such as `spec/final-verification.md`, `spec/findings.md`, and review markdown stay derivative artifacts.
- Extra payload fields are allowed only when they are part of a documented role contract.
- If helper submission fails with a backend transport error, stop and escalate; do not retry by manually creating `RESULT.json`.

## Structured Terminal Markers

Terminal markers are a narrow runtime telemetry and emergency-blocker channel. They are not the primary terminal outcome API.

Rules:
- Keep each marker on one line.
- Put exactly one JSON object after the marker prefix.
- Replace example `work_item_id` value `123` with the numeric `work_item_id` from `HYDRATION.json` when present.
- Do not invent marker names, wrapper keys, markdown formats, or extra schema variants.
- Do not use terminal markers for normal pass/fail/completed/skipped outcomes; use `scripts/write-result.sh`.

Progress marker:

```text
SDD_PROGRESS: {"status":"in_progress","message":"<short status>","work_item_id":123}
```

Runtime/tooling blocker marker:

```text
SDD_ERROR: {"summary":"<short summary>","details":"<specific failure>","needs_operator_input":false,"work_item_id":123}
```

Operator-actionable runtime blocker marker:

```text
SDD_ERROR: {"summary":"<short summary>","details":"<what the operator must do>","needs_operator_input":true,"work_item_id":123}
```

Use `SDD_ERROR` only for runtime/protocol/tooling blockers where the helper cannot represent or deliver the current outcome.
Active launcher confirmation menus with an affirmative option, including Claude dynamic workflow consent, are accepted by the tmux host and do not generate synthetic `SDD_ERROR` blockers. Requirements questions and selections without an affirmative option still use the existing operator-input contract.
For implementer operator decisions, prefer a `failed` helper result with `--needs-operator-input`; do not use `SDD_ERROR` as routed work delivery.

## Output Types

The current backend consumes these terminal `output_type` values:
- `completed`
- `passed`
- `failed`
- `blocked_review_cycle`
- `blocked_verification_cycle`
- `skipped_not_needed`

For deterministic routing, roles should prefer the smallest meaningful set:
- use `completed` for successful bounded work
- use `failed` for normal negative outcomes or operator blockers
- use `blocked_review_cycle` / `blocked_verification_cycle` only for explicit non-converging retry loops
- use `skipped_not_needed` only for optional lanes that policy allows to skip

## Minimal Role Contracts

For QA verification, scripts/e2e-verify.sh produces spec/e2e-verdict.json and phase receipts. Submit the
usual verification result through write-result.sh. The coordinator derives passed/failed/blocked/accepted_with_warnings from
validated e2e evidence: stale work-item/source/strategy/support-file evidence and success without actual runs are rejected.
Environment/baseline blockers retain the verification stage for recovery or an explicit baseline
decision, rather than automatically entering code correction. The final verification report comes from the runner's evidence. See [e2e-workflow.md](e2e-workflow.md).
Missing shared Appium launch permission for Android Chromedriver autodownload is a native environment
blocker, even if native-only tests can pass. The runner never restarts another user's server.
The verifier completes e2e.platforms in the common verification strategy with task-provided command
arrays, environment, collection scope and selected checks. Collection emits JSON identifiers; runs emit
JUnit and JSON outcomes. Task-local integration files are digest-bound. No separate e2e plan is required;
legacy contract-version-1 evidence and operator decisions require a fresh version-2 gate.
Dedicated iOS pool assignment is native execution context, not an operator requirement choice.
Use FACTORY_E2E_APPIUM_CAPABILITIES for the leased UDID, WDA/MJPEG ports and derived-data path;
pytest_evidence applies these automatically. Other adapters must consume the assigned capabilities.
Receipts identify the leased device; ios_simulator_cleanup and cleanup_warnings retain its shutdown
outcome. Busy pools wait within the total gate timeout before becoming environment blockers.

### Verification Coordinator

Used during `verification_requested`.

Required:
- `output_type`
- `payload.work_item_id`

Preferred deterministic outcome field:
- `payload.result`

Allowed `payload.result` values:
- `passed`
- `failed`

When verification fails, at least one explicit failure signal must be present:
- `payload.result = "failed"`
- or `payload.status = "failed"`
- or non-empty `payload.failure`
- or non-empty `payload.failures`
- or a failed command entry in `payload.commands`

Recommended minimal pass example:

```json
{
  "output_type": "completed",
  "payload": {
    "work_item_id": 481,
    "result": "passed"
  }
}
```

Recommended minimal fail example:

```json
{
  "output_type": "completed",
  "payload": {
    "work_item_id": 481,
    "result": "failed",
    "failures": [
      "build-for-testing failed"
    ]
  }
}
```

Recommended blocked-cycle example:

```json
{
  "output_type": "blocked_verification_cycle",
  "payload": {
    "work_item_id": 481,
    "summary": "verification cycle blocked",
    "details": "The same failure repeated after correction."
  }
}
```

Useful but derivative:
- `summary`
- `details`
- `verification_report_path`
- `commands`
- `check_outputs`
- `final_verification_markdown`

Those fields help artifact materialization, but the pass/fail decision must not depend on prose.

For QA tasks, the native `spec/e2e-verdict.json` determines the outcome for every verification terminal
submission, including `blocked_verification_cycle`. Submit `passed --result passed` for a passed native
verdict, or `failed --result failed` for a failed or blocked verdict through `write-result.sh`. A blocked
native verdict routes to e2e environment recovery, not a cycle-resolution question. Missing or stale
native evidence is rejected. Retry creates a new verification item and refreshes the strategy, including
when recovering a legacy QA cycle-review item.
QA summaries and details are generated from the native verdict and receipt error excerpts. Task and
baseline exceptions remain distinct; baseline failure does not by itself establish an infrastructure cause.
A native accepted_with_warnings verdict is submitted as passed --result passed for gate routing,
but its e2e_result and verification-outcome status remain accepted_with_warnings. The coordinator
requires matching operator events for every accepted finding; a worker cannot grant an exception.
Original failure receipts and baseline errors remain in the final report and MR description.
Use POST /operator/resolve-e2e-baseline with the current work item, verdict digest, selected finding
IDs, action accept/correct and an optional comment. Accept continues the same gate and requires all
remaining checks; correct routes to implementation without pretending a regression was proven.
Continuation uses the accepted app artifact. Fresh native verdicts also govern QA SDD_ERROR recovery;
historical errors from the accepted gate cannot reopen it. Retrying the continuation after environment
recovery preserves its work item and decisions, whereas a fresh verification retry does not.
Runtime collection/intake and operator accept/resume/retry are serialized per session; drained error
signatures remain superseded even when worker and native summaries differ. Baseline acceptance requires
actual execution failures, not setup/teardown errors. Task adapters must use the factory-supplied endpoint.

### Convention Reviewer

Used during `convention_review_requested`.

Required:
- `output_type`
- `payload.work_item_id`

Routing by `output_type`:
- `completed` or `passed` -> convention review passed
- `failed` -> convention issues found
- `blocked_review_cycle` -> operator escalation

### Requirements Reviewer

Used during `requirements_review_requested`.

Required:
- `output_type`
- `payload.work_item_id`

Routing by `output_type`:
- `completed` or `passed` -> requirements review passed
- `failed` -> requirements issues found
- `blocked_review_cycle` -> operator escalation

### Story Planning Workers

Applies to:
- `proposal-context-worker`
- `requirements-clarifier-worker`
- `acceptance-criteria-worker`
- `constraints-worker`
- `task-decomposer-worker`

Required:
- `output_type`
- `payload.work_item_id`

For successful completion, the minimal contract is:

```json
{
  "output_type": "completed",
  "payload": {
    "work_item_id": 31
  }
}
```

For blocked planning rounds that need operator input, use `failed` and include only the relevant structured blocker fields:
- `needs_operator_input`
- `failures`
- `missing_inputs`
- `pending_decisions`
- `blocker_questions`
- `next_step`

Example:

```json
{
  "output_type": "failed",
  "payload": {
    "work_item_id": 31,
    "summary": "requirements clarification needed",
    "needs_operator_input": true,
    "missing_inputs": [
      "backend API response shape"
    ],
    "pending_decisions": [
      "choose option A or B"
    ]
  }
}
```

### Spec Verifier Worker

Used during `spec_verification_requested`.

Required:
- `output_type`
- `payload.work_item_id`

For clean completion:

```json
{
  "output_type": "completed",
  "payload": {
    "work_item_id": 41
  }
}
```

For blocked planning verification:

```json
{
  "output_type": "failed",
  "payload": {
    "work_item_id": 41,
    "summary": "planning blockers remain",
    "blocker_questions": [
      "Should cleanup include literals too?"
    ]
  }
}
```

### Doc Harvest

Used during `doc_harvest_requested`.

Required:
- `output_type`
- `payload.work_item_id`

Minimal example:

```json
{
  "output_type": "completed",
  "payload": {
    "work_item_id": 91,
    "summary": "README updated"
  }
}
```

### Coding And Follow-Up Roles

Applies to:
- `implementer`

Required:
- `output_type`
- `payload.work_item_id`

Minimal example:

```json
{
  "output_type": "completed",
  "payload": {
    "work_item_id": 501
  }
}
```

If the routed work is a subtask implementation, include:
- `payload.subtask_key`

Example:

```json
{
  "output_type": "completed",
  "payload": {
    "work_item_id": 501,
    "subtask_key": "IOS-55555"
  }
}
```

## Fields That Should Stay Out Of Terminal Payloads

These fields are often useful for humans or artifacts, but they should not be required for terminal routing:
- long prose summaries
- duplicated markdown content
- report bodies
- full command stdout/stderr
- patch text
- diff excerpts
- repeated absolute paths that are already known from hydration

Keep those in dedicated files under `spec/`, `review/`, `plan/`, or task-local verification logs.

## Supported Path

The supported path is the shared writer helper plus backend ingress.
New role guidance, tests, and runtime work should treat helper submission as the product behavior.
