# Setup Guide

This guide describes the supported setup for the current Constellation: Agent Runtime platform.

Use this guide for the backend/UI runtime model.

Capacity recovery uses the existing stall-retry cooldown and the role's configured model. It needs no
additional machine ENV variables or launcher configuration. See [runtime-model.md](runtime-model.md).

## Required Tools

The supported platform expects these tools locally:

- `tmux`
- `jq`
- `glab`
- `twg`
- Python environment for the backend and factory tooling
- Node/npm for the operator UI
- at least one supported live runner host:
  - Claude Code
  - Codex CLI

## Required Environment

For mobile QA tasks, also configure the machine ENV variables described in
[e2e-workflow.md](e2e-workflow.md) in ~/.zshrc and run the factory e2e doctor. Run policy is managed in
Runtime Defaults; dependency versions are declared in factory/e2e/toolchain.json.
For a dedicated factory iOS pool, create separate simulators on the same installed runtime and set
SDD_E2E_IOS_SIMULATOR_UDIDS (comma-separated UUIDs), SDD_E2E_IOS_WDA_PORT_BASE,
SDD_E2E_IOS_MJPEG_PORT_BASE and SDD_E2E_IOS_WDA_ROOT in ~/.zshrc. Reserve a different WDA and MJPEG
port for each slot (base plus slot index), separate from workspace ports. Keep the shared
E2E_IOS_SIMULATOR_UDID for workspace tests; the factory pool takes precedence for native gates.
Source ~/.zshrc and restart the existing local stack to load the new ENV into its workers.
QA launch scripts explicitly export the current pool ENV (or unset removed values), so an existing
tmux server cannot substitute its older configuration. Restart idle QA verifier runtimes when applying
changes to a session that was already started.
The factory boots only its leased simulator and shuts it down after execution; full pools wait
within the verification time limit. The existing shared Appium server remains in use.
E2E_PYTHON is required in ~/.zshrc; the factory does not assume a project virtualenv location.
Project-specific execution is supplied through the task verification strategy and digest-bound
task-local helpers. Configure repository/layout conventions in the project, not in factory defaults.
Task integration must map the supplied Appium endpoint to the project's client configuration; a ready
server alone does not verify that the project client connects to it. Connection/setup failures require recovery.
Verification keeps a digest-checked app copy in the task snapshot, so replacing shared master builds
does not invalidate an in-flight gate. Its location is derived from SDD_WORKDIR, without new ENV settings.
The shared Appium server must include `--allow-insecure uiautomator2:chromedriver_autodownload`.
The factory supplies the scoped flag when launching it; doctor and verification also inspect the
launch flags of an existing server with lsof/ps. Restart an incompatible shared server after active
runs finish. No separate factory Appium instance or new ENV setting is required.
Doctor verifies installed dependency pins and shared-server launch flags; it does not establish WebView compatibility with every iOS
runtime. WebKit protocol errors can require a toolchain update; missing elements or contexts on baseline
do not by themselves establish an Appium version problem.
After resolving a reported baseline or environment blocker, use "Retry verification" on the blocked-run
card. Check the task and baseline errors separately; the recovery category alone does not identify the cause.
For evidenced baseline test failures, an operator may instead select specific findings and use
"Continue with findings", with an optional comment or issue reference. This needs no new machine ENV
or global test exclusions. Infrastructure failures without actual test evidence still require recovery.
If a continuation encounters an environment failure, "Retry continuation" preserves the decision
and original build. "Retry verification" starts a new gate without accepted findings.

At minimum, set:

```bash
SDD_WORKDIR=/path/to/workdir
IOS_DIR=/path/to/ios/repo
ANDROID_DIR=/path/to/android/repo
```

Optional but commonly useful:

