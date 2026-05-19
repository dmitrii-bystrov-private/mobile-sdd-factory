# Deprecated Surface

This document tracks the legacy slash-command orchestration surface that remains in the repository as a deprecated compatibility layer.

The current primary product surface is:

- the backend session runtime
- the operator UI
- persistent tmux-backed role runtimes
- project-local runtime defaults in `.sdd-factory/settings.local.json`

The deprecated surface remains only because it is still useful as:

- a reference for older workflow behavior
- a fallback/manual compatibility path while the new system continues to harden
- a source of migration context for roles, policies, and follow-up lanes

## Deprecated Inventory

The following repository areas are considered deprecated surface:

- `CLAUDE.md`
  Notes for the legacy slash-driven orchestration model.
- `.claude/skills/README.md`
  Legacy skill catalog.
- `.claude/skills/jira-task/`
- `.claude/skills/jira-story/`
- `.claude/skills/jira-bug/`
- `.claude/skills/oneshot/`
- `.claude/skills/snapshot/`
- `.claude/skills/self-review/`
- `.claude/skills/boy-scout/`
- `.claude/skills/final-verification/`
- `.claude/skills/doc-harvest/`
- `.claude/skills/create-mr/`
- `.claude/skills/send-to-test/`
- `.claude/skills/handle-mr-comments/`

The following repository areas are not deprecated and remain part of the supported platform:

- `backend/`
- `factory/`
- `ui/`
- `tests/`
- `scripts/`
- `.sdd-factory/settings.local.json` as the project-local runtime defaults store

## Supported Semantics

For the deprecated slash-command surface:

- compatibility is best-effort
- documentation should be explicit that these flows are no longer the primary product path
- configuration through old env flags should be treated as legacy-only
- parity with the current backend/runtime platform is not a goal by default

For the supported platform:

- the operator UI and backend runtime semantics are the source of truth
- live task execution should assume persistent long-running roles
- delivery, follow-up, cleanup, and recovery behavior should be judged against the backend/UI implementation, not legacy slash flow docs

## Removal Criteria

The deprecated surface can be deleted once all of the following are true:

1. The backend/UI system is the only required operator path for story, bug, oneshot, MR follow-up, QA reopen, cleanup, and delivery flows.
2. The new runtime model is considered stable enough that the legacy skill files are no longer needed as behavioral reference material.
3. Any still-useful intent from the legacy files has been migrated into:
   - supported product docs
   - backend tests / acceptance harnesses
   - role prompts or runtime contracts that still matter
4. Operators and developers no longer need slash-command fallback for normal work.

## Retirement Checklist

When the team decides to remove the deprecated surface, use this order:

1. Remove deprecated references from `README.md`.
2. Remove deprecated compatibility notes from `CLAUDE.md`.
3. Delete `.claude/skills/README.md` if it no longer serves as migration reference.
4. Delete deprecated skill directories listed above.
5. Remove legacy env-flag expectations that exist only for slash-command skills.
6. Re-run backend, UI, and live acceptance validation to confirm the supported platform is unaffected.

## Notes

- Deprecated does not mean forbidden. It means the surface is not the main product contract and should not drive new architectural decisions.
- New features should be added to the backend/UI runtime model first. They should only be mirrored into the deprecated surface if there is a concrete short-term compatibility reason.
