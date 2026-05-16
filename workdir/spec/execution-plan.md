# SDD Factory Execution Plan

## Purpose

Provide one execution-focused source of truth for implementation progress.

This file answers:

- where the project is now
- what phases already completed
- what is currently in progress
- what exact next steps should happen next

Status markers:

- `[done]`
- `[in_progress]`
- `[pending]`
- `[deferred]`

## Current Position

- Current phase: `Phase 43. Environment Setup, Doctor, And Permanent Documentation`
- Overall status: `persistent runtime, story and bug runtime acceptance, launcher-backed operator recovery acceptance, launcher-backed MR follow-up acceptance, real launcher-backed implementer completion, file-backed role result handling, real two-round live implementer validation, and the first environment doctor baseline are complete; the next active track remains environment setup, doctor, and permanent documentation`
- Current implementation mode: `launcher-backed live roles now use PTY transport plus file-backed handoff/result semantics; the first doctor/status surface now exists and the next work should widen environment productization beyond the baseline`
- Primary source of truth for next work: `this file`
- Filesystem/runtime source of truth: `workdir/spec/filesystem-runtime-model.md`
- External runner session cleanup policy: `workdir/spec/external-runner-session-cleanup-policy.md`
- Permanent documentation rule: `workdir/spec/permanent-documentation-principle.md`
- Test environment status: `local .venv created, backend tests now run without skip-based dependency fallback`

## Current Immediate Next Step

- `[in_progress]` continue `Phase 43` after completing the baseline doctor and its first operator-facing surface

## Reserved Next Phase

- `[pending]` no later named phase reserved yet

## Phase 1. Architecture Contract

- Status: `[done]`
- Goal: fix core architecture, stack, MVP boundaries, and artifact location
- Exit criteria:
  - core project/spec artifacts exist
  - stack is fixed
  - MVP role set is fixed
  - artifact location strategy is fixed
- Completed:
  - `[done]` stack fixed as `Python + FastAPI + SQLite + tmux`
  - `[done]` MVP role set fixed as `task-coordinator + implementer + verification-coordinator`
  - `[done]` temporary/project spec artifacts moved to `workdir/spec/`
  - `[done]` initial architecture/spec files created in `workdir/spec/`
- Notes:
  - initial contract exists, but some documents are now stale relative to implemented backend behavior

## Phase 2. Repository Transition Mapping

- Status: `[done]`
- Goal: define what gets reused, migrated, deprecated, or kept as compatibility layer
- Exit criteria:
  - repository transition map exists
  - shell adapters identified
  - migration boundary from `.claude/` to backend is documented
- Completed:
  - `[done]` `workdir/spec/repository-transition-map.md` created
  - `[done]` current `.claude/` and `scripts/` components classified
  - `[done]` deterministic adapter candidates identified

## Phase 3. State Core

- Status: `[done]`
- Goal: establish SQLite as source of truth
- Exit criteria:
  - backend scaffold exists
  - SQLite schema and migrations exist
  - repositories can create/read/update core entities
- Completed:
  - `[done]` backend scaffold created
  - `[done]` SQLite bootstrap and migration tracking implemented
  - `[done]` repositories implemented for sessions, roles, events, work items, artifacts
  - `[done]` backend tests added for repository coverage
- Notes:
  - state model works for current MVP loop, but checkpoint/verification repositories still need completeness review

## Phase 4. Session Backend

- Status: `[done]`
- Goal: provide runtime abstraction for long-lived role processes
- Exit criteria:
  - `SessionBackend` exists
  - `TmuxSessionBackend` exists
  - runtime handles and role IO can be exercised through the abstraction
- Completed:
  - `[done]` `SessionBackend` abstraction implemented
  - `[done]` `TmuxSessionBackend` implemented
  - `[done]` recording fallback implemented when `tmux` is unavailable
  - `[done]` role input dispatch implemented through runtime backend
  - `[done]` raw runtime output collection implemented

## Phase 5. Coordinator MVP

- Status: `[done]`
- Goal: make one persistent task session complete the core implementation-verification cycle
- Exit criteria:
  - task session can be created and prepared
  - implementation handoff works
  - verification handoff works
  - failure correction loop works
  - verification success completes the session
- Completed:
  - `[done]` session creation and default role spawning
  - `[done]` deterministic intake and snapshot preparation
  - `[done]` initial implementation work item and handoff
  - `[done]` `implementation_completed -> verification_requested`
  - `[done]` `verification_failed -> verification_correction_requested`
  - `[done]` `verification_passed -> task_completed`
  - `[done]` hydration/prompt artifact generation
  - `[done]` structured role output ingestion
  - `[done]` raw runtime marker normalization for `SDD_OUTPUT`, `SDD_PROGRESS`, `SDD_ERROR`
  - `[done]` runtime-error escalation to `waiting_for_operator`
  - `[done]` loop reconciliation for missing dispatch after restart/interruption
- Notes:
  - checkpoints and explicit verification orchestration rules are still lighter than original plan implied

## Phase 6. API Layer / Operator Control

- Status: `[done]`
- Goal: let an operator inspect and control a session without touching runtime internals
- Exit criteria:
  - session inspection endpoints exist
  - event and artifact inspection exist
  - role output and runtime polling endpoints exist
  - live session updates exist
  - operator recovery actions exist
  - API surface is reconciled against the actual MVP contract
- Completed:
  - `[done]` session endpoints: create, list, prepare
  - `[done]` event endpoints: list, inject, SSE stream
  - `[done]` role endpoints: list, submit output, collect output
  - `[done]` artifact endpoints: list, detail
  - `[done]` work item inspection endpoint
  - `[done]` operator polling endpoint
  - `[done]` operator loop control endpoints
  - `[done]` operator `pause-session`
  - `[done]` SSE replay with `since_event_id`
  - `[done]` operator `resume-session`
  - `[done]` operator `retry-session`
  - `[done]` operator `redirect-session`
  - `[done]` redirect policy enforcement by stage
  - `[done]` compact API/operator inventory documented in `workdir/spec/api-operator-contract.md`
- Remaining:
  - `[done]` reconcile API surface against documented MVP contract and remove drift
  - `[done]` define explicit operator pause semantics as part of MVP
  - `[done]` mark cancel semantics out of scope for current backend MVP
- Notes:
  - accepted as sufficient for backend MVP, with experimental routes and deferred items explicitly recorded
- Why still in progress:
  - none

## Phase 7. Workflow Policy And Session Configuration

- Status: `[done]`
- Goal: restore old flow flexibility through explicit session policy rather than ad hoc operator overrides
- Exit criteria:
  - workflow policy model is documented
  - role control is separated from workflow control in the spec set
  - startup configuration needs are defined for `story_full`, `bug_full`, and `oneshot`
  - the plan reflects that `redirect` is not the main path-selection mechanism
- Progress:
  - `[done]` inspect legacy `jira-story`, `jira-bug`, and `oneshot` flow structure from existing skills
  - `[done]` identify that optional stages and flow promotion are workflow-path concerns, not role-routing concerns
  - `[done]` document workflow policy model in `workdir/spec/workflow-policy-model.md`
  - `[done]` classify `redirect` as experimental/internal rather than a stable workflow primitive
  - `[done]` decide that the first policy schema uses unified tri-state semantics: `disabled | enabled | required`
  - `[done]` freeze the first implementation payload in `workdir/spec/session-policy-v1.md`
  - `[done]` define the session-start backend/UI contract in `workdir/spec/session-start-contract.md`
  - `[done]` implement policy-aware session creation and normalized session reads in backend
  - `[done]` remove `redirect` from the future stable operator surface and UI plan

