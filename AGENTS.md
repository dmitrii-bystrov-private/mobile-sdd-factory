# Repository Guidelines

## Supported Platform First
This repository is the current Constellation: Agent Runtime orchestration platform.
The supported product model is:

- `backend/` for API, coordinator, session lifecycle, runtime contracts, and state
- `ui/` for the operator console
- `factory/` for doctor, cleanup, acceptance harnesses, and local stack helpers
- `scripts/` for direct shell helpers and compatibility automation

Treat the backend/UI/tmux runtime model as the source of truth.
`.claude/settings.json` is only launcher-side Claude configuration source material.

## Project Structure

- `backend/` — FastAPI routes, coordinator, runtime plumbing, role prompts/workspaces, repositories
- `ui/` — Vite/React operator console
- `factory/` — doctor, runtime capabilities, cleanup, bootstrap, acceptance tooling
- `tests/backend/` — backend regression suite
- `scripts/` — direct CLI helpers, snapshot/build/test/lint wrappers, Jira/MR utilities
- `scripts/tests/` — shell regression tests for script behavior
- `docs/` — supported platform docs

Add new product behavior to `backend/`, `ui/`, or `factory/` as appropriate.

## Key Commands
Run commands from the repository root.

Supported platform checks:

- `bash scripts/run-supported-tests.sh`
- `./.venv/bin/python -m unittest discover -s tests/backend -p 'test_*.py'`
- `cd ui && npm run build`
- `bash factory/acceptance/run-happy-path-acceptance.sh`
- `bash factory/acceptance/run-followup-reopen-acceptance.sh`
- `bash factory/acceptance/run-mr-followup-acceptance.sh`
- `bash factory/acceptance/run-delivery-acceptance.sh`

High-signal live/runtime acceptance:

- `bash scripts/run-supported-tests.sh --live`
- `PYTHONPATH=. ./.venv/bin/python factory/acceptance/run-real-story-runtime-acceptance.py`
- `PYTHONPATH=. ./.venv/bin/python factory/acceptance/run-real-codex-quality-loop-validation.py`

Direct shell helpers that still matter:

- `bash scripts/dev.sh help`
- `bash scripts/dev.sh ui`
- `bash scripts/dev.sh test`
- `bash scripts/dev.sh doctor`
- `bash scripts/dev.sh bootstrap`
- `bash factory/run-local-stack.sh`
- `bash factory/open-local-ui.sh`
- `bash scripts/snapshot.sh <KEY>`
- `bash scripts/run-test.sh <KEY>`
- `bash scripts/run-lint.sh <KEY>`
- `bash scripts/run-build.sh <KEY>`

## Coding Conventions

Python:

- prefer small explicit coordinator/runtime changes over broad rewrites
- keep state transitions and operator semantics easy to trace
- add tests for lifecycle and regression-sensitive behavior

TypeScript/React:

- preserve the supported operator surface: `Daily`, `Recovery`, runtime visibility, runtime defaults
- avoid surfacing deprecated or internal-only controls as normal product actions
- keep labels and tooltips operator-readable rather than backend-internal

Bash:

- use `#!/usr/bin/env bash` and `set -euo pipefail`
- keep helpers idempotent and fail fast

General:

- prefer ASCII unless the file already uses Unicode
- keep generated artifacts deterministic

## Testing Expectations

When behavior changes:

- run the narrowest affected backend tests first
- run `cd ui && npm run build` for UI changes
- run targeted acceptance when the change affects orchestration or operator flow
- do not add subprocess-based crash harnesses for hosted mobile tests
- in iOS/Android app-hosted test targets, do not respawn the current executable or app binary to assert `precondition` / `fatalError` behavior
- prefer deterministic seams instead: injectable assertion/trap handlers, `throws`, or other testable contracts that do not depend on process relaunch

For live acceptance:

- use the shared acceptance runtime defaults in `factory/acceptance/runtime-defaults.json`
- Claude defaults should stay on `sonnet`
- Codex live tests should stay on `gpt-5.3-codex-spark`
- do not rely on dirty repo state; acceptance should execute in isolated task-like environments

## Documentation Expectations

Keep these files aligned with supported behavior:

- `README.md`
- `AGENTS.md`
- `DEVELOPERS_GUIDE.md`
- `docs/setup.md`
- `docs/operator-guide.md`
- `docs/runtime-model.md`
- `docs/terminal-result-contract.md`

If the supported platform changes, update those docs in the same slice unless the change is clearly internal-only.

## Commit Guidance

Use concise conventional commits such as:

- `feat: ...`
- `fix: ...`
- `refactor: ...`
- `docs: ...`
- `test: ...`
