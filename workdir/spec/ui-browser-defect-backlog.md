# UI Browser Defect Backlog

Source of truth for this backlog:

- live browser-driven inspection through `playwright-cli`
- working local UI/backend pair at the time of review:
  - UI: `http://127.0.0.1:4175`
  - backend: `http://127.0.0.1:8010`

This file intentionally captures product defects from rendered behavior first, not from code inspection.

## Progress Notes

- Completed in the latest browser-driven passes:
  - navigation copy shortened
  - `Start Session` happy path compressed
  - settings file-system path removed from the normal surface
  - health cards no longer expose runner binary paths in the normal path
  - loading state now uses session-aware language instead of a generic hydration blank
  - `Workflow Pulse` now distinguishes:
    - active now
    - standing by
    - waiting

- Still worth another dedicated pass:
  - selected-session detail should dominate the page more strongly than left-column run creation
  - queue cards still read as compressed metadata stacks
  - runtime/debug affordances still need a friendlier `Open Console` style entrypoint
  - health sidebar still duplicates some low-value summary copy
  - top-level and panel-level prose can still be trimmed further

## Workflow Runs

### 1. Start form is still too dense for the normal path

- What gets in the way
  - the main start form still shows several policy controls, explanatory paragraphs, a workflow summary card, and an advanced override entry before the primary action
- Why this is bad
  - the happy path still feels like configuration work instead of “start a run”
  - the operator has to read and decide too much before entering a task key
- Expected UX
  - the normal start path should be:
    - task key
    - workflow choice
    - one concise summary
    - primary action
  - optional policies should become a compact “tune this run” section, not the main form body

### 2. Session queue cards are still too compressed

- What gets in the way
  - queue cards read as tight stacks of `task key / status / profile / stage / owner`
  - in the accessibility snapshot the strings still effectively concatenate into a dense blob
- Why this is bad
  - the queue is harder to scan than it should be
  - “what matters now” does not jump out visually
- Expected UX
  - stronger queue card rhythm:
    - top line: task key + status
    - secondary line: workflow profile
    - metadata row: stage / owner
  - clearer spacing and stronger visual separation between cards

### 3. Top-level run state is weak during loading/hydration

- What gets in the way
  - the right side still shows a generic `Hydrating operator surface…`
  - selected session is already known in the sidebar while the main area still feels blank
- Why this is bad
  - it creates uncertainty about whether the session is loading correctly or the UI is broken
- Expected UX
  - a session-scoped loading state:
    - “Loading IOS-10000”
    - skeletons or partial preserved layout
  - avoid a generic empty-feeling panel once the app already knows what is selected

## Session Detail

### 1. Progress is still too abstract

- What gets in the way
  - the page shows:
    - status
    - stage
    - owner
    - roles
  - but still does not tell the operator clearly:
    - who is actively doing work right now
    - what exactly they are doing
    - what changed recently
- Why this is bad
  - the operator still cannot reliably answer:
    - “what is happening now?”
    - “is the system making progress?”
    - “which lane should I care about?”
- Expected UX
  - an explicit progress surface:
    - `Active now`
    - `Waiting`
    - `Blocked`
    - `Recent updates`
  - worker cards should describe live activity, not just lane existence

### 2. “Roles And Work” is cleaner, but still too shallow

- What gets in the way
  - role cards mostly say `Working`
  - work items often say `0`
- Why this is bad
  - the surface looks alive but still does not convey meaningful state
  - “Working” without context is only marginally better than raw runtime status
- Expected UX
  - role cards should say things like:
    - `Implementer: applying requested fixes`
    - `Verification Coordinator: waiting for implementer output`
  - if there is no work item, explain whether the lane is idle, waiting, or just not yet engaged

### 3. Runtime session is still too prominent in the normal path

- What gets in the way
  - `Runtime Session` remains a large main-path panel
  - stop/restart runtime controls are still visible before many truly operator-facing progress views exist
- Why this is bad
  - it suggests runtime control is a normal part of day-to-day operation
  - it steals attention from actual workflow understanding
- Expected UX
  - the normal session path should emphasize:
    - progress
    - blockers
    - next operator action
  - runtime controls should collapse further into a dedicated debug affordance

### 4. Raw debug affordances are still not operator-safe enough

- What gets in the way
  - advanced runtime groups still advertise `tmux` / debug semantics directly
  - there is no friendly debug action like `Open Worker Console`
- Why this is bad
  - operators still see implementation details instead of usable debug tools
- Expected UX
  - replace low-level attach semantics with:
    - `Open Worker Console`
    - `Open Runtime Debug`
    - `Copy Debug Command`
  - only reveal raw tmux commands on explicit demand

