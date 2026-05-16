# Phase 43 Runtime Capabilities Baseline

## Implemented

Added a bounded runtime-capability surface that separates:

- live runner capabilities
- legacy role defaults

### Backend

- added `factory/doctor/runtime_capabilities.py`
- added operator route:
  - `GET /operator/runtime-capabilities`
- exposed:
  - available runners
  - default runner
  - live model lists per runner
  - supported effort/reasoning levels per model
  - legacy role defaults from `.claude/agents/*.md`

### UI

- added `RuntimeCapabilitiesPanel`
- surfaced runner/model/effort capabilities in the operator console sidebar
- surfaced legacy role defaults separately, without pretending they are the live runtime catalog

## Validation

- `./.venv/bin/python -m unittest tests.backend.test_runtime_capabilities tests.backend.test_environment_doctor tests.backend.test_api_sessions`
- `./.venv/bin/python -m unittest discover -s tests/backend -p 'test_*.py'`
- `npm run build`

## Result

The product now has a real source for:

- which runners are available
- which models are actually selectable per runner
- which effort/reasoning levels are actually supported per model

This is enough to begin the next phase:

- role-level runtime configuration

without hardcoding stale lists in the UI.
