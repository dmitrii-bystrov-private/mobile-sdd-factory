# Execution Task List

## Checklist

- [x] 1. Add environment validation to snapshot script
- [x] 2. Implement Jira retrieval stage (parent + subtasks)
- [x] 3. Implement ADF-to-Markdown renderer
- [x] 4. Add ADF renderer unit tests with fixtures
- [x] 5. Implement description.md formatter
- [x] 6. Implement comments.md formatter
- [x] 7. Implement statuses.md formatter
- [x] 8. Implement git worktree setup stage
- [x] 9. Implement iOS bootstrap stage
- [ ] 10. Wire all stages into snapshot.sh orchestration
- [ ] 11. Add snapshot formatter golden-file tests
- [ ] 12. Add failure-mode tests for snapshot script
- [ ] 13. Create snapshot skill in .claude/skills/

- summary: "Add environment validation to snapshot script"
  description: |
    Create the entry-point shell script `scripts/snapshot.sh` with `#!/usr/bin/env bash` and `set -euo pipefail`.
    Implement the environment-validation stage as the first step:
    - Require exactly one positional argument (the Jira parent issue key); exit non-zero with usage hint if missing.
    - Require `SDD_WORKDIR` to be set and non-empty; if unset or empty, print an error mentioning `SDD_WORKDIR` and exit non-zero.
    - Require that exactly one of `IOS_DIR` or `ANDROID_DIR` is set and non-empty. If both are set or both are unset/empty, print an error that explicitly mentions both variable names and exit non-zero.
    - Require that `acli` and `jq` are available on PATH; if either is missing, print the name of the missing tool and exit non-zero.
    Write all errors to stderr. Do not implement any Jira retrieval or file-writing logic yet — validation stage only.
  artifact: "scripts/snapshot.sh (validation stage only)"
  validation: "Running the script with no args, or with SDD_WORKDIR unset, or with both/neither platform dirs set, produces the expected non-zero exit code and error message. Running with valid env and a placeholder key proceeds past validation without crashing."

***

- summary: "Implement Jira retrieval stage (parent + subtasks)"
  description: |
    Extend `scripts/snapshot.sh` with a Jira retrieval stage that uses `acli` and `jq` as defined in `spec/requirements.md` Q22:
    - Fetch parent core: `acli jira workitem view <KEY> --fields key,issuetype,summary,status,description --json`
    - Fetch parent comments: `acli jira workitem view <KEY> --fields key,comment --json`
    - Fetch subtask list: `acli jira workitem search --jql "parent = <KEY> ORDER BY key ASC" --fields key,issuetype,summary,status --json --paginate`
    - For each subtask key, fetch subtask core and subtask comments using the same patterns as parent.
    Store all raw JSON in temporary variables or `/tmp` files for use by downstream stages.
    Fail fast (non-zero + stderr message) if parent retrieval fails.
    If one or more subtask retrievals fail, record which keys failed, exit non-zero at the end, but continue with remaining subtasks.
    Do not write any snapshot artifacts yet.
  artifact: "scripts/snapshot.sh (retrieval stage added)"
  validation: "With a real Jira key (or recorded fixture), the script successfully fetches and holds all required JSON. Parent failure causes immediate exit. A subtask failure records the key and continues to retrieve remaining subtasks, then exits non-zero with the list of failed keys."

***

- summary: "Implement ADF-to-Markdown renderer"
  description: |
    Create a self-contained script or function library `scripts/adf_to_md.sh` (or equivalent in a separate file included via `source`) that deterministically renders Jira ADF JSON to Markdown.
    The renderer must handle, at minimum:
    - paragraph, heading (levels 1–6), hardBreak
    - bulletList, orderedList, listItem
    - text with marks: strong, em, code, link (with href), strike
    - codeBlock (with optional language attribute)
    - rule (horizontal rule)
    - Unsupported node types: emit their text content if available, otherwise skip silently.
    The renderer must be a pure function: same ADF JSON input always produces the same Markdown output (AC-JIRA-03).
    Use only bash and standard tools (jq, sed) — no new global dependencies.
    Expose as a shell function `render_adf_to_markdown` that accepts ADF JSON via stdin or first argument.
  artifact: "scripts/adf_to_md.sh"
  validation: "Unit tests (next task) cover all listed node types and confirm byte-for-byte identical output on repeated runs with the same input."

