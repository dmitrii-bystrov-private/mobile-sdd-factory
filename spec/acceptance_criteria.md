# Acceptance Criteria — Spec‑Driven Workflow Improvements

These acceptance criteria are derived from `spec/proposal.md` and the clarified items in `spec/requirements.md`.

## 1) Invocation & Scope

- AC-SCOPE-01: WHEN the preparatory snapshot tool is invoked with a Jira parent issue key THEN it SHALL operate on that parent issue and its subtasks as the in-scope hierarchy.
- AC-SCOPE-02: WHEN the preparatory snapshot tool is invoked for a parent issue with zero subtasks THEN it SHALL still generate the parent artifacts and a valid `statuses.md` table containing only the parent row.
- AC-SCOPE-03: WHEN the preparatory snapshot tool is invoked THEN it SHALL snapshot both the Jira description and the full comment history (so downstream tools can apply their own precedence rules without the snapshot tool rewriting the snapshot).
- AC-ENV-01: WHEN the tool is invoked THEN it SHALL require that exactly one of `IOS_DIR` or `ANDROID_DIR` is set and non-empty; if both are set or both are unset/empty THEN it SHALL exit non-zero and SHALL print an error that explicitly mentions both `IOS_DIR` and `ANDROID_DIR`.

## 2) Git Worktree & Branching

- AC-GIT-01: WHEN the preparatory snapshot tool creates a new worktree for a Jira issue key THEN it SHALL create exactly one worktree rooted at `$SDD_WORKDIR/<TASK-KEY>/repo/`.
- AC-GIT-02: WHEN the Jira issue type is `Bug` THEN the created branch name SHALL be `bugfix/<TASK-KEY>`.
- AC-GIT-03: WHEN the Jira issue type is not `Bug` THEN the created branch name SHALL be `feature/<TASK-KEY>`.
- AC-GIT-04: WHEN `$SDD_WORKDIR/<TASK-KEY>/repo/` already exists and is an existing git worktree THEN the tool SHALL not modify git branch state, shall not reset files, and shall not modify uncommitted work in that worktree.
- AC-GIT-05: WHEN `$SDD_WORKDIR/<TASK-KEY>/repo/` does not exist and a worktree must be created THEN the tool SHALL ensure the base branch `master` is updated to match `origin/master` before adding the new worktree.
- AC-GIT-06: WHEN creating the worktree fails (e.g., branch name collision or git error) THEN the tool SHALL exit with a non-zero status and SHALL not leave a partially created worktree at `$SDD_WORKDIR/<TASK-KEY>/repo/`.
- AC-GIT-07: WHEN the tool is run in an environment where `SDD_WORKDIR` is unset or empty THEN it SHALL fail fast with a non-zero status and SHALL print an error that explicitly mentions `SDD_WORKDIR`.
- AC-GIT-IOS-01: WHEN a new worktree is created and `IOS_DIR` is set (and `ANDROID_DIR` is unset) THEN it SHALL perform the one-time iOS bootstrap:
  - Create/update a symlink at `$SDD_WORKDIR/<TASK-KEY>/repo/swift_format` pointing to `$IOS_DIR/swift_format`.
  - Run `mise trust` in `$SDD_WORKDIR/<TASK-KEY>/repo/`.
  - Run `mise exec -- tuist generate --no-open` in `$SDD_WORKDIR/<TASK-KEY>/repo/` and require success.
  - Run `pod install` in `$SDD_WORKDIR/<TASK-KEY>/repo/` and require success.
- AC-GIT-IOS-02: WHEN `$SDD_WORKDIR/<TASK-KEY>/repo/` already exists and is an existing git worktree THEN the tool SHALL not re-run iOS bootstrap steps.

## 3) Jira Retrieval & Rendering

- AC-JIRA-01: WHEN the tool retrieves Jira issue data THEN it SHALL obtain, at minimum, the issue key, issue type, summary/title, current status, description, and full comment history for the parent and each subtask.
- AC-JIRA-02: WHEN Jira description or comment bodies are stored to disk THEN they SHALL be stored as deterministically rendered Markdown (with no embedded raw Jira ADF JSON).
- AC-JIRA-03: WHEN the tool is run multiple times against unchanged Jira content THEN it SHALL produce byte-for-byte identical rendered Markdown content for descriptions and comments.
- AC-JIRA-04: WHEN the requested parent issue key does not exist or is not accessible THEN the tool SHALL exit with a non-zero status and SHALL not write snapshot artifacts for that parent under `$SDD_WORKDIR/`.
- AC-JIRA-05: WHEN one or more subtasks cannot be retrieved (e.g., permissions or transient failure) THEN the tool SHALL exit with a non-zero status and SHALL indicate which subtask key(s) failed.
- AC-JIRA-06: WHEN one or more subtasks cannot be retrieved THEN the tool MAY still write/update the parent snapshot artifacts and any successfully retrieved subtask snapshot artifacts, but it SHALL NOT delete or overwrite existing snapshot artifacts for failed subtask keys under `$SDD_WORKDIR/<PARENT-KEY>/subtasks/<SUBTASK-KEY>/`.

