# Requirements Analysis — Spec‑Driven Workflow Improvements

Source: `spec/proposal.md`

## 1) Ambiguities (needs clarification)

- **“Preparatory skill/script”**: unclear if this is one skill with multiple scripts, a single script, or a standalone tool outside skills.
- **“Read the Jira issue and subtasks via the API”**: unclear which Jira deployment (Cloud/Data Center), which auth method, and which fields are required.
- **Jira access mechanism**: whether integration should call Jira REST directly or shell out to an existing CLI (resolved below, but originally ambiguous).
- **“Source of truth” precedence rules**: comments override description “by default”, but it’s unclear how to resolve conflicts across multiple comments and whether some commenters (e.g., QA/PM) have higher authority.
- **“Create the worktree/branch”**: unclear naming conventions, branching model (trunk-based vs long-lived branches), and whether this is per-ticket, per-subtask, or per-MR.
- **“Persist the issue and subtasks into files in the workspace”**: unclear file formats (Markdown/JSON/YAML), directory layout, and what constitutes the “source of truth”.
- **Artifacts granularity**: parent needs a single “source of truth” artifact, subtasks need focused artifacts, and statuses should live in a dedicated lightweight file (naming/paths now defined below).
- **`comments.md` exact delimiter format**: metadata fields are specified, but the precise block structure (e.g., required separators, exact labels, how to escape `---` in bodies) is not yet pinned down for robust parsing.
- **Jira ADF handling**: resolved: snapshot stores only deterministically rendered Markdown (no raw ADF JSON).
- **Structured output contract**: Markdown-only is desired, but exact “strictly structured, easily parseable” conventions (headings/delimiters/field labels) are not yet specified.
- **“Clarify the roles of sub-agents and skills”**: unclear enforcement mechanism (docs only vs automated routing/guardrails) and how delegation decisions are made.
- **“Two-phase context building with a cheaper model”**: unclear which model(s), quality targets, cost limits, and what artifacts (index format, excerpts policy) must be produced.
- **“Compact index/summary … pointers to key project areas”**: ambiguous definition of “pointer” (file paths only? symbols? ripgrep hits? dependency graph nodes?).
- **“MR packaging”**: unclear if this includes changelog updates, reviewers, labels, CI checks, templates, or compliance steps.

## 2) Missing Information (needed to implement)

### Jira integration
- Jira base URL, project(s), issue types, and workflow states (may be implicit if using `acli`, but still matters for filtering/validation).
- Required Jira fields to fetch (description, acceptance criteria, custom fields, linked issues, attachments, comments).
- (Resolved) ADF fields (`fields.description`, `fields.comment.comments[].body`) must be deterministically rendered to Markdown, and only the rendered Markdown is stored in snapshot files (no raw ADF JSON).
  - Remaining: specify the exact ADF→Markdown renderer/pipeline and how to handle unsupported ADF nodes, links/mentions, code blocks, tables, and escaping to keep output stable.
- How to model “source of truth”: whether to compute an **effective requirements view** (description + prioritized comment deltas) and how to represent it on disk.
- Subtask/linked-issue rules: whether to treat linked issues (blocks/is blocked by/relates) as part of the hierarchy.
- Whether to use Jira REST directly or reuse an authenticated tool (resolved: reuse `acli`).
- Rate limits, pagination, and expected max sizes (comments, attachments).
- QA-cycle boundary strategy (no reliable status history via `acli`):
  - Snapshot `comments.md` keeps the **full comment history** in chronological order (oldest → newest) for both parent tasks and subtasks.
  - A `[QA_HANDOFF]` marker comment denotes the start of a new QA cycle.
  - QA-feedback consumers interpret the boundary at consumption time by ignoring comments before the most recent marker.

### Git/worktree setup
- Branch naming convention based on Jira type (Resolved: `Bug` → `bugfix/<KEY>`, else `feature/<KEY>`).
- Worktree root location (Resolved: `$SDD_WORKDIR/<KEY>/repo/`).
- Idempotency rules for reruns (Resolved: reuse existing worktree as-is; non-destructive; no resets).
- Monorepo/multi-repo handling (one ticket may touch multiple repos?).

### Workspace artifacts
- Artifact contract (directory layout, filenames, overwrite policy) is now defined (see Q5 answer), but remaining missing pieces:
  - (Resolved) Exact `comments.md` delimiter-safe block template and parsing rules (see Q24 answer).
  - Any required **limits** (max comments, truncation/summarization rules).
  - (Resolved) No `task.json`; outputs should be Markdown-only, but strictly structured and parseable.
  - (Resolved) Derived artifacts live under `$SDD_WORKDIR/<PARENT-KEY>/spec/` and are never touched by the snapshot script.

