# Terminal Result Contract

This document fixes the minimum deterministic contract for role `RESULT.json` files.

The goal is simple:
- orchestration must depend only on a small structured payload
- markdown reports, summaries, and console output stay human-facing
- roles should not hand-assemble large JSON objects when only a few fields drive state transitions

## General Rules

Every terminal result file must be a single valid JSON object:

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
- `RESULT.json` is the only terminal state input for orchestration.
- Free-form console output, `summary`, markdown files, and telemetry never decide state transitions.
- Role-specific reports such as `spec/final-verification.md`, `spec/findings.md`, and review markdown stay derivative artifacts.
- Extra payload fields are allowed only when they are part of a documented role contract.

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

### Code Scout

Used during `boy_scout_requested`.

Required:
- `output_type`
- `payload.work_item_id`
- `payload.result`

Allowed `payload.result` values:
- `clean`
- `findings_found`

Additional required fields when `payload.result == "findings_found"`:
- `payload.findings_count`
- `payload.findings_path`

Minimal clean example:

```json
{
  "output_type": "completed",
  "payload": {
    "work_item_id": 123,
    "result": "clean"
  }
}
```

Minimal findings example:

```json
{
  "output_type": "completed",
  "payload": {
    "work_item_id": 123,
    "result": "findings_found",
    "findings_count": 2,
    "findings_path": "/abs/path/to/spec/findings.md"
  }
}
```

Not required for orchestration:
- `summary`
- `details`
- echoed finding text inside `RESULT.json`

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

### Code Reviewer

Used during `self_review_requested`.

Required:
- `output_type`
- `payload.work_item_id`

Routing by `output_type`:
- `completed` or `passed` -> self review passed
- `failed` -> issues found
- `blocked_review_cycle` -> operator escalation

Minimal pass example:

```json
{
  "output_type": "completed",
  "payload": {
    "work_item_id": 210,
    "summary": "clean review"
  }
}
```

Minimal issues-found example:

```json
{
  "output_type": "failed",
  "payload": {
    "work_item_id": 210,
    "summary": "review issues found"
  }
}
```

Minimal blocked-cycle example:

```json
{
  "output_type": "blocked_review_cycle",
  "payload": {
    "work_item_id": 210,
    "summary": "self review cycle blocked",
    "details": "The same issue repeated after correction."
  }
}
```

Useful but derivative:
- `details`
- `issues_markdown`
- report file paths

The routed review markdown file is still required as an artifact, but orchestration does not need it inside `RESULT.json`.

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

### Coding And MR Follow-Up Roles

Applies to:
- `implementer`
- `bug-fixer`
- `mr-comments-analyst-worker`

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

## Fields That Should Move Out Of RESULT.json

These fields are often useful for humans or artifacts, but they should not be required for terminal routing:
- long prose summaries
- duplicated markdown content
- report bodies
- full command stdout/stderr
- patch text
- diff excerpts
- repeated absolute paths that are already known from hydration

Keep those in dedicated files under `spec/`, `review/`, `plan/`, or task-local verification logs.

## Next Migration Step

To make this contract deterministic in practice:
- roles should stop writing JSON manually
- a shared writer helper should emit `RESULT.json`
- prompts should ask roles for the minimum fields only

This document defines the target schema for that helper migration.
