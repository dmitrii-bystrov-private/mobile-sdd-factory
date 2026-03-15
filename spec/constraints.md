# Technical Constraints — Spec‑Driven Workflow Improvements

Links (source of truth):
- `spec/proposal.md`
- `spec/requirements.md`
- `spec/acceptance_criteria.md`

These constraints are written to be directly verifiable during implementation and review.

---

## 1) Project Structure (packages, modules)

### MUST
- Implement the “preparatory snapshot tool” as a callable CLI entrypoint under `scripts/` (so it can run deterministically without an LLM).
- Expose the snapshot tool to Claude Code as a dedicated skill under `.claude/skills/` (so agents can invoke it consistently from workflows).
- Keep Jira snapshot outputs strictly under `$SDD_WORKDIR/<PARENT-KEY>/` with this exact layout (AC-LAYOUT-01, AC-LAYOUT-02):
  - Parent: `$SDD_WORKDIR/<PARENT-KEY>/description.md`
  - Parent: `$SDD_WORKDIR/<PARENT-KEY>/comments.md`
  - Parent: `$SDD_WORKDIR/<PARENT-KEY>/statuses.md`
  - Subtasks: `$SDD_WORKDIR/<PARENT-KEY>/subtasks/<SUBTASK-KEY>/description.md`
  - Subtasks: `$SDD_WORKDIR/<PARENT-KEY>/subtasks/<SUBTASK-KEY>/comments.md`
- Keep derived artifacts strictly under `$SDD_WORKDIR/<PARENT-KEY>/spec/` and its subdirectories (AC-DERIVED-02); treat this directory tree as write-safe for agents and read-only for the snapshot tool (AC-DERIVED-03).

### SHOULD
- Keep ADF→Markdown rendering logic in its own module/file under `scripts/` so it can be unit-tested independently from Jira/git orchestration.
- Keep snapshot formatting templates (for `description.md`, `comments.md`, `statuses.md`) in one place (single module or single shell file) to avoid divergent formatting across parent vs subtask.

### MUST NOT
- Do not add any JSON “source of truth” output under `$SDD_WORKDIR/<PARENT-KEY>/` (AC-LAYOUT-06).
- Do not write snapshot artifacts anywhere outside `$SDD_WORKDIR/<PARENT-KEY>/` (except temporary files under `/tmp` during generation).

---

## 2) Component Design (classes, interfaces, patterns)

### MUST
- Design the snapshot tool as a small pipeline of deterministic stages with explicit inputs/outputs:
  1) Validate environment and arguments (AC-GIT-07).
  2) Retrieve Jira JSON for parent + subtasks via `acli` (AC-JIRA-01).
  3) Render Jira ADF bodies to Markdown deterministically (AC-JIRA-02, AC-JIRA-03).
  4) Create/reuse git worktree (AC-GIT-01…AC-GIT-06).
  5) Write snapshot artifacts (AC-LAYOUT-01…AC-LAYOUT-04; AC-DESC-*; AC-COMMENTS-*; AC-STATUS-*).
- As part of environment validation, require that exactly one of `IOS_DIR` or `ANDROID_DIR` is set and non-empty; if both are set or both are unset/empty, fail fast with a non-zero exit code and an error that mentions both variable names (AC-ENV-01).
- Make each stage fail-fast with a non-zero exit code and a single, human-readable error summary to stderr.
- Ensure the tool is idempotent:
  - If `$SDD_WORKDIR/<TASK-KEY>/repo/` already exists and is an existing git worktree, do not alter branch state and do not touch uncommitted work (AC-GIT-04).
  - On re-run, overwrite snapshot artifacts only (AC-LAYOUT-03, AC-LAYOUT-04) and never modify derived artifacts (AC-LAYOUT-05, AC-DERIVED-03).
- Implement snapshot file writers as “pure formatting” components:
  - Inputs: already-normalized metadata + rendered Markdown body + ordered comment list.
  - Output: byte-for-byte deterministic file content for unchanged Jira inputs (AC-JIRA-03).
