---
description: >
  Full story flow for a Jira story task: snapshot, collect proposal and context, clarify requirements, write spec, decompose, create subtasks, implement, open MR.
  TRIGGER when the user wants to work on a Jira story end-to-end.
  Examples: "work on IOS-1234 story", "jira-story IOS-1234", "implement story IOS-1234".
---

Orchestrate the full story flow for Jira story `$ARGUMENTS`.

## Step 0 — Resolve key

```bash
KEY="$(bash scripts/get-issue-parent.sh <KEY>)"
```

If a subtask key was passed, `<KEY>` is replaced with its parent story key. All subsequent steps use the resolved
`<KEY>`.

## Step 1 — Snapshot

Run `/snapshot <KEY>` to fetch Jira data, create worktree on `feature/<KEY>`, and write `description.md`, `comments.md`,
`statuses.md`.

## Step 1.5 — Flow triage (fresh start only)

Skip this step if `$SDD_WORKDIR/<KEY>/spec/proposal.md` already exists (resuming a previous session).

Read `$SDD_WORKDIR/<KEY>/description.md` and `$SDD_WORKDIR/<KEY>/comments.md`. Assess the story:

- **Oneshot** is appropriate when: it is a config change, a text/copy update, a simple wiring or mapping task, a small isolated UI tweak — anything self-contained enough that full spec, decomposition, and subtasks would be over-engineering.
- **Full flow** is appropriate when: the story involves new screens or flows, significant business logic, multiple components, platform-specific integration, or anything that benefits from requirements clarification and structured decomposition.

Present the two options to the user (one line each), marking the recommended one:

```
How should I implement this story?

1. **Oneshot** — implement directly from the description → MR
2. **Full story flow** — proposal → context → requirements → spec → decompose → subtasks → implement → MR  [recommended]
```

(Swap `[recommended]` to option 1 when the story is clearly small and self-contained.)

Wait for the user's choice.

- If **Oneshot** chosen: delegate to `/oneshot <KEY>` and stop. Do not continue this skill.
- If **Full flow** chosen: continue to Step 2.

## Step 2 — Resume check

Read `$SDD_WORKDIR/<KEY>/statuses.md` to determine story status and progress.

Each entry is a **starting point** — after resuming from that step, continue all subsequent steps in order through Step 12.

Subtask status always takes priority over parent story status. Check subtask conditions before story-level conditions.

| Condition                                                            | Start from                                |
|----------------------------------------------------------------------|-------------------------------------------|
| `spec/proposal.md` missing                                           | Step 3                                    |
| `spec/proposal.md` exists, `spec/context/` empty or missing          | Step 4                                    |
| `spec/context/` populated, `spec/requirements.md` missing            | Step 5                                    |
| `spec/requirements.md` exists, `spec/acceptance_criteria.md` missing | Step 6                                    |
| `spec/acceptance_criteria.md` exists, `spec/constraints.md` missing  | Step 7                                    |
| `spec/constraints.md` exists, `plan/index.md` missing                | Step 8                                    |
| `plan/index.md` exists, no Jira subtasks yet                         | Step 10                                   |
| Subtasks exist, some are `To Do` / `In Progress` / `Reopened`        | Step 11 *(regardless of parent story status)* |
| All subtasks `Resolved` / `Ready for test`, no MR yet                | Step 12                                   |
| Story status is `Ready for test` / `Released`, **and** no open subtasks | Inform user — no action needed         |

## Step 3 — Collect proposal

Invoke the `proposal-collector` subagent with key `<KEY>`.

On failure: surface the error to the user. Do not proceed.

## Step 4 — Collect context

Invoke the `context-collector` subagent with key `<KEY>`.

On failure: surface the error to the user. Do not proceed.

## Step 5 — Clarify requirements

Ask the user which autonomy level to use:

```
How much should I ask you during requirements clarification?

1. **Ask a lot** — ask about almost everything except the most obvious details
2. **Ask selectively** — ask only when something is genuinely ambiguous and I can't make a reasonable call *(default)*
3. **Autonomous** — resolve all ambiguities on my own, ask nothing
```

Wait for the answer. Then invoke the `requirements-clarifier` subagent (Pass 1) with key `<KEY>` and the chosen level in the prompt (e.g. `Autonomy level: ask-selectively`).

**If the agent reports questions** (`spec/clarification-questions.md` is present):
- Read the file and present each question to the user.
- Collect all answers.
- Write `spec/clarification-answers.md`:
  ```markdown
  # Clarification Answers: <KEY>

  ## Q1: <title>
  **Answer**: <user's answer>

  ## Q2: ...
  ```
- Invoke the `requirements-clarifier` subagent again (Pass 2) with the same working directory and autonomy level.
- **Repeat** this loop until the agent writes `spec/requirements.md` (no more questions).

**If the agent writes `spec/requirements.md` directly** (no questions): proceed to Step 6.

## Step 6 — Write acceptance criteria

Invoke the `acceptance-criteria-writer` subagent with key `<KEY>`.

## Step 7 — Define constraints

Invoke the `constraints-definer` subagent with key `<KEY>`.

## Step 8 — Verify spec

Invoke the `spec-verifier` subagent (Pass 1) with key `<KEY>`.

The planning/spec agents should treat `spec/context/feature-overview.md` as the primary compact handoff and pull deeper context files only when they are actually needed.

