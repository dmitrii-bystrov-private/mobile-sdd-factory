# Claude Code Best Practices — Checklist

Based on: https://code.claude.com/docs/en/best-practices

---

## 1. Give Claude a way to verify its work

> Include tests, screenshots, or expected outputs so Claude can check itself. This is the single highest-leverage thing you can do.

| # | Practice | Status | Notes |
|---|----------|--------|-------|
| 1.1 | Provide verification criteria (test cases, expected outputs) | 🟡 Partial | Skills like `review-mr` and `spec` have checklists, but no automated test suite for the assistant itself |
| 1.2 | Verify UI changes visually (screenshots, Chrome extension) | 🔴 Not done | Not applicable — project is a CLI assistant, not a UI app |
| 1.3 | Address root causes, not symptoms (paste errors, ask for root cause fix) | 🟢 Done | CLAUDE.md rule: "If a command fails, explain the error and suggest a fix" |

---

## 2. Explore first, then plan, then code

> Separate research and planning from implementation to avoid solving the wrong problem.

| # | Practice | Status | Notes |
|---|----------|--------|-------|
| 2.1 | Use Plan Mode for research before implementation | 🟢 Done | Rule added to CLAUDE.md: research first for non-trivial tasks |
| 2.2 | Create implementation plans before coding | 🟢 Done | `spec` skill explicitly follows explore → plan → implement flow |
| 2.3 | Commit with descriptive messages and create PRs | 🟢 Done | `review-mr` and `request-review` skills handle MR workflow |

---

## 3. Provide specific context in prompts

> The more precise your instructions, the fewer corrections you'll need.

| # | Practice | Status | Notes |
|---|----------|--------|-------|
| 3.1 | Scope tasks (specify files, scenarios, testing preferences) | 🟢 Done | Skills like `spec` and `review-mr` provide structured task scoping |
| 3.2 | Point to sources (git history, specific files) | 🟢 Done | CLAUDE.md documents paths to iOS/Android projects, CLI tools, scripts |
| 3.3 | Reference existing patterns in the codebase | 🟢 Done | RAG tools (`ios-rag`, `android-rag`) configured for pattern discovery |
| 3.4 | Describe symptoms with likely location and "fixed" criteria | 🟡 Partial | `crashes` skill fetches Crashlytics data, but no structured bug-fix workflow |

### Rich content

| # | Practice | Status | Notes |
|---|----------|--------|-------|
| 3.5 | Reference files with `@` | 🟢 Done | Available natively in Claude Code |
| 3.6 | Paste images directly | 🟢 Done | Available natively |
| 3.7 | Give URLs for docs and API references | 🟡 Partial | Some domains allowlisted in `settings.local.json`, but no curated list of useful doc URLs |
| 3.8 | Pipe data into Claude (`cat log \| claude`) | 🟢 Done | Available natively; scripts in `scripts/` use this pattern |
| 3.9 | Let Claude fetch what it needs (Bash, MCP, file reads) | 🟢 Done | Extensive permissions configured for CLI tools and MCP |

---

## 4. Configure your environment

### 4.1 Write an effective CLAUDE.md

| # | Practice | Status | Notes |
|---|----------|--------|-------|
| 4.1.1 | CLAUDE.md exists with project-specific instructions | 🟢 Done | Comprehensive CLAUDE.md with rules, tools, paths, commands |
| 4.1.2 | Includes Bash commands Claude can't guess | 🟢 Done | `glab`, `acli` commands with examples; script paths |
| 4.1.3 | Includes code style rules | 🔴 Not done | No code style rules — acceptable since this is a config/script project, not a codebase |
| 4.1.4 | Includes testing instructions | 🔴 Not done | No test framework configured for the assistant project |
| 4.1.5 | Keep it concise, prune regularly | 🟢 Done | CLI tool docs extracted to `docs/` and imported via `@`; CLAUDE.md reduced from ~125 to ~40 lines |
| 4.1.6 | Check CLAUDE.md into git | 🟢 Done | Tracked in the repo |
| 4.1.7 | Use `@path/to/import` for modular instructions | 🟢 Done | `@docs/glab.md`, `@docs/acli.md`, `@docs/rag.md` imported from CLAUDE.md |

