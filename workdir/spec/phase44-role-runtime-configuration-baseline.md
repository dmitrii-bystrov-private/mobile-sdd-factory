# Phase 44 Role Runtime Configuration Baseline

## Implemented

Added the first real session-scoped role runtime configuration layer.

### Session Contract

- `POST /sessions` now accepts `role_config`
- session state now stores `role_config_json`
- session reads now expose normalized role runtime config

### Normalization

- added `backend/role_runtime_config.py`
- effective roles are normalized against:
  - live runner/model/effort capabilities
  - legacy role defaults where they still provide useful starting values
- invalid runner/model/effort combinations now fail at session creation time instead of surfacing later in launcher runtime

### Launcher Integration

- launcher plans now emit:
  - `SDD_FACTORY_ROLE_RUNNER`
  - `SDD_FACTORY_ROLE_MODEL`
  - `SDD_FACTORY_ROLE_EFFORT`
- `factory/scripts/run-role-agent.sh` now respects those values for:
  - `claude`
  - `codex`

### UI

- `SessionStartForm` now renders role-level runner/model/effort controls
- the form is driven by the live runtime capability surface instead of hardcoded lists

## Validation

- `./.venv/bin/python -m unittest tests.backend.test_runtime_capabilities tests.backend.test_api_sessions tests.backend.test_session_creation tests.backend.test_repositories`
- `./.venv/bin/python -m unittest discover -s tests/backend -p 'test_*.py'`
- `npm run build`

## Result

The product can now choose real runner/model/effort values per role at session start.

This closes the first half of `Phase 44` and creates the right base for:

- role-scoped MCP isolation
- runtime session management
- deeper codex parity