## Phase 8. UI Layer

- Status: `[done]`
- Goal: create the operator console
- Exit criteria:
  - one session can be inspected and controlled through UI
  - UI consumes API/SSE rather than runtime internals
  - the UI milestone is aligned with the workflow-policy direction
- Progress:
  - `[done]` create `ui/` scaffold
  - `[done]` build sessions list/detail screens
  - `[done]` build role/artifact/operator panels
  - `[done]` add live session updates over SSE
  - `[done]` validate operator flows against the running backend manually
  - `[done]` record live validation results in `workdir/spec/ui-operator-validation.md`
  - `[done]` implement policy-aware start-session form in UI
  - `[done]` assess the first stable operator-console milestone in `workdir/spec/ui-milestone-assessment.md`

## Phase 9. Lifecycle Extension

- Status: `[done]`
- Goal: survive beyond the first implementation-verification loop
- Exit criteria:
  - MR feedback loop exists
  - QA reopen loop exists
  - follow-up work handling exists
- Progress:
  - `[done]` choose lifecycle extension as the next primary post-UI direction in `workdir/spec/next-phase-direction.md`
  - `[done]` MR comments ingestion can now reopen a completed session into an implementer follow-up loop
  - `[done]` QA reopen events can now reactivate a completed session into an implementer follow-up loop
  - `[done]` follow-up work item creation/handling now uses a shared `followup_implementation` lane that returns to verification
  - `[done]` choose `operator-triggerable follow-up intake surface` as the next concrete `Phase 9` slice in `workdir/spec/phase9-next-slice.md`
  - `[done]` expose MR follow-up intake as a stable operator UI flow
  - `[done]` expose QA reopen intake as a stable operator UI flow
  - `[done]` show follow-up source/context in the session UI
  - `[done]` validate that completed sessions can be reopened from the console and that follow-up context is visible end-to-end in `workdir/spec/phase9-followup-intake-validation.md`
  - `[done]` decide that the next disciplined move is formal `Phase 9` milestone assessment, not another implementation slice, in `workdir/spec/phase9-completion-direction.md`
  - `[done]` assess `Phase 9` completion against its declared goal and exit criteria in `workdir/spec/phase9-assessment.md`

## Phase 10. Hardening And Completion

- Status: `[done]`
- Goal: turn the backend MVP into a declared, reviewable milestone
- Exit criteria:
  - tests and docs match actual behavior
  - current milestone is explicitly declared complete
  - deferred items are separated from MVP
- Remaining:
  - `[done]` local Python test environment initialized via `.venv` with project dependencies installed
  - `[done]` backend test suite now runs without `fastapi`-missing skips
  - `[done]` test-environment activation exposed a real API defect in `prepare_session`, which was fixed
  - `[done]` checkpoints explicitly removed from current MVP and treated as deferred capability
  - `[done]` reconcile backend MVP against the actual implementation and record milestone verdict
  - `[done]` classify missing pieces as `required`, `optional`, or `deferred`
  - `[done]` produce backend MVP completion note
  - `[done]` reconcile remaining spec docs with implemented behavior
  - `[done]` add milestone completion checklist for later phases in `workdir/spec/milestone-checklist.md`
  - `[done]` assess `Phase 10` completion and record the verdict in `workdir/spec/phase10-assessment.md`

## Phase 11. Delivery And Handoff

- Status: `[done]`
- Goal: extend one persistent session from internal verification success to explicit delivery completion and external handoff
- Exit criteria:
  - the post-verification path is explicit rather than implied
  - at least one delivery/handoff action exists as a real session-controlled capability
  - optional quality or documentation lanes are either implemented or explicitly deferred for this phase
- Remaining:
  - `[done]` choose the first concrete `Phase 11` slice inside delivery and handoff in `workdir/spec/phase11-first-slice.md`
  - `[done]` implement the `MR Handoff` slice
  - `[done]` validate the `MR Handoff` slice end-to-end in `workdir/spec/phase11-mr-handoff-validation.md`
  - `[done]` choose the next concrete `Phase 11` slice after `MR Handoff` in `workdir/spec/phase11-next-slice.md`
  - `[done]` implement the `Send To Test Handoff` slice
  - `[done]` validate the `Send To Test Handoff` slice end-to-end in `workdir/spec/phase11-send-to-test-validation.md`
  - `[done]` decide that optional quality/documentation lanes do not need to block `Phase 11` assessment in `workdir/spec/phase11-completion-direction.md`
  - `[done]` assess `Phase 11` completion against its declared goal and exit criteria in `workdir/spec/phase11-assessment.md`

## Phase 12. Workflow Control And Optional Lanes

- Status: `[done]`
- Goal: make selected optional workflow lanes explicit and policy-driven rather than merely declared in session policy
- Exit criteria:
  - at least one optional lane is represented as a real session stage path
  - session policy influences explicit lane execution rather than only session-start metadata
  - optional lanes are either implemented or explicitly deferred by written phase decision
- Remaining:
  - `[done]` choose the first concrete `Phase 12` slice inside workflow control and optional lanes in `workdir/spec/phase12-first-slice.md`
  - `[done]` implement the `Doc Harvest Lane` slice
  - `[done]` validate the `Doc Harvest Lane` slice end-to-end in `workdir/spec/phase12-doc-harvest-validation.md`
  - `[done]` decide the next `Phase 12` slice after `Doc Harvest Lane` in `workdir/spec/phase12-next-slice.md`
  - `[done]` implement the `Self Review Lane` slice
  - `[done]` validate the `Self Review Lane` slice end-to-end in `workdir/spec/phase12-self-review-validation.md`
  - `[done]` decide the next `Phase 12` slice after `Self Review Lane` in `workdir/spec/phase12-completion-direction.md`
  - `[done]` assess `Phase 12` completion against its declared goal and exit criteria in `workdir/spec/phase12-assessment.md`

## Phase 13. Planning And Execution Coverage

- Status: `[complete]`
- Goal: restore the missing story/bug/subtask capability classes in a cleaner session-native form so the new system is not weaker than the old workflow where it mattered
- Exit criteria:
  - a real story planning/spec lane exists
  - a real bug-analysis lane exists
  - a real subtask graph orchestration path exists
  - the new system covers these capability classes without reverting to the old orchestration model
- Notes:
  - this phase exists to close the most important workflow-coverage gaps before active cross-session knowledge work
- Remaining:
  - `[done]` choose the first concrete `Phase 13` slice inside planning and execution coverage in `workdir/spec/phase13-coverage-first-slice.md`
  - `[done]` implement the `Bug Analysis Lane` slice
  - `[done]` validate the `Bug Analysis Lane` slice end-to-end in `workdir/spec/phase13-bug-analysis-validation.md`
  - `[done]` choose the next `Phase 13` slice in `workdir/spec/phase13-next-slice.md`
  - `[done]` implement the `Story Planning/Spec Lane` slice
  - `[done]` validate the `Story Planning/Spec Lane` slice end-to-end in `workdir/spec/phase13-story-spec-validation.md`
  - `[done]` implement the `Subtask Graph Orchestration` slice
  - `[done]` validate the `Subtask Graph Orchestration` slice end-to-end in `workdir/spec/phase13-subtask-graph-validation.md`
  - `[done]` assess `Phase 13` completion against its declared goal and exit criteria in `workdir/spec/phase13-assessment.md`

