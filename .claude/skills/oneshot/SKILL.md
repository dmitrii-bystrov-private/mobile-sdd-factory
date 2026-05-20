---
description: >
  One-shot flow for a Jira story or bug: snapshot, then implement directly from description.md and comments.md without
  planning, spec preparation, or bug reproduction. Designed for small, self-contained tasks.
  TRIGGER only on explicit invocation: "/oneshot <KEY>" or when the user explicitly asks to "oneshot" a task.
  DO NOT TRIGGER automatically when the user mentions a Jira key — use /jira-task for that.
---

Orchestrate a one-shot implementation for Jira issue `$ARGUMENTS`.

This skill defines the legacy slash-command oneshot flow. The current primary product flow runs through the operator UI and backend session runtime, where even oneshot execution continues through persistent quality and delivery stages.

## Step 1 — Snapshot

Run `/snapshot <KEY>` to fetch Jira data, create the worktree, and write `description.md`, `comments.md`, `statuses.md`.

The branch will be `feature/<KEY>` for stories and `bugfix/<KEY>` for bugs.

## Step 2 — Status check

Read `$SDD_WORKDIR/<KEY>/statuses.md`.

| Status | Action |
|--------|--------|
| `Ready for test` / `Resolved` / `Released` | Inform the user — no action needed. Stop. |
| `Reopened` | Step 3 — implement reopened fixes with comments priority. |
| Subtasks exist, any `To Do` / `In Progress` | Step 3.5 — subtask loop. |
| Any other status | Proceed to Step 3. |

## Step 3 — Implement

Invoke the `implementer` subagent with:

```
Implement the task described in $SDD_WORKDIR/<KEY>/description.md.
Additional context (QA comments, clarifications): $SDD_WORKDIR/<KEY>/comments.md
Project directory: $SDD_WORKDIR/<KEY>/repo
```

If the implementer fails after retries: surface failure details to the user and stop.

## Step 3.5 — Subtask implementation loop

Reached when subtasks exist with `To Do` or `In Progress` status (created via `/handle-mr-comments`). Skip Step 4 after this step — commits and parent transition happen here.

For each subtask with status `To Do`, `In Progress`, or `Reopened` (in order from `statuses.md`):

1. Invoke the `implementer` subagent:
   - If status is `To Do` or `In Progress`, pass:
     ```
     Implement subtask <SUBTASK-KEY>.
     Spec: $SDD_WORKDIR/<KEY>/<SUBTASK-KEY>/description.md
     Project directory: $SDD_WORKDIR/<KEY>/repo
     ```
   - If status is `Reopened`, pass:
     ```
     Fix reopened subtask <SUBTASK-KEY>.
     Original spec: $SDD_WORKDIR/<KEY>/<SUBTASK-KEY>/description.md
     Latest comments and QA feedback: $SDD_WORKDIR/<KEY>/<SUBTASK-KEY>/comments.md
     Project directory: $SDD_WORKDIR/<KEY>/repo

     Read the original spec first to understand the original intent.
     Prioritize the latest comments and fix only the reopened issues unless a tiny directly-related adjustment is required.
     ```
2. After the implementer succeeds, run `/send-to-test <SUBTASK-KEY>`.

On subtask success, immediately launch the next without pausing.

**Failure handling:** if implementer fails after 3 retries, report failure details to the user and wait for input before continuing with remaining subtasks.

After all subtasks complete, run `/send-to-test <KEY>` to transition the parent issue to **Ready for test**. Then proceed to Step 4.5 (self-review).

## Step 4 — Send to test

```bash
bash scripts/send-to-test.sh <KEY>
```

Transitions the issue to **Ready for test** after the workflow has already committed progress and completed MR handoff.

Skip this step when coming from Step 3.5 — the parent was already transitioned there.

## Step 4.5 — Self-review

Run `/self-review <KEY>`.

If self-review is disabled, the skill stops silently and control returns here.
If self-review finds recurring review cycles or exhausts retry attempts, stop and surface that result to the user.

## Step 4.6 — Boy Scout pass

Run `/boy-scout <KEY>`.

If findings are found:
- `Implement now` was chosen and code was changed → proceed to Step 4.7 after the improvements are applied.
- subtasks / tech-debt stories were created or the pass was skipped/clean → proceed to Step 4.7.

## Step 4.7 — Final verification

Run `/final-verification <KEY>`.

If final verification still fails after its retry limit, stop and surface that result to the user.

## Step 5 — Harvest documentation

Run `/doc-harvest <KEY>`. If doc-harvest is disabled, it stops silently. If enabled, it creates or enriches the feature README from the git diff and commits it as a separate commit on the branch.

## Step 6 — Open MR

Run `/create-mr` to push the branch, open a GitLab MR to master, and prepare the review message.

---

## Workdir layout produced

```
$SDD_WORKDIR/<KEY>/
├── description.md
├── comments.md
├── statuses.md
├── spec/
│   ├── diff.md                   # structured source diff for self-review / scout
│   ├── final-verification.md     # workflow-level test + lint report
│   └── full-diff.md              # structured source + documentation diff for doc-harvest
├── <SUBTASK-KEY>/                # present only when MR review subtasks exist
│   ├── description.md
│   └── comments.md
└── repo/  (feature/<KEY> or bugfix/<KEY> branch)
```

No `plan/`, requirements, or story-spec files.

## Rules

- MUST NOT be triggered automatically by a bare Jira key — requires explicit `/oneshot` invocation or explicit user request to oneshot.
- MUST NOT create Jira subtasks, produce `plan/` files, or run any spec/planning agents.
- MUST NOT run a bug-style analysis/reproduction phase or force failing-test-first behavior.
- MUST pass `description.md` and `comments.md` directly to the implementer — no intermediate transformation.
- MUST treat `Reopened` parent status in Step 2 as a normal implementation pass with comments priority, not as a separate skill route.
- MUST treat `Reopened` subtasks in Step 3.5 as normal implementer work with comments priority, not as a separate skill route.
- MUST use `implementer` subagent for subtask implementation in Step 3.5.
- MUST run `/send-to-test <SUBTASK-KEY>` after each subtask succeeds in Step 3.5.
- MUST run `/send-to-test <KEY>` after all subtasks complete to transition the parent.
- MUST skip Step 4 when coming from Step 3.5.
- MUST surface implementer failure to user and halt.
- MUST delegate Step 4.5 self-review to `/self-review <KEY>` instead of inlining the review loop.
- MUST run Step 4.6 Boy Scout before final verification so that `Implement now` changes cannot bypass the `test + lint` gate.
- MUST delegate Step 4.7 final verification to `/final-verification <KEY>` instead of inlining the verification loop.
