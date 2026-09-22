# Setup Guide

This guide describes the supported setup for the current Constellation: Agent Runtime platform.

Use this guide for the backend/UI runtime model.

## Required Tools

The supported platform expects these tools locally:

- `tmux`
- `jq`
- `glab`
- `twg`
- Python environment for the backend and factory tooling
- at least one supported live runner host:
  - Claude Code
  - Codex CLI

## Required Environment

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
```

Install and authenticate Atlassian Teamwork Graph CLI (`twg`) for Jira reads, writes, and transitions. During `snapshot.sh`, Stories and Bugs moving from `To Do` to `In Progress` use TWG metadata to fill empty `Dev finish date` with today's date and empty `Story Points` before transition.

`SDD_IOS_WORKSPACE_NAME` is passed to iOS `xcodebuild -workspace`.
When it is not set, the verification scripts auto-detect a single `.xcworkspace` at the iOS repo root.
`SDD_IOS_DEFAULT_SCHEME` is used when the generated verification strategy does not provide a preferred scheme.
`IOS_RUN_DEVICE_ID` is used by the operator UI manual iOS launch action. It is separate from the verification simulator so manual app inspection does not have to share the test runner destination. If unset, the launch helper falls back to `TESTING_DEVICE_ID`. Manual launches reuse the task-local iOS verification DerivedData cache and keep it until the task is cleaned up.

`IOS_MIN_FREE_DISK_GB` controls automatic task-local iOS DerivedData pruning before build, test, and manual launch operations. The default is `50`. When free space on `$SDD_WORKDIR` drops below the threshold, older sibling task caches are removed while the current task and active iOS task locks are preserved. Set `IOS_DERIVED_DATA_PRUNE_ENABLED=0` to disable pruning.

## tmux

`tmux` is the supported operational runtime host.

The platform uses it for:

- persistent role runtimes
- restart and continuation
- runtime visibility
- manual attach/capture debugging
- automatic recovery

If `tmux` is missing, the supported live runtime model is not available.

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