### Orchestration & responsibilities
- What triggers which sub-agent (manual vs automated) and what inputs/outputs each stage must produce.
- Success criteria for each stage (what “done” means for exploration/spec/implementation/review).
- Error handling and retries (Jira unavailable, git conflicts, missing permissions).

### Slack + Jira transitions
- (Resolved) “Request review in Slack” is already implemented as a skill at `.claude/skills/request-review/SKILL.md`; external behavior/UX should remain unchanged.
- Remaining: define how to refactor internals so Slack message preparation/sending is delegated to the cheapest possible agent or a thin scripted path.
- Jira transition mapping (which statuses correspond to “in progress”, “in review”, “testing”).

### Cost/quality constraints (two-phase approach)
- Budget targets (tokens/$ per ticket) and latency constraints.
- Minimum quality thresholds for the “cheap” phase (recall/precision expectations).
- Privacy/security constraints on what content can be summarized or stored.

## 3) Implicit Assumptions (should be explicit)

- The environment has network access to Jira/Slack and credentials are available non-interactively.
- Jira access can be done via an already-authenticated CLI (`acli`) available in the environment (no new token management).
- Exactly one of `IOS_DIR` or `ANDROID_DIR` is set (mutually exclusive) and points to the platform repository that should be used as the source for `git worktree`.
- `$SDD_WORKDIR` exists and is writable, and tickets are always prepared under `$SDD_WORKDIR/<PARENT-KEY>/`.
- The preparatory script overwrites artifacts on rerun, and downstream agents are okay with snapshot semantics (no need to preserve historical local edits).
- Snapshot artifacts (`description.md`, `comments.md`, `statuses.md`, `subtasks/**`) are **read-only inputs** for agents; derived artifacts must be written outside the snapshot tree managed by the script.
- The repo(s) use git and support worktrees; developers are comfortable with worktree-based workflows.
- Ticket “hierarchy” is primarily the **parent task + its subtasks**, and subtasks represent the current execution plan.
- Parent description is the baseline “problem/outcome”, but **comments may override it** and therefore must be treated as higher-priority inputs unless stated otherwise.
- QA feedback is scoped by a **comment marker** (e.g., `[QA_HANDOFF]`) at consumption time; the snapshot keeps full comment history.
- All required context can be captured as files without leaking sensitive data.
- “Cheaper model” results are sufficiently reliable to guide “expensive” phases without frequent rework.
- The same conventions (spec format, MR template, Jira workflow) apply across all projects involved.

## 4) Edge Cases (not addressed)

### Jira data variability
- Tickets with **no subtasks**, or with many subtasks (pagination/performance).
- Subtasks that belong to different components/repos or have conflicting priorities.
- Tickets with large comment threads, attachments, or restricted fields (permissions).
- Conflicting comment “overrides” (multiple comments refining/overriding requirements in different directions).
- Comments edited after posting, or deleted comments, affecting “latest clarification” semantics.
- Issues with **no `[QA_HANDOFF]` marker**: QA-feedback consumers have no boundary and must treat the full thread as in-scope (potentially noisy/large).
- Linked issues that are more important than subtasks (blocks/depends-on).

### Git/worktree conflicts
- Branch name collision (branch already exists locally/remotely).
- Worktree path already exists, or repo is in a dirty state.
- Ticket requires changes across multiple repos (or a monorepo with multiple packages).

### Re-runs and partial failures
- Script runs halfway, produces some files, then fails (recovery behavior).
- Jira/Slack transient outages and retry/backoff.
- Changing Jira issue contents after artifacts were generated (refresh strategy).
- Local manual edits to generated Markdown files: overwrite-on-rerun will discard them (is that acceptable/expected?).
  - (Resolved) Snapshot is read-only; any edits would be lost and are out of scope.
 - Git/worktree reruns: must be non-destructive and skip worktree creation/bootstrap when `<workdir>/repo` already exists.
- Identifying “comments after last testing transition” when:
  - the issue was moved into testing multiple times,
  - testing is represented by multiple statuses,
  - QA uses comments without changing status,
  - or status history is unavailable due to permissions/configuration (now avoided by marker strategy).

### Content handling
- Very large files or generated artifacts causing context bloat even in summaries.
- Binary files or non-text attachments that “context building” can’t meaningfully parse.
- Security constraints: secrets in tickets/comments; redaction requirements.

## 5) Clarifying Questions (ask stakeholder)

Note: These are the questions to resolve before implementation. Each includes why it matters.

