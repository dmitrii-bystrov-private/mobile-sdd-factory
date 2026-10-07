# Repository Guidelines

## Supported Platform First
This repository is the current Constellation: Agent Runtime orchestration platform.
The supported product model is:

- `backend/` for API, coordinator, session lifecycle, runtime contracts, and state
- `ui/` for the operator console
- `factory/` for doctor, cleanup, acceptance harnesses, and local stack helpers
- `scripts/` for direct shell helpers and workflow automation

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
- automatically accept active launcher confirmation menus with an affirmative option, including dynamic workflow consent; keep requirements choices routed to the operator
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
- conflicts between task requirements and fundamental rules require an explicit operator decision;
  report both sides and their sources, then follow the recorded decision
- implementer may report failed with needs_operator_input=true during any coding correction stage,
  including documentation review correction; preserve the reasoned disagreement for the operator

## Testing Expectations

QA keys use the factory-owned mobile e2e workflow in `docs/e2e-workflow.md`. Default app builds are
master unless a build is explicitly selected. Product policy stays in settings; local paths/devices/ports
stay in ENV and ~/.zshrc; toolchain/SDK versions belong in dependency manifests. Never load external
workspace skills, docs or scripts at runtime. Compare test revisions on the same app build.
Native QA verdicts govern all verification outcomes, including blocked-cycle submissions. Environment
failures require recovery; evidenced baseline failures await an operator decision. Retry creates a
fresh verification work item and strategy.
Operator messages must explain native failure evidence rather than display serialized classifications.
Keep task and baseline error messages distinct. The blocked-run card offers retry, corrections and
explicit acceptance of selected, evidenced baseline failures. Bind acceptance to the current gate,
source, execution strategy, task support files and app artifact; preserve the original failures and operator event. Remaining
checks must run, and delivery must retain accepted_with_warnings rather than report all tests passed.
Continue on the accepted app artifact even when newer master builds appear. Environment recovery may
resume the same gate with its decisions; fresh verification retries must not inherit them. Drain prior
tmux output before continuation and use fresh native verdicts for QA runtime error recovery.
QA MR handoff may retain verification across committed regular documentation changes only, with a
clean worktree and verified ancestor. Preserve original evidence; code/configuration and bound support
changes invalidate delivery. Verification and baseline decisions retain exact source binding.
Factory iOS gates record native execution state. Resource waits preserve the active work item and
terminal; defer premature role results while its bound runner is alive. Nested shell lock wrappers
are expected; only owner ancestry proves recursive acquisition. Never remove another live owner's lock.
Completed coding work-item replays are stale/idempotent even when the same implementer owns a new
correction. Never advance the new stage or mark its dispatch complete from an earlier work-item ID.
Start shared Appium with --allow-insecure uiautomator2:chromedriver_autodownload. Check its version
and explicit launch flags before reuse; report mismatches without stopping other users' server.
Project commands, environment, collection scope, smoke checks and application IDs are task data in
verification-strategy.json. Do not add project imports, fixed test paths or project-specific setup to
factory code or role defaults. Use generic evidence protocols and digest-bound task-local integration.
Map factory device/server context to the project inputs in task data. Setup/teardown failures are not
acceptance candidates. Serialize operator continuations with collection and preserve the verifier owner.
Dedicated iOS simulator pools use factory-specific ENV, per-device locks and separate WDA ports/caches.
Wait for a free pool slot within the gate time limit. Stop only the leased simulator before releasing
its lock, including failure, partial boot, timeout and graceful interruption. Preserve workspace devices.

When behavior changes:

- completed runtime hibernation must checkpoint exact task/role conversations and operator decisions;
  wake only the required role with current hydration, and retain live agents if checkpointing fails

- iOS verification must invalidate prior test evidence before preparation and reject replayed deferred
  responses after native completion; fresh terminal evidence governs the verdict
- closed verifier work-item results must not affect a fresh gate; retries supersede earlier queued
  continuations and drain previous terminal output

- capacity recovery must recognize the current Codex footer, preserve the configured model, and allow
  repeated capacity retries after cooldown without repeating generic idle pokes or pending results

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

Keep the root README focused on the product overview, quick start, workflow profiles and documentation
navigation. Put configuration, verification, protocol and recovery details in their topical guides.
Align the README through concise capability summaries and links; avoid appending individual fixes or
regression scenarios to it.

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
