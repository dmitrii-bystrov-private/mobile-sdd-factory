# SDD Factory

> *"The earlier you invest in clarity, the cheaper the implementation."*

**SDD Factory** is the current orchestration platform for the mobile SDD workflow. It runs a backend + UI operator console, launches persistent tmux-backed role runtimes, and drives Jira tasks from snapshot through implementation, review, verification, MR handoff, and send-to-test.

The current implementation supports both Claude and Codex runners, project-local runtime defaults, task cleanup, runtime recovery, and live operator intervention when the workflow genuinely needs a human decision. Legacy slash-command flows still exist as a compatibility surface, but they are no longer the primary product model.

---

## The Core Idea

Most AI coding tools are interactive chat assistants — you prompt, they generate, you review, you correct. That model works for small tasks but breaks down at the feature level, where the real cost is not writing code but *understanding what to build*.

SDD Factory is built around a different premise: **spec first, code second**.

Before any implementation starts, the pipeline forces a full spec pass — collecting requirements from Jira, clarifying ambiguities, writing acceptance criteria, defining constraints, and verifying the spec for completeness. Only then does an implementer agent touch the code. The spec becomes the contract; the implementation agent works from it in isolation.

This is what *Spec-Driven Development* means in practice.

---

## Current Runtime Model

The current system is centered on the operator console and persistent role runtimes:

- the backend owns session state, work items, stage transitions, and cleanup
- the UI exposes session creation, runtime visibility, operator actions, runtime defaults, doctor, bootstrap guidance, and runtime capabilities
- live roles run under persistent tmux-backed runtimes
- quality lanes such as self-review and verification are long-running roles that keep their context across correction rounds
- task execution, MR follow-up, and QA reopen flows can route through the same subtask graph instead of spawning disconnected one-off lanes

The main workflow profiles are still the same:

### Story flow — `story_full`

```
prepare snapshot   →  Jira snapshot + task-local git repo/worktree prepared
proposal/context   →  proposal package + grounded context package materialized
story planning     →  requirements, acceptance criteria, constraints, spec verification, story spec
decomposition      →  plan/index.md + per-task plan files
execution          →  implementation starts automatically, Jira subtasks are created automatically when needed, and the flow enters subtask execution if unresolved subtasks exist
self-review        →  optional/required persistent reviewer lane with correction loop
boy scout          →  optional/required scout lane with implement-now vs tech-debt resolution flow
verification       →  persistent verifier lane with correction loop
delivery           →  automatic MR handoff + automatic send-to-test
follow-up          →  MR comments and QA reopen can materialize new subtasks and resume the same execution model
```

### Bug flow — `bug_full`

```
prepare snapshot   →  Jira snapshot + task-local git repo/worktree prepared
bug analysis/fix   →  bug-fixer diagnoses and implements the fix
self-review        →  optional/required persistent reviewer lane
boy scout          →  optional/required scout lane
verification       →  persistent verifier lane
delivery           →  automatic MR handoff + automatic send-to-test
```

### One-shot flow — `oneshot`

For small, self-contained tasks where spec preparation would be overkill:

```
prepare snapshot   →  Jira snapshot + task-local git repo/worktree prepared
implementation     →  implementer reads the snapshot directly without story planning
self-review        →  optional/required persistent reviewer lane
boy scout          →  optional/required scout lane
verification       →  persistent verifier lane
delivery           →  automatic MR handoff + automatic send-to-test
```

No proposal, no requirements pass, no plan. Just snapshot → implement → quality loops → ship.

Human checkpoints still exist, but only where the workflow actually needs a person:

- requirements clarification when the agent cannot proceed safely without answers
- Boy Scout findings that may need to become tech-debt stories
- blocked review / verification cycles that cannot converge automatically
- external blockers such as missing MCP access, authentication, or VPN
- manual cleanup and exceptional recovery actions

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

## Role Catalog

The current pipeline is composed of specialized long-running or on-demand roles:

| Role | Responsibility |
|------|----------------|
| `task-coordinator` | Owns session routing, stage transitions, follow-up dispatch, and recovery decisions. |
| `proposal-context-worker` | Builds the proposal and grounded context package from Jira plus relevant code context. |
| `requirements-clarifier-worker` | Clarifies requirements and can stop for live operator answers when ambiguity matters. |
| `acceptance-criteria-worker` | Writes testable acceptance criteria. |
| `constraints-worker` | Defines technical and architectural constraints. |
| `spec-verifier-worker` | Checks planning artifacts for blockers and can stop the flow for blocker resolution. |
| `story-spec-worker` | Produces the final implementation-shaping story spec. |
| `task-decomposer-worker` | Produces `plan/index.md` and the self-contained task package for execution. |
| `bug-fixer` | Analyzes bug root cause and implements the fix. |
| `implementer` | Executes the current implementation or correction pass against the task-local repo. |
| `code-reviewer` | Persistent self-review lane that can pass, request corrections, skip when optional, or block a non-converging review cycle. |
| `code-scout` | Boy Scout lane that can produce implement-now findings or old-code tech-debt candidates. |
| `verification-coordinator` | Persistent verification lane that runs the workflow gate and can request corrections or block a non-converging verification cycle. |
| `mr-comments-analyst-worker` | Groups unresolved MR discussions into actionable themes and a follow-up subtask plan. |
| `doc-harvest-worker` | Produces or updates documentation when the diff justifies it. |