1. **(Answered)** Scope is the **parent task + its subtasks**, with **comments treated as higher-priority by default**; QA feedback is captured in subtask comments, scoped to the current QA cycle.

2. **Which Jira deployment and auth method are required (Jira Cloud vs Data Center; OAuth vs API token; where are secrets stored)?**  
   Why: drives API endpoints, libraries, secret loading, and whether the script can run unattended.
2. **(Answered)** Use `acli` for Jira access; it’s already authenticated in the environment, and the preparatory script should reuse existing `acli` usage patterns in this repo (no bespoke auth/token management).

3. **What exact files should the preparatory script create, and where (directory layout + formats)?**  
   Why: other agents/scripts will depend on stable paths and schemas; this impacts reproducibility and tooling.
3. **(Partially answered)** Artifacts needed:
   - Parent: one “source of truth” artifact containing parent description + refining/overriding comments + current status of parent and all subtasks.
   - Each subtask: focused artifact with subtask description + full comment history (QA-cycle boundary determined by `[QA_HANDOFF]` at consumption time).
   - Statuses: a dedicated lightweight artifact (e.g., `status.md`) for quick access to current state.

4. **(Answered)** No `task.json` is desired; outputs should be Markdown-only but strictly structured and parseable.

4a. **What is the exact “strictly structured” Markdown template for `description.md` and `statuses.md` (headers/field labels/delimiters), similar to the defined `comments.md` format?**  
   Why: downstream automation depends on a stable, parseable contract; without a concrete template, agents/scripts will drift in how they read/write these files.
4a. **(Answered)** Strict, line-oriented Markdown templates:
   - `description.md` (parent + subtask):
     - Must start with `# Description`
     - Must include these metadata lines (one per line, exact `Key: Value`): `ID`, `Type`, `Title`, `Status`
     - `Title:` must be normalized like `statuses.md` title: replace line breaks with spaces, collapse whitespace, and escape `|`.
     - `Status:` should use `fields.status.name` verbatim (optionally escape Markdown-significant chars defensively).
     - Must include stable section: `## Raw Description` (verbatim Jira description)
     - Raw description body must be wrapped with delimiter-safe sentinels:
       - `<!-- jira-description:start -->`
       - `<!-- jira-description:end -->`
     - Parsers must rely on the sentinel pair, not on Markdown headings, to extract the rendered description body.
     - Must NOT include `## Effective Notes` (Effective Notes are derived artifacts outside the snapshot)
     - Future metadata allowed only as additional `Key: Value` lines above `## Raw Description`
   - `statuses.md`:
     - First non-comment line must be `# Statuses`
     - Must be a Markdown table with fixed column order: `Key | Type | Title | Status`
     - No free-form text below the table; future metadata should be new columns, not paragraphs

5. **Branch/worktree conventions: how should branches be named, and is it one branch per Jira ticket or per subtask?**  
   Why: affects git automation, MR granularity, and how the workflow maps to review/testing.
5. **(Answered)** One branch/worktree per parent task under `$SDD_WORKDIR/<PARENT-KEY>/repo/` on branch:
   - `bugfix/<PARENT-KEY>` when Jira type is `Bug`
   - otherwise `feature/<PARENT-KEY>`

5a. **(Answered)** Git/worktree rerun semantics and branching:
   - Branch name:
     - Jira type `Bug` → `bugfix/<TASK-KEY>`
     - Else → `feature/<TASK-KEY>`
   - Workdir: `$SDD_WORKDIR/<TASK-KEY>/` (ensure directory exists).
   - Worktree check: if `$SDD_WORKDIR/<TASK-KEY>/repo/` is already an existing worktree, **skip** creation/bootstrap and do not touch branch state or uncommitted work.
   - If worktree does not exist:
     - Ensure base branch `master` is checked out and updated (`git checkout master`, `git pull origin master`) before creating the worktree.
     - Create worktree + branch: `git worktree add <workdir>/repo -b <branch-name>`.
     - iOS-only one-time bootstrap: symlink `swift_format`, run `mise trust`, `mise exec -- tuist generate --no-open`, and `pod install`.

6. **Idempotency: what should happen if the branch/worktree/artifacts already exist (reuse, overwrite, create new, or abort)?**  
   Why: reruns are inevitable; clear rules prevent destructive actions and reduce operator confusion.

7. **What are the required Jira-to-status transitions and when should they happen (e.g., move to “In Progress”, “In Review”, “Testing”)?**  
   Why: status changes are high-signal automation; incorrect transitions break team workflows.