***

- summary: "Add ADF renderer unit tests with fixtures"
  description: |
    Create a test script `scripts/tests/test_adf_to_md.sh` that:
    - Loads `scripts/adf_to_md.sh` and runs `render_adf_to_markdown` against small, hand-crafted ADF JSON fixture strings.
    - Asserts exact string output for each fixture: paragraph, heading, bulletList, orderedList, codeBlock, inline marks (bold/italic/code/link), rule (---).
    - Includes a fixture that has `##` headings and `---` sequences inside a text body to verify they are rendered safely.
    - Asserts that running the renderer twice on the same input produces byte-for-byte identical output (AC-JIRA-03).
    - Reports pass/fail per test case and exits non-zero if any assertion fails.
    Tests must not require network access or `acli` authentication.
  artifact: "scripts/tests/test_adf_to_md.sh"
  validation: "Running `bash scripts/tests/test_adf_to_md.sh` offline produces all-pass output and exits 0."

***

- summary: "Implement description.md formatter"
  description: |
    Create a shell function `write_description_md` in `scripts/snapshot_formatters.sh` that writes a `description.md` file conforming to AC-DESC-01 through AC-DESC-09:
    - First non-empty line: `# Description`
    - Required metadata block (exact `Key: Value` format): `ID:`, `Type:`, `Title:`, `Status:`
    - `Title:` must be normalized: replace line breaks with single spaces, collapse whitespace, escape `|`.
    - `Status:` must match `fields.status.name` verbatim.
    - `## Raw Description` section with body wrapped by sentinel pair:
      - `<!-- jira-description:start -->`
      - `<!-- jira-description:end -->`
    - Must NOT include `## Effective Notes`.
    Centralize the sentinel constants as variables at the top of the formatters file to prevent drift.
    The function takes already-rendered Markdown for the description body (not raw ADF).
  artifact: "scripts/snapshot_formatters.sh (write_description_md)"
  validation: "Golden-file test (next step or inline assertion) confirms that the function output matches the expected description.md template byte-for-byte for both a parent issue and a subtask fixture."

***

- summary: "Implement comments.md formatter"
  description: |
    Add shell function `write_comments_md` to `scripts/snapshot_formatters.sh` that writes `comments.md` conforming to AC-COMMENTS-01 through AC-COMMENTS-07:
    - File begins with `## Comments`.
    - Each comment is wrapped by `<!-- jira-comment:start -->` and `<!-- jira-comment:end -->` delimiters.
    - Inside each comment block: exactly one metadata line `ID: <comment-id>`, then a blank line, then the Markdown body.
    - Comments are ordered by Jira `created` ascending; tie-break by `id` ascending.
    - `[QA_HANDOFF]` marker comments are included as normal comment blocks in their chronological position (AC-COMMENTS-07).
    The function accepts an ordered array/list of already-rendered Markdown comment bodies plus their metadata.
    Reuse the sentinel constants defined in the formatters file.
  artifact: "scripts/snapshot_formatters.sh (write_comments_md)"
  validation: "Test with a fixture containing 3 comments including one [QA_HANDOFF] marker: output matches the expected comments.md format, order is chronological, no ambiguous delimiters appear."

***