- Ensure failure does not leave partial git/worktree state. For snapshot outputs, partial output is allowed for subtask-retrieval failures but not for parent-retrieval failures:
  - If worktree creation fails, do not leave a partially created `$SDD_WORKDIR/<TASK-KEY>/repo/` directory behind (AC-GIT-06).
  - If Jira retrieval fails for the parent, do not write snapshot artifacts under `$SDD_WORKDIR/<PARENT-KEY>/` (AC-JIRA-04).
  - If Jira retrieval fails for one or more subtasks:
    - Exit non-zero and report failed subtask key(s) (AC-JIRA-05).
    - It is acceptable to write/update parent snapshot artifacts and any successfully retrieved subtask snapshot artifacts.
    - Leave any existing snapshot artifacts for failed subtasks untouched (may be stale).
    - `statuses.md` must include all subtasks from the JQL list; if any subtask detail retrieval fails and there are no last-known values available for that subtask, fail before writing `statuses.md`.

### SHOULD
- Use a small internal interface for rendering and normalization:
  - `render_adf_to_markdown(adf_json) -> markdown_string`
  - `normalize_title(text) -> normalized_text` (applies whitespace collapse and `|` escaping)
  - `write_description_md(...)`, `write_comments_md(...)`, `write_statuses_md(...)`
- Centralize delimiter and sentinel constants (e.g., `<!-- jira-comment:start -->`) in one place to prevent drift.

### MUST NOT
- Do not synthesize “effective notes”, merged interpretations, or comment overrides inside snapshot artifacts (AC-DERIVED-01; AC-DESC-08).
- Do not attempt to infer QA-cycle scope inside the snapshot tool; snapshot must store full history and let consumers filter (AC-SCOPE-03; AC-QA-02/03).

---

## 3) Technology Decisions (specific libraries, configurations)

### MUST
- Use `acli` as the only Jira access mechanism (no direct Jira REST calls and no new auth/token handling) (requirements.md Q2 Answer; AC-JIRA-01).
- Use `jq` for JSON parsing/selection when shell is used (docs in `docs/acli.md`).
- Retrieve Jira data using the canonical `acli` commands from `spec/requirements.md` Q22 (parent core, parent comments, subtask list via JQL, subtask core, subtask comments), and always with `--json`.
- Render Jira ADF (`fields.description`, `fields.comment.comments[].body`) into Markdown with a deterministic in-repo renderer (no embedded raw ADF JSON in snapshot files) (AC-JIRA-02, AC-JIRA-03).
- For git worktrees:
  - Use `git worktree` against the platform repo (`$IOS_DIR` or `$ANDROID_DIR`) as the source repo.
  - Ensure base branch `master` is updated from `origin/master` before creating a new worktree (AC-GIT-05).
  - Choose branch name by Jira type: `Bug` → `bugfix/<TASK-KEY>`, else `feature/<TASK-KEY>` (AC-GIT-02, AC-GIT-03).
- For iOS bootstrap on newly created worktrees, run exactly the one-time steps required by AC-GIT-IOS-01 and skip them when the worktree already exists (AC-GIT-IOS-02).

### SHOULD
- Prefer standard-library-only implementations for the ADF→Markdown renderer to avoid adding dependency managers to this repo.
- Set locale/time-related environment variables inside the script (e.g., `LC_ALL=C`) when needed to guarantee stable sorting and formatting across environments.

### MUST NOT
- Do not depend on LLM calls (or MCP tools) to generate snapshot files; snapshots must be producible offline given Jira JSON input.
- Do not introduce new global machine-level dependencies that are not already part of the documented prerequisites in `scripts/README.md` unless they are explicitly pinned and documented.

---

## 4) Code Style (naming, patterns to follow, anti-patterns to avoid)