7a. **(Answered)** Workflow statuses: `TO DO -> IN PROGRESS -> READY FOR TEST -> IN TESTING -> REOPENED`, with completed work in `RESOLVED`. Detailed QA feedback is expected in **subtask comments**, but QA-cycle scoping is done via a `[QA_HANDOFF]` marker comment (not via changelog timestamps).

8. **(Answered/Existing)** Slack “request review” flow exists as `.claude/skills/request-review/SKILL.md`; keep external UX the same.

8a. **What does “cheapest possible agent (or scripted path)” mean in practice for Slack posting—i.e., which model/tier is acceptable, and what inputs should it read to compose the message (MR URL, ticket key, `spec/summary.md`, etc.)?**  
   Why: determines the internal contract for the Slack skill refactor and ensures we can reduce cost without changing user-visible behavior.
8a. **(Answered)** “Cheapest possible” means:
   - Prefer a fully deterministic scripted path by default (routing/validation/arg parsing/message payload creation via templates + scripts), ideally with **no LLM call**.
   - If an LLM is required, use narrowly scoped sub-agents on low-cost models for bounded tasks (min tools, no unnecessary MCP), reserving more capable models only for strictly necessary semantic work.
   - This “script first, then sub-agents” principle should generalize to other mechanical integrations (webhooks, chat tools, small internal APIs).

22. **(Answered)** Canonical `acli` Jira snapshot commands (require `--json` everywhere):
   - Parent core (description + summary + type + status):
     - `acli jira workitem view <PARENT> --fields key,issuetype,summary,status,description --json`
     - Parse: `fields.summary`, `fields.issuetype.name`, `fields.status.name`, `fields.description` (ADF JSON doc; treat as structured, not free text)
   - Parent comments:
     - `acli jira workitem view <PARENT> --fields key,comment --json`
     - Parse per entry in `fields.comment.comments[]`: `id`, `created`, `updated`, `self`, `author.displayName`, `author.emailAddress`, `author.accountId`, `body`
   - Subtask list (stable ordering + pagination):
     - `acli jira workitem search --jql "parent = <PARENT> ORDER BY key ASC" --fields key,issuetype,summary,status --json --paginate`
     - Parse per item: `key`, `fields.summary`, `fields.issuetype.name`, `fields.status.name`
   - Each subtask core + comments (repeat parent patterns):
     - `acli jira workitem view <SUBKEY> --fields key,issuetype,summary,status,description --json`
     - `acli jira workitem view <SUBKEY> --fields key,comment --json`

23. **(Answered)** Jira ADF in snapshot:
   - Snapshot script must render ADF (`fields.description`, `fields.comment.comments[].body`) into Markdown via a deterministic ADF→Markdown renderer.
   - Snapshot stores **only rendered Markdown** (no embedded raw ADF JSON and no mixed representations).

9. **Two-phase context building: what artifact(s) must the cheap phase output (file list only, excerpts, symbol index, dependency map), and what max size is acceptable?**  
   Why: defines the contract between cheap and expensive phases and prevents context bloat.

10. **Quality/cost targets: do you have a token/$ budget per ticket and acceptable latency for each phase?**  
   Why: needed to choose model tiers, summarization depth, and when to fall back to deeper exploration.

11. **Security/privacy constraints: are there any Jira fields or attachments that must be excluded or redacted when persisting to disk?**  
   Why: prevents leaking sensitive data into repos/workspaces and shapes storage/redaction logic.

12. **Multi-repo/monorepo: should the workflow support tickets spanning multiple repositories, and if so how is that represented?**  
   Why: impacts workspace preparation, artifact layout, and whether the pipeline can remain “single-worktree”.

13. **(Answered)** Artifact contract and overwrite semantics:
   - Root: `$SDD_WORKDIR/<PARENT-KEY>/` (e.g. `$SDD_WORKDIR/IOS-11860/`)
   - Worktree: `repo/` on branch `bugfix/<PARENT-KEY>` when Jira type is `Bug`, otherwise `feature/<PARENT-KEY>`
   - Parent artifacts: `description.md`, `comments.md`, `statuses.md`
   - Subtasks: `subtasks/<SUBTASK-KEY>/description.md`, `subtasks/<SUBTASK-KEY>/comments.md`
   - Semantics: `comments.md` contains the **full** comment history in strict chronological order (oldest → newest), including `[QA_HANDOFF]` markers.
   - QA-cycle boundary rule (consumption-time):
     - If a `[QA_HANDOFF]` marker exists: “current QA cycle” consumers ignore comments **before** the most recent marker.
     - Else: treat the full thread as in-scope.
   - Reruns: **overwrite** all artifacts to reflect current Jira snapshot