## 4) Snapshot Artifact Layout & Overwrite Semantics

- AC-LAYOUT-01: WHEN the tool completes successfully THEN it SHALL write parent snapshot artifacts at `$SDD_WORKDIR/<PARENT-KEY>/description.md`, `$SDD_WORKDIR/<PARENT-KEY>/comments.md`, and `$SDD_WORKDIR/<PARENT-KEY>/statuses.md`.
- AC-LAYOUT-02: WHEN the tool completes successfully and the parent has subtasks THEN it SHALL write each subtask’s snapshot artifacts at `$SDD_WORKDIR/<PARENT-KEY>/subtasks/<SUBTASK-KEY>/description.md` and `$SDD_WORKDIR/<PARENT-KEY>/subtasks/<SUBTASK-KEY>/comments.md`.
- AC-LAYOUT-03: WHEN the tool is re-run for the same parent key THEN it SHALL overwrite all snapshot artifacts listed in AC-LAYOUT-01 and AC-LAYOUT-02 to reflect the current Jira snapshot.
- AC-LAYOUT-04: WHEN snapshot artifacts contain local manual edits from a previous run THEN a successful re-run SHALL overwrite those edits (snapshot files are treated as disposable outputs).
- AC-LAYOUT-05: WHEN the tool writes snapshot artifacts THEN it SHALL not create or update any derived artifacts under `$SDD_WORKDIR/<PARENT-KEY>/spec/`.
- AC-LAYOUT-06: WHEN the tool completes successfully THEN it SHALL not write any JSON “source of truth” artifact (for example, it SHALL not create `$SDD_WORKDIR/<PARENT-KEY>/task.json`).

## 5) `description.md` Format (Parent and Subtasks)

- AC-DESC-01: WHEN the tool writes a snapshot `description.md` for any issue THEN the file SHALL start with `# Description` as the first non-empty line.
- AC-DESC-02: WHEN the tool writes a snapshot `description.md` THEN it SHALL include exactly these required metadata lines (one per line, exact `Key: Value` format): `ID: ...`, `Type: ...`, `Title: ...`, `Status: ...`.
- AC-DESC-03: WHEN `Title:` is written in `description.md` THEN it SHALL be normalized by replacing any line breaks with spaces, collapsing whitespace, and escaping `|`.
- AC-DESC-04: WHEN `Status:` is written in `description.md` THEN it SHALL match the Jira `fields.status.name` value for that issue.
- AC-DESC-05: WHEN the tool writes `description.md` THEN it SHALL contain a `## Raw Description` section.
- AC-DESC-06: WHEN the raw description body is written THEN it SHALL appear only between the sentinel lines `<!-- jira-description:start -->` and `<!-- jira-description:end -->`.
- AC-DESC-07: WHEN the Jira description contains arbitrary Markdown (including `##` headings) THEN the raw description body extraction SHALL remain unambiguous due to the sentinel pair in AC-DESC-06.
- AC-DESC-08: WHEN the tool writes `description.md` THEN it SHALL NOT include an `## Effective Notes` section (Effective Notes are derived artifacts outside the snapshot).
- AC-DESC-09: WHEN additional metadata is included in future versions THEN it SHALL appear only as additional `Key: Value` lines above `## Raw Description` (and SHALL not appear as free-form paragraphs).

## 6) `comments.md` Format & Ordering (Parent and Subtasks)

- AC-COMMENTS-01: WHEN the tool writes a snapshot `comments.md` THEN it SHALL begin with a `## Comments` heading.
- AC-COMMENTS-02: WHEN the tool writes comments to `comments.md` THEN it SHALL preserve strict chronological order from oldest to newest by sorting by Jira `created` timestamp ascending, with a deterministic tie-breaker of `id` ascending.
- AC-COMMENTS-03: WHEN a comment is written to `comments.md` THEN it SHALL be enclosed within `<!-- jira-comment:start -->` and `<!-- jira-comment:end -->` delimiters.
- AC-COMMENTS-04: WHEN a comment block is written THEN the block header SHALL consist of exactly one `Key: Value` line: `ID: <comment-id>` (no other header lines).
- AC-COMMENTS-05: WHEN a comment body is written THEN the first blank line after the `ID:` line SHALL begin the Markdown body, and the body SHALL be preserved as arbitrary Markdown content.
- AC-COMMENTS-06: WHEN a comment body contains delimiter-like sequences such as `---` THEN parsing comment boundaries SHALL remain unambiguous due to the HTML comment delimiters in AC-COMMENTS-03.
- AC-COMMENTS-07: WHEN a Jira comment matches the `[QA_HANDOFF]` marker rule THEN it SHALL still be included in `comments.md` as a normal comment block in its chronological position.

