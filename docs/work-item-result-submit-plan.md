# Work Item Result Submit Plan

This document fixes the rollout plan for deterministic terminal result submission.

## Goal

Routed roles should not need to know:
- the terminal `RESULT.json` path
- the role name for terminal submission
- any other coordinator-owned filesystem details

The only coordinator context key a role should submit is:
- `work_item_id`

The role should submit only the outcome fields it actually knows from the current run.

## Rollout Steps

1. Make `work_item_id` the primary terminal submit key.
2. Teach `write-result.py` to resolve session, role, stage, and canonical result path from `work_item_id`.
3. Remove `--output` from the primary prompt contract.
4. Remove explicit role names from the primary prompt contract when they can be derived from `work_item_id`.
5. Update prompts and AGENTS/workspace rules to show the minimal helper invocation.
6. Keep strict backend intake and schema validation fail-closed.
7. Add helper tests for `work_item_id` resolution and invalid context cases.
8. Roll the short submit form out to `verification-coordinator`, `code-scout`, and `code-reviewer` first.
9. Verify live roles submit successfully with the short `--work-item-id` form.
10. If live rollout stays stable, keep the submit contract limited to `work_item_id` plus outcome fields.

## Non-Goals For This Step

- This step does not yet replace file-based result submission with an HTTP or socket ingress.
- This step does not relax backend schema validation.
- This step does not make invalid terminal payloads recover automatically; that remains a separate recovery flow.