## Phase 14. Memory And Feedback Loop

- Status: `[complete]`
- Goal: turn task feedback and implementation discoveries into reusable repo-visible knowledge instead of leaving them as passive history
- Exit criteria:
  - a first repo-visible knowledge structure exists under `knowledge/`
  - extraction starts from review feedback and session insights
  - at least one bounded knowledge reuse path exists for later sessions
  - the phase is explicitly kept narrower than autonomous external intake or production-native platform expansion
- Notes:
  - the earlier exploratory `verification failure lessons` loop has been removed from active code so the future knowledge phase can proceed only from the accepted model
  - this phase stays explicitly next after `Phase 13`, not deleted
- Remaining:
  - `[done]` record the strategic direction in `workdir/spec/memory-feedback-loop-direction.md`
  - `[done]` define the first accepted knowledge slice in `workdir/spec/phase14-first-slice.md`
  - `[done]` remove the exploratory verification-failure memory loop from active backend behavior
  - `[done]` reactivate implementation once `Phase 13` is complete
  - `[done]` implement the `Review And Session Insight Knowledge` slice
  - `[done]` validate the `Review And Session Insight Knowledge` slice end-to-end in `workdir/spec/phase14-review-session-insight-knowledge-validation.md`
  - `[done]` assess `Phase 14` completion against its declared goal and exit criteria in `workdir/spec/phase14-assessment.md`

## Phase 15. Knowledge Expansion And Governance

- Status: `[complete]`
- Goal: expand the repo-visible knowledge model beyond the first proof while keeping capture, reuse, and curation explicit and bounded
- Exit criteria:
  - at least one additional high-value external knowledge source exists beyond review feedback
  - repo-visible knowledge remains the primary source of truth
  - reuse remains explainable through visible artifacts and events
  - the phase does not expand into hidden memory infrastructure or broad autonomous ingestion
- Notes:
  - the first proof in `Phase 14` is complete, so the next step is selective expansion, not reinvention
- Remaining:
  - `[done]` choose the next named implementation phase after `Phase 14` in `workdir/spec/phase15-direction.md`
  - `[done]` choose the first concrete `Phase 15` slice in `workdir/spec/phase15-first-slice.md`
  - `[done]` implement the `QA Knowledge` slice
  - `[done]` validate the `QA Knowledge` slice end-to-end in `workdir/spec/phase15-qa-knowledge-validation.md`
  - `[done]` choose the next `Phase 15` slice in `workdir/spec/phase15-next-slice.md`
  - `[done]` implement the `Knowledge Visibility` slice
  - `[done]` validate the `Knowledge Visibility` slice end-to-end in `workdir/spec/phase15-knowledge-visibility-validation.md`
  - `[done]` assess `Phase 15` completion against its declared goal and exit criteria in `workdir/spec/phase15-assessment.md`

## Phase 16. Knowledge Base Structure And Curation

- Status: `[complete]`
- Goal: improve the structure and curation of the shared knowledge base so it stays useful as it grows
- Exit criteria:
  - the `knowledge/` tree has a clearer semantic taxonomy
  - operators and developers can browse the corpus through a more meaningful catalog
  - the phase improves human usefulness without introducing hidden retrieval infrastructure
- Notes:
  - this phase exists to strengthen the knowledge base itself before any future automation around it
- Remaining:
  - `[done]` choose the next named implementation phase after `Phase 15` in `workdir/spec/phase16-direction.md`
  - `[done]` choose the first concrete `Phase 16` slice in `workdir/spec/phase16-first-slice.md`
  - `[done]` implement the `Knowledge Taxonomy And Catalog` slice
  - `[done]` validate the `Knowledge Taxonomy And Catalog` slice end-to-end in `workdir/spec/phase16-knowledge-taxonomy-catalog-validation.md`
  - `[done]` assess `Phase 16` completion against its declared goal and exit criteria in `workdir/spec/phase16-assessment.md`

## Phase 17. Agent Runtime Integration

- Status: `[complete]`
- Goal: connect the already-built deterministic session skeleton to a real agent execution model with persistent long-runners where they create value and one-shot workers where they do not
- Exit criteria:
  - the current runtime boundary is documented precisely
  - old agent flows are classified into deterministic control, long-runners, and one-shot workers
  - the persistent agent directory model is defined
  - the first concrete agent-runtime implementation slice is chosen
- Notes:
  - this phase exists because the system is already structurally strong, but still cannot honestly claim full agent-backed execution for iterative roles
- Remaining:
  - `[done]` choose the next named implementation phase after `Phase 16` in `workdir/spec/phase17-direction.md`
  - `[done]` write the as-is technical description in `workdir/spec/agent-runtime-as-is.md`
  - `[done]` write the old-to-new mapping plan in `workdir/spec/agent-runtime-mapping-plan.md`
  - `[done]` choose the first concrete `Phase 17` slice in `workdir/spec/phase17-first-slice.md`
  - `[done]` implement the `Persistent Role Workspace Contract` slice
  - `[done]` validate the `Persistent Role Workspace Contract` slice end-to-end in `workdir/spec/phase17-persistent-role-workspace-validation.md`
  - `[done]` choose the next `Phase 17` slice in `workdir/spec/phase17-next-slice.md`
  - `[done]` implement the `Reviewer Long-Runner Pilot` slice
  - `[done]` validate the `Reviewer Long-Runner Pilot` slice end-to-end in `workdir/spec/phase17-reviewer-long-runner-validation.md`
  - `[done]` choose the next `Phase 17` slice in `workdir/spec/phase17-next-after-reviewer.md`
  - `[done]` implement the `Implementer Long-Runner Pilot` slice
  - `[done]` validate the `Implementer Long-Runner Pilot` slice end-to-end in `workdir/spec/phase17-implementer-long-runner-validation.md`
  - `[done]` choose the next `Phase 17` slice in `workdir/spec/phase17-next-after-implementer.md`
  - `[done]` implement the `Verification-Coordinator Long-Runner Pilot` slice
  - `[done]` validate the `Verification-Coordinator Long-Runner Pilot` slice end-to-end in `workdir/spec/phase17-verification-long-runner-validation.md`
  - `[done]` choose the next `Phase 17` slice in `workdir/spec/phase17-next-after-verification.md`
  - `[done]` implement the `Agent Launcher Integration` slice
  - `[done]` validate the `Agent Launcher Integration` slice end-to-end in `workdir/spec/phase17-agent-launcher-validation.md`
  - `[done]` assess `Phase 17` completion in `workdir/spec/phase17-assessment.md`

## Phase 18. One-Shot Worker Integration

- Status: `[complete]`
- Goal: integrate a clean runtime model for narrow one-shot workers without regressing back to blind cold-start subagent orchestration
- Exit criteria:
  - the one-shot worker class is defined explicitly in the architecture
  - the first bounded one-shot worker slice is chosen
  - the selected slice is implemented and validated
- Notes:
  - this phase exists because the persistent-role runtime model is now real, but the bounded worker class from the old flow still needs a first-class place in the new architecture
- Remaining:
  - `[done]` choose the next named implementation phase after `Phase 17` in `workdir/spec/phase18-direction.md`
  - `[done]` choose the first concrete `Phase 18` slice in `workdir/spec/phase18-first-slice.md`
  - `[done]` implement and validate the `Story Spec One-Shot Worker` slice in `workdir/spec/phase18-story-spec-validation.md`
  - `[done]` withdraw the incorrect `Bug Analysis One-Shot Worker` follow-up in `workdir/spec/phase18-next-slice.md` and `workdir/spec/phase18-bug-analysis-validation.md`
  - `[done]` assess `Phase 18` completion in `workdir/spec/phase18-assessment.md`