- summary: "Implement statuses.md formatter"
  description: |
    Add shell function `write_statuses_md` to `scripts/snapshot_formatters.sh` that writes `statuses.md` conforming to AC-STATUS-01 through AC-STATUS-11:
    - First non-comment line: `# Statuses`.
    - Exactly one Markdown table with fixed column order: `Key | Type | Title | Status`.
    - First row: parent issue.
    - Subsequent rows: subtasks sorted by key ascending.
    - No free-form text below the table.
    - Title normalization: replace line breaks with spaces, collapse whitespace, escape `|`.
    - Status written verbatim from Jira (AC-STATUS-08).
    Include logic to carry forward last-known values from an existing `statuses.md` for subtasks whose detail retrieval failed (AC-STATUS-10). If no existing file and any subtask details failed, do not write the file at all (AC-STATUS-11).
  artifact: "scripts/snapshot_formatters.sh (write_statuses_md)"
  validation: "Test with fixture: parent + 2 subtasks (one with failed detail retrieval, existing statuses.md present) produces correct table with carried-forward values. Test zero-subtask case produces a single-row table."

***

- summary: "Implement git worktree setup stage"
  description: |
    Add a git-worktree stage to `scripts/snapshot.sh` that:
    - Determines branch name from Jira issue type: `Bug` → `bugfix/<KEY>`, else `feature/<KEY>`.
    - If `$SDD_WORKDIR/<KEY>/repo/` already exists and is a valid git worktree (`git -C <path> rev-parse --is-inside-work-tree` succeeds), skip creation entirely (AC-GIT-04, AC-GIT-IOS-02).
    - If worktree does not exist:
      - Ensure `$SDD_WORKDIR/<KEY>/` directory exists.
      - Run `git -C <platform-dir> checkout master` and `git -C <platform-dir> pull origin master`.
      - Run `git -C <platform-dir> worktree add "$SDD_WORKDIR/<KEY>/repo" -b <branch-name>`.
      - If creation fails, remove any partially created directory at `$SDD_WORKDIR/<KEY>/repo/` and exit non-zero (AC-GIT-06).
    - Use `$IOS_DIR` or `$ANDROID_DIR` as the source repo (whichever is set, per validation stage).
    Always use `git -C <path>` syntax; never `cd` into directories.
  artifact: "scripts/snapshot.sh (git worktree stage)"
  validation: "Running twice with the same key skips creation on second run without error. Running on a fresh key creates the worktree at the expected path on the correct branch. A simulated git failure causes cleanup of the partial directory and non-zero exit."

***

- summary: "Implement iOS bootstrap stage"
  description: |
    Extend the git worktree stage in `scripts/snapshot.sh` to run iOS-only one-time bootstrap when a new worktree is created and `IOS_DIR` is set:
    - Create/update symlink: `ln -sf "$IOS_DIR/swift_format" "$SDD_WORKDIR/<KEY>/repo/swift_format"`.
    - Run `mise trust` in `$SDD_WORKDIR/<KEY>/repo/` (use `bash -c "cd <path> && mise trust"` or equivalent).
    - Run `mise exec -- tuist generate --no-open` from the worktree directory; exit non-zero on failure.
    - Run `pod install` from the worktree directory; exit non-zero on failure.
    Skip all bootstrap steps if the worktree already existed (AC-GIT-IOS-02).
    Do not run any bootstrap steps when `ANDROID_DIR` is set.
  artifact: "scripts/snapshot.sh (iOS bootstrap stage)"
  validation: "When IOS_DIR is set and worktree is newly created, all four bootstrap steps are executed in order. When worktree already exists, bootstrap is skipped. When ANDROID_DIR is set, bootstrap steps are not executed."

***

- summary: "Wire all stages into snapshot.sh orchestration"
  description: |
    Wire together all stages in `scripts/snapshot.sh` in the required pipeline order:
    1. Validate environment and arguments.
    2. Retrieve Jira JSON (parent core, parent comments, subtask list, each subtask core + comments).
    3. Render all ADF bodies to Markdown (using `render_adf_to_markdown` from `scripts/adf_to_md.sh`).
    4. Create or reuse git worktree (with iOS bootstrap if applicable).
    5. Write snapshot artifacts (description.md, comments.md for parent; statuses.md; description.md, comments.md for each subtask).
    Ensure:
    - Parent retrieval failure exits immediately without writing any snapshot artifacts.
    - Subtask retrieval failures are accumulated; all successful subtasks are written; statuses.md carries forward last-known values if available; script exits non-zero with list of failed keys.
    - Derived artifacts under `spec/` are never created or modified by this script.
    Source `scripts/adf_to_md.sh` and `scripts/snapshot_formatters.sh` at the top of the script.
  artifact: "scripts/snapshot.sh (complete, end-to-end)"
  validation: "Running the script end-to-end against a real Jira key (or recorded fixtures) produces the correct directory layout with all required snapshot files containing valid, parseable Markdown. Re-run is idempotent and does not touch spec/ directory."

