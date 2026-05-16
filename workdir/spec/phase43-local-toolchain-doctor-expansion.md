# Phase 43 Local Toolchain Doctor Expansion

## Scope

Expand the doctor with the next most useful local setup checks:

- local `.venv`
- `node`
- `npm`

The goal is to improve the existing doctor/guidance loop without starting setup automation yet.

## Implemented

The doctor now checks:

- `.venv` presence in the repository root
- `node` availability on `PATH`
- `npm` availability on `PATH`

The new checks are surfaced through:

- shell doctor output
- shell bootstrap guidance output
- backend doctor route
- backend bootstrap guidance route
- UI doctor/guidance surfaces

## Validation

Passed:

- `./.venv/bin/python -m unittest tests.backend.test_environment_doctor tests.backend.test_bootstrap_guidance`
- `./.venv/bin/python -m unittest discover -s tests/backend -p 'test_*.py'`
- `bash factory/doctor/run-doctor.sh`
- `bash factory/doctor/run-bootstrap-guide.sh`

## Result

The setup/tooling model now includes both backend and frontend local toolchain prerequisites, not only repository/env/auth checks.
