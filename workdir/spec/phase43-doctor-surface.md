# Phase 43 Doctor Surface

## Scope

Expose the existing environment doctor baseline through the product surface, not only through shell entrypoints.

The bounded goal of this slice is:

- backend read-only doctor route
- typed API schema
- UI sidebar panel showing the current doctor state

## Implemented

### Backend

Added:

- `GET /operator/environment-doctor`

The route returns the current report from:

- `factory/doctor/environment_doctor.py`

Typed response models were added in:

- `backend/api/schemas.py`

### UI

Added:

- `EnvironmentDoctorPanel`

Integrated into:

- `SessionsPage`

The operator console now shows:

- overall doctor status
- required checks summary
- optional warning count
- non-green checks with hints

## Validation

Passed:

- `./.venv/bin/python -m unittest tests.backend.test_environment_doctor tests.backend.test_api_sessions`
- `./.venv/bin/python -m unittest discover -s tests/backend -p 'test_*.py'`
- `npm run build` in `ui/`

## Result

The factory now has:

1. a shell doctor baseline
2. an operator-facing doctor surface

The next `Phase 43` work can move higher-level:

- richer bootstrap/setup guidance
- stronger doctor semantics
- or the first permanent reconciled docs package
