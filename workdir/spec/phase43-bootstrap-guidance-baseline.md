# Phase 43 Bootstrap Guidance Baseline

## Scope

Build the first actionable setup layer on top of the existing doctor report.

The goal of this slice is not a full installer.

It is a bounded guidance surface that answers:

- what must be fixed first
- what is optional
- what concrete next step follows from the current doctor state

## Implemented

Added:

- `factory/doctor/bootstrap_guidance.py`
- `factory/doctor/run-bootstrap-guide.py`
- `factory/doctor/run-bootstrap-guide.sh`

## Behavior

The guidance layer consumes the doctor report and produces:

- overall doctor status
- required action count
- optional action count
- one prioritized `next_step`
- `required_actions`
- `optional_actions`

It supports:

- human-readable output
- `--json` output

## Validation

Passed:

- `./.venv/bin/python -m unittest tests.backend.test_bootstrap_guidance tests.backend.test_environment_doctor`
- `./.venv/bin/python -m unittest tests.backend.test_runtime_backend tests.backend.test_bootstrap_guidance tests.backend.test_environment_doctor`
- `./.venv/bin/python -m unittest discover -s tests/backend -p 'test_*.py'`
- `bash factory/doctor/run-bootstrap-guide.sh`
- `bash factory/doctor/run-bootstrap-guide.sh --json`

## Result

The environment tooling now has two layers:

1. doctor: what is healthy or broken
2. bootstrap guidance: what to do next

This still does **not** mean a full installer exists yet.

The next `Phase 43` work can move toward:

- richer doctor semantics
- actual setup/bootstrap automation
- or the first permanent reconciled docs package
