# Skills

This catalog documents the legacy slash-command skill surface. The current primary product entrypoint is the operator UI and backend session runtime, but these skills still exist for compatibility and local scripted use. Each skill lives in its own directory with a `SKILL.md` file.

## Task lifecycle

```
Story flow:
/jira-task → /jira-story → (internal: proposal/context → requirements clarification →
  acceptance criteria → constraints → spec verification → story spec →
  task decomposition → automatic execution / subtask graph →
  optional-or-required self-review → optional-or-required boy-scout →
  verification → automatic MR handoff → automatic send-to-test)

Bug flow:
/jira-task → /jira-bug → (internal: bug-fixer →
  optional-or-required self-review → optional-or-required boy-scout →
  verification → automatic MR handoff → automatic send-to-test)

One-shot flow (explicit only):
/oneshot → /snapshot → (internal: implementer →
  optional-or-required self-review → optional-or-required boy-scout →
  verification → automatic MR handoff → automatic send-to-test)

QA / MR follow-up loop (all flows):
  send-to-test completed → [QA reviews or MR comments] → reopen / follow-up analysis →
  optional subtask materialization → execution / quality loops → automatic delivery again
```

## Catalog

### Planning & implementation

| Skill | Command | Description |
|-------|---------|-------------|
| jira-task | `/jira-task <KEY>` | Router: fetch issue type and delegate to `/jira-story` (Story) or `/jira-bug` (Bug). Also triggered by pasting a bare Jira URL. |
| jira-story | `/jira-story <KEY>` | Full story flow: produce planning artifacts, decompose into a plan, execute through the implementation/subtask graph, and continue through quality and delivery lanes. |
| jira-bug | `/jira-bug <KEY>` | Bug flow: analyze root cause, implement the fix, and continue through quality and delivery lanes. |
| oneshot | `/oneshot <KEY>` | One-shot flow for stories or bugs: snapshot → implement from description.md + comments.md directly, no context/spec pipeline. For small, self-contained tasks. Must be invoked explicitly. |
| snapshot | `/snapshot <KEY>` | Prepare a Jira workspace — fetch issue data, create a git worktree, write `description.md`, `comments.md`, `statuses.md`. Called internally by story/bug skills; also available standalone for refresh. |
| self-review | `/self-review <KEY>` | Run the review lane as a standalone orchestration step. The persistent `code-reviewer` can pass, request corrections, skip when optional, or block a non-converging review cycle. |
| final-verification | `/final-verification <KEY>` | Run the workflow-level verification lane as a standalone orchestration step. The persistent `verification-coordinator` can pass, request corrections, or block a non-converging verification cycle. |

### QA workflow

| Skill | Command | Description |
|-------|---------|-------------|
| send-to-test | `/send-to-test <KEY>` | Manual compatibility entrypoint for the final delivery transition. In the current platform this is normally driven automatically after MR handoff. |

### GitLab & Slack

| Skill | Command | Description |
|-------|---------|-------------|
| create-mr | `/create-mr` | Manual compatibility entrypoint for MR handoff. In the current platform this is normally driven automatically by the delivery stage. |
| handle-mr-comments | `/handle-mr-comments <KEY> <MR>` | Fetch unresolved MR discussions, group them into actionable themes, write `plan/` files, and support follow-up Jira subtask creation and execution. Requires an existing task workspace (`/snapshot <KEY>`); can auto-detect the Jira key from the MR if omitted. |

### Jira

| Skill | Command | Description |
|-------|---------|-------------|
| create-task | `/create-task` | Create a Jira Bug or Story in the iOS or Android project. |

### Documentation

| Skill | Command | Description |
|-------|---------|-------------|
| doc-harvest | `/doc-harvest <KEY>` | Create or enrich feature-level `README.md` files in the repository from the structured branch diff. In the current platform it can be optional or required and may auto-skip as `not needed` when appropriate. |
| boy-scout | `/boy-scout <KEY>` | Run the Boy Scout lane over the structured source diff, route implement-now findings back to coding, and escalate old-code candidates into tech-debt decisions when needed. |

### Workspace maintenance

| Skill | Command | Description |
|-------|---------|-------------|
| cleanup | `/cleanup` | Scan `$SDD_WORKDIR`, check Jira status, and remove worktree + directory for tasks with status `Resolved`. |

## File layout per task

```
$SDD_WORKDIR/<STORY-KEY>/
├── description.md          # parent issue metadata + description (snapshot)
├── comments.md             # parent issue comments, chronological (snapshot)
├── statuses.md             # parent + subtasks status table (snapshot)
├── spec/
│   ├── proposal.md         # collected requirements (proposal-collector)
│   ├── context/
│   │   └── project.md -> <project>/CLAUDE.md
│   ├── requirements.md     # clarified requirements
│   ├── acceptance_criteria.md
│   ├── constraints.md
│   ├── diff.md             # structured source diff vs master (default generate-diff.sh output)
│   ├── final-verification.md  # workflow-level test + lint report (optional)
│   ├── doc-diff.md         # structured documentation-only diff (optional)
│   └── full-diff.md        # structured source + documentation diff (optional, e.g. doc-harvest)
├── plan/                   # stories only
│   ├── index.md
│   └── NN-task-name.md
├── repo/                   # git worktree on feature/<KEY> or bugfix/<KEY>
└── <SUBTASK-KEY>/
    ├── description.md
    └── comments.md
```

For bugs: no `plan/`; `spec/` contains `bug-analysis.md` plus generated verification/diff artifacts instead of `requirements.md`/`acceptance_criteria.md`/`constraints.md`.

## Direct script reference

The skills are wrappers around the shell scripts in [`scripts/`](../../scripts). For direct CLI usage, environment-variable requirements, and debugging helpers, see [`scripts/README.md`](../../scripts/README.md).