## Phase 19. Unified Bug-Fix Runtime Alignment

- Status: `[done]`
- Goal: align the new runtime model with the updated unified `bug-fixer` semantics from the legacy bug flow
- Exit criteria:
  - the bug runtime role shape is decided explicitly
  - the chosen shape is implemented in the runtime
  - the resulting behavior matches the accepted `jira-bug` semantics closely enough to replace the old detached orchestration pattern
- Notes:
  - this phase exists because the detached `bug-analysis` helper model has now been explicitly rejected
- Remaining:
  - `[done]` choose the next named implementation phase after `Phase 18` in `workdir/spec/phase19-direction.md`
  - `[done]` choose the first concrete `Phase 19` slice in `workdir/spec/phase19-first-slice.md`
  - `[done]` implement the `Bug Runtime Role Decision` slice in `workdir/spec/phase19-bug-runtime-role-decision.md`
  - `[done]` implement and validate the `bug-fixer` long-runner pilot in `workdir/spec/phase19-bug-fixer-pilot-validation.md`
  - `[done]` choose the next `Phase 19` slice in `workdir/spec/phase19-next-slice.md`
  - `[done]` implement and validate the `Bug-Fixer Mode-Aware Handoffs` slice in `workdir/spec/phase19-bug-fixer-mode-aware-validation.md`
  - `[done]` assess `Phase 19` completion in `workdir/spec/phase19-assessment.md`

## Phase 20. Role Contract Alignment

- Status: `[done]`
- Goal: align persistent runtime roles with the accepted legacy agent contracts without changing the already-proven control plane
- Exit criteria:
  - the next role alignment target is chosen explicitly
  - the selected role contract is materially deepened in the runtime
  - the updated role contract is validated inside the current runtime model
- Notes:
  - this phase exists because runtime ownership is now largely solved, but durable role guidance still lags behind accepted legacy semantics
- Remaining:
  - `[done]` choose the next named implementation phase after `Phase 19` in `workdir/spec/phase20-direction.md`
  - `[done]` choose the first concrete `Phase 20` slice in `workdir/spec/phase20-first-slice.md`
  - `[done]` implement and validate the `Implementer Contract Alignment` slice in `workdir/spec/phase20-implementer-contract-validation.md`
  - `[done]` choose the next `Phase 20` slice in `workdir/spec/phase20-next-slice.md`
  - `[done]` implement and validate the `Code-Reviewer Contract Alignment` slice in `workdir/spec/phase20-code-reviewer-contract-validation.md`
  - `[done]` choose the next `Phase 20` slice in `workdir/spec/phase20-next-after-reviewer.md`
  - `[done]` implement and validate the `Verification-Coordinator Contract Alignment` slice in `workdir/spec/phase20-verification-contract-validation.md`
  - `[done]` assess `Phase 20` completion in `workdir/spec/phase20-assessment.md`

## Phase 21. Real Agent Launcher And End-to-End Runtime Proof

- Status: `[done]`
- Goal: back the persistent role launcher contract with a real agent executable model and prove the first end-to-end runtime path
- Exit criteria:
  - the next launcher-integration target is chosen explicitly
  - persistent roles can start through a real launcher bootstrap
  - the resulting runtime path is validated end-to-end
- Notes:
  - this phase exists because orchestration, persistence, and core role contracts are now strong enough; the main unresolved gap is real agent execution behind the launcher contract
- Remaining:
  - `[done]` choose the next named implementation phase after `Phase 20` in `workdir/spec/phase21-direction.md`
  - `[done]` choose the first concrete `Phase 21` slice in `workdir/spec/phase21-first-slice.md`
  - `[done]` implement and validate the `Real Launcher Bootstrap For Persistent Roles` slice in `workdir/spec/phase21-real-launcher-validation.md`
  - `[done]` choose the next `Phase 21` slice in `workdir/spec/phase21-next-slice.md`
  - `[done]` implement and validate the `End-to-End Persistent Runtime Acceptance` slice in `workdir/spec/phase21-e2e-runtime-validation.md`
  - `[done]` assess `Phase 21` completion in `workdir/spec/phase21-assessment.md`

## Phase 22. Live Operator Acceptance And Workflow Validation

- Status: `[done]`
- Goal: prove the assembled system on a real operator-driven workflow path
- Exit criteria:
  - the first live acceptance scenario is chosen explicitly
  - the scenario is executed through the real operator surface
  - the outcome is recorded with concrete findings and follow-up actions
- Notes:
  - this phase exists because architecture, runtime, and automated acceptance are now strong enough; the remaining gap is live product-level proof
- Remaining:
  - `[done]` choose the next named implementation phase after `Phase 21` in `workdir/spec/phase22-direction.md`
  - `[done]` choose the first concrete `Phase 22` slice in `workdir/spec/phase22-first-slice.md`
  - `[done]` implement and validate the `Happy-Path Task Session Acceptance` slice in `workdir/spec/phase22-happy-path-validation.md`
  - `[done]` assess `Phase 22` completion in `workdir/spec/phase22-assessment.md`

## Phase 23. Advanced Operator Acceptance

- Status: `[done]`
- Goal: validate more realistic operator-driven lifecycle branches beyond the basic happy path
- Exit criteria:
  - the next advanced operator acceptance scenario is chosen explicitly
  - the scenario is executed through a reproducible operator acceptance harness
  - the outcome is recorded with concrete lifecycle findings
- Notes:
  - this phase exists because the basic happy path is now proven; the next strongest signal comes from advanced lifecycle acceptance
- Remaining:
  - `[done]` choose the next named implementation phase after `Phase 22` in `workdir/spec/phase23-direction.md`
  - `[done]` choose the first concrete `Phase 23` slice in `workdir/spec/phase23-first-slice.md`
  - `[done]` implement and validate the `Follow-Up Reopen Acceptance` slice in `workdir/spec/phase23-followup-reopen-validation.md`
  - `[done]` assess `Phase 23` completion in `workdir/spec/phase23-assessment.md`

## Phase 24. Delivery Acceptance

- Status: `[done]`
- Goal: validate the delivery boundary through the operator surface
- Exit criteria:
  - the first delivery acceptance scenario is chosen explicitly
  - the scenario is executed through a reproducible operator acceptance harness
  - the outcome is recorded with concrete delivery findings
- Notes:
  - this phase exists because the internal lifecycle and reopen paths are already acceptance-tested; the next remaining user-facing branch is the delivery path
- Remaining:
  - `[done]` choose the next named implementation phase after `Phase 23` in `workdir/spec/phase24-direction.md`
  - `[done]` choose the first concrete `Phase 24` slice in `workdir/spec/phase24-first-slice.md`
  - `[done]` implement and validate the `MR + Send-To-Test Delivery Acceptance` slice in `workdir/spec/phase24-delivery-validation.md`
  - `[done]` assess `Phase 24` completion in `workdir/spec/phase24-assessment.md`

## Phase 25. MR Feedback Acceptance

- Status: `[done]`
- Goal: validate the MR feedback loop through the operator surface
- Exit criteria:
  - the first MR-feedback acceptance scenario is chosen explicitly
  - the scenario is executed through a reproducible operator acceptance harness
  - the outcome is recorded with concrete MR-follow-up findings