## 7) `statuses.md` Format & Determinism

- AC-STATUS-01: WHEN the tool writes `statuses.md` THEN the first non-comment line SHALL be `# Statuses`.
- AC-STATUS-02: WHEN the tool writes `statuses.md` THEN it SHALL contain exactly one Markdown table with fixed column order: `Key | Type | Title | Status`.
- AC-STATUS-03: WHEN the tool writes `statuses.md` THEN it SHALL not include any free-form text below the table.
- AC-STATUS-04: WHEN the tool writes `statuses.md` THEN the first table row SHALL represent the parent issue.
- AC-STATUS-05: WHEN the tool writes `statuses.md` and there are subtasks THEN subsequent rows SHALL list subtasks sorted by key ascending.
- AC-STATUS-06: WHEN a title contains line breaks or multiple whitespace characters THEN the written `Title` cell SHALL replace line breaks with spaces and collapse whitespace to single spaces.
- AC-STATUS-07: WHEN a title contains the `|` character THEN the written `Title` cell SHALL escape `|` to preserve a valid Markdown table.
- AC-STATUS-08: WHEN a Jira issue’s current status is not one of the expected workflow statuses THEN the `Status` cell SHALL still record the Jira status name verbatim (rather than failing or substituting a mapped value).
- AC-STATUS-09: WHEN subtask list retrieval via JQL succeeds THEN `statuses.md` SHALL include rows for all subtask keys returned by that JQL (regardless of whether subsequent per-subtask detail retrieval succeeds).
- AC-STATUS-10: WHEN one or more subtask detail retrievals fail AND an existing `$SDD_WORKDIR/<PARENT-KEY>/statuses.md` exists THEN the tool SHALL carry forward the last-known `Type`, `Title`, and `Status` cell values for those failed subtask keys from the existing `statuses.md`.
- AC-STATUS-11: WHEN one or more subtask detail retrievals fail AND there is no existing `$SDD_WORKDIR/<PARENT-KEY>/statuses.md` to provide last-known values THEN the tool SHALL exit non-zero and SHALL NOT write `statuses.md` for that run.

## 8) QA-Cycle Scoping via `[QA_HANDOFF]`

- AC-QA-01: WHEN a Jira comment body begins with the exact prefix `[QA_HANDOFF]` at the first character of the first line THEN that comment SHALL be treated as a QA-cycle marker (case-sensitive; underscore required).
- AC-QA-02: WHEN a `[QA_HANDOFF]` marker comment exists in an issue’s `comments.md` THEN any consumer that focuses on the “current QA cycle” SHALL ignore (a) the marker comment itself and (b) all comments before the most recent marker.
- AC-QA-03: WHEN no `[QA_HANDOFF]` marker comment exists THEN any consumer that focuses on QA feedback SHALL treat the full comment history as in-scope.
- AC-QA-04: WHEN `[QA_HANDOFF]` appears anywhere other than the first character of the first line (e.g., leading whitespace or later lines) THEN it SHALL NOT be treated as a QA-cycle marker.
- AC-QA-05: WHEN a `[QA_HANDOFF]` marker comment contains additional text after the prefix on the first line THEN that additional text SHALL not affect marker matching.

## 9) Snapshot vs Derived Artifacts Responsibilities

- AC-DERIVED-01: WHEN the preparatory snapshot tool runs THEN it SHALL dump raw Jira inputs into snapshot files only and SHALL not synthesize “effective” interpretations (such as comment overrides) inside snapshot artifacts.
- AC-DERIVED-02: WHEN an agent or downstream tool needs “Effective Notes”, summaries, specs, or plans THEN it SHALL write them only under `$SDD_WORKDIR/<PARENT-KEY>/spec/` (or its subdirectories), not into snapshot files.
- AC-DERIVED-03: WHEN derived artifacts exist under `$SDD_WORKDIR/<PARENT-KEY>/spec/` THEN a successful re-run of the snapshot tool SHALL not modify or delete those derived artifacts.

## 10) Slack Review Request (External UX Stability)

- AC-SLACK-01: WHEN the Slack “request review” flow is triggered THEN it SHALL preserve the existing external user experience (inputs required, output formatting expectations, and observable side effects) compared to the current `.claude/skills/request-review` behavior.
