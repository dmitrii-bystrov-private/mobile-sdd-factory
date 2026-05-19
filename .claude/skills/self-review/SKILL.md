---
description: >
  Self-review pass: run a convention-focused diff review, route fixes through implementer,
  and stop on recurring review cycles. Can be invoked standalone: /self-review <KEY>.
---

Run a self-review pass for Jira task `$ARGUMENTS`.

Parse `<KEY>` from `$ARGUMENTS`.

- `<KEY>` is required.

This skill defines the legacy slash-command self-review surface. The current primary product flow runs self-review through the backend session runtime and persistent reviewer lane.

## Step 0 — Check feature flag

```bash
echo "${SELF_REVIEW_ENABLED:-false}"
```

If the output is not `true` — stop immediately with no output. Do not proceed to Step 1.
This env flag gates the legacy slash-command surface only. The current platform normally configures self-review policy through `.sdd-factory/settings.local.json` and the operator UI.

## Step 1 — Generate diff

```bash
bash scripts/generate-diff.sh <KEY>
```

This writes `$SDD_WORKDIR/<KEY>/spec/diff.md`.

## Step 2 — Pick output file

Determine the next pass number: count existing files matching `$SDD_WORKDIR/<KEY>/review/pass-*.md` and add 1.
Zero-pad to two digits (e.g. `pass-01.md`, `pass-02.md`).
Set:

```bash
PASS_FILE=$SDD_WORKDIR/<KEY>/review/pass-NN.md
```

## Step 3 — Run reviewer

Collect paths of all existing pass files (if any):

```bash
ls $SDD_WORKDIR/<KEY>/review/pass-*.md 2>/dev/null
```

Invoke the `code-reviewer` subagent:

```text
Key: <KEY>
Diff: $SDD_WORKDIR/<KEY>/spec/diff.md
Project directory: $SDD_WORKDIR/<KEY>/repo
Output: <PASS_FILE>
Previous reviews: <space-separated list of existing pass-*.md paths>   ← omit line if none exist
```

The reviewer writes its result to `<PASS_FILE>`.

## Step 4 — Read result

Read the **first line** of `<PASS_FILE>`:

- `REVIEW_RESULT: clean` → stop and return control to the caller.
- `REVIEW_RESULT: issues_found` → proceed to Step 5.

## Step 5 — Cycle detection

Run cycle detection in two stages.

**Stage 1 — filename overlap**
- Extract the set of filenames from `### [error]` and `### [warning]` heading lines in `<PASS_FILE>`.
- If a previous pass file exists (`pass-(NN-1).md`), extract the same set from it.
- If the two sets do not overlap, there is no cycle. Proceed to Step 6.

**Stage 2 — issue identity check**
- Only when filenames overlap, compare the section body for each overlapping filename in both pass files.
- The section body is the text between the `### [...]` heading and the next heading or end of file.
- If the body text for any overlapping filename is semantically identical (same rule violated, same code location, same recommendation), treat it as a true cycle.

If a true cycle is detected:
- stop immediately;
- show the user the full content of both pass files verbatim;
- do not invoke the fixer again.

If overlapping filenames exist but the body text differs, proceed to Step 6.

## Step 6 — Route fixes

Invoke the `implementer` subagent:

```text
Mode: self-review-fix
Fix the following code review issues in the project.
Project directory: $SDD_WORKDIR/<KEY>/repo
Issues file: <PASS_FILE>
```

After the fixer succeeds, commit the fixes:

```bash
git -C "$SDD_WORKDIR/<KEY>/repo" commit -am "fix(<KEY>): self-review corrections"
```

Then re-run the skill starting from Step 1.

## Step 7 — Retry limit

If issues are still found after 10 fix attempts, stop and report the remaining issues to the user.
Do not continue the outer workflow automatically.

## Rules

- MUST stop silently when `SELF_REVIEW_ENABLED` is not `true`.
- MUST act only as orchestration: generate the diff, invoke `code-reviewer`, invoke `implementer`, and manage pass files.
- MUST NOT inspect code or make implementation decisions itself.
- MUST return control to the caller immediately when review result is clean.
