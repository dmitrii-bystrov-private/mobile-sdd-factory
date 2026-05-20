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

## External Review Triage

Reviewed independently against the current product direction. Only items that still look valid or strategically useful were accepted into the backlog below.

### Accepted

- `Workspace` appears twice in the page hierarchy.
  - The left sidebar already establishes the navigation context.
  - Repeating `Workspace` again above the right-side surface header weakens hierarchy instead of helping it.

- Current surface selection is still too subtle.
  - Border-only selection on the navigation cards is serviceable but not strong enough.
  - The selected section should be easier to identify at a glance.

- The left sidebar still reads as one long control column.
  - `Navigation`, `Factory Queue`, and `New Workflow` are different tasks but still feel too close in tone and structure.
  - The sections need clearer visual zoning.

- The top-right live status chip is still ambiguous.
  - It can legitimately disagree with the selected session card because it reflects the event stream rather than run state.
  - That distinction is not explained clearly enough in the UI, so the operator can read it as a contradiction.

- `Refresh Surface` still uses internal wording.
  - `Surface` is product-internal language, not operator language.
  - Rename to something simpler such as `Refresh`.

- Queue card metadata hierarchy is still too flat.
  - Stage and owner should visually outrank workflow profile.
  - Right now the three values still read too much like one metadata line.

- Truncated task titles still need a recovery affordance.
  - Clamp is good, but queue cards should provide either a native tooltip/title or another easy way to inspect the full text.

- `Current Focus` still duplicates nearby session state.
  - It is better than before but still too close to repeating header + metrics + stage/owner context.
  - It should become either tighter or more action-oriented.

- Jira affordance should be more visible.
  - `Open in Jira` remains important enough to deserve stronger placement than a quiet text link under the title block.

- Queue/session state mismatches need product clarification.
  - Cases like `In Progress` with `Unassigned`, or `In Progress` with no active lanes, may be valid.
  - But when they are valid, the UI should explain that state rather than leaving it as an apparent contradiction.

- `Standing By` roles still need better expectation setting.
  - A standing-by role should say what kind of handoff or trigger it is waiting for, not just that it exists.

- `Runtime & Trace` naming is still too internal.
  - `Trace` is not operator language.
  - The tab and panel naming should become more explicit and less implementation-flavoured.

- `Latest Activity` still lacks time information.
  - Without timestamps or relative age, the operator cannot judge whether progress is fresh or stale.

- `Task Key` still needs friendlier input guidance.
  - Placeholder alone is weak.
  - Inline validation or format guidance would reduce avoidable errors.

- Start-form policy pills still need explanation.
  - `Self-review`, `Boy Scout`, `Doc Harvest` are meaningful but still opaque for less experienced operators.

- `Tune This Run` and `Advanced Runtime Overrides` still overlap semantically.
  - The distinction is cleaner than before but still not obvious enough from labels alone.

- `Start Run` discoverability can still degrade in long left-column states.
  - This especially matters when advanced sections are opened.

- `Operator Actions` hierarchy remains weak.
  - `Daily Flow` and `Recovery And Debug` still look more like section labels than intentionally structured action groups.

- `Pause Session` should look riskier than normal actions.
  - It should have stronger destructive/recovery affordance and likely a confirmation step.

- `Process Updates` still needs a clearer label.
  - The current label does not tell the operator what concrete outcome to expect.

- `Settings` still mixes too much abstraction on one surface.
  - Project defaults, workflow defaults, and advanced role-level configuration are all present, but the hierarchy is not fully obvious yet.

- Profile tabs in `Settings` still need contextual explanation.
  - The differences between `One-shot`, `Bug Flow`, and `Story Flow` are still not discoverable enough from the surface itself.

- `Advanced Role Overrides` is still easy to miss.
  - It is correctly hidden from the happy path, but first-time configuration still needs a stronger cue that deeper role defaults exist.

