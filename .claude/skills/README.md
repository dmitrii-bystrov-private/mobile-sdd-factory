# Skills

Skills are prompt templates invoked via `/skill-name` in Claude Code. Each skill lives in its own directory with a `SKILL.md` file.

## Task lifecycle

```
Story flow:
/jira-task → /jira-story → (internal: proposal-collector → context-collector →
  requirements-clarifier → acceptance-criteria-writer → constraints-definer →
  spec-verifier → task-decomposer → subtask creation → implementer loop →
  optional /self-review → optional boy-scout → /final-verification → optional doc-harvest) → /create-mr → /send-to-test

Bug flow:
/jira-task → /jira-bug → (internal: bug-fixer →
  commit → optional /self-review → optional boy-scout → /final-verification → optional doc-harvest) → /create-mr → /send-to-test

One-shot flow (explicit only):
/oneshot → /snapshot → (internal: implementer → commit →
  optional /self-review → optional boy-scout → /final-verification → optional doc-harvest) → /create-mr → /send-to-test

QA loop (all flows):
  /send-to-test → [QA reviews] → (if Reopened) reopen the task and continue the normal implementation flow with comments priority → /send-to-test
```

## Catalog

### Planning & implementation

| Skill | Command | Description |
|-------|---------|-------------|
| jira-task | `/jira-task <KEY>` | Router: fetch issue type and delegate to `/jira-story` (Story) or `/jira-bug` (Bug). Also triggered by pasting a bare Jira URL. |
| jira-story | `/jira-story <KEY>` | Full story flow: collect requirements, write spec, decompose into subtasks, create subtasks in Jira, run implementer loop, open MR. |
| jira-bug | `/jira-bug <KEY>` | Bug flow: analyze root cause, write and commit failing test, implement fix, send to QA. |
| oneshot | `/oneshot <KEY>` | One-shot flow for stories or bugs: snapshot → implement from description.md + comments.md directly, no context/spec pipeline. For small, self-contained tasks. Must be invoked explicitly. |
| snapshot | `/snapshot <KEY>` | Prepare a Jira workspace — fetch issue data, create a git worktree, write `description.md`, `comments.md`, `statuses.md`. Called internally by story/bug skills; also available standalone for refresh. |
| self-review | `/self-review <KEY>` | Run the optional convention-focused diff review as a standalone orchestration step. Generates the structured diff, calls `code-reviewer`, and routes fixes through `implementer`. |
| final-verification | `/final-verification <KEY>` | Run the workflow-level `test + lint` gate as a standalone orchestration step. Calls `final-verifier`, routes verification corrections through `implementer`, and manages the retry loop. |

### QA workflow

| Skill | Command | Description |
|-------|---------|-------------|
| send-to-test | `/send-to-test <KEY>` | Commit local changes and transition the task to "Ready for test". |

### GitLab & Slack

| Skill | Command | Description |
|-------|---------|-------------|
| create-mr | `/create-mr` | Commit changes, push, open a GitLab merge request to master, and prepare the Slack-ready review message. |
| handle-mr-comments | `/handle-mr-comments <KEY> <MR>` | Fetch unresolved MR discussions, group them into actionable themes, write `plan/` files, and create Jira subtasks. Supports selective subtask creation with `create-subtasks-batch.sh --task-file` when only new follow-up artifacts should be created. Requires an existing task workspace (`/snapshot <KEY>`); can auto-detect the Jira key from the MR if omitted. |

### Jira

| Skill | Command | Description |
|-------|---------|-------------|
| create-task | `/create-task` | Create a Jira Bug or Story in the iOS or Android project. |

### Documentation

| Skill | Command | Description |
|-------|---------|-------------|
| doc-harvest | `/doc-harvest <KEY>` | Create or enrich feature-level `README.md` files in the repository from the structured branch diff. Called automatically by flows only when enabled; also available standalone. |
| boy-scout | `/boy-scout <KEY>` | Run an optional improvement pass over the structured source diff, present real maintainability findings, and optionally create subtasks or tech-debt stories. |

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