### 4.2 Configure permissions

| # | Practice | Status | Notes |
|---|----------|--------|-------|
| 4.2.1 | Permission allowlists for safe commands | 🟢 Done | Extensive allowlist in `settings.json`: glab, acli, git, jq, bash, MCP tools |
| 4.2.2 | Deny list for dangerous commands | 🟢 Done | `rm`, `glab mr merge/close`, `acli workitem delete` explicitly denied |
| 4.2.3 | Sandbox enabled | 🟢 Done | `sandbox.enabled: true` with `autoAllowBashIfSandboxed: true` |

### 4.3 Use CLI tools

| # | Practice | Status | Notes |
|---|----------|--------|-------|
| 4.3.1 | Install and configure relevant CLI tools | 🟢 Done | `glab` (GitLab), `acli` (Jira), `firebase` CLI all configured |
| 4.3.2 | Document CLI tool usage in CLAUDE.md | 🟢 Done | Full command references for glab and acli |

### 4.4 Connect MCP servers

| # | Practice | Status | Notes |
|---|----------|--------|-------|
| 4.4.1 | MCP servers configured in `.mcp.json` | 🟢 Done | 4 servers: Notion, ios-rag, android-rag, Firebase |
| 4.4.2 | MCP tool permissions configured | 🟢 Done | Granular allow rules for each MCP tool in settings |

### 4.5 Set up hooks

| # | Practice | Status | Notes |
|---|----------|--------|-------|
| 4.5.1 | Hooks for mandatory actions (lint, format, validation) | 🟢 Done | `validate-spec` hook blocks saving spec.md with missing required sections |

### 4.6 Create skills

| # | Practice | Status | Notes |
|---|----------|--------|-------|
| 4.6.1 | Skills for domain knowledge | 🟢 Done | `review-mr`, `spec` with detailed checklists |
| 4.6.2 | Skills for repeatable workflows | 🟢 Done | `standup`, `gitlab`, `crashes`, `create-task`, `send-to-test`, `request-review` |
| 4.6.3 | Use `disable-model-invocation` for side-effect workflows | 🟡 Partial | Not all skills with side effects use this flag — worth auditing |

### 4.7 Create custom subagents

| # | Practice | Status | Notes |
|---|----------|--------|-------|
| 4.7.1 | Subagent definitions in `.claude/agents/` | 🟢 Done | `implementer` agent (Sonnet) — implements tasks from spec files |
| 4.7.2 | `reviewer` agent (Opus) | 🔜 Planned | Deep code review before MR: patterns, edge cases, security. Works on local files, complements `review-mr` |
| 4.7.3 | `test-writer` agent (Sonnet) | 🔜 Planned | Write unit tests for implemented code. Chain after `implementer` |
| 4.7.4 | `bug-investigator` agent (Opus) | 🔜 Planned | From crash report / bug description → RAG research → root cause → fix proposal. Pairs with `/crashes` |
| 4.7.5 | `migrator` agent (Sonnet) | 🔜 Planned | Cross-platform: find implementation on one platform via RAG, reproduce on the other |

### 4.8 Install plugins

| # | Practice | Status | Notes |
|---|----------|--------|-------|
| 4.8.1 | Browse and install relevant plugins | 🟢 Done | `swift-lsp` and `kotlin-lsp` installed globally |

---

## 5. Communicate effectively

| # | Practice | Status | Notes |
|---|----------|--------|-------|
| 5.1 | Ask codebase questions directly | 🟢 Done | RAG tools + local file access make this seamless |
| 5.2 | Let Claude interview you for larger features | 🟢 Done | Rule added to CLAUDE.md: interview about requirements, edge cases, tradeoffs before planning |

---

## 6. Manage your session

