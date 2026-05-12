---
description: >
  Final verification pass: run workflow-level test + lint, route verification fixes through implementer,
  and stop after repeated failed verification cycles. Can be invoked standalone: /final-verification <KEY>.
---

Run final verification for Jira task `$ARGUMENTS`.

Parse `<KEY>` from `$ARGUMENTS`. If missing, ask for it.

## Step 1 — Run verification

Invoke the `final-verifier` subagent with key `<KEY>`.

The agent writes `$SDD_WORKDIR/<KEY>/spec/final-verification.md`.

## Step 2 — Read result

Read `$SDD_WORKDIR/<KEY>/spec/final-verification.md`.

- If the result is `PASS` — stop and return control to the caller.
- If the result is `FAIL` — proceed to Step 3.

## Step 3 — Fix verification failures

Invoke the `implementer` subagent:

```text
Fix the final verification failures in the project.
Project directory: $SDD_WORKDIR/<KEY>/repo
Issues file: $SDD_WORKDIR/<KEY>/spec/final-verification.md
```

After the implementer succeeds, commit the fixes:

```bash
git -C "$SDD_WORKDIR/<KEY>/repo" commit -am "fix(<KEY>): verification corrections"
```

Then re-run the skill from Step 1.

## Step 4 — Retry limit

If verification still fails after 3 verification/fix cycles, stop and report the remaining failures to the user.
Do not continue the outer workflow automatically.

## Rules

- MUST act only as orchestration: invoke `final-verifier`, read `spec/final-verification.md`, invoke `implementer`, and manage retry cycles.
- MUST NOT inspect code or make implementation decisions itself.
- MUST use `implementer` for verification correction passes in all flows.
- MUST return control to the caller immediately when verification passes.