- `Save Runtime Defaults` needs clearer success feedback.
  - Save semantics should be explicit through toast, status copy, or other visible confirmation.

- `Health` still contains some low-value duplication in ready states.
  - Especially when everything is healthy, always-visible setup/bootstrap framing still feels heavier than necessary.

- Empty “none” sections in `Health` are still too literal.
  - When nothing requires attention, absence should compress into a stronger success state instead of multiple empty subsections.

- Ready runner cards still lack meaningful differentiation.
  - When multiple runners are healthy, the normal surface should help the operator understand what matters about each one.

### Not Accepted

- “No empty state for queue.”
  - Not accepted; the queue already has a dedicated empty state.

- “Advanced Runtime Overrides” is hidden in the `New Workflow` happy path.
  - Not accepted as stated; hiding it is intentional.
  - The valid issue is discoverability/label clarity, not visibility by default.

- “Health section title is duplicated.”
  - Partially rejected.
  - Repeating the page title and the first panel title is not ideal, but it is a lower-priority copy/structure issue than the stronger health-state problems above.

## Additional Review Triage

Reviewed against the current live UI. Only product-relevant items were accepted into the next execution batches.

### Accepted

- `Workflow` / `Runtime Tools` tabs can stretch into malformed vertical pills when the sidebar grows.
- Switching sessions does not reliably return the main content area to the top.
- Session hero metrics can collapse into empty-looking blocks under layout stress.
- `Workflow Policies` side-by-side selects do not have enough width in all states.
- `Latest Activity` should not show `Unknown time`; missing/invalid time should degrade more gracefully.
- Event stream wording still conflicts in some idle states.
- `Settings Guide` / `Health Guide` read too much like dead navigation cards.
- Surface headings and first cards still need stronger vertical separation.
- `Current Session` eyebrow/title/title-meta spacing still needs more breathing room.
- `Project Baseline` body copy and controls need clearer vertical rhythm.
- Settings tabs, profile description, policy card, runtime override disclosure, and CTA still need more separation.
- Queue metadata pills still need a more uniform row rhythm and clearer template.
- Selected-state styling still over-relies on glow-like accents.
- `Workflow Runs` heading + `Viewing ...` context is still a candidate for removal or stronger compression.

### Not Accepted

- `Latest Activity` missing full task title in every session is not a UI defect by itself.
  - Some sessions simply do not have title metadata yet.
  - The valid issue is graceful fallback, not enforced presence.

- Profile description only appearing for `One-shot`.
  - Not accepted.
  - The form does provide profile-specific description text; this is not a real current bug.

- `Local Stack` being always present is not automatically wrong.
  - The valid issue is ready-state weight and default emphasis, not existence.

## Next Execution Order

1. Fix structural layout bugs.
   - stop cross-column stretch
   - reset scroll on session switch
   - protect hero metrics/tabs from layout collapse

2. Fix spacing/rhythm defects.
   - surface heading vs first card
   - hero eyebrow/title/meta spacing
   - settings baseline/profile/CTA gaps
   - queue metadata row rhythm

3. Simplify ambiguous status language.
   - event stream idle wording
   - `Unknown time` fallback
   - queue/session state mismatch copy where needed

4. Reduce misleading pseudo-navigation.
   - make `Settings Guide` / `Health Guide` read like notes, not dead links
   - revisit whether `Workflow Runs` heading/context line should be removed or compressed

## Latest Operator Review Batch

These items were reconfirmed from the current UI direction and direct operator feedback. They should be treated as the next highest-priority cleanup batch.

### 1. `Factory State` still duplicates what the page already says

- What gets in the way
  - `Overview / Factory State` repeats high-level run counts and selected task identity that are already visible elsewhere on the screen
- Why this is bad
  - it burns prime vertical space without helping the operator decide what to do next
- Expected UX
  - either remove this strip entirely
  - or replace it with genuinely new information that is not already duplicated by the selected session and queue