```bash
JIRA_BASE_URL=https://your-org.atlassian.net/browse/
SDD_JIRA_TEAM_FIELD_ID=12345
SDD_JIRA_TEAM_CUSTOM_FIELD_ID=customfield_10625
SDD_JIRA_STORY_POINTS_VALUE=1
SDD_GITLAB_IOS_PROJECT_PATH=group%2Fmobile%2Fios-app
SDD_GITLAB_ANDROID_PROJECT_PATH=group%2Fmobile%2Fandroid-app
DEFAULT_JIRA_ASSIGNEE=you@example.com
SDD_IOS_WORKSPACE_NAME=App-Tuist.xcworkspace
SDD_IOS_DEFAULT_SCHEME=App
IOS_RUN_DEVICE_ID=ios-simulator-uuid-for-manual-launches
IOS_MIN_FREE_DISK_GB=50
REVIEW_MESSAGE_CACHE_TTL_SECONDS=600
```

Install and authenticate Atlassian Teamwork Graph CLI (`twg`) for Jira reads, writes, and transitions. During `snapshot.sh`, Stories and Bugs moving from `To Do` to `In Progress` use TWG metadata to fill empty `Dev finish date` with today's date and empty `Story Points` before transition.

`SDD_IOS_WORKSPACE_NAME` is passed to iOS `xcodebuild -workspace`.
When it is not set, the verification scripts auto-detect a single `.xcworkspace` at the iOS repo root.
`SDD_IOS_DEFAULT_SCHEME` is used when the generated verification strategy does not provide a preferred scheme.
`IOS_RUN_DEVICE_ID` is used by the operator UI manual iOS launch action. It is separate from the verification simulator so manual app inspection does not have to share the test runner destination. If unset, the launch helper falls back to `TESTING_DEVICE_ID`. Manual launches reuse the task-local iOS verification DerivedData cache and keep it until the task is cleaned up.

`IOS_MIN_FREE_DISK_GB` controls automatic task-local iOS DerivedData pruning; the default is `50`.
The shared check runs before preparing verification files, snapshot creation and result delivery, and
periodically through backend persistence activity, in addition to build/test/launch checks.
The backend check is throttled to once per minute, with a cross-process cleanup lock. Only older
sibling DerivedData caches with known low-priority statuses are eligible. Current tasks, live iOS
locks and unfinished factory sessions are protected; logs, xcresult evidence and source checkouts are retained.
Background/client checks use local status snapshots and skip unknown statuses. An insufficient cleanup
does not authorize deleting protected caches. Set `IOS_DERIVED_DATA_PRUNE_ENABLED=0` to disable pruning.

`REVIEW_MESSAGE_CACHE_TTL_SECONDS` controls when cached MR review message previews become stale. The default is `600`; stale previews are shown immediately and refreshed in the background by the operator UI.

## tmux

The tmux host automatically accepts active launcher confirmation menus with an affirmative option, including Claude dynamic workflow consent. No extra setting is required. Workspace trust and update prompts retain their dedicated bootstrap handling.

`tmux` is the supported operational runtime host.

The platform uses it for:

- persistent role runtimes
- restart and continuation
- runtime visibility
- manual attach/capture debugging
- automatic recovery

If `tmux` is missing, the supported live runtime model is not available.

Completed-role checkpoints live in each task's role workspace: `NATIVE_SESSION.json`,
`RUNTIME_CHECKPOINT.json` and a private `native-transcript.jsonl` backup. On wake, `RESUME_CONTEXT.json`
contains current factory state and recorded operator events. Native history uses the runner's existing
local directories (`CODEX_HOME` / `CLAUDE_CONFIG_DIR` when configured); those optional machine paths
belong in ENV and ~/.zshrc. Per-role conversation IDs are generated runtime data, not shell settings.

## MCP Availability

The supported platform expects codebase MCP access to be available when the chosen runner/environment uses it.

Important MCP surfaces include:

- `ios-rag`
- `android-rag`
- `frontend-rag`

For Claude launcher sessions, MCP visibility is scoped per role from `backend/role_baselines.py`.
Current built-in MCP access is:

- `implementer`: `ios-rag`, `android-rag`, `frontend-rag`
- `proposal-context-worker`: `ios-rag`, `android-rag`, `frontend-rag`

Roles such as `convention-reviewer`, `requirements-reviewer`, `verification-coordinator`, `doc-harvest-worker`, and `documentation-reviewer` receive an empty scoped MCP config by default.
`env` values from `.claude/settings.json` or `.claude/settings.local.json` are not copied into role-scoped worker settings.

