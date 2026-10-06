# Developers Guide

This guide is for engineers working on the supported Constellation: Agent Runtime platform.

It complements:

- [README.md](README.md) for the high-level product model
- [AGENTS.md](AGENTS.md) for repository rules
- [docs/setup.md](docs/setup.md) for environment/setup
- [docs/operator-guide.md](docs/operator-guide.md) for supported operator behavior
- [docs/runtime-model.md](docs/runtime-model.md) for session/runtime semantics

## What Is Supported

The supported platform is the backend/UI/tmux runtime model:

- `backend/` owns sessions, stages, work items, artifacts, operator recovery, and runtime contracts
- `ui/` is the primary operator surface
- `factory/` owns doctor, cleanup, local stack helpers, and acceptance harnesses
- `scripts/` remains useful for direct helpers and workflow automation

`.claude/settings.json` remains Claude launcher source material only; supported role contracts live in backend code.

## Directory Map

```text
backend/                API, coordinator, runtime, repositories, role contracts
ui/                     operator console
factory/                doctor, bootstrap, cleanup, acceptance, local stack helpers
tests/backend/          backend regression suite
scripts/                direct shell helpers and wrappers
scripts/tests/          shell regression tests
docs/                   supported platform documentation
.claude/settings.json   Claude launcher permission source material
```

## Local Development Loop

Backend regression:

```bash
./.venv/bin/python -m unittest discover -s tests/backend -p 'test_*.py'
```

Full supported test rail:

```bash
bash scripts/run-supported-tests.sh
```

Full supported test rail plus live acceptance:

```bash
bash scripts/run-supported-tests.sh --live
```

UI build:

```bash
cd ui && npm run build
```

Local backend/UI stack:

```bash
bash factory/run-local-stack.sh
```

Local backend/UI stack plus auto-opened browser:

```bash
bash factory/open-local-ui.sh
bash scripts/dev.sh ui
```

Developer convenience entrypoint:

```bash
bash scripts/dev.sh help
```

Useful shortcuts:

```bash
bash scripts/dev.sh stack
bash scripts/dev.sh test
bash scripts/dev.sh test-live
bash scripts/dev.sh doctor
bash scripts/dev.sh bootstrap
```

Supported operator-flow acceptance:

```bash
bash factory/acceptance/run-happy-path-acceptance.sh
bash factory/acceptance/run-followup-reopen-acceptance.sh
bash factory/acceptance/run-mr-followup-acceptance.sh
bash factory/acceptance/run-delivery-acceptance.sh
```

High-signal live acceptance:

```bash
PYTHONPATH=. ./.venv/bin/python factory/acceptance/run-real-story-runtime-acceptance.py
PYTHONPATH=. ./.venv/bin/python factory/acceptance/run-real-codex-quality-loop-validation.py
```

## Runtime Defaults and Role Baselines

There are two different configuration layers:

1. Supported project/runtime defaults

```text
.sdd-factory/settings.local.json
```

This stores:

- default runner
- per-role runner/model/effort overrides
- per-workflow policy defaults

2. Supported built-in role baselines

```text
backend/role_baselines.py
```

This is the current supported source of truth for default role baselines used by backend and UI.
Role baselines also own built-in MCP visibility for Claude launcher sessions. Keep MCP server lists scoped to roles that actually need those tools; `.claude/settings*.json` is only filtered launcher source material, not the baseline authority.

## Acceptance Runtime Defaults

Live acceptance uses shared defaults in:

```text
factory/acceptance/runtime-defaults.json
```

Current intended defaults:

- Claude → `sonnet`
- Codex → `gpt-5.3-codex-spark`

Live tests should run in isolated task-like environments, not against dirty state in the main repo.

## Behavioral Rules Worth Preserving

Workers must report conflicts between task requirements and fundamental rules with evidence for both
sides and wait for the operator to decide their priority. Continue according to the recorded decision.
Implementer failed + needs_operator_input=true is a valid blocked result during documentation review
correction, just as in other coding lanes. Unresolved conflicts retain their evidence for the operator;
completed must not be used to bypass a decision.