- Notes:
  - this phase exists because MR feedback is the last major operator-visible lifecycle branch not yet covered by reproducible acceptance tooling
- Remaining:
  - `[done]` choose the next named implementation phase after `Phase 24` in `workdir/spec/phase25-direction.md`
  - `[done]` choose the first concrete `Phase 25` slice in `workdir/spec/phase25-first-slice.md`
  - `[done]` implement and validate the `MR Comment Follow-Up Acceptance` slice in `workdir/spec/phase25-mr-followup-validation.md`
  - `[done]` assess `Phase 25` completion in `workdir/spec/phase25-assessment.md`

## Phase 26. One-Shot Worker Launcher Parity

- Status: `[done]`
- Goal: bring one-shot workers to credible launcher/runtime parity with the persistent runtime model
- Exit criteria:
  - the first one-shot worker parity target is chosen explicitly
  - the selected worker uses the real launcher model credibly
  - bounded launch / execute / exit behavior is validated
- Notes:
  - this phase exists because one-shot workers still lag behind the persistent runtime path in runtime credibility
- Remaining:
  - `[done]` choose the next named implementation phase after `Phase 25` in `workdir/spec/phase26-direction.md`
  - `[done]` choose the first concrete `Phase 26` slice in `workdir/spec/phase26-first-slice.md`
  - `[done]` implement and validate the `Story Spec Worker Launcher Parity` slice in `workdir/spec/phase26-story-spec-parity-validation.md`
  - `[done]` assess `Phase 26` completion in `workdir/spec/phase26-assessment.md`

## Phase 27. Specialized Role Fidelity

- Status: `[done]`
- Goal: deepen the highest-value remaining specialized role contracts inside the proven runtime model
- Exit criteria:
  - the first specialized role fidelity target is chosen explicitly
  - that role contract is materially deepened
  - the deeper role contract is validated inside the current runtime/workflow model
- Notes:
  - this phase exists because the remaining highest-value gaps are now role-specific rather than structural
- Remaining:
  - `[done]` choose the next named implementation phase after `Phase 26` in `workdir/spec/phase27-direction.md`
  - `[done]` choose the first concrete `Phase 27` slice in `workdir/spec/phase27-first-slice.md`
  - `[done]` implement the `Bug-Fixer Contract Deepening` slice
  - `[done]` validate the `Bug-Fixer Contract Deepening` slice
  - `[done]` assess `Phase 27` completion in `workdir/spec/phase27-assessment.md`

## Phase 28. Planning Worker Expansion

- Status: `[done]`
- Goal: expand the bounded one-shot planning/helper side of the runtime after the first worker parity proof and the specialized bug-fixer alignment
- Exit criteria:
  - the first bounded planning/helper target is chosen explicitly
  - that helper is implemented through the current one-shot worker launcher model
  - the expanded planning/helper path is validated inside the story-planning workflow
- Notes:
  - this phase broadens bounded helpers without undoing the accepted distinction between persistent long-runners and one-shot workers
- Remaining:
  - `[done]` choose the next named implementation phase after `Phase 27` in `workdir/spec/phase28-direction.md`
  - `[done]` choose the first concrete `Phase 28` slice in `workdir/spec/phase28-first-slice.md`
  - `[done]` implement the `Proposal And Context Worker Split` slice
  - `[done]` validate the `Proposal And Context Worker Split` slice
  - `[done]` assess `Phase 28` completion in `workdir/spec/phase28-assessment.md`

## Phase 29. Story Planning Decomposition

- Status: `[done]`
- Goal: continue splitting the remaining broad story-planning work into bounded one-shot helpers
- Exit criteria:
  - the next bounded story-planning helper target is chosen explicitly
  - that helper is implemented in the current one-shot worker model
  - the deeper story-planning chain is validated
- Notes:
  - this phase continues planning-worker broadening without undoing the accepted runtime distinction between long-runners and one-shot workers
- Remaining:
  - `[done]` choose the next named implementation phase after `Phase 28` in `workdir/spec/phase29-direction.md`
  - `[done]` choose the first concrete `Phase 29` slice in `workdir/spec/phase29-first-slice.md`
  - `[done]` implement the `Requirements Clarifier Worker` slice
  - `[done]` validate the `Requirements Clarifier Worker` slice
  - `[done]` assess `Phase 29` completion in `workdir/spec/phase29-assessment.md`

## Phase 30. Planning Helper Expansion Continuation

- Status: `[done]`
- Goal: continue broadening bounded planning helpers after proposal/context and requirements decomposition
- Exit criteria:
  - the next bounded planning helper target is chosen explicitly
  - that helper is implemented in the current one-shot worker model
  - the broader planning chain is validated
- Notes:
  - this phase continues planning-helper broadening without changing the accepted runtime split between long-runners and one-shot workers
- Remaining:
  - `[done]` choose the next named implementation phase after `Phase 29` in `workdir/spec/phase30-direction.md`
  - `[done]` choose the first concrete `Phase 30` slice in `workdir/spec/phase30-first-slice.md`
  - `[done]` implement the `Acceptance Criteria Worker` slice
  - `[done]` validate the `Acceptance Criteria Worker` slice
  - `[done]` assess `Phase 30` completion in `workdir/spec/phase30-assessment.md`

## Phase 31. Planning Constraints Decomposition

- Status: `[in_progress]`
- Goal: continue narrowing the remaining final story-planning step by extracting explicit constraints into a bounded helper
- Exit criteria:
  - the next bounded planning helper target is chosen explicitly
  - that helper is implemented in the current one-shot worker model
  - the broader planning chain is validated
- Notes:
  - this phase keeps broadening planning helpers without changing the accepted runtime split between long-runners and one-shot workers
- Remaining:
  - `[done]` choose the next named implementation phase after `Phase 30` in `workdir/spec/phase31-direction.md`
  - `[done]` choose the first concrete `Phase 31` slice in `workdir/spec/phase31-first-slice.md`
  - `[done]` implement the `Constraints Worker` slice
  - `[done]` validate the `Constraints Worker` slice in `workdir/spec/phase31-constraints-validation.md`
  - `[done]` assess `Phase 31` completion in `workdir/spec/phase31-assessment.md`

## Phase 32. Planning Verification Before Coding

- Status: `[in_progress]`
- Goal: insert a bounded verification step for the assembled planning package before the final coding handoff
- Exit criteria:
  - the next bounded planning helper after constraints is chosen explicitly
  - a planning-verification helper is implemented in the one-shot worker model
  - the broader planning chain remains coherent after the extra verification step
- Remaining:
  - `[done]` choose the next named implementation phase after `Phase 31` in `workdir/spec/phase32-direction.md`
  - `[done]` choose the first concrete `Phase 32` slice in `workdir/spec/phase32-first-slice.md`
  - `[done]` implement the `Spec Verifier Worker` slice
  - `[done]` validate the `Spec Verifier Worker` slice in `workdir/spec/phase32-spec-verifier-validation.md`
  - `[done]` assess `Phase 32` completion in `workdir/spec/phase32-assessment.md`

## Phase 33. Planning Decomposition Before Execution

- Status: `[in_progress]`
- Goal: make decomposition explicit before execution starts so the verified planning package can feed downstream subtask work more directly
- Exit criteria:
  - the next bounded helper after planning verification is chosen explicitly
  - a decomposition-oriented helper or equivalent step is implemented
  - the broader planning and subtask chain remains coherent after the new step