***

- summary: "Add snapshot formatter golden-file tests"
  description: |
    Create `scripts/tests/test_snapshot_formatters.sh` that tests all three formatters against recorded acli JSON fixtures:
    - Provide fixture files under `scripts/tests/fixtures/` (sample acli --json output for parent core, parent comments, subtask list, subtask core, subtask comments).
    - Run the full formatting pipeline against fixtures and assert byte-for-byte identical output against golden files under `scripts/tests/golden/`.
    - Include a zero-subtask fixture; assert `statuses.md` has exactly one data row (AC-SCOPE-02, AC-STATUS-04).
    - Run the formatter twice on the same fixture and assert outputs are identical (AC-JIRA-03).
    - Test title normalization: titles with line breaks, extra spaces, and `|` characters produce expected escaped output (AC-DESC-03, AC-STATUS-06, AC-STATUS-07).
    Tests must not require network access or acli authentication.
  artifact: "scripts/tests/test_snapshot_formatters.sh, scripts/tests/fixtures/, scripts/tests/golden/"
  validation: "Running `bash scripts/tests/test_snapshot_formatters.sh` offline produces all-pass output and exits 0."

***

- summary: "Add failure-mode tests for snapshot script"
  description: |
    Create `scripts/tests/test_snapshot_errors.sh` that tests error handling without network calls:
    - Missing/empty `SDD_WORKDIR`: script exits non-zero and stderr mentions `SDD_WORKDIR`.
    - Both `IOS_DIR` and `ANDROID_DIR` set: script exits non-zero and stderr mentions both variable names (AC-ENV-01).
    - Neither `IOS_DIR` nor `ANDROID_DIR` set: script exits non-zero and stderr mentions both variable names (AC-ENV-01).
    - Parent retrieval simulated failure: no snapshot artifacts written under `$SDD_WORKDIR/` (AC-JIRA-04); use a mock/stub that returns a non-zero exit to simulate acli failure.
    - Subtask retrieval simulated failure: non-zero exit, failed subtask key(s) reported, parent artifacts written, other subtask artifacts written (AC-JIRA-05, AC-JIRA-06).
    Mock acli calls by temporarily overriding the command with a shell function that returns fixture data or errors as needed.
  artifact: "scripts/tests/test_snapshot_errors.sh"
  validation: "Running `bash scripts/tests/test_snapshot_errors.sh` offline produces all-pass output and exits 0."

***

- summary: "Create snapshot skill in .claude/skills/"
  description: |
    Create `.claude/skills/snapshot/SKILL.md` that exposes the snapshot script to Claude Code agents.
    The skill must describe:
    - When to trigger: when an agent needs to prepare a Jira workspace (snapshot + worktree) before starting implementation.
    - Inputs: Jira parent issue key.
    - What the script does at a high level (Jira retrieval, worktree creation, artifact layout).
    - How to invoke: `bash scripts/snapshot.sh <PARENT-KEY>`.
    - Expected outputs: list of artifact paths the skill creates, so agents know where to read them.
    - Idempotency note: safe to re-run; existing worktree is preserved; snapshot files are overwritten with fresh Jira data.
    - Error guidance: what to check if the script fails (SDD_WORKDIR, IOS_DIR/ANDROID_DIR, acli auth, VPN).
    Keep instructions concise and script-first per CLAUDE.md skill-authoring rules. All content in English.
  artifact: ".claude/skills/snapshot/SKILL.md"
  validation: "Skill file exists, is in English, follows the SKILL.md authoring conventions, and correctly documents the script's invocation, inputs, outputs, and error cases."