### MUST
- Keep all written file content in English (project rule in `CLAUDE.md`).
- For shell scripts:
  - Use `#!/usr/bin/env bash` and `set -euo pipefail`.
  - Quote all variable expansions and paths.
  - Write errors to stderr and return non-zero on failure.
- Enforce deterministic output:
  - Always emit normalized titles that replace line breaks with spaces, collapse whitespace, and escape `|` (AC-DESC-03; AC-STATUS-06; AC-STATUS-07).
  - Preserve strict comment ordering oldest→newest (AC-COMMENTS-02).
  - Include all Jira comments in the snapshot (including `[QA_HANDOFF]` marker comments) as ordinary comment blocks in chronological position (AC-COMMENTS-07).
  - Sort subtask rows by key ascending in `statuses.md` (AC-STATUS-05).
- Match snapshot file templates exactly:
  - `description.md` starts with `# Description`, then required `Key: Value` metadata lines, then `## Raw Description`, then sentinel-bounded body (AC-DESC-01…AC-DESC-07).
  - `comments.md` starts with `## Comments` and uses HTML comment delimiters per comment (AC-COMMENTS-01…AC-COMMENTS-06).
  - `statuses.md` starts with `# Statuses` and contains exactly one Markdown table with fixed column order and no free-form text below (AC-STATUS-01…AC-STATUS-03).

### SHOULD
- Prefer “pure functions” for formatting and normalization so snapshot determinism can be tested with golden fixtures.
- Keep skill instructions (`.claude/skills/**/SKILL.md`) concise and script-first (“script does the work, skill just routes/validates args”) (requirements.md Q8a Answer).

### MUST NOT
- Do not parse or split comment bodies using ambiguous delimiters like `---`; rely only on the HTML comment delimiters (AC-COMMENTS-06).
- Do not write additional free-form paragraphs into snapshot files; only structured headings and `Key: Value` lines as allowed by the acceptance criteria (AC-DESC-09; AC-STATUS-03).
- Do not change the external UX of `.claude/skills/request-review` (AC-SLACK-01).

---

## 5) Testing Strategy (what to test, how to test)

### MUST
- Add automated tests that do not require network access to Jira:
  - Use recorded `acli --json` outputs as fixtures (parent core/comments, subtask list, subtask core/comments).
  - Run the snapshot formatting pipeline against fixtures and assert exact file content for:
    - `description.md` template + sentinels (AC-DESC-01…AC-DESC-07).
    - `comments.md` ordering + delimiters (AC-COMMENTS-01…AC-COMMENTS-06).
    - `statuses.md` table shape/order and absence of trailing prose (AC-STATUS-01…AC-STATUS-08).
- Include a fixture case with zero subtasks and assert that `statuses.md` contains exactly one row for the parent issue (AC-SCOPE-02; AC-STATUS-04).
- Test deterministic re-runs: running the formatter twice on the same fixture inputs must yield byte-for-byte identical outputs (AC-JIRA-03).
- Test failure modes:
  - Missing/empty `SDD_WORKDIR` fails fast and explicitly mentions `SDD_WORKDIR` (AC-GIT-07).
  - Unretrievable parent issue produces non-zero and writes no snapshot artifacts under `$SDD_WORKDIR/` (AC-JIRA-04).
  - Subtask retrieval failure is non-zero and reports which subtask key(s) failed (AC-JIRA-05).

### SHOULD
- Unit-test the ADF→Markdown renderer with small ADF fixture cases covering:
  - headings, paragraphs, lists, inline code, code blocks, links
  - nested formatting (bold/italic/code)
  - content containing `##` headings and `---` sequences (to validate sentinel/delimiter robustness)
- Add a small end-to-end “local integration” test mode gated by an explicit env var (e.g., `RUN_LIVE_JIRA_TESTS=1`) that is allowed to call `acli` against a real issue key (kept off by default).

### MUST NOT
- Do not make default test runs depend on `acli` authentication, Jira availability, Slack availability, or access to `$IOS_DIR`/`$ANDROID_DIR`.
