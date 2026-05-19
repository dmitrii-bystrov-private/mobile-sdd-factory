# UI Product Track Plan

## Goal

Bring the operator UI to a genuinely usable product state:

- functionally reliable
- understandable
- visually coherent
- convenient for everyday operator work
- validated through real browser-driven usage, not only code-level checks

This track is broader than fixing isolated bugs.
The target is a working operator product surface, not just a buildable frontend.

## Success Criteria

- local UI works end-to-end against the backend without `Failed to fetch`
- the main supported surfaces load and behave correctly:
  - sessions
  - runtime defaults
  - environment doctor
  - bootstrap guidance
  - runtime capabilities
- the interface has clear navigation and a sane information architecture
- settings are understandable and grouped by meaning
- session detail and operator actions are readable and usable
- layout is stable and does not visibly break or overlap
- dark theme is real and usable
- the main browser scenarios can be exercised and validated from a live browser session
- dense technical content is progressively translated into operator-facing language
- settings are not only visible, but actually usable and complete enough for day-to-day control
- high-frequency operator actions remain near the top of the relevant surface instead of being buried deep in long pages
- runtime and worker state are explained in operator terms rather than raw plumbing identifiers
- low-level implementation details such as tmux socket paths are either hidden, downgraded, or moved into explicit advanced/debug areas
- spacing, typography, card structure, labels, and action placement feel consistent across surfaces

## Expanded Product Quality Bar

The next pass should no longer treat the UI as "good enough because it works".
It should be judged against a stronger product bar:

- `Functional completeness`
  - important settings must actually let the operator control the system in a meaningful way
  - visible controls should have a clear supported purpose
- `Operator-first language`
  - labels, statuses, and descriptions should describe intent and consequence
  - raw internal implementation terms should not dominate the main path
- `Information density control`
  - long text blocks should be reduced, chunked, summarized, or progressively disclosed
  - high-signal information should appear first
- `Action locality`
  - actions the operator needs frequently should sit near the relevant state
  - low-frequency or risky actions should move to advanced/recovery/debug seams
- `Design consistency`
  - spacing, headings, pills, cards, controls, and empty states should follow a coherent system
- `Operator-safe abstraction`
  - advanced runtime/debug information may exist, but should not pollute the normal workflow surface

## Expanded Execution Model

The original phase plan remains valid, but it now needs a second layer:

1. improve the platform surface globally
2. then run a dedicated functional review for each major UI surface
3. then run cross-cutting design consistency passes
4. then revalidate through browser usage

This is necessary because the remaining issues are no longer only architectural.
They are now a mix of:

- surface-specific usability flaws
- weak operator language
- misplaced actions
- incomplete settings semantics
- design inconsistency between panels

## Functional Review Tracks

After the baseline architecture pass, each major surface should be reviewed independently.

### A. Workflow Runs Surface Review

Questions:

- Is the "start session" path concise enough for normal use?
- Are advanced controls hidden until actually needed?
- Is the session list readable at a glance?
- Is the selected session summary high-signal enough?
- Are the most common actions visible near the state they affect?

Typical defects to hunt:

- overlong start forms
- weak session summaries
- buried actions
- noisy cards
- technical wording in the main operator path

### B. Session Detail Surface Review

Questions:

- Can an operator understand current stage, owner, blockers, and next action in seconds?
- Are worker statuses understandable without knowing backend implementation details?
- Are runtime panels helping or just leaking internals?
- Are panels ordered by operator importance rather than by implementation source?

Typical defects to hunt:

- unclear worker status semantics
- raw stage / role / runtime language
- tmux/runtime debug details shown too prominently
- long scrolls before reaching relevant actions
- low-priority panels placed ahead of operationally critical ones

### C. Settings Surface Review

Questions:

- Which settings are truly day-to-day?
- Which are advanced per-role overrides?
- Which current controls are incomplete or misleading?
- Are defaults understandable as product behavior, not config storage?