| # | Practice | Status | Notes |
|---|----------|--------|-------|
| 6.1 | Course-correct early (Esc, /rewind, "undo that") | 🟢 Done | Available natively in Claude Code |
| 6.2 | Use `/clear` between unrelated tasks | 🟢 Done | CLAUDE.md rule: use `/clear` between unrelated tasks |
| 6.3 | Use `/compact` with custom instructions | 🟢 Done | CLAUDE.md rule: preserve task context, modified files, and tool commands when compacting |
| 6.4 | Use subagents for investigation to preserve context | 🟢 Done | RAG tools offload codebase exploration; Agent tool available |
| 6.5 | Use checkpoints and `/rewind` | 🟢 Done | Available natively |
| 6.6 | Resume conversations (`--continue`, `--resume`) | 🟢 Done | Available natively |

---

## 7. Automate and scale

| # | Practice | Status | Notes |
|---|----------|--------|-------|
| 7.1 | Non-interactive mode (`claude -p`) in scripts | 🟡 Partial | Scripts in `scripts/` exist but don't use `claude -p` — they are invoked by skills |
| 7.2 | Multiple parallel Claude sessions | 🔴 Not done | No multi-session workflows configured |
| 7.3 | Fan out across files for migrations | 🔴 Not done | No batch processing scripts; could be useful for large refactors |
| 7.4 | Safe autonomous mode (sandbox or `--dangerously-skip-permissions`) | 🟢 Done | Sandbox enabled with auto-allow for bash |

---

## 8. Avoid common failure patterns

| # | Pattern | Mitigation Status | Notes |
|---|---------|-------------------|-------|
| 8.1 | Kitchen sink session (mixing unrelated tasks) | 🟢 Done | CLAUDE.md rule: use `/clear` between unrelated tasks |
| 8.2 | Correcting over and over | 🟢 Done | CLAUDE.md rule: suggest fresh session after two failed corrections |
| 8.3 | Over-specified CLAUDE.md | 🟢 Done | CLI docs extracted to `docs/`; CLAUDE.md is now ~40 lines of essential rules only |
| 8.4 | Trust-then-verify gap | 🟡 Partial | Skills have checklists but no automated verification step |
| 8.5 | Infinite exploration | 🟢 Done | RAG tools scope investigations; CLAUDE.md has usage patterns for targeted search |

---

## 9. Persistent memory

| # | Practice | Status | Notes |
|---|----------|--------|-------|
| 9.1 | Memory directory for cross-session knowledge | 🟢 Done | `memory/MEMORY.md` + topic files (e.g. `android-patterns.md`) |
| 9.2 | Memory is concise and topic-organized | 🟢 Done | Semantic organization, not chronological |

---

## Summary

| Category | 🟢 Done | 🟡 Partial | 🔴 Not Done | 🔜 Planned |
|----------|---------|-----------|------------|-----------|
| 1. Verification | 1 | 1 | 1 (N/A) | — |
| 2. Explore → Plan → Code | 3 | — | — | — |
| 3. Specific context | 6 | 2 | — | — |
| 4. Environment setup | 15 | 2 | 2 | 4 |
| 5. Communication | 2 | — | — | — |
| 6. Session management | 6 | — | — | — |
| 7. Automate & scale | 1 | 1 | 2 | — |
| 8. Failure patterns | 4 | 1 | — | — |
| 9. Memory | 2 | — | — | — |
| **Total** | **40** | **7** | **5** | **4** |

### Remaining work

**Partial — needs improvement:**
- 1.1 — Automated verification for assistant skills (test suite)
- 3.4 — Structured bug-fix workflow (pairs with planned `bug-investigator` agent)
- 3.7 — Curated list of allowlisted doc URLs
- 4.5.1 — Hooks for mandatory validations (lint, commit messages)
- 4.6.3 — Audit `disable-model-invocation` across skills with side effects
- 7.1 — Use `claude -p` in automation scripts
- 8.4 — Automated verification step in implementation workflow

**Not done:**
- 4.1.3 — Code style rules (N/A for this project)
- 4.1.4 — Testing instructions (N/A for this project)
- 7.2 — Multi-session parallel workflows
- 7.3 — Fan-out batch processing scripts

**Planned subagents (4.7):**
- `reviewer` — deep code review before MR
- `test-writer` — unit tests after implementation
- `bug-investigator` — crash/bug root cause analysis
- `migrator` — cross-platform implementation
