# Runtime Model

This document describes the supported runtime model of Constellation: Agent Runtime.

## Core Principles

The supported platform is built around:

- backend-owned session state
- persistent tmux-backed role runtimes
- operator UI as the primary control surface
- long-running quality lanes instead of repeated stateless one-shot passes

The coordinator routes work, records artifacts, owns state transitions and runtime recovery, and runs
deterministic helper scripts. Product code is edited by the implementation role.

## Sessions

A session is the top-level unit of execution for a Jira task.

A session includes:

- task key
- workflow profile
- policy values
- current stage
- current owner
- work items
- artifacts
- runtime session state

Supported workflow profiles:

- `story_full`: context, requirements, acceptance criteria, constraints, specification verification
  and Jira subtask decomposition before implementation.
- `oneshot`: direct implementation for small, self-contained tasks.

Both profiles route implementation through convention/requirements review and workflow verification.
Documentation harvest/review runs after verification when configured, followed by MR and Jira handoff.
After decomposition, Jira subtask state is the execution source of truth; follow-ups can re-enter it.

Task snapshots and worktrees live under `$SDD_WORKDIR/<TASK-KEY>/`. The snapshot holds Jira metadata,
specifications, review reports and verification evidence; `repo/` holds the task worktree. Role
workspaces and routed input live under the task's `runtime/`. Roles receive current work through
`ROUTED_WORK.md` and `HYDRATION.json`. Subtask execution reuses the parent worktree. Planning files are
temporary decomposition artifacts; Jira governs later follow-up ordering.

## Roles

The platform routes work to specialized roles.

| Role | Responsibility |
| --- | --- |
| `proposal-context-worker` | Collects grounded task context from Jira and repository documentation/code. |
| `requirements-clarifier-worker` | Clarifies requirements and asks the operator when ambiguity blocks progress. |
| `acceptance-criteria-worker` | Writes explicit, testable acceptance criteria. |
| `constraints-worker` | Extracts task-specific technical and architectural constraints. |
| `spec-verifier-worker` | Checks the planning package before decomposition. |
| `task-decomposer-worker` | Produces temporary planning files for Jira subtasks. |
| `implementer` | Implements tasks, subtasks, follow-ups and corrections. |
| `convention-reviewer` | Reviews local conventions, nearby patterns and test style. |
| `requirements-reviewer` | Reviews Jira scope, follow-up priority, regressions, edge cases and coverage. |
| `doc-harvest-worker` | Updates durable documentation when the completed diff justifies it. |
| `documentation-reviewer` | Reviews documentation and source comments after documentation changes. |
| `verification-coordinator` | Runs workflow verification and routes corrections when it fails. |

Some roles are short planning lanes.
Some roles are persistent long-runners.

## Persistent Long-Runners

The most important supported long-running roles are:

- `implementer`
- `convention-reviewer`
- `requirements-reviewer`
- `verification-coordinator`

The platform keeps these roles alive across rounds while their task is active. Completed sessions
release quiescent roles after a 60-second delivery/response grace period, provided no work remains pending.
Every role first receives a durable checkpoint with its exact native conversation ID, transcript backup,
model configuration and recorded operator events. If any checkpoint fails or history is ambiguous,
all roles remain live. Manual wake has the same grace period.

Follow-up dispatch wakes only the needed role, resumes the bound conversation (without selecting the
latest unrelated chat), and writes RESUME_CONTEXT.json from current factory state. HYDRATION.json
governs current work IDs; historical decisions retain their original evidence/scope bindings.

This supports:

- native continuation after restart
- correction loops without stateless drift
- explicit blocked-cycle outcomes such as:
  - `blocked_review_cycle`
  - `blocked_verification_cycle`

## Runtime Host

The supported operational host is `tmux`.

Other host variants are outside the supported operational model.

`tmux` is used for:

- persistent role windows
- runtime visibility
- manual attach/capture for debugging
- restart and continuation
- automatic recovery

## Runtime Defaults