- Remaining:
  - `[done]` choose the next named implementation phase after `Phase 32` in `workdir/spec/phase33-direction.md`
  - `[done]` choose the first concrete `Phase 33` slice in `workdir/spec/phase33-first-slice.md`
  - `[done]` implement the `Task Decomposer Worker` slice
  - `[done]` validate the `Task Decomposer Worker` slice in `workdir/spec/phase33-task-decomposer-validation.md`
  - `[done]` assess `Phase 33` completion in `workdir/spec/phase33-assessment.md`

## Phase 34. Decomposition-To-Subtask Graph Integration

- Status: `[in_progress]`
- Goal: make the new decomposition output a more explicit upstream input to the subtask graph and execution path
- Exit criteria:
  - the next concrete integration slice after explicit decomposition is chosen
  - decomposition output influences the subtask graph path more directly than before
  - the richer integration preserves the current bounded-control model
- Remaining:
  - `[done]` choose the next named implementation phase after `Phase 33` in `workdir/spec/phase34-direction.md`
  - `[done]` choose the first concrete `Phase 34` slice in `workdir/spec/phase34-first-slice.md`
  - `[done]` implement the `Decomposition-Aware Subtask Graph Start` slice
  - `[done]` validate the `Decomposition-Aware Subtask Graph Start` slice in `workdir/spec/phase34-decomposition-subtask-validation.md`
  - `[done]` assess `Phase 34` completion in `workdir/spec/phase34-assessment.md`

## Phase 35. Planning Artifact Surfacing And Visibility

- Status: `[complete]`
- Goal: make the richer planning chain easier for operators to inspect as one coherent package
- Exit criteria:
  - the first visibility-focused slice for the planning chain is chosen
  - planning summaries or artifact surfacing improve operator understanding of the chain
  - the richer visibility does not change current lifecycle semantics
- Remaining:
  - `[done]` choose the next named implementation phase after `Phase 34` in `workdir/spec/phase35-direction.md`
  - `[done]` choose the first concrete `Phase 35` slice in `workdir/spec/phase35-first-slice.md`
  - `[done]` implement the `Planning Chain Summary Surface` slice
  - `[done]` validate the `Planning Chain Summary Surface` slice
  - `[done]` assess `Phase 35` completion in `workdir/spec/phase35-assessment.md`

## Phase 36. Subtask Lifecycle Synchronization And Operator Surfaces

- Status: `[complete]`
- Goal: make the story subtask lane observable, synchronized, and operator-safe through explicit contracts and controls
- Exit criteria:
  - the first subtask-surface slice is chosen
  - created Jira subtasks, subtask graph state, and queue progression become explicit operator surfaces
  - refreshed snapshot state can safely reconcile the remaining local subtask lane
  - the richer subtask loop is acceptance-covered
- Remaining:
  - `[done]` choose the next named implementation phase after `Phase 35` in `workdir/spec/phase36-direction.md`
  - `[done]` choose the first concrete `Phase 36` slice in `workdir/spec/phase36-first-slice.md`
  - `[done]` implement the `Subtask Graph Status Panel` slice
  - `[done]` validate the `Subtask Graph Status Panel` slice
  - `[done]` implement and validate the broader subtask synchronization/operator surfaces
  - `[done]` assess `Phase 36` completion in `workdir/spec/phase36-assessment.md`

## Phase 37. Live Task Runtime Acceptance

- Status: `[complete_with_deferred_items]`
- Goal: validate the assembled runtime against a realistic task-shaped operator flow rather than only bounded fake-adapter slices
- Exit criteria:
  - the next named runtime-acceptance phase is chosen
  - the first concrete live-acceptance slice is chosen
  - a realistic task-shaped runtime acceptance pass is executed and documented
- Remaining:
  - `[done]` choose the next named implementation phase after `Phase 36` in `workdir/spec/phase37-direction.md`
  - `[done]` choose the first concrete `Phase 37` slice in `workdir/spec/phase37-first-slice.md`
  - `[done]` implement and run the `Real Story Session Acceptance` slice
  - `[done]` document the acceptance result in `workdir/spec/phase37-real-story-runtime-validation.md`
  - `[done]` assess `Phase 37` completion in `workdir/spec/phase37-assessment.md`

## Phase 38. Bug Runtime Acceptance

- Status: `[complete_with_deferred_items]`
- Goal: validate the unified `bug-fixer` runtime path through a realistic bug-shaped operator flow
- Exit criteria:
  - the next named acceptance phase after `Phase 37` is chosen
  - the first concrete bug-shaped acceptance slice is chosen
  - at least one realistic bug-shaped runtime pass is executed and documented
- Remaining:
  - `[done]` choose the next named implementation phase after `Phase 37`
  - `[done]` choose the first concrete `Phase 38` slice
  - `[done]` implement and run the `Real Bug Session Acceptance` slice
  - `[done]` document the acceptance result and resulting operational gaps
  - `[done]` assess `Phase 38` completion in `workdir/spec/phase38-assessment.md`

## Phase 39. Operator Recovery Runtime Acceptance

- Status: `[complete_with_deferred_items]`
- Goal: validate operator recovery behavior under the launcher-backed persistent runtime model
- Exit criteria:
  - the next named acceptance phase after `Phase 38` is chosen
  - the first concrete recovery acceptance slice is chosen
  - at least one launcher-backed recovery path is executed and documented
- Remaining:
  - `[done]` choose the next named implementation phase after `Phase 38`
  - `[done]` choose the first concrete `Phase 39` slice
  - `[done]` implement and run the `Escalation And Resume Acceptance` slice
  - `[done]` document the acceptance result and resulting operational gaps
  - `[done]` assess `Phase 39` completion in `workdir/spec/phase39-assessment.md`

## Phase 40. MR Follow-Up Runtime Acceptance

- Status: `[complete_with_deferred_items]`
- Goal: validate launcher-backed MR-comment reopen behavior through a realistic follow-up runtime flow
- Exit criteria:
  - the next named acceptance phase after `Phase 39` is chosen
  - the first concrete MR follow-up acceptance slice is chosen
  - at least one launcher-backed MR follow-up runtime pass is executed and documented
- Remaining:
  - `[done]` choose the next named implementation phase after `Phase 39`
  - `[done]` choose the first concrete `Phase 40` slice
  - `[done]` implement and run the `Real MR Follow-Up Runtime Acceptance` slice
  - `[done]` document the acceptance result and resulting operational gaps
  - `[done]` assess `Phase 40` completion in `workdir/spec/phase40-assessment.md`

## Phase 41. Live Agent Process Validation

- Status: `[complete_with_deferred_items]`
- Goal: validate real launched agent processes inside the persistent runtime contract
- Exit criteria:
  - the next named phase after `Phase 40` is chosen
  - the first concrete live-agent validation slice is chosen
  - at least one real launched persistent role process is validated and documented
- Remaining:
  - `[done]` choose the next named implementation phase after `Phase 40`
  - `[done]` choose the first concrete `Phase 41` slice
  - `[done]` implement and run the `Implementer Live Runtime Smoke` slice
  - `[done]` document the validation result and resulting operational gaps
  - `[done]` assess `Phase 41` completion in `workdir/spec/phase41-assessment.md`

## Phase 42. Authenticated Live Agent Execution