### 5. Artifact/history area is still too low-signal

- What gets in the way
  - `Artifacts And Events` still ends with a sparse low-value list when there are few artifacts
  - `Recent Events` gives identifiers but not enough human narrative
- Why this is bad
  - history exists, but it does not help the operator reconstruct what happened
- Expected UX
  - event history should favor human summaries like:
    - `Task started`
    - `Self-review requested`
    - `Verification blocked on operator input`

## Settings

### 1. Runtime defaults are improved but still read as a long policy sheet

- What gets in the way
  - three workflow blocks each repeat several policy selectors
  - all of them are visible at once
- Why this is bad
  - the surface still feels like a config matrix instead of a settings page
  - the operator has to visually parse too many similar controls
- Expected UX
  - either:
    - tab by workflow profile
    - accordion by workflow profile
    - or a smaller summary-first layout with explicit expand actions

### 2. Stored config path is still exposed in the normal settings path

- What gets in the way
  - `Stored in project config: /Users/.../settings.local.json`
- Why this is bad
  - this is internal file-system plumbing, not a normal operator concern
- Expected UX
  - hide the raw path from the normal surface
  - if needed, move it into an advanced/debug section

### 3. Shared knowledge empty state exists, but knowledge still lacks product structure

- What gets in the way
  - the panel is better, but the feature still looks like a passive store rather than an operator tool
- Why this is bad
  - it is not obvious when or why someone should use it
- Expected UX
  - clearer framing:
    - what belongs here
    - when to capture it
    - how it helps later sessions

## Health

### 1. Bootstrap guidance reports the wrong local stack URLs for the active reviewed instance

- What gets in the way
  - browser review was performed against `4175/8010`
  - the UI still shows `Backend: http://127.0.0.1:8000` and `UI: http://127.0.0.1:4173`
- Why this is bad
  - the health surface lies about the actual running local stack
  - this will send operators to the wrong place during debugging
- Expected UX
  - health/setup guidance must reflect the active runtime pair the operator is actually using

### 2. Capabilities still expose too much tool-installation detail in the main path

- What gets in the way
  - runner cards show binary paths like `/Users/.../claude` and `/opt/homebrew/bin/codex`
- Why this is bad
  - for most operators this is low-value implementation detail
  - it increases visual noise on a surface that should first answer “is the environment ready?”
- Expected UX
  - normal capability cards should show only:
    - runner name
    - availability
    - model catalog count
  - binary path belongs in advanced debug only

### 3. Health sidebar is useful, but still duplicates low-value content

- What gets in the way
  - the left `Health Scope` panel and the main content both describe the same concepts
- Why this is bad
  - the navigation column uses space that could be more focused on high-signal summary
- Expected UX
  - sidebar cards should be shorter and more status-driven
  - avoid repeating copy already visible in the main surface

## Navigation / Layout / Copy

### 1. Too many explanatory paragraphs remain in the primary surfaces

- What gets in the way
  - almost every panel starts with another explanatory paragraph
- Why this is bad
  - the UI still reads like documentation embedded into cards
  - it slows down visual scanning
- Expected UX
  - fewer paragraphs
  - more concise headings, pills, labels, and summaries
  - explanations only where the operator is likely to hesitate

### 2. Surface navigation cards are still verbose

- What gets in the way
  - each nav card contains a full sentence
- Why this is bad
  - navigation should be immediate, not explanatory prose
- Expected UX
  - shorter nav copy
  - clearer distinction between:
    - run work
    - defaults/settings
    - environment/debugging

### 3. Layout hierarchy still favors left-column setup over active work

- What gets in the way
  - start session and queue still dominate the left column even when a live session is selected
- Why this is bad
  - once a session is active, the operator’s attention should bias toward that session’s progress and actions
- Expected UX
  - selected-session work should visually dominate
  - starting a new run should remain available, but not compete equally with active session handling

### 4. Favicon/brand residual still creates visible noise in console and polish

- What gets in the way
  - browser still reports `favicon.ico 404`
- Why this is bad
  - low severity, but reinforces “unfinished internal tool” feeling
- Expected UX
  - either provide favicon or suppress that dead request path cleanly

## Highest-Pain Next Batch

The next implementation batch should prioritize:

1. `Session Detail`
  - make selected-session work dominate more strongly than the left column
  - replace remaining runtime/debug semantics with operator-safe debug actions
2. `Runs`
  - improve queue-card scanability and reduce compressed metadata blobs
3. `Health`
  - remove duplicated sidebar explanation and keep the page more status-driven
4. `Navigation / Copy`
  - keep trimming explanatory prose until the interface reads like a product surface rather than embedded documentation