14. **(Answered)** `comments.md` formatting:
   - Preserve strict chronological order (oldest → newest).
   - Include per-comment metadata and delimiter-safe blocks as specified in Q24 (`ID:` only + body).

15. **(Answered)** `statuses.md` contents (minimal):
   - For each issue (parent + subtasks): issue type, issue key, summary (title), current status.
   - Ordering: parent row first, then subtasks sorted by key ascending (deterministic; matches JQL `ORDER BY key ASC`).
   - Title normalization: replace line breaks with single spaces, collapse whitespace, and escape `|` for Markdown tables (keep other characters as-is).

16. **(Answered)** Snapshot vs derived artifacts:
   - The preparatory script only dumps raw, structured Jira inputs into the snapshot files and overwrites them on every run.
   - Agents must treat snapshot files as read-only and write derived artifacts (specs, notes, plans, summaries) into separate paths not managed by the snapshot script.
   - The preparatory script does **not** synthesize “comment overrides” or write semantic interpretations back into snapshot files.

17. **Should snapshot `description.md` include a `## Effective Notes` placeholder section (always empty), or should “Effective Notes” live only as a derived artifact outside the snapshot?**  
   Why: affects the strict parsing template and avoids conflicting expectations (snapshot must be raw+overwritten, while “Effective Notes” are explicitly a downstream derived output).
17. **(Answered)** “Effective Notes” are **not** part of the Jira snapshot. Snapshot `description.md` contains only raw Jira data (metadata + original description). Any Effective Notes must be written as derived artifacts outside the snapshot tree.

18. **(Answered)** Derived artifacts contract:
   - Root write-safe directory: `$SDD_WORKDIR/<PARENT-KEY>/spec/` (never overwritten by snapshot script).
   - Expected persistent artifacts:
     - `spec/spec.md` (parent task spec)
     - `spec/summary.md` (high-level summary/current state)
     - `spec/notes.md` (consolidated interpretations from comments)
     - Optional: `spec/qa-notes.md`
     - Optional per-subtask: `spec/subtasks/<SUBKEY>/spec.md`, `spec/subtasks/<SUBKEY>/notes.md`
   - Planning: prefer **no long-lived `plan.md`**; Jira subtask tree is the canonical execution plan. If a `plan.md` exists, it should be ephemeral/scratchpad only.

19. **(Answered)** QA-cycle scoping without changelog:
   - Do not rely on Jira status transition history (not reliably available via `acli`).
   - Use a marker comment with standardized prefix `[QA_HANDOFF]` as the QA-cycle boundary.
   - Snapshot includes full comment history; QA-feedback consumers ignore comments before the most recent marker.

20. **Should the snapshot `comments.md` include the `[QA_HANDOFF]` marker comment itself (as the first/last comment in the file), and what is the exact required marker format (case sensitivity, allowed variants, must it be first line)?**  
   Why: scripts need an unambiguous delimiter; inclusion/exclusion affects what agents see as “current cycle context” and avoids off-by-one mistakes in comment filtering.
20. **(Answered)** `comments.md` includes `[QA_HANDOFF]` marker comments as part of the full history, but QA-feedback consumers should ignore the marker comment itself (and anything before it) when focusing on the “current QA cycle”.

21. **(Answered)** `[QA_HANDOFF]` marker matching rule:
   - Case-sensitive.
   - Must begin at the first character of the first line of the comment body (no leading whitespace).
   - Must start with the exact prefix `[QA_HANDOFF]` (underscore required).
   - Any text after the prefix on that first line is allowed and ignored for matching.

24. **(Answered)** `comments.md` strict block template (delimiter-safe):
   - File begins with `## Comments`.
   - Each comment is wrapped by HTML comment delimiters:
     - Start: `<!-- jira-comment:start -->`
     - End: `<!-- jira-comment:end -->`
   - Inside each block, the header must be exactly one `Key: Value` line:
     - `ID: <comment-id>`
   - The first blank line after `ID:` starts the Markdown body; body may contain arbitrary Markdown including `---`.
   - Parsing rule: split by start/end markers; within a block, parse the top contiguous `Key: Value` lines as metadata, then everything after the first blank line as body.

25. **(Answered)** `description.md` raw body delimiters:
   - `## Raw Description` remains as human-friendly header.
   - The rendered description body must be between:
     - `<!-- jira-description:start -->`
     - `<!-- jira-description:end -->`
   - Parsing relies on these sentinels only (description content may contain arbitrary Markdown, including `##` headings).