Runtime defaults are project-local and stored in:

```text
.sdd-factory/settings.local.json
```

They define:

- default runner
- per-role runner/model/effort defaults
- per-workflow policy defaults

These defaults are surfaced and edited through the UI.

They are distinct from `.claude/settings.json` or `.claude/settings.local.json`, which remain Claude-specific launcher source material for scoped permissions and MCP visibility rather than the supported runtime-defaults store.
The launcher filters those Claude settings per role and does not copy `env` values into worker-local settings.

MCP visibility is role-scoped for Claude sessions. Current built-in baselines expose `ios-rag`, `android-rag`, and `frontend-rag` to `implementer` and `proposal-context-worker`; other roles receive an empty scoped MCP config by default.

## Policy Semantics

Optional lanes follow this model:

- `disabled`
- `enabled`
- `required`

`enabled` means:

- the lane auto-starts
- the agent may emit `skipped_not_needed`

`required` means:

- the lane auto-starts
- `skipped_not_needed` is not allowed

This applies to optional quality/documentation lanes such as:

- review gate
- doc harvest

When documentation harvest runs after verification, `documentation-reviewer` checks the resulting documentation and source comments before delivery.
Conflicts between task requirements and fundamental rules require an explicit operator decision;
the workers preserve both sides and their sources. Documentation correction accepts implementer
failed + needs_operator_input=true as implementation_blocked, preserves the current owner/stage and
reasoned disagreement, and waits for a real operator decision rather than protocol recovery.

## Follow-Up Flows

The supported platform routes follow-up work back into the same runtime model instead of branching into disconnected side paths.

Important follow-up inputs:

- QA reopen comments
- refreshed Jira subtasks

These can materialize new follow-up subtasks and re-enter execution through the subtask graph.

## Delivery Model

Delivery is part of the workflow, not a separate manual phase.
For QA MR handoff, committed documentation-only changes after verification preserve the original
native evidence when Git proves a clean worktree, verified ancestry and regular documentation files.
Changes to code/configuration, bound strategy/support files or execution evidence require a fresh gate.
The MR records both revisions; verifier submissions and baseline decisions remain exactly source-bound.

The normal supported path is:

- verification passes
- task completes
- MR handoff runs automatically
- send-to-test runs automatically

Manual delivery actions remain as recovery tools only when automatic delivery fails.

## Recovery Model

Coding results for already-completed work items are stale/idempotent regardless of the current owner.
The current correction, its dispatch and required review remain active. An old result cannot send a
documentation correction into verification or turn the following valid result into schema recovery.

Factory iOS verification records its command lifecycle under the task's `tmp/verification/ios/`.
Native test steps distinguish cache pruning from execution and invalidate old evidence before either.
Previously deferred responses remain invalid after the same bound command finishes; the verifier
must inspect final output and submit fresh evidence. Log markers alone do not establish completion.
Closed verifier results cannot advance a new round. Retry drains previous output and identifies the
new work item explicitly, superseding queued continuation instructions from earlier rounds.
Waiting for a shared task/simulator lock is an active gate. The coordinator verifies the current work
item, dispatch time, source and runner process before deferring a premature error/terminal result.
The worker continues its existing terminal; feedback is deduplicated per run/state. Fresh completed
results and dead/stale runners use normal result/recovery handling. Native scripts reject proven recursive
lock acquisition by owner ancestry and leave other live owners alone.