Typical defects to hunt:

- incomplete settings
- controls whose effect is unclear
- long role-by-role dumps
- lack of distinction between project default, session override, and runtime baseline

### D. Health Surface Review

Questions:

- Does this page help an operator act, or just display diagnostics?
- Is there a clear distinction between healthy state, warning state, and actionable failure?
- Are bootstrap and doctor outputs concise enough?

Typical defects to hunt:

- verbose diagnostics without prioritization
- too much raw runtime detail
- unclear next steps
- poor hierarchy between healthy information and actionable warnings

### E. Cross-Surface Navigation Review

Questions:

- Is it always obvious where the user is?
- Is the difference between `Runs`, `Settings`, and `Health` consistently reinforced?
- Are there any important functions stranded on the wrong surface?

Typical defects to hunt:

- duplicate concepts on multiple surfaces
- misplaced actions
- navigation labels that are technically correct but not product-clear

## Cross-Cutting Cleanup Tracks

These should be revisited after each functional review pass.

### 1. Text Density Reduction

Target:

- replace portyanky of prose with:
  - short summaries
  - chunked sections
  - progressive disclosure
  - stronger labels with fewer explanatory paragraphs

### 2. Status Language Rewrite

Target:

- make session, worker, and blocker states readable in operator terms
- distinguish clearly between:
  - active work
  - waiting for operator
  - blocked on environment/runtime
  - completed

### 3. Action Placement Audit

Target:

- move high-frequency actions upward
- keep destructive/debug actions out of the main workflow line
- colocate actions with the state they operate on

### 4. Runtime Plumbing Containment

Target:

- remove or demote raw technical details like:
  - tmux socket paths
  - runtime handles
  - low-level role plumbing identifiers
- keep them only where advanced debugging genuinely needs them

### 5. Design Consistency Pass

Target:

- unify paddings, spacing, control heights, panel rhythm, metric cards, badges, empty states, and disclosure components
- eliminate splayed / sticky / uneven clusters of controls

## Execution Order

### 1. Stabilize

Remove technical blockers that make the UI impossible to evaluate honestly.

Scope:

- fix local dev integration
- fix backend/UI connectivity
- remove `Failed to fetch` startup state
- ensure the browser can actually load supported data surfaces

Expected result:

- local backend + UI start reliably
- browser-driven audit becomes possible

### 2. Information Architecture

Restructure the UI so it is no longer one overloaded surface with mixed concerns.

Scope:

- separate workflow execution from settings and environment surfaces
- introduce clear top-level navigation
- reduce the amount of unrelated configuration and diagnostics shown in the same visual area

Expected result:

- the operator understands where to go for:
  - runs
  - settings
  - health / environment
  - optionally knowledge later

### 3. Settings Surface

Turn runtime defaults and workflow defaults into a real settings experience.

Scope:

- group settings by purpose
- explain what is global vs session-local
- remove the feeling of random raw config fragments
- make defaults readable and editable as product features, not internal plumbing

Expected result:

- settings are understandable
- the operator can confidently change defaults without reading backend code

### 4. Session UX

Improve the main working session surface.

Scope:

- better summary of current state
- cleaner grouping of panels
- clearer stage / owner / status presentation
- better operator action presentation
- better empty / loading / error states

Expected result:

- selected sessions are easy to understand quickly
- the operator is not forced to scan noisy or weakly grouped panels

### 5. Visual System

Make the interface visually coherent and suitable for everyday use.

Scope:

- real dark theme
- consistent spacing and alignment
- stable panel layout
- no overlapping or broken controls
- stronger typography and clearer hierarchy
- responsive behavior that still feels intentional

Expected result:

- the UI stops feeling like a rough internal tool
- visual quality matches the supported-platform ambition

### 6. Browser-Driven Audit

After each major slice, validate the UI through real browser usage.

Scope:

- open the UI in a browser
- inspect the real rendered state
- exercise the main workflows
- capture real UX defects instead of relying only on code inspection