---

## Legacy Skill Reference

The legacy slash-command surface still exists for compatibility and local scripted use:

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
| [Claude Code](https://claude.ai/code) | One supported live runner host | See docs |
| Codex CLI | One supported live runner host | See local environment setup |
| `acli` | Jira Cloud CLI | `brew install acli` or see [acli docs](https://developer.atlassian.com/cloud/acli/) |
| `glab` | GitLab CLI | `brew install glab` |
| `jq` | JSON processing | `brew install jq` |
| `tmux` | Required operational runtime host | `brew install tmux` |

For codebase semantic search, the `ios-rag`, `android-rag`, and `frontend-rag` MCP servers should be available in the runner environment. The operator console exposes Environment Doctor, Bootstrap Guidance, and Runtime Capabilities to make missing setup visible before sessions start.

### Environment variables

Set these in `.claude/.env` (or your shell profile):

```bash
SDD_WORKDIR=/path/to/your/workdir   # where task snapshots and worktrees are created
IOS_DIR=/path/to/ios/repo           # iOS project root
ANDROID_DIR=/path/to/android/repo   # Android project root
JIRA_BASE_URL=https://your-org.atlassian.net/browse/   # optional override for Jira links
DEFAULT_JIRA_ASSIGNEE=you@example.com                  # optional default for create-issue.sh
```

### Runtime Defaults

Project-local runtime and workflow defaults are stored in:

```text
.sdd-factory/settings.local.json
```

These defaults are editable from the UI `Settings → Runtime Defaults` panel and cover:

- default runner
- per-role runner/model/effort defaults
- per-workflow policy defaults

Example:

```json
{
  "runtime_defaults": {
    "default_runner": "claude",
    "role_defaults": {
      "implementer": {
        "runner": "codex",
        "model": "gpt-5.3-codex-spark",
        "effort": "medium"
      }
    },
    "policy_defaults": {
      "story_full": {
        "self_review_policy": "enabled",
        "boy_scout_policy": "enabled",
        "doc_harvest_policy": "enabled",
        "requirements_clarification_mode": "ask-selectively"
      }
    }
  }
}
```

Policy values use:

- `disabled`
- `enabled` = auto-start with agent-controlled `skipped_not_needed`
- `required`

### Add scripts to PATH

```bash
export PATH="$PATH:/path/to/mobile-dev-sdd/scripts"
```

---

## Usage

### Starting a task

The current primary entrypoint is the operator UI:

- create a session for a Jira key
- choose `story_full`, `bug_full`, or `oneshot`
- adjust role/runtime config if needed
- let the coordinator drive the flow

From there the UI exposes:

- live session state
- runtime visibility and tmux attach/capture commands
- operator actions grouped into `Daily Flow`, `Advanced Flow`, and `Recovery And Debug`
- runtime defaults
- environment doctor, bootstrap guidance, and runtime capabilities
- task cleanup controls

The legacy slash-command entrypoints still exist for manual use:

```bash
/jira-task IOS-1234
/jira-story IOS-1234
/jira-bug IOS-1234
/oneshot IOS-1234
```

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

Legacy/manual steps can still be run standalone if you need to resume a partial flow:

```bash
/snapshot IOS-1234       # re-fetch Jira data
/create-mr               # open MR from current worktree
/send-to-test IOS-1234   # transition to QA
/cleanup                 # remove Resolved workspaces from $SDD_WORKDIR
```

### Standalone script toolbox

The repo also exposes direct shell entry points for automation and debugging:

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
backend/          # backend API, coordinator, runtime, repositories, session logic
factory/          # doctor, cleanup, acceptance harnesses, local stack helpers
ui/               # operator console frontend
.claude/
├── agents/       # legacy agent definitions and role metadata
├── commands/     # legacy slash-command entry points
├── hooks/        # assistant runtime hooks
├── memory/       # persistent Claude memory
└── skills/       # legacy workflow skills
tests/            # backend test suite
scripts/          # bash automation and standalone helpers
│   └── tests/    # shell regression tests + golden fixtures
AGENTS.md         # repository-specific coding and workflow rules
CLAUDE.md         # runner guidance and legacy orchestration context
README.md         # high-level workflow and setup guide
index.html        # local static presentation deck for the SDD workflow
```

## More Docs

- [`scripts/README.md`](scripts/README.md) — direct CLI reference for every helper script
- [`docs/operator-guide.md`](docs/operator-guide.md) — practical operator workflow for the supported backend/UI runtime model
- [`docs/runtime-model.md`](docs/runtime-model.md) — supported session, role, quality-loop, recovery, and cleanup model
- [`docs/deprecated-surface.md`](docs/deprecated-surface.md) — deprecated slash-command compatibility inventory and retirement criteria
- [`.claude/skills/README.md`](.claude/skills/README.md) — slash-command catalog and task workspace layout
- [`AGENTS.md`](AGENTS.md) — repository conventions for contributors and coding agents