- Status: `[complete_with_deferred_items]`
- Goal: validate repeated routed work against real launched agents
- Exit criteria:
  - the next named phase after `Phase 41` is chosen
  - the first concrete authenticated live-agent slice is chosen
  - at least one multi-round live role path is executed and documented
- Remaining:
  - `[done]` choose the next named implementation phase after `Phase 41`
  - `[done]` choose the first concrete `Phase 42` slice
  - `[done]` implement and run the `Live Agent Readiness Probe` groundwork slice
  - `[done]` document readiness results and environmental blockers in `workdir/spec/phase42-live-agent-readiness-validation.md`
  - `[done]` remove the live multi-line paste transport by materializing routed work into `ROUTED_WORK.md`
  - `[done]` implement and run the `Real Launcher File Handoff Probe` slice
  - `[done]` document file-handoff results in `workdir/spec/phase42-real-launcher-file-handoff-probe.md`
  - `[done]` implement and run the `Real Launcher Minimal Completion Probe` slice
  - `[done]` document minimal live completion in `workdir/spec/phase42-real-launcher-minimal-completion-probe.md`
  - `[done]` implement the `File-Based Result Contract` slice
  - `[done]` document file-based result behavior in `workdir/spec/phase42-file-based-result-contract.md`
  - `[done]` rerun real launcher-backed implementer validation through file-backed completion
  - `[done]` document the validation result in `workdir/spec/phase42-real-implementer-two-round-validation.md`
  - `[done]` assess `Phase 42` completion in `workdir/spec/phase42-assessment.md`

## Phase 43. Environment Setup, Doctor, And Permanent Documentation

- Status: `[in_progress]`
- Goal: produce the first durable environment tooling and later reconcile it into permanent docs
- Exit criteria:
  - the first concrete doctor slice is implemented and validated
  - the next concrete setup/docs slice is chosen
  - permanent documentation work is still deferred until implementation reconciliation
- Remaining:
  - `[done]` choose the first concrete `Phase 43` slice
  - `[done]` implement the `Environment Doctor Baseline` slice
  - `[done]` validate the `Environment Doctor Baseline` slice
  - `[done]` document the baseline in `workdir/spec/phase43-environment-doctor-baseline.md`
  - `[done]` expose the doctor baseline through backend/UI surface
  - `[done]` document the surface in `workdir/spec/phase43-doctor-surface.md`
  - `[done]` choose the next concrete `Phase 43` slice
  - `[done]` implement the `Bootstrap Guidance Baseline` slice
  - `[done]` validate the `Bootstrap Guidance Baseline` slice
  - `[done]` document the baseline in `workdir/spec/phase43-bootstrap-guidance-baseline.md`
  - `[pending]` choose the next concrete `Phase 43` slice

## Immediate Next Steps

