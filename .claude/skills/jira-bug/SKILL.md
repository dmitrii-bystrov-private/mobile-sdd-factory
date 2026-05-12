---
description: >
  Full bug-fix flow for a Jira bug task: snapshot, analyze bug, optionally write a failing test, implement fix, open MR, request review, send to QA.
  TRIGGER when the user wants to work on a Jira bug end-to-end.
  Examples: "work on IOS-1234 bug", "fix bug IOS-1234", "jira-bug IOS-1234".
---

Orchestrate the full bug-fix flow for Jira bug `$ARGUMENTS`.

## Step 0 — Resolve parent

Determine whether `<KEY>` is a standalone bug or a sub-bug on a story:

```bash
STORY_KEY="$(bash scripts/get-issue-parent.sh <KEY>)"
```

- **Standalone bug** (`STORY_KEY == KEY`): continue with this skill.
- **Sub-bug** (`STORY_KEY != KEY`): delegate to `/jira-story <STORY_KEY>` and stop. Do not proceed further in this skill.

## Step 1 — Snapshot

Run `/snapshot <KEY>` to create the worktree on `bugfix/<KEY>` branch and write `description.md`, `comments.md`, `statuses.md`.

## Step 1.5 — Flow triage (fresh start only)

Skip this step if `$SDD_WORKDIR/<KEY>/spec/bug-analysis.md` already exists (resuming a previous session).

Read `$SDD_WORKDIR/<KEY>/description.md` and `$SDD_WORKDIR/<KEY>/comments.md`. Assess the bug:

- **Oneshot** is appropriate when: it is a UI/visual bug, a copy/text fix, a minor layout issue, a simple config or wiring change — anything where writing a unit or integration test would be over-engineering.
- **Full flow** is appropriate when: the bug is in business logic, involves a data transformation, a state machine, an algorithm, or any behaviour that a unit/integration test could meaningfully protect against regression.

Present the two options to the user (one line each), marking the recommended one:

```
How should I fix this bug?

1. **Oneshot** — snapshot → implement directly → MR  [recommended]
2. **Full bug flow** — snapshot → analyze → optional failing test → fix → MR
```

(Swap `[recommended]` to option 2 when the full flow is more appropriate.)

Wait for the user's choice.

- If **Oneshot** chosen: delegate to `/oneshot <KEY>` and stop. Do not continue this skill.
- If **Full flow** chosen: ask the user which mode to use:

  ```
  How should I run the bug-fix flow?

  1. **Autonomous** — run all steps without pausing; surface only failures and non-reproducible results *(default)*
  2. **With checkpoints** — pause after bug analysis so you can review findings before the fix starts
  ```

  Wait for the answer. Remember the chosen mode for the rest of the flow.

## Step 2 — Resume check

Read `$SDD_WORKDIR/<KEY>/statuses.md` to determine progress.

Resume from the appropriate step:

| Condition | Resume from |
|-----------|-------------|
| Status is `Ready for test` / `Resolved` / `Released` | Inform the user — no action needed |
| Status is `Reopened` | Step 4 — continue from saved analysis with comments priority |
| Subtasks exist, any `To Do` / `In Progress` | Step 5.5 — subtask loop |
| `spec/bug-analysis.md` missing | Step 3 — unified bug work |
| `spec/bug-analysis.md` exists | Step 4 — continue from saved analysis |

## Step 3 — Unified bug work

If mode is **Autonomous**:
- invoke the `bug-fixer` subagent with:
  ```
  Mode: full-bug-fix
  Key: <KEY>
  ```
- the agent reads `description.md` and `comments.md`, analyzes the bug, writes `spec/bug-analysis.md`, optionally writes and commits a failing test, and implements the fix

If mode is **With checkpoints**:
- invoke the `bug-fixer` subagent with:
  ```
  Mode: analysis-only
  Key: <KEY>
  ```
- the agent analyzes the bug, writes `spec/bug-analysis.md`, and optionally writes and commits a failing test, but does not change product code
- present a summary of `spec/bug-analysis.md` to the user and ask: `Ready to proceed with the fix?`
- wait for confirmation before continuing to Step 4

If the agent reports the bug as non-reproducible or not actionable yet:
- surface `spec/bug-analysis.md` findings to the user
- wait for user direction
- do NOT proceed automatically

## Step 4 — Fix the bug

Invoke the `bug-fixer` subagent with:

- for normal continuation:
  ```
  Mode: fix-only
  Key: <KEY>
  ```
