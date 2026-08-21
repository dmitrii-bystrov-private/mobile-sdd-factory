# Constellation: Agent Runtime

Constellation is a local agent orchestration platform for a specialized mobile SDD workflow.
It runs a backend API, an operator UI, and persistent tmux-backed role runtimes that move Jira tasks through planning, implementation, review, verification, MR handoff, and send-to-test.

This is not a generic drop-in agent framework. It is intentionally shaped around a concrete Jira/GitLab/mobile repository workflow. It can be used as a foundation for another workflow, but expect to adapt bootstrap, repository layout, build and verification scripts, role baselines, Jira/GitLab helpers, and workflow policies.

## Quick Start

From the repository root:

```bash
bash factory/open-local-ui.sh
```

This starts the backend and UI, waits for the UI to become ready, opens the operator console, and keeps both processes attached until `Ctrl+C`.

To start the same local stack without opening a browser:

```bash
bash factory/run-local-stack.sh
```

Default local URLs:

- Backend API: `http://127.0.0.1:8000`
- Operator UI: `http://127.0.0.1:4173`

Useful aliases:

```bash
bash scripts/dev.sh ui
bash scripts/dev.sh stack
bash scripts/dev.sh doctor
bash scripts/dev.sh test
```

## What The System Does

The backend owns the workflow state. The UI is the operator control surface. Role agents run in persistent tmux windows and receive routed work through task-local `ROUTED_WORK.md` and `HYDRATION.json` files.

A normal session looks like this:

1. Snapshot the Jira task and prepare a task-local worktree.
2. Route work to the current role.
3. Collect the role result through the deterministic terminal result contract.
4. Advance the session to the next stage.
5. Stop for the operator only when a real decision or environment fix is required.

The coordinator does not edit product code. It routes work, records artifacts, owns state transitions, manages runtime recovery, and runs deterministic helper scripts.

## Workflow Profiles

### `story_full`

For larger stories that need planning before implementation:

```text
snapshot
proposal/context
requirements clarification
acceptance criteria
constraints
spec verification
task decomposition
subtask implementation
convention review
requirements review
documentation harvest/review when needed
workflow verification
MR handoff
send-to-test
```

Jira subtasks are the execution source of truth after decomposition. Follow-up Jira subtasks can re-enter the same execution model.

### `bug_full`

For bug tickets:

```text
snapshot
bug analysis
bug fix
convention review
requirements review
documentation harvest/review when needed
workflow verification
MR handoff
send-to-test
```

The `bug-fixer` owns both analysis and fix passes.

### `oneshot`

For small, self-contained work where full story planning would be overhead:

```text
snapshot
implementation
convention review
requirements review
documentation harvest/review when needed
workflow verification
MR handoff
send-to-test
```

## Roles

| Role | Responsibility |
| --- | --- |
| `proposal-context-worker` | Collects grounded task context from Jira and local repository docs/code. |
| `requirements-clarifier-worker` | Clarifies implementation-shaping requirements and asks the operator when ambiguity blocks safe planning. |
| `acceptance-criteria-worker` | Writes explicit, testable acceptance criteria. |
| `constraints-worker` | Extracts task-specific technical and architectural constraints. |
| `spec-verifier-worker` | Checks the assembled planning package before decomposition. |
| `task-decomposer-worker` | Produces temporary planning files used to create Jira subtasks. |
| `implementer` | Implements normal tasks, subtasks, follow-ups, and correction passes. |
| `bug-fixer` | Handles bug analysis and bug fix implementation. |
| `convention-reviewer` | Reviews the diff against local project conventions, nearby patterns, and test style. |
| `requirements-reviewer` | Reviews the diff against current Jira scope, follow-up priority, regressions, edge cases, and focused test coverage. |
| `doc-harvest-worker` | Updates durable documentation when the completed diff justifies it. |
| `documentation-reviewer` | Reviews documentation and source comments after documentation changes. |
| `verification-coordinator` | Runs workflow-level verification and routes concrete correction work when verification fails. |

Long-running implementation, review, and verification roles keep their runtime context across correction rounds. Planning and documentation roles are started only when the workflow needs them.

## Operator UI

Use the UI for normal operation:

- create and prepare sessions
- choose `story_full`, `bug_full`, or `oneshot`
- inspect stage, owner, work items, artifacts, and live runtime output
- send operator replies when a role asks a real question
- retry or resume blocked sessions
- stop/restart role runtimes
- edit runtime defaults
- run environment doctor and bootstrap checks
- clean task runtime/worktree residue

See [`docs/operator-guide.md`](docs/operator-guide.md) for day-to-day usage.

## Runtime Model

`tmux` is the supported runtime host. Each task gets a runtime session, and each active role gets its own window.