### 2. The task title and `Open in Jira` are still over-framed

- What gets in the way
  - the task title and Jira link are wrapped in a decorative block that does not add real meaning
- Why this is bad
  - it adds chrome around content that should read as the natural header of the selected task
- Expected UX
  - keep the title and Jira affordance visually separated from run status
  - but do it with lighter structure, not another ornamental card

### 3. Hero metric cards are oversized for their value

- What gets in the way
  - `Status / Active Workers / Waiting / Standing By` consume a lot of space for very short values
- Why this is bad
  - they dominate the visual hierarchy despite being compact secondary facts
- Expected UX
  - keep the metrics, but shrink them substantially
  - reduce card padding and visual weight so the task and current activity remain dominant

### 4. `Current Focus` still duplicates the surrounding state

- What gets in the way
  - `Current Focus` repeats:
    - status
    - stage
    - owner
    - active/standing-by/role counts
  - much of this is already visible in nearby surfaces
- Why this is bad
  - it becomes a large explanatory block without adding enough new information
- Expected UX
  - either collapse this into a tighter summary
  - or rewrite it to answer only one thing clearly:
    - what is happening now
    - what the operator should care about next

### 5. `Run Defaults` is still low-value duplication

- What gets in the way
  - the selected session shows `Boy Scout / Doc Harvest / Self Review` in a dedicated block
  - for most runs this just repeats default policy information
- Why this is bad
  - it adds another block to scan without helping daily operation
- Expected UX
  - demote this into secondary details
  - or hide it unless the run actually diverges from project defaults

### 6. Empty `Waiting` state wastes space and harms layout rhythm

- What gets in the way
  - `Waiting / 0 / No lanes are currently waiting on a handoff` takes the same footprint as genuinely useful progress panels
  - it visually collides with the panel below
- Why this is bad
  - it creates dead weight in the main progress grid
- Expected UX
  - either collapse empty progress states
  - or use their slot for a more useful panel such as planning/follow-up context

### 7. `Planning Chain` placeholder content is too prominent when unused

- What gets in the way
  - `This workflow profile does not use the extended story-planning chain.` appears as a full panel in non-story flows
- Why this is bad
  - it spends a full panel to say “nothing here”
- Expected UX
  - hide the panel entirely when the current workflow does not use story planning
  - do not reserve full-height space for unavailable features

### 8. `Operator Actions` still has too much framing around too few actions

- What gets in the way
  - when only one or two controls are available, the section still wraps them with multiple headers, descriptions, and action cards
- Why this is bad
  - the section feels heavier than the actions it contains
- Expected UX
  - when there are only a couple of actions, render them more directly
  - reduce the amount of explanatory chrome around obvious controls

### 9. `Workflow Details` still risks becoming a duplicate dump

- What gets in the way
  - the new collapsed details surface groups many secondary panels, but some of them still repeat nearby progress/context
- Why this is bad
  - this can become a deferred duplication bucket rather than a purposeful second level
- Expected UX
  - keep only truly secondary panels there
  - remove panels that repeat the same information already available in `Current Session`, `Workflow Pulse`, or `Operator Actions`

### 10. `Tune This Run` and `Advanced Runtime Overrides` still need affordance cleanup

- What gets in the way
  - one disclosure still reads like it uses the wrong icon affordance
  - the runtime override disclosure still pairs the chevron with low-value metadata text
- Why this is bad
  - the UI language is inconsistent and still visually noisy
- Expected UX
  - use one consistent chevron affordance
  - remove non-essential disclosure metadata unless it actively helps decision-making

### 11. `New Workflow Run` can be simpler

- What gets in the way
  - the heading/copy is still slightly over-explained for such an obvious form
- Why this is bad
  - the operator sees more framing than action
- Expected UX
  - `New Workflow` is enough
  - the extra explanatory sentence can likely disappear entirely

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