- if the current Jira status is `Reopened`:
  ```
  Mode: fix-only
  Key: <KEY>
  Follow-up comments: $SDD_WORKDIR/<KEY>/comments.md
  ```

The agent reads `spec/bug-analysis.md` and implements the fix from it. For reopened tasks, it must treat the latest comments as the highest-priority follow-up scope on top of the saved analysis.

If failure after retries: surface failure details to the user. Stop.

## Step 5.5 — Subtask implementation loop

Reached when subtasks exist with `To Do` or `In Progress` status (created via `/handle-mr-comments`). Skip Step 6 after this step — commits and parent transition happen here.

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

After all subtasks complete, run `/send-to-test <KEY>` to transition the parent bug to **Ready for test**. Then proceed to Step 6.5 (self-review).

## Step 6 — Commit and send to test

```bash
bash scripts/commit-and-resolve.sh <KEY>
```

Commits all changes with message `<KEY>: <title>` and transitions the bug to **Ready for test**.

Skip this step when coming from Step 5.5 — the parent was already transitioned there.

## Step 6.5 — Self-review

Run `/self-review <KEY>`.

If self-review is disabled, the skill stops silently and control returns here.
If self-review finds recurring review cycles or exhausts retry attempts, stop and surface that result to the user.

## Step 6.6 — Boy Scout pass

Run `/boy-scout <KEY>`.

If findings are found:
- `Implement now` was chosen and code was changed → proceed to Step 6.7 after the improvements are applied.
- subtasks / tech-debt stories were created or the pass was skipped/clean → proceed to Step 6.7.

## Step 6.7 — Final verification

Run `/final-verification <KEY>`.

If final verification still fails after its retry limit, stop and surface that result to the user.

## Step 7 — Harvest documentation

Run `/doc-harvest <KEY>`. If doc-harvest is disabled, it stops silently. If enabled, it creates or enriches the feature README from the git diff and commits it as a separate commit on the bugfix branch.

## Step 8 — Open MR

Run `/create-mr` to push the `bugfix/<KEY>` branch, open a GitLab MR to master, and prepare the review message.

---

## Workdir layout produced

```
$SDD_WORKDIR/<KEY>/
├── description.md
├── comments.md
├── statuses.md
├── spec/
│   ├── bug-analysis.md          # analysis + root cause + optional failing test info
│   ├── diff.md                   # structured source diff for self-review / scout
│   ├── final-verification.md     # workflow-level test + lint report
│   └── full-diff.md              # structured source + documentation diff for doc-harvest
├── <SUBTASK-KEY>/                # present only when MR review subtasks exist
│   ├── description.md
│   └── comments.md
└── repo/  (bugfix/<KEY> branch)
```

No `plan/` directory.

## Rules

- MUST run triage (Step 1.5) on fresh start and present both options with `[recommended]` before proceeding.
- MUST skip triage when resuming (spec/bug-analysis.md already exists).
- MUST delegate to `/oneshot <KEY>` and stop if user chooses Oneshot.
- MUST ask for mode (Autonomous / With checkpoints) only after user selects Full flow.
- MUST use `bug-fixer` as the single bug-work agent for analysis and fix; do not invoke a separate analyst.
- MUST pause after Step 3 and wait for user confirmation before Step 4 when mode is **With checkpoints**.
- MUST NOT create Jira subtasks, produce `plan/` files, or run `task-decomposer`.
- MUST run resume check (Step 2) after every snapshot and skip already-completed steps.
- MUST treat `Reopened` parent status as a narrow follow-up implementation pass using saved analysis plus current comments, not as a separate skill route.
- MUST treat `Reopened` subtasks in Step 5.5 as normal implementer work with comments priority, not as a separate skill route.
- MUST use `implementer` subagent (not `bug-fixer`) for subtask implementation in Step 5.5.
- MUST run `/send-to-test <SUBTASK-KEY>` after each subtask succeeds in Step 5.5.
- MUST run `/send-to-test <KEY>` after all subtasks complete to transition the parent.
- MUST skip Step 6 when coming from Step 5.5.
- MUST surface `bug-fixer` failure to user and halt.
- MUST delegate Step 6.5 self-review to `/self-review <KEY>` instead of inlining the review loop.
- MUST run Step 6.6 Boy Scout before final verification so that `Implement now` changes cannot bypass the `test + lint` gate.
- MUST delegate Step 6.7 final verification to `/final-verification <KEY>` instead of inlining the verification loop.
- MUST NOT inspect code, make implementation decisions, or run build/test/lint directly.