Core scenarios:

- open UI
- create session
- inspect selected session
- inspect settings
- inspect health/doctor/bootstrap surfaces
- exercise operator actions where appropriate

Expected result:

- regressions and usability problems are found through actual interaction

### 7. Regression Guard

Once the UI stabilizes, protect the most important flows.

Scope:

- add a small set of browser-based smoke scenarios
- keep the supported operator UI from regressing silently

Expected result:

- the most important operator flows have repeatable validation

## Working Principle

Do not jump directly into cosmetic fixes.

The preferred order is:

1. stabilize the product path
2. improve structure and navigation
3. improve settings semantics
4. improve session usability
5. improve visual design
6. validate in a live browser
7. lock key flows with regression checks

## Current Priority

Start with:

1. Stabilize
2. Information Architecture
3. Settings Surface

Only after that move into the broader visual redesign layer.

## Progress Snapshot

Completed in the current UI product pass:

- `Stabilize`
  - local backend/UI connectivity works end-to-end
  - CORS no longer blocks local browser usage
  - Vite local port is strict, so launcher URLs stay honest
  - real browser validation is now possible without `Failed to fetch`
- `Information Architecture`
  - top-level navigation is now split into `Workflow Runs`, `Settings`, and `Health`
  - sidebar content is contextual instead of showing the same overloaded stack on every surface
- `Settings Surface`
  - project defaults are separated from session-local runtime overrides
  - advanced role overrides are moved behind disclosure instead of dominating the default screen
- `Session UX`
  - session start flow is simplified and summarized before advanced knobs
  - session execution remains on the `Runs` surface instead of being mixed with settings/health
- `Visual System`
  - dark theme and panel styling were upgraded from rough internal-tool defaults to a coherent baseline
- `Browser-Driven Audit`
  - live browser checks were used to validate runs/settings/health surfaces
- `Regression Guard`
  - browser smoke now exists for the main supported UI surfaces and is wired into the `--live` supported test rail

Known residuals for later passes:

- `SessionDetail` is functional, but still dense and can be simplified further
- `Runtime Defaults` is much better structured, but the role-baseline area is still inherently expert-facing
- favicon/brand polish is still low priority compared with workflow usability

Completed after the initial milestone:

- `Session Detail Surface Review`
  - current focus, owner, stage, and operator actions are now promoted above lower-priority runtime traces
  - worker/runtime surfaces are reordered around operator comprehension instead of backend implementation order
- `Settings Surface Review`
  - workflow defaults use product-facing labels instead of raw enum ids
  - shared knowledge has an explicit empty state and less raw metadata noise
  - advanced lane overrides stay available, but are visibly separated from daily defaults
- `Health Surface Review`
  - doctor/bootstrap/capabilities now lead with actionable summaries
  - required attention is separated from optional warnings
  - model catalogs and role baselines are contained behind advanced disclosure
- `Text Density Reduction`
  - several long explanatory blocks were shortened or moved behind progressive disclosure
- `Status Language Rewrite`
  - session, work-item, and runtime labels now use shorter operator-facing wording
- `Runtime Plumbing Containment`
  - low-level tmux/runtime details and cleanup controls are now demoted into advanced/debug seams

Residuals that still deserve another pass later:

- the session detail surface can still be shortened further, especially around artifact/history-heavy panels
- the visual system is now coherent, but still not polished enough to count as final product-grade design
- some advanced settings remain necessarily expert-facing because they expose lane-level baseline control
- browser-driven review should continue to drive the next defects list rather than relying on code inspection alone

## Updated Next Priority

The next serious pass should focus on:

1. `Action Placement Audit`
2. `Cross-Surface Navigation Review`
3. additional `Session Detail` simplification
4. follow-up browser-driven UX review

Only after these should broader visual polish continue, because the remaining problems are now mostly about usability, hierarchy, and operator comprehension rather than simple theming.