**If the verifier reports BLOCKERs** (`spec/verification-report.md` is present):
- Read `spec/verification-report.md` and present each BLOCKER to the user with its options.
- Collect the user's decisions for all BLOCKERs.
- Write `spec/blocker-resolutions.md`:
  ```markdown
  # Blocker Resolutions: <KEY>

  ## B1: <title>
  **Decision**: <chosen option or free-form answer>

  ## B2: ...
  ```
- Invoke the `spec-verifier` subagent again (Pass 2) with the same working directory.
- Repeat until the verifier reports clean.

**If the verifier reports clean** (no `spec/verification-report.md`): proceed to Step 9.

## Step 9 — Decompose into tasks

Invoke the `task-decomposer` subagent with key `<KEY>`.

## Step 10 — Create Jira subtasks

1. Run:
   ```bash
   scripts/create-subtasks-batch.sh --parent <KEY>
   ```

   On partial failure: surface which task failed and why to the user. Halt.

2. Run `/snapshot <KEY>` to fetch fresh details and update `statuses.md` before starting the first subtask.

3. Notify the developer:
   > **Action required before implementation starts:**
   > Stories require **Story Points** and **Dev finish date** to be set in Jira before they can be moved to In Progress.
   > Please update [KEY](https://pnlfintech.atlassian.net/browse/KEY) and transition it to **In Progress** manually.
   > Let me know when done — I'll proceed with implementation.

   Wait for the user to confirm before continuing to Step 11.

## Step 11 — Implementation loop

For first subtask from `statuses.md` with status `To Do`, `In Progress`, or `Reopened`:

1. Invoke the `implementer` subagent with the subtask spec:
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

   Pass exactly the shown block for the chosen case — no extra instructions. The implementer agent owns the code changes; workflow-level verification runs later in this skill.

2. After the implementer succeeds, run `/send-to-test <SUBTASK-KEY>` to commit changes and transition the subtask to Ready for test.

On subtask success, immediately launch the next subtask without pausing.

**Failure handling:** if an implementer fails after 3 retry attempts:

- Report failure details to the user.
- Wait for user input before continuing with remaining subtasks.

## Step 11.5 — Self-review

Run `/self-review <KEY>`.

If self-review is disabled, the skill stops silently and control returns here.
If self-review finds recurring review cycles or exhausts retry attempts, stop and surface that result to the user.

## Step 11.6 — Boy Scout pass

Run `/boy-scout <KEY>`.

If findings are found:
- `Implement now` was chosen and code was changed → proceed to Step 11.7 after the improvements are applied.
- subtasks / tech-debt stories were created or the pass was skipped/clean → proceed to Step 11.7.

## Step 11.7 — Final verification

Run `/final-verification <KEY>`.

If final verification still fails after its retry limit, stop and surface that result to the user.

## Step 12 — After all subtasks complete

1. Run `/doc-harvest <KEY>`. If doc-harvest is disabled, it stops silently. If enabled, it creates or enriches the feature README in the repository from the branch diff and commits it as a separate commit on the feature branch.

2. Run `/send-to-test <KEY>` to transition the parent story to **Ready for test**.

3. Run `/create-mr` automatically.

---

## Workdir layout produced

```
$SDD_WORKDIR/<KEY>/
├── description.md
├── comments.md
├── statuses.md
├── spec/
│   ├── proposal.md
│   ├── context/
│   │   └── project.md -> <project>/CLAUDE.md
│   ├── requirements.md
│   ├── acceptance_criteria.md
│   ├── constraints.md
│   ├── diff.md                   # structured source diff for self-review / scout
│   ├── final-verification.md     # workflow-level test + lint report
│   └── full-diff.md              # structured source + documentation diff for doc-harvest
├── plan/
│   ├── index.md
│   └── NN-task-name.md (one per task)
├── <SUBTASK-KEY>/
│   ├── description.md
│   └── comments.md
└── repo/ (feature/<KEY> branch)
```

## Rules

- MUST run triage (Step 1.5) on fresh start and present both options with `[recommended]` before proceeding.
- MUST skip triage when resuming (spec/proposal.md already exists).
- MUST delegate to `/oneshot <KEY>` and stop if user chooses Oneshot.
- MUST run resume check (Step 2) after every snapshot and skip already-completed steps.
- MUST orchestrate steps 3–12 in the order defined above, starting from the resume point.
- MUST NOT inspect code, make implementation decisions, or run build/test/lint directly.
- MUST use `scripts/create-subtasks-batch.sh` for Jira subtask creation.
- MUST run `/send-to-test <SUBTASK-KEY>` after each implementer succeeds.
- MUST run `/send-to-test <KEY>` to transition the story to Ready for test before creating the MR.
- MUST automatically run `/create-mr` after all subtasks complete.
- MUST treat `Reopened` subtasks in Step 11 as normal implementer work with comments priority, not as a separate skill route.
- MUST delegate Step 11.5 self-review to `/self-review <KEY>` instead of inlining the review loop.
- MUST run Step 11.5 self-review before later post-code-work steps; do not proceed while issues remain.
- MUST run Step 11.6 Boy Scout before final verification so that `Implement now` changes cannot bypass the `test + lint` gate.
- MUST delegate Step 11.7 final verification to `/final-verification <KEY>` instead of inlining the verification loop.