1. `[done]` Complete the roadmap through `Phase 16. Knowledge Base Structure And Curation`.
2. `[done]` Open `Phase 17. Agent Runtime Integration`.
3. `[done]` Choose the first concrete `Phase 17` slice.
4. `[done]` Implement the `Persistent Role Workspace Contract` slice.
5. `[done]` Validate the `Persistent Role Workspace Contract` slice end-to-end.
6. `[done]` Choose the next `Phase 17` slice.
7. `[done]` Implement the `Reviewer Long-Runner Pilot` slice.
8. `[done]` Validate the `Reviewer Long-Runner Pilot` slice end-to-end.
9. `[done]` Choose the next `Phase 17` slice.
10. `[done]` Implement the `Implementer Long-Runner Pilot` slice.
11. `[done]` Validate the `Implementer Long-Runner Pilot` slice end-to-end.
12. `[done]` Choose the next `Phase 17` slice.
13. `[done]` Implement the `Verification-Coordinator Long-Runner Pilot` slice.
14. `[done]` Validate the `Verification-Coordinator Long-Runner Pilot` slice end-to-end.
15. `[done]` Choose the next `Phase 17` slice.
16. `[done]` Implement the `Agent Launcher Integration` slice.
17. `[done]` Validate the `Agent Launcher Integration` slice end-to-end.
18. `[done]` Assess `Phase 17` completion.
19. `[done]` Choose the next named implementation phase after `Phase 17`.
20. `[done]` Choose the first concrete `Phase 18` slice.
21. `[done]` Implement the `Story Spec One-Shot Worker` slice.
22. `[done]` Validate the `Story Spec One-Shot Worker` slice end-to-end.
23. `[done]` Correct the invalid `Bug Analysis One-Shot Worker` direction.
26. `[done]` Assess `Phase 18` completion.
27. `[done]` Choose the next named implementation phase after `Phase 18`.
28. `[done]` Choose the first concrete `Phase 19` slice.
29. `[done]` Implement the `Bug Runtime Role Decision` slice.
30. `[done]` Implement the `bug-fixer` long-runner pilot.
31. `[done]` Validate the `bug-fixer` long-runner pilot.
32. `[done]` Choose the next `Phase 19` slice.
33. `[done]` Implement the `Bug-Fixer Mode-Aware Handoffs` slice.
34. `[done]` Validate the `Bug-Fixer Mode-Aware Handoffs` slice.
35. `[done]` Assess `Phase 19` completion.
36. `[done]` Choose the next named implementation phase after `Phase 19`.
37. `[done]` Choose the first concrete `Phase 20` slice.
38. `[done]` Implement the `Implementer Contract Alignment` slice.
39. `[done]` Validate the `Implementer Contract Alignment` slice.
40. `[done]` Choose the next `Phase 20` slice.
41. `[done]` Implement the `Code-Reviewer Contract Alignment` slice.
42. `[done]` Validate the `Code-Reviewer Contract Alignment` slice.
43. `[done]` Choose the next `Phase 20` slice.
44. `[done]` Implement the `Verification-Coordinator Contract Alignment` slice.
45. `[done]` Validate the `Verification-Coordinator Contract Alignment` slice.
46. `[done]` Assess `Phase 20` completion.
47. `[done]` Choose the next named implementation phase after `Phase 20`.
48. `[done]` Choose the first concrete `Phase 21` slice.
49. `[done]` Implement the `Real Launcher Bootstrap For Persistent Roles` slice.
50. `[done]` Validate the `Real Launcher Bootstrap For Persistent Roles` slice.
51. `[done]` Choose the next `Phase 21` slice.
52. `[done]` Implement the `End-to-End Persistent Runtime Acceptance` slice.
53. `[done]` Validate the `End-to-End Persistent Runtime Acceptance` slice.
54. `[done]` Assess `Phase 21` completion.
55. `[done]` Choose the next named implementation phase after `Phase 21`.
56. `[done]` Choose the first concrete `Phase 22` slice.
57. `[done]` Implement the `Happy-Path Task Session Acceptance` slice.
58. `[done]` Validate the `Happy-Path Task Session Acceptance` slice.
59. `[done]` Assess `Phase 22` completion.
60. `[done]` Choose the next named implementation phase after `Phase 22`.
61. `[done]` Choose the first concrete `Phase 23` slice.
62. `[done]` Implement the `Follow-Up Reopen Acceptance` slice.
63. `[done]` Validate the `Follow-Up Reopen Acceptance` slice.
64. `[done]` Assess `Phase 23` completion.
65. `[done]` Choose the next named implementation phase after `Phase 23`.
66. `[done]` Choose the first concrete `Phase 24` slice.
67. `[done]` Implement the `MR + Send-To-Test Delivery Acceptance` slice.
68. `[done]` Validate the `MR + Send-To-Test Delivery Acceptance` slice.
69. `[done]` Assess `Phase 24` completion.
70. `[done]` Choose the next named implementation phase after `Phase 24`.
71. `[done]` Choose the first concrete `Phase 25` slice.
72. `[done]` Implement the `MR Comment Follow-Up Acceptance` slice.
73. `[done]` Validate the `MR Comment Follow-Up Acceptance` slice.
74. `[done]` Assess `Phase 25` completion.
75. `[done]` Choose the next named implementation phase after `Phase 25`.
76. `[done]` Choose the first concrete `Phase 26` slice.
77. `[done]` Implement the `Story Spec Worker Launcher Parity` slice.
78. `[done]` Validate the `Story Spec Worker Launcher Parity` slice.
79. `[done]` Assess `Phase 26` completion.
80. `[done]` Choose the next named implementation phase after `Phase 26`.
81. `[done]` Choose the first concrete `Phase 27` slice.
82. `[done]` Implement the `Bug-Fixer Contract Deepening` slice.
83. `[done]` Validate the `Bug-Fixer Contract Deepening` slice.
84. `[done]` Assess `Phase 27` completion.
85. `[done]` Choose the next named implementation phase after `Phase 27`.
86. `[done]` Choose the first concrete `Phase 28` slice.
87. `[done]` Implement the `Proposal And Context Worker Split` slice.
88. `[done]` Validate the `Proposal And Context Worker Split` slice.
89. `[done]` Assess `Phase 28` completion.
90. `[done]` Choose the next named implementation phase after `Phase 28`.
91. `[done]` Choose the first concrete `Phase 29` slice.
92. `[done]` Implement the `Requirements Clarifier Worker` slice.
93. `[done]` Validate the `Requirements Clarifier Worker` slice.
94. `[done]` Assess `Phase 29` completion.
95. `[done]` Choose the next named implementation phase after `Phase 29`.
96. `[done]` Choose the first concrete `Phase 30` slice.
97. `[done]` Implement the `Acceptance Criteria Worker` slice.
98. `[done]` Validate the `Acceptance Criteria Worker` slice.
99. `[done]` Assess `Phase 30` completion.
100. `[done]` Choose the next named implementation phase after `Phase 30`.
101. `[done]` Choose the first concrete `Phase 31` slice.
102. `[done]` Implement the `Constraints Worker` slice.
103. `[done]` Validate the `Constraints Worker` slice.
104. `[done]` Assess `Phase 31` completion.
105. `[done]` Choose the next named implementation phase after `Phase 31`.
106. `[done]` Choose the first concrete `Phase 32` slice.
107. `[done]` Implement the `Spec Verifier Worker` slice.
108. `[done]` Validate the `Spec Verifier Worker` slice.
109. `[done]` Assess `Phase 32` completion.
110. `[done]` Choose the next named implementation phase after `Phase 32`.
111. `[done]` Choose the first concrete `Phase 33` slice.
112. `[done]` Implement the `Task Decomposer Worker` slice.
113. `[done]` Validate the `Task Decomposer Worker` slice.
114. `[done]` Assess `Phase 33` completion.
115. `[done]` Choose the next named implementation phase after `Phase 33`.
116. `[done]` Choose the first concrete `Phase 34` slice.
117. `[done]` Implement the `Decomposition-Aware Subtask Graph Start` slice.
118. `[done]` Validate the `Decomposition-Aware Subtask Graph Start` slice.
119. `[done]` Assess `Phase 34` completion.
120. `[done]` Choose the next named implementation phase after `Phase 34`.
121. `[done]` Choose the first concrete `Phase 35` slice.
122. `[done]` Implement the `Planning Chain Summary Surface` slice.
123. `[done]` Validate the `Planning Chain Summary Surface` slice.
124. `[done]` Assess `Phase 35` completion.
125. `[done]` Choose the next named implementation phase after `Phase 35`.
126. `[done]` Choose the first concrete `Phase 36` slice.
127. `[done]` Implement the `Subtask Graph Status Panel` slice.
128. `[done]` Validate the `Subtask Graph Status Panel` slice.
129. `[done]` Implement and validate the broader subtask synchronization/operator surfaces.
130. `[done]` Assess `Phase 36` completion.
131. `[done]` Choose the next named implementation phase after `Phase 36`.
132. `[done]` Choose the first concrete `Phase 37` slice.
133. `[done]` Implement and run the `Real Story Session Acceptance` slice.
134. `[done]` Document the acceptance result and resulting operational gaps.
135. `[done]` Assess `Phase 37` completion.
136. `[done]` Choose the next named implementation phase after `Phase 37`.
137. `[done]` Choose the first concrete `Phase 38` slice.
138. `[done]` Implement and run the `Real Bug Session Acceptance` slice.
139. `[done]` Document the acceptance result and resulting operational gaps.
140. `[done]` Assess `Phase 38` completion.
141. `[done]` Choose the next named implementation phase after `Phase 38`.
142. `[done]` Choose the first concrete `Phase 39` slice.
143. `[done]` Implement and run the `Escalation And Resume Acceptance` slice.
144. `[done]` Document the acceptance result and resulting operational gaps.
145. `[done]` Assess `Phase 39` completion.
146. `[done]` Choose the next named implementation phase after `Phase 39`.
147. `[done]` Choose the first concrete `Phase 40` slice.
148. `[done]` Implement and run the `Real MR Follow-Up Runtime Acceptance` slice.
149. `[done]` Document the acceptance result and resulting operational gaps.
150. `[done]` Assess `Phase 40` completion.
151. `[done]` Choose the next named implementation phase after `Phase 40`.
152. `[done]` Choose the first concrete `Phase 41` slice.
153. `[done]` Implement and run the `Implementer Live Runtime Smoke` slice.
154. `[done]` Document the validation result and resulting operational gaps.
155. `[done]` Assess `Phase 41` completion.
156. `[done]` Choose the next named implementation phase after `Phase 41`.
157. `[done]` Choose the first concrete `Phase 42` slice.
158. `[done]` Implement and run the `Live Agent Readiness Probe` groundwork slice.
159. `[done]` Document readiness results and environmental blockers.
160. `[done]` Implement and run the `Implementer Two-Round Live Validation` slice.
161. `[done]` Document the validation result and resulting operational gaps.
162. `[done]` Implement the `Environment Doctor Baseline` slice.
163. `[done]` Validate the `Environment Doctor Baseline` slice.
164. `[done]` Expose the doctor baseline through backend/UI surface.
165. `[done]` Choose the next concrete `Phase 43` slice.
166. `[done]` Implement the `Bootstrap Guidance Baseline` slice.
167. `[done]` Validate the `Bootstrap Guidance Baseline` slice.
168. `[pending]` Choose the next concrete `Phase 43` slice.

## What Was Going Wrong

- We had roadmap and backlog documents, but no maintained status-driven execution file.
- Implementation started following "technically logical next step" rather than "next unchecked step in a tracked phase".
- Operator-recovery primitives started absorbing workflow-path questions that should instead live in session policy.
- Commits remained valid, but project control degraded.

## Structural Reference

- The canonical filesystem/runtime layout is fixed in `workdir/spec/filesystem-runtime-model.md`.
- Future runtime, knowledge, workspace, and temporary-path changes should align to that document rather than ad-hoc local assumptions.

## Control Rule From Now On

- New implementation work should start only from an unchecked item in this file.
- After each completed slice:
  - update this file
  - update `workdir/spec/progress-log.md`
  - commit the code slice
