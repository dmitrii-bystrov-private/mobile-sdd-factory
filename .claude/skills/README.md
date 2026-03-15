# Skills

Skills are prompt templates invoked via `/skill-name` in Claude Code. Each skill lives in its own directory with a `SKILL.md` file.

## Task lifecycle

```
/snapshot → /spec → /implement → /send-to-test
                                      ↓ (Reopened)
                               /fix-review → /send-to-test
```

At any point: `/create-mr` to open an MR, `/request-review` to post it to Slack.

## Catalog

### Planning & implementation

| Skill | Command | Description |
|-------|---------|-------------|
| snapshot | `/snapshot <KEY>` | Prepare a Jira workspace — fetch issue data, create a git worktree, write `description.md`, `comments.md`, `statuses.md`. Run before starting or resuming work. |
| spec | `/spec <KEY>` | Prepare a technical spec — read the Jira task, discuss with the user, delegate deep research and spec writing to an Opus subagent. |
| implement | `/implement <KEY>` | Implement a task from its spec using the implementer subagent, then review the result. |

### QA workflow

| Skill | Command | Description |
|-------|---------|-------------|
| send-to-test | `/send-to-test <KEY>` | Post a `[QA_HANDOFF]` comment and transition the task to "Ready for test". |
| fix-review | `/fix-review <KEY>` | Fix QA review issues for a Reopened task — read feedback from `comments.md` (after the last `[QA_HANDOFF]` marker), fix in the worktree, commit, send back to test. |

### GitLab & Slack

| Skill | Command | Description |
|-------|---------|-------------|
| create-mr | `/create-mr` | Commit changes, push, and open a GitLab merge request to master. |
| request-review | `/request-review` | Post an MR to the team Slack channel for review. |
| review-mr | `/review-mr <MR>` | Review a GitLab MR — fetch diff, load Jira context, explore codebase with RAG tools, produce a structured review. |

### Jira

| Skill | Command | Description |
|-------|---------|-------------|
| create-task | `/create-task` | Create a Jira Bug or Story in the iOS or Android project. |

## File layout per task

```
$SDD_WORKDIR/<STORY-KEY>/
├── description.md          # parent issue metadata + description (snapshot artifact)
├── comments.md             # parent issue comments, chronological (snapshot artifact)
├── statuses.md             # parent + subtasks status table (snapshot artifact)
├── spec.md                 # high-level architecture and plan (spec artifact)
├── spec-<KEY>.md           # detailed implementation spec per task/subtask
├── spec-qa-<KEY>.md        # fix spec written by qa-spec-writer (if needed)
├── qa-<KEY>.md             # QA feedback extracted by fix-review
├── repo/                   # git worktree on feature/<STORY-KEY>
└── <SUBTASK-KEY>/
    ├── description.md      # subtask description (snapshot artifact)
    └── comments.md         # subtask comments (snapshot artifact)
```
