# Repository Guidelines

## Project Structure & Module Organization
This repository is the orchestration layer for the mobile SDD workflow. Keep top-level changes focused and predictable:

- `.claude/agents/` stores agent definitions.
- `.claude/commands/` contains slash-command entry points such as Jira and MR flows.
- `.claude/skills/` holds reusable workflow skills and prompts.
- `.claude/hooks/` contains automation hooks executed by the assistant runtime.
- `scripts/` contains Bash utilities used directly and by agents.
- `scripts/tests/` contains shell-based regression tests for snapshot and formatter behavior.

Add new automation in `scripts/` unless it is purely prompt/agent logic, in which case it belongs under `.claude/`.

## Build, Test, and Development Commands
Run commands from the repository root:

- `bash scripts/snapshot.sh IOS-1234` prepares the Jira workspace and worktree.
- `bash scripts/run-build.sh IOS-1234` runs the platform-aware build wrapper.
- `bash scripts/run-test.sh IOS-1234` runs the platform-aware test wrapper.
- `bash scripts/run-lint.sh IOS-1234` runs the platform-aware lint wrapper.
- `bash scripts/tests/test_adf_to_md.sh` validates ADF-to-Markdown conversion.
- `bash scripts/tests/test_snapshot_formatters.sh` checks golden-file output.
- `bash scripts/tests/test_snapshot_errors.sh` covers snapshot failure paths.

Required tooling is documented in `README.md` and `scripts/README.md`; most flows expect `acli`, `glab`, `jq`, and the `SDD_WORKDIR` / `IOS_DIR` / `ANDROID_DIR` environment variables.

## Coding Style & Naming Conventions
Use Bash with `#!/usr/bin/env bash` and `set -euo pipefail`. Follow the existing style: two-space indentation, uppercase constants (`SCRIPT_DIR`), lowercase function names (`need_cmd`), and clear fatal error messages. Keep scripts idempotent and fail fast. Name tests `test_*.sh`; name helper libraries by responsibility, such as `snapshot-formatters.sh`.

## Testing Guidelines
Add or update focused shell tests when behavior changes in `scripts/`. Prefer golden-file checks for formatted output and isolated assertions for helpers. Run the narrowest affected test first, then the broader wrapper (`run-test.sh`) if the change touches task execution.

## Commit & Pull Request Guidelines
Recent history uses concise conventional commits such as `fix:` and `chore:`. Follow that style for repository changes; task-worktree commits created by automation use `<KEY>: <TASK-TITLE>`. For merge requests, include the Jira key, describe the workflow impact, list validation performed, and attach screenshots only when user-visible Slack or generated Markdown output changes.

## Agent-Specific Notes
Do not mix orchestration logic with implementation details. Agents should delegate platform work to scripts where possible, keep generated artifacts deterministic, and avoid hidden side effects outside `$SDD_WORKDIR`.