QA tasks reuse the coordinator lifecycle with the `e2e_gate` strategy and factory-owned Appium adapter.
Shared Appium launch/reuse requires the scoped uiautomator2:chromedriver_autodownload permission.
Doctor and ensure_server check launch flags with lsof/ps; do not replace an incompatible shared server
automatically.
The iOS pool is machine configuration: SDD_E2E_IOS_SIMULATOR_UDIDS and its WDA/MJPEG port bases and
cache root belong in ~/.zshrc. Per-device leases allow concurrent gates on the shared Appium server.
Exhausted pools wait within the gate's total time budget. Shutdown runs before the lease is released;
SIGINT/SIGTERM terminate the owned test process before device cleanup. Never stop workspace devices.
Publish generic assigned Appium capabilities; pytest_evidence applies them without project imports,
and other task execution adapters must consume them explicitly.
See [e2e-workflow.md](docs/e2e-workflow.md) for settings/ENV/toolchain ownership, test selection, receipts,
same-app baseline comparisons and QA Jira/MR delivery. External workspace files are research sources,
not runtime dependencies. Preserve native verdict validation for all QA terminal outcomes, including
blocked-cycle submissions. Retry of a legacy QA cycle-review item must create a verification item and
refresh its strategy rather than reuse the previous gate's receipts.
Derive operator summaries from native verdicts and bounded error excerpts. A failing baseline does not
establish an SDK failure or imply that its error is identical to the task run's error.
`POST /operator/resolve-e2e-baseline` accepts specific findings or requests corrections. Acceptance
records an operator event and immutable evidence snapshot, then redispatches the same verification
work item with a new dispatch token. The native runner excludes only those scenarios, verifies all
remaining checks and platforms, and returns accepted_with_warnings. Validate event-backed decisions
and source/strategy/support-file/app bindings before allowing delivery; fresh retries do not inherit exceptions.
QA execution uses the common verification-strategy.json: the verifier supplies e2e.platforms command
arrays, environment and check identifiers from the task checkout. Project setup belongs in task-local
support files, bound by content digest. Generic factory execution/evidence code must not import project
configuration or infer test/smoke paths. The optional pytest_evidence plugin implements the generic
collection/JUnit/outcome protocol without project imports. Legacy gates need fresh contract-version-2 evidence.
Setup/teardown failures on both revisions are environment findings, not acceptable failed checks.
Per-session reentrant serialization protects accept/resume/retry and role-output collection/intake.
Baseline acceptance restores ownership and persists drained error signatures independently of summary wording.
Continue with the accepted build, not the latest master artifact. "Retry continuation" resumes the
same gate after environment recovery. Archive previous terminal output before redispatch; fresh
native QA verdicts govern runtime error recovery, and historical errors cannot reopen an accepted gate.

When changing orchestration:

- preserve capacity recovery through both the tmux idle detector and coordinator retry guard;
  test real Codex shortcut/warning footers, cooldown retries and historical capacity text during work

- happy path should stay automatic
- active launcher confirmation menus with an affirmative option are accepted automatically, including dynamic workflow consent; never answer old prompts in scrollback
- operator involvement should happen only when the workflow genuinely needs a human
- direct live replies should be modeled through interactive blockers and `Send Runtime Input`
- recovery-style blockers should not be disguised as interactive replies
- optional lanes may auto-start and emit `skipped_not_needed`
- required lanes may not use `skipped_not_needed`
- delivery failures should use stage-specific retries, not generic recovery actions

## Test Design Rules

For supported backend/UI/runtime work, treat mobile hosted tests as a constrained environment:

- do not add subprocess-based crash harnesses for app-hosted iOS or Android tests
- do not respawn `CommandLine.arguments[0]`, the app host binary, or simulator app bundles to prove `precondition` / `fatalError` behavior
- do not treat dyld crashes, simulator launch failures, or arbitrary child-process signals as valid proof that a specific assertion path was exercised
- prefer deterministic seams instead:
  - injectable assertion/trap handlers
  - `throws`-based contracts where feasible
  - narrowly scoped adapters that can be unit-tested without process relaunch

If a test requires a separate process to validate a crash contract, that harness must live outside normal hosted mobile test execution and must not depend on relaunching the simulator app binary.

## Documentation Hygiene

If you change supported behavior, keep these aligned:

- `README.md`
- `AGENTS.md`
- `DEVELOPERS_GUIDE.md`
- `docs/setup.md`
- `docs/operator-guide.md`
- `docs/runtime-model.md`
- `docs/terminal-result-contract.md`
