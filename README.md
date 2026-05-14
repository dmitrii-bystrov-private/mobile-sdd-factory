# SDD Assistant

> *"The earlier you invest in clarity, the cheaper the implementation."*

**SDD Assistant** is an AI orchestration layer built on [Claude Code](https://claude.ai/code) that automates the full mobile development workflow for iOS and Android Jira tasks — from ticket to merged MR.

One command kicks off a pipeline that writes the spec, decomposes the work, implements the code, opens the MR, and hands off to QA. You stay in the loop at the decisions that matter; the pipeline handles everything in between.

---

## The Core Idea

Most AI coding tools are interactive chat assistants — you prompt, they generate, you review, you correct. That model works for small tasks but breaks down at the feature level, where the real cost is not writing code but *understanding what to build*.

SDD Assistant is built around a different premise: **spec first, code second**.

Before any implementation starts, the pipeline forces a full spec pass — collecting requirements from Jira, clarifying ambiguities, writing acceptance criteria, defining constraints, and verifying the spec for completeness. Only then does an implementer agent touch the code. The spec becomes the contract; the implementation agent works from it in isolation.

This is what *Spec-Driven Development* means in practice.

---

## How It Works

The pipeline has three flows — two full flows selected automatically, and one lightweight flow invoked explicitly:

### Story flow — `feature/IOS-*`

```
/snapshot          →  worktree on feature/ branch, Jira snapshot written
proposal-collector →  collect requirements from Jira comments & description
context-collector  →  find relevant code, write context files
requirements-clarifier  →  [CHECKPOINT] one Q&A round with you
acceptance-criteria-writer + constraints-definer + spec-verifier
task-decomposer    →  plan/index.md + per-task files, subtasks created in Jira
                   →  [CHECKPOINT] step-by-step or auto implementation mode
implementer loop   →  each task implemented and committed
/self-review       →  optional diff review; internally runs code-reviewer and implementer fix passes
/final-verification → workflow-level test + lint gate after code changes; internally runs final-verifier and implementer correction passes
doc-harvest        →  optional feature README update from structured branch diff
/create-mr → /send-to-test
```

### Bug flow — `bugfix/IOS-*`

```
/snapshot          →  worktree on bugfix/ branch, Jira snapshot written
bug-fixer          →  analyze root cause, optionally commit a failing test, and implement fix
                   →  [CHECKPOINT] analysis can be reviewed before the fix starts
commit             →  code committed to branch
/self-review       →  optional diff review; internally runs code-reviewer and implementer fix passes
/final-verification → workflow-level test + lint gate after code changes; internally runs final-verifier and implementer correction passes
doc-harvest        →  optional feature README update from structured branch diff
/create-mr → /send-to-test
```

### One-shot flow — `/oneshot <KEY>`

For small, self-contained tasks where spec preparation would be overkill:

```
/snapshot          →  worktree created, Jira snapshot written
implementer        →  reads description.md + comments.md directly
commit             →  code committed to branch
/self-review       →  optional diff review; internally runs code-reviewer and implementer fix passes
/final-verification → workflow-level test + lint gate after code changes; internally runs final-verifier and implementer correction passes
doc-harvest        →  optional feature README update from structured branch diff
/create-mr → /send-to-test
```

No proposal, no requirements pass, no plan. Just snapshot → implement → document → ship.
Must be invoked explicitly with `/oneshot` — never triggered automatically by a bare Jira key.

Human checkpoints are deliberate but not fixed to a constant number. Full flows may pause for clarification answers, blocker resolutions, bug-flow mode selection, and explicit user decisions on follow-up work when the workflow requires them.

---

## Design Principles

**Orchestrator never touches code.**
CLAUDE.md instructs Claude to delegate. The main agent is a router, not an implementer. Skills and subagents do the actual work. This separation keeps the orchestrator predictable and the subagents focused.

**Self-contained task files.**
Each `plan/NN-task-name.md` includes all context inline — acceptance criteria, constraints, relevant code snippets. The implementing agent has no access to the spec package. If the task file is complete, the implementation will be correct.

**Bash-first determinism.**
If a step can be a shell script, it is a shell script. Predictable, zero token waste, easy to debug. AI where it adds value; bash where it is sufficient. `snapshot.sh`, `create-subtasks-batch.sh`, `request-review-message.sh` — these never hallucinate.

**Minimal context per agent.**
Each subagent receives only the tools and files relevant to its task. No agent reads the whole spec — only the slice it needs. Smaller context = fewer hallucinations = better output.

**Fail fast, fail loud.**
Every pipeline stage either produces its artifact or reports failure and halts. No silent partial outputs. Broken input never silently propagates downstream.

---

## Agent Catalog

The pipeline is composed of specialized subagents, each with a single responsibility:

| Agent | Role |
|-------|------|
| `proposal-collector` | Reads Jira issue, extracts structured requirements into `spec/proposal.md` |
| `context-collector` | Searches the codebase via RAG, writes `spec/context/` files |
| `requirements-clarifier` | Identifies ambiguities, runs one Q&A round, produces `spec/requirements.md` |
| `acceptance-criteria-writer` | Writes testable WHEN-THEN-SHALL criteria |
| `constraints-definer` | Defines architecture, performance, and platform constraints |
| `spec-verifier` | Checks the spec package for completeness and consistency; blocks on blockers |
| `task-decomposer` | Decomposes spec into ordered, self-contained task files with dependency graph |
| `bug-fixer` | Unified bug agent: analyzes root cause, optionally writes and commits a failing test, implements the fix, and leaves the workflow-level `test + lint` gate to `final-verifier` |
| `implementer` | Implements a single task file; has no access to spec — task file is the spec |
| `mr-comments-analyst` | Groups unresolved MR review threads into actionable themes, enriches them with code context, and writes `plan/` files for Jira subtask creation |
| `code-reviewer` | Reviews the feature branch diff against project conventions (read from CLAUDE.md); produces a structured issue report; triggers implementer if issues found |
| `final-verifier` | Runs the current workflow gate (`test + lint`), writes `spec/final-verification.md`, and never modifies code |
| `doc-harvest` | Generates structured full diff, creates or enriches feature-level README docs from what actually changed |

---

## Skill Reference

Skills are slash commands available in Claude Code:

| Skill | Trigger condition |
|-------|------------------|
| `/jira-task <KEY>` | Auto-routes by issue type (Story → `/jira-story`, Bug → `/jira-bug`) |
| `/jira-story <KEY>` | Full story flow end-to-end |
| `/jira-bug <KEY>` | Full bug-fix flow end-to-end |
| `/oneshot <KEY>` | Skip spec/planning — snapshot then implement directly. For small, self-contained tasks. |
| `/snapshot <KEY>` | Fetch Jira data, create worktree |
| `/self-review <KEY>` | Run the optional convention-focused diff review as a standalone step; generates a structured diff, calls `code-reviewer`, and routes fixes through `implementer`. |
| `/final-verification <KEY>` | Run the workflow-level `test + lint` gate as a standalone step; calls `final-verifier`, routes verification fixes through `implementer`, and manages retry attempts. |
| `/create-mr` | Commit, push, open GitLab MR, and prepare a Slack-ready review message |
| `/handle-mr-comments <MR>` | Group unresolved MR discussions into plan files and Jira subtasks; can auto-detect the Jira key from the MR when needed |
| `/send-to-test <KEY>` | Commit local changes and transition the task to "Ready for test" |
| `/create-task` | Create a new Jira Bug or Story |
| `/doc-harvest <KEY>` | Create or enrich feature README from structured branch diff (runs automatically at the end of story / bug / oneshot flows when enabled; also available standalone) |
| `/cleanup` | Remove resolved task workspaces from `$SDD_WORKDIR` |

---

## Worktree Layout

The workspace is organized around the parent Jira issue. `snapshot.sh` always
creates the git worktree and shared artifacts under `$SDD_WORKDIR/<PARENT-KEY>/`.
Subtask snapshots are stored inside that parent directory.

```
$SDD_WORKDIR/IOS-1234/
├── description.md          ← Jira issue description (Markdown)
├── comments.md             ← Jira comments (Markdown)
├── statuses.md             ← subtask status summary
├── spec/
│   ├── proposal.md         ← collected requirements
│   ├── context/            ← codebase context files
│   │   ├── project.md      ← symlink to IOS_DIR/CLAUDE.md
│   │   ├── feature-overview.md
│   │   ├── relevant-code.md            (optional)
│   │   ├── documentation.md            (optional)
│   │   ├── implementation-patterns.md  (optional)
│   │   └── preconditions.md            (optional)
│   ├── requirements.md     ← clarified requirements
│   ├── acceptance_criteria.md
│   ├── constraints.md
│   ├── diff.md             ← structured source diff vs master
│   ├── final-verification.md ← workflow-level test + lint report (optional)
│   ├── doc-diff.md         ← structured documentation-only diff (optional)
│   └── full-diff.md        ← structured source + documentation diff (optional)
├── plan/                   ← stories only
│   ├── index.md            ← task list + dependency graph
│   ├── 01-setup-data-models.md
│   ├── 02-implement-api-layer.md
│   └── 03-build-ui-components.md
├── repo/                   ← git worktree on feature/IOS-1234
└── IOS-1235/               ← subtask snapshot directory
    ├── description.md
    └── comments.md
```

For bugs: `plan/` is absent; `spec/` contains `bug-analysis.md` plus generated verification/diff artifacts; branch is `bugfix/<KEY>`.
For subtasks: there is no separate `repo/`; they reuse the parent issue's worktree.

---

## Setup

### Prerequisites

| Tool | Purpose | Install |
|------|---------|---------|
| [Claude Code](https://claude.ai/code) | The AI runtime | See docs |
| `acli` | Jira Cloud CLI | `brew install acli` or see [acli docs](https://developer.atlassian.com/cloud/acli/) |
| `glab` | GitLab CLI | `brew install glab` |
| `jq` | JSON processing | `brew install jq` |

For codebase semantic search, the `ios-rag` and `android-rag` MCP servers must be configured in Claude Code settings.

### Environment variables

Set these in `.claude/.env` (or your shell profile):

```bash
SDD_WORKDIR=/path/to/your/workdir   # where task snapshots and worktrees are created
IOS_DIR=/path/to/ios/repo           # iOS project root
ANDROID_DIR=/path/to/android/repo   # Android project root
JIRA_BASE_URL=https://your-org.atlassian.net/browse/   # optional override for Jira links
DEFAULT_JIRA_ASSIGNEE=you@example.com                  # optional default for create-issue.sh
```

### Feature flags

Optional pipeline steps are gated by env vars. The project default is `false` for all flags — they are disabled for everyone unless explicitly opted in.

To enable locally, add the flags to `.claude/settings.local.json` (gitignored):

```json
{
  "env": {
    "BOY_SCOUT_ENABLED": "true",
    "DOC_HARVEST_ENABLED": "true",
    "SELF_REVIEW_ENABLED": "true"
  }
}
```

| Flag | Default | What it controls |
|------|---------|-----------------|
| `BOY_SCOUT_ENABLED` | `false` | Boy Scout pass at the end of jira-story / jira-bug / oneshot — scans the diff for SOLID/DRY improvement opportunities and offers to create subtasks or tech-debt stories. |
| `DOC_HARVEST_ENABLED` | `false` | Doc harvest pass at the end of jira-story / jira-bug / oneshot — generates or enriches feature-level README.md files from the structured branch diff and commits them to the branch. |
| `SELF_REVIEW_ENABLED` | `false` | Self-review pass before doc-harvest / MR creation — runs convention-focused diff review and routes fixes through the implementer. |

### Add scripts to PATH

```bash
export PATH="$PATH:/path/to/mobile-dev-sdd/scripts"
```

---

## Usage

### Starting a task

```bash
# Auto-route by issue type (recommended)
/jira-task IOS-1234

# Or paste the Jira URL directly — auto-detected
/jira-task https://your-org.atlassian.net/browse/IOS-1234

# Explicit flow selection
/jira-story IOS-1234   # story — full spec pipeline
/jira-bug   IOS-1234   # bug — root cause analysis + failing test
/oneshot    IOS-1234   # any type — skip spec, implement directly (for micro-tasks)
```

The pipeline runs, pausing at the three checkpoints for your input.

When a workflow writes follow-up artifacts into an existing `plan/` directory and only the newly added files should become Jira subtasks, use selective batch creation:

```bash
bash scripts/create-subtasks-batch.sh \
  --parent IOS-1234 \
  --plan-dir "$SDD_WORKDIR/IOS-1234/plan" \
  --task-file ./10-follow-up-a.md \
  --task-file ./11-follow-up-b.md
```

### QA cycle

When a task comes back from QA (status: Reopened), resume the normal task flow for that Jira key. The workflow should treat the latest comments as the highest-priority follow-up input instead of routing to a separate dedicated skill.

### Individual steps

Each step can also be run standalone if you need to resume a partial flow:

```bash
/snapshot IOS-1234       # re-fetch Jira data
/create-mr               # open MR from current worktree
/send-to-test IOS-1234   # transition to QA
/cleanup                 # remove Resolved workspaces from $SDD_WORKDIR
```

### Standalone script toolbox

The slash commands are the primary interface, but the repo also exposes direct shell entry points for automation and debugging:

- `bash scripts/snapshot.sh <KEY>` — fetch Jira data, create/update the task worktree, and refresh snapshot files
- `bash scripts/run-test.sh <KEY>` / `run-lint.sh <KEY>` — platform-aware wrappers used by the current workflow-level verification gate
- `bash scripts/run-build.sh <KEY>` — legacy wrapper kept for manual use; no longer part of the default workflow gate
- `bash scripts/create-mr.sh <KEY>` — push the task branch and open a GitLab MR
- `bash scripts/commit-and-resolve.sh <KEY>` — commit local changes and transition Jira status
- `bash scripts/create-issue.sh ...` / `create-subtask.sh ...` / `create-subtasks-batch.sh ...` — Jira creation helpers
- `bash scripts/fetch-mr-comments.sh <ios|android> <mr_iid>` — export unresolved MR discussions as Markdown
- `bash scripts/get-mr-jira-key.sh <ios|android> <mr_iid>` — extract the Jira key from an MR title or description
- `bash scripts/request-review-message.sh <ios|android> <mr_iid>` — generate a Slack-ready review message
- `bash scripts/cleanup.sh` — remove resolved workspaces from `$SDD_WORKDIR`

Detailed CLI usage lives in [`scripts/README.md`](scripts/README.md).

## Project Layout

```
.claude/
├── agents/       # subagent definitions used by the orchestration flows
├── commands/     # lightweight slash-command entry points
├── hooks/        # assistant runtime hooks
├── memory/       # persistent Claude memory
└── skills/       # workflow skills, one directory per slash command
scripts/          # bash automation and standalone helpers
│   └── tests/    # shell regression tests + golden fixtures
AGENTS.md         # repository-specific coding and workflow rules
CLAUDE.md         # orchestrator instructions consumed by Claude Code
README.md         # high-level workflow and setup guide
index.html        # local static presentation deck for the SDD Assistant workflow
```

## More Docs

- [`scripts/README.md`](scripts/README.md) — direct CLI reference for every helper script
- [`.claude/skills/README.md`](.claude/skills/README.md) — slash-command catalog and task workspace layout
- [`AGENTS.md`](AGENTS.md) — repository conventions for contributors and coding agents