QA mobile e2e tasks use the same roles and lifecycle, with a factory-owned `e2e_gate` strategy. The runner
leases a free configured iOS pool device through a per-UDID lock, independent of workspace devices.
The same lease covers collection, tests, fresh-install repeats and baseline comparisons. Pool slots
have distinct WDA/MJPEG ports and derived-data caches. A full pool waits within the gate's existing
time budget. Only a booted/partially booted leased device is shut down before unlocking it, including
failed or gracefully interrupted runs. Collection-only checks do not boot or shut down devices.
The runner
checks the shared Appium version and scoped Chromedriver autodownload launch permission before reuse;
a mismatch is an environment blocker and does not stop the shared server. New servers launch with
that permission. Verification
binds command receipts to the current work item, source SHA, execution strategy and task support-file
digests. The verifier supplies project commands/environment/checks in the common verification strategy;
factory code consumes generic collection/JUnit/outcome evidence. Master app artifacts are the
default. Baseline comparisons change the test revision while retaining the app artifact. Environment and
baseline failures await recovery or an explicit operator decision; proven test regressions route to
implementation correction.
This routing uses the native verdict even for blocked-cycle submissions. Retry converts legacy QA
cycle-review items into fresh verification work with a new strategy and evidence binding.
The `e2e_environment` recovery category covers both baseline and infrastructure blockers. Operator
messages describe which evidence failed and show task and baseline errors separately. The blocked-run
card offers retry, corrections and explicit acceptance of evidenced baseline test failures. The
backend records e2e_baseline_accepted_by_operator with exact finding IDs and a snapshot digest, and
redispatches the same verification item with a new hydration/dispatch token. The native runner
consumes spec/e2e-operator-decisions.json, excludes only accepted scenarios and verifies all remaining
checks. accepted_with_warnings allows delivery while preserving the failures, comments and operator
events in native evidence, final verification and the MR. New gates do not inherit exceptions.
Continuation pins the accepted app artifact. Environment recovery can resume the same gate and its
decisions; historical tmux errors are drained before redispatch and fresh native verdicts determine
QA runtime error recovery rather than worker error text.
Continuation and runtime collection/intake share a per-session transition lock. Acceptance restores
the verifier owner and persists drained error signatures. Setup/teardown failures on both revisions
are environment findings and cannot produce operator-accepted baseline warnings.
The selected app is copied and digest-checked inside the task snapshot before execution. Baseline,
retries and continuation retain this copy independently of shared build-store pruning.
No internal classification dictionaries are presented as prose.
See [e2e-workflow.md](e2e-workflow.md) for the complete contract.

The tmux host automatically accepts active numbered launcher confirmation menus with a `Yes`, `Allow`, or `Approve` option, including Claude dynamic workflow consent. It checks the latest menu and its cancel footer so historical prompts do not cause input. Repeated captures are throttled; a confirmation that remains visible is retried. Arbitrary selection menus without an affirmative option still require operator input.

Recovery is first-class in the runtime model.

The tmux host recognizes Codex shortcut/warning footers when checking the current idle prompt. A model
capacity error immediately triggers a retry on the same configured model. Continued capacity errors
can retry after the existing cooldown for the same work item; the coordinator's unresolved-poke guard
still suppresses repeated generic idle pokes. Historical capacity text during active work does not
trigger recovery. `runtime_role_stall_poked` records the recovery reason and current work item.

The platform supports:

- pause / resume
- retry current stage
- runtime input for interactive blockers
- runtime stop / restart at role or session level
- automatic runtime recovery after owner-runtime death

For live runtime escalations, roles should distinguish between:

- interactive blockers that need a direct operator reply in the same live session
- runtime/tooling/recovery blockers that need retry, resume, or external repair instead

Use the structured `SDD_ERROR` marker only for runtime/protocol/tooling blockers where
the terminal result helper cannot represent or deliver the current outcome. Set
`needs_operator_input: true` only when the blocker requires a direct operator reply in
the same live session. Normal routed pass/fail/completed/skipped outcomes must go
through `scripts/write-result.sh`.

The supported rule is:

- happy path should be automatic
- operator involvement should happen only when the workflow cannot safely proceed

## Cleanup Model

Task cleanup is explicit and lifecycle-aware.

Supported cleanup actions:

- runtime residue cleanup
- full task cleanup when closed-task rules allow it

Acceptance/test runtime cleanup is isolated separately under project-scoped runtime roots.
Forced full cleanup remains an internal emergency seam rather than part of the normal supported operator model.