MCP server endpoints are local machine configuration. To enable them, create a repo-local `.mcp.json`; it is ignored by git:

```json
{
  "mcpServers": {
    "ios-rag": {
      "type": "http",
      "url": "https://example.com/mcp/swift"
    },
    "android-rag": {
      "type": "http",
      "url": "https://example.com/mcp/kotlin"
    },
    "frontend-rag": {
      "type": "http",
      "url": "https://example.com/mcp/frontend"
    }
  }
}
```

If they are unavailable because of authentication, VPN, or network problems, the platform should stop and move the session to `waiting_for_operator` until access is restored.

## Runtime Defaults

Project-local defaults live in:

```text
.sdd-factory/settings.local.json
```

These defaults are managed from the UI and should be treated as the supported configuration path for:

- default runner
- per-role runner/model/effort defaults
- per-workflow policy defaults

## Acceptance / Live Test Defaults

Live acceptance harnesses use their own shared runtime defaults so test runs are consistent and isolated from ad-hoc local choices.

Shared acceptance defaults live in:

```text
factory/acceptance/runtime-defaults.json
```

Current intended defaults:

- Claude → `sonnet`
- Codex → `gpt-5.3-codex-spark`

They can be overridden when needed with environment variables:

```bash
SDD_FACTORY_ACCEPTANCE_DEFAULT_RUNNER=claude
SDD_FACTORY_ACCEPTANCE_CLAUDE_MODEL=sonnet
SDD_FACTORY_ACCEPTANCE_CLAUDE_EFFORT=medium
SDD_FACTORY_ACCEPTANCE_CODEX_MODEL=gpt-5.3-codex-spark
SDD_FACTORY_ACCEPTANCE_CODEX_EFFORT=medium
```

Acceptance runs should execute in isolated task-like environments rather than against dirty state in the main repository checkout.

## Doctor and Bootstrap Guidance

Before relying on live sessions, use the operator surfaces that expose setup state:

- `Environment Doctor`
- `Bootstrap Guidance`
- `Runtime Capabilities`

These are the supported way to verify that:

- required tools exist
- the runtime host is available
- runner/model catalogs are visible
- supported role baselines and current runtime defaults resolve into a valid configuration

## Starting the Local Platform

After upgrading result-ingress code, restart the existing backend to load completed-work-item replay
protection. Repeated completion for a closed coding item must not advance another correction stage.

iOS resource queues need no additional machine settings. Task/simulator lock paths retain their ENV
configuration. Native execution-state files are task-local runtime artifacts. Restart the existing
backend after upgrading coordinator code so live-run deferral and completed-run replay protection are
active; do not launch a second stack.

After changing machine ENV in ~/.zshrc, run `source ~/.zshrc` in the launch terminal before restarting
the existing stack. Already-running processes retain their old environment. Restart affected QA roles
to receive the backend's current pool values; the launcher explicitly clears unconfigured pool ENV.

QA MR-description generation reads stored evidence without requiring device/Appium ENV. Actual E2E
runs still require the machine configuration above. Documentation-only delivery checks are described
in [e2e-workflow.md](e2e-workflow.md).

After updating coordinator contracts or worker instructions, restart the existing backend to load the
new code. A valid implementer request for operator input during documentation correction does not
require environment recovery; conflicts between requirements and fundamental rules await a decision.

The normal supported workflow is:

1. Start the backend/UI stack:

```bash
bash factory/run-local-stack.sh
```

Or use the convenience wrapper that also opens the browser automatically:

```bash
bash factory/open-local-ui.sh
```

2. Open the operator UI.
3. Check doctor and bootstrap guidance if this machine is not yet proven healthy.
4. Review runtime defaults.
5. Create a session and let the backend route the flow.

## Cleanup Expectations

Supported setup also includes clean lifecycle handling:

- task runtime residue should be cleaned through the platform cleanup actions
- closed-task cleanup should use the project cleanup flow
- acceptance/test residue should stay under project-scoped runtime roots