The UI exposes attach and capture commands for direct debugging. The backend also uses tmux state for runtime visibility, restart, continuation, and automatic recovery.

Claude and Codex runners are both supported. Runtime defaults are stored in:

```text
.sdd-factory/settings.local.json
```

Those defaults cover:

- default runner
- per-role runner/model/effort
- per-workflow policy defaults

Claude `.claude/settings.json` and `.claude/settings.local.json` are only launcher-side source material for scoped permissions and MCP visibility. They are not the product runtime-defaults store.

## Required Environment

Required tools:

- `tmux`
- `jq`
- `glab`
- `acli`
- Python environment for backend/factory tooling
- Node/npm for the UI
- at least one live runner host: Claude Code or Codex CLI

Required environment variables:

```bash
SDD_WORKDIR=/path/to/workdir
IOS_DIR=/path/to/ios/repo
ANDROID_DIR=/path/to/android/repo
```

Optional:

```bash
JIRA_BASE_URL=https://your-org.atlassian.net/browse/
SDD_JIRA_TEAM_FIELD_ID=12345
SDD_GITLAB_IOS_PROJECT_PATH=group%2Fmobile%2Fios-app
SDD_GITLAB_ANDROID_PROJECT_PATH=group%2Fmobile%2Fandroid-app
DEFAULT_JIRA_ASSIGNEE=you@example.com
```

For codebase semantic search, the runtime can use role-scoped MCP servers such as `ios-rag`, `android-rag`, and `frontend-rag` when available. Add them through a local-only `.mcp.json`; this file is intentionally ignored by git.

See [`docs/setup.md`](docs/setup.md) for setup details.

## Task Workdir

Task snapshots and worktrees live under `$SDD_WORKDIR/<TASK-KEY>/`.

Typical layout:

```text
$SDD_WORKDIR/IOS-1234/
├── description.md
├── comments.md
├── statuses.md
├── spec/
│   ├── proposal.md
│   ├── requirements.md
│   ├── acceptance_criteria.md
│   ├── constraints.md
│   ├── diff.md
│   ├── final-verification.md
│   ├── doc-diff.md
│   └── full-diff.md
├── plan/
│   ├── index.md
│   └── 01-example-subtask.md
├── repo/
└── IOS-1235/
    ├── description.md
    └── comments.md
```

For subtask execution, the parent task worktree is reused. `plan/` files are temporary decomposition artifacts, not the long-term source of truth for follow-up ordering; Jira task/subtask state is.

## Verification And Delivery

Workflow verification is a routed role stage, not something normal coding roles should run themselves.

The verifier uses deterministic wrappers such as:

```bash
bash scripts/run-test.sh <KEY>
bash scripts/run-lint.sh <KEY>
```

When verification passes, the backend completes the task, creates the MR, and moves the Jira task to testing automatically. Manual MR/send-to-test actions are recovery tools for failed delivery, not the normal path.

## Useful Commands

```bash
bash scripts/run-supported-tests.sh
bash scripts/run-supported-tests.sh --live
./.venv/bin/python -m unittest discover -s tests/backend -p 'test_*.py'
cd ui && npm run build
```

Direct helper scripts:

```bash
bash scripts/snapshot.sh <KEY>
bash scripts/run-test.sh <KEY>
bash scripts/run-lint.sh <KEY>
bash scripts/run-build.sh <KEY>
bash scripts/create-mr.sh <KEY>
bash scripts/send-to-test.sh <KEY>
bash scripts/cleanup.sh
```

Detailed script reference: [`scripts/README.md`](scripts/README.md).

## Project Layout

```text
backend/          FastAPI routes, coordinator, runtime contracts, repositories
ui/               Vite/React operator console
factory/          doctor, cleanup, acceptance harnesses, local stack helpers
scripts/          direct shell helpers and workflow automation
tests/backend/    backend regression suite
scripts/tests/    shell regression tests
docs/             supported platform documentation
AGENTS.md         repository rules for contributors and coding agents
```

## More Docs

- [`docs/setup.md`](docs/setup.md) - local setup and runtime prerequisites
- [`docs/operator-guide.md`](docs/operator-guide.md) - operator workflow
- [`docs/runtime-model.md`](docs/runtime-model.md) - sessions, roles, policies, recovery, delivery
- [`docs/terminal-result-contract.md`](docs/terminal-result-contract.md) - deterministic role result protocol
- [`DEVELOPERS_GUIDE.md`](DEVELOPERS_GUIDE.md) - development and testing guide
- [`scripts/README.md`](scripts/README.md) - direct CLI helper reference
- [`AGENTS.md`](AGENTS.md) - repository conventions
