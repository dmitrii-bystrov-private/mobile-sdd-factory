# Phase 43 Environment Doctor Baseline

## Scope

Implement the first bounded doctor surface for the factory environment.

The baseline should answer, without guesswork:

- which required environment variables are present and valid
- which required CLI tools are installed
- whether at least one live role runner is available
- whether the main auth surfaces are healthy
- whether required MCP servers are configured
- which optional runtime pieces are missing but non-blocking

## Implemented Surface

The baseline doctor now exists as:

- `factory/doctor/run-doctor.sh`
- `factory/doctor/run-doctor.py`
- `factory/doctor/environment_doctor.py`

It supports:

- human-readable summary output
- `--json` machine-readable output

## Checks Included

### Required environment

- `SDD_WORKDIR`
- `IOS_DIR`
- `ANDROID_DIR`

The doctor accepts values from:

- process environment
- fallback `.claude/.env`

### Required CLI

- `python3`
- `jq`
- `acli`
- `glab`

### Runtime

- at least one of:
  - `claude`
  - `codex`

### Auth

- `acli jira auth status`
- `glab auth status`
- `claude auth status`
- `codex login status`
- synthesized "at least one live role runner authenticated"

### MCP configuration

Required:

- `ios-rag`
- `android-rag`

Optional but surfaced:

- `frontend-rag`

## Validation

Passed:

- `./.venv/bin/python -m unittest tests.backend.test_environment_doctor`
- `bash factory/doctor/run-doctor.sh`
- `bash factory/doctor/run-doctor.sh --json`

## Result

`Environment Doctor Baseline` is now implemented and validated.

This does **not** yet complete `Phase 43`.

Remaining later work in the phase still includes:

- richer setup/bootstrap guidance
- permanent documentation after implementation reconciliation
