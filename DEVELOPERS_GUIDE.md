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
- `scripts/` remains useful for direct helpers and compatibility automation

The `.claude/` tree is deprecated compatibility surface unless you are explicitly working on legacy retirement or migration support.

## Directory Map

```text
backend/                API, coordinator, runtime, repositories, role contracts
ui/                     operator console
factory/                doctor, bootstrap, cleanup, acceptance, local stack helpers
tests/backend/          backend regression suite
scripts/                direct shell helpers and wrappers
scripts/tests/          shell regression tests
docs/                   supported platform documentation
.claude/                deprecated compatibility surface
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
Do not reintroduce `.claude/agents/*.md` as the baseline source.

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

When changing orchestration:

- happy path should stay automatic
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

If behavior is only deprecated compatibility, document it under:

- `docs/deprecated-surface.md`

## When To Touch Legacy Surface

Touch `.claude/` only when:

- fixing compatibility drift that still matters
- marking remaining legacy material as deprecated
- preparing final retirement/removal

Do not add new primary workflow capabilities there.
