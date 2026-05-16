# Phase 43 Bootstrap Guidance Surface

## Scope

Expose the already implemented bootstrap guidance through the product surface.

The bounded goal of this slice is:

- backend read-only bootstrap guidance route
- typed API schema
- UI panel showing prioritized setup actions

## Implemented

### Backend

Added:

- `GET /operator/bootstrap-guidance`

The route builds guidance from the current doctor report using:

- `factory/doctor/bootstrap_guidance.py`

### UI

Added:

- `BootstrapGuidancePanel`

Integrated into:

- `SessionsPage`

The operator console now shows:

- prioritized next setup step
- required action count
- optional action count
- required actions with hints
- optional improvements with hints

## Validation

Passed:

- `./.venv/bin/python -m unittest tests.backend.test_environment_doctor tests.backend.test_bootstrap_guidance tests.backend.test_api_sessions`
- `./.venv/bin/python -m unittest discover -s tests/backend -p 'test_*.py'`
- `npm run build` in `ui/`

## Result

The setup/tooling flow now has three layers:

1. doctor
2. bootstrap guidance
3. operator-facing guidance surface

The next `Phase 43` slice can now move toward either:

- richer checks
- actual setup automation
- or reconciled permanent docs
