---
description: Review a GitLab MR — fetch diff, load Jira context, read project rules, explore codebase with RAG tools, and produce a structured review

TRIGGER when: user mentions an MR number or MR URL together with intent to review it — review, check, look at, go through, give feedback, or any similar phrasing in any language.
DO NOT TRIGGER when: user only asks about MR status, pipeline, or whether an MR exists — without asking for a code review.
---

Review a GitLab MR. Argument: MR ID (e.g. `/review-mr 3900`).

## Steps

### 1. Determine platform and project directory

MR titles follow the pattern `[JIRA-KEY]: [title]`:
- `IOS-XXXXX` → iOS → `/Users/d.bystrov/Projects/Finom/finomcommon`
- `ANDR-XXXXX` → Android → `/Users/d.bystrov/Projects/Finom/finom`

If no argument is given, ask for the MR ID and platform.

Fetch MR data (run from the correct project directory):
```
cd <project_dir> && glab mr view <id>
cd <project_dir> && glab mr diff <id>
```

Extract the Jira key from the MR title.

### 2. Load Jira task context

```
acli jira workitem view <JIRA-KEY>
```

Read: summary, description, acceptance criteria, story points.

### 3. Load project rules

Read these files to understand the coding standards before reviewing:

**iOS** (`/Users/d.bystrov/Projects/Finom/finomcommon`):
- `.claude/CLAUDE.md` — stack, core principles, module boundaries
- `.claude/rules/coding-general.md` — memory management, closures, API models
- `.claude/rules/viper.md` — VIPER pattern: file roles, protocols, assembly, state management
- `.claude/rules/testing.md` — test naming, structure, mocks, assertions

**Android** (`/Users/d.bystrov/Projects/Finom/finom`):
- `.claude/CLAUDE.md` — stack, core principles, module boundaries
- `.claude/rules/coding-general.md` — Kotlin rules, threading constraints
- `.claude/rules/moxy.md` — MVP/Moxy presenter rules, contract structure, Compose integration
- `.claude/rules/compose.md` — stateless composables, state ownership, preview requirements
- `.claude/rules/rx.md` — RxJava rules, threading, error handling, CompositeDisposable
- `.claude/rules/di-dagger.md` — Dagger DI structure, required files, component patterns
- `.claude/rules/navigation-cicerone.md` — Cicerone navigation, internal/external screens
- `.coderabbit.yaml` — path-specific review rules configured for this project

### 4. Explore changed files with RAG tools

Use **ios-rag** for iOS, **android-rag** for Android.

For each meaningful changed file (skip generated files, version bumps, resource-only changes):

1. `search` — look up the main class/protocol/function being changed
2. `graph_neighbors` — understand dependencies (`out`: what it uses, `in`: who uses it)
3. `semantic_search` — if something is unclear, find related patterns in the codebase

Goal: understand the context well enough to evaluate correctness and architecture fit — not just syntax.

### 5. Post comments (optional)

If the user asks to post comments to GitLab, use `glab mr note`:

```
cd <project_dir> && glab mr note <id> -m "<comment text>"
```

**Do not attempt inline (positional) comments via the Discussions API** — GitLab silently ignores the position and falls back to a general comment without any error, even with correct SHAs and line numbers. The API requires `application/json` content-type which `glab api` does not support for nested parameters.

Instead, reference the location clearly in the comment body:
```
**[CRITICAL]** `path/to/File.kt:17` — description of the issue
```

**Notes:**
- `glab api` does **not** support `--jq` flag — always pipe to `| jq` instead
- Always confirm with the user before posting — comments are visible to the whole team

### 6. Produce a structured review

---

**MR:** !<id> — <title>
**Jira:** <key> — <summary>
**Platform:** iOS / Android

**Summary**
One paragraph: what this MR does and why, in your own words.

**Verdict:** ✅ Looks good / ⚠️ Minor issues / 🔴 Needs changes

**Issues**
For each issue:
- `[CRITICAL / MAJOR / MINOR]` **<file>:<line>** — <description>
  > Suggestion (if applicable)

**Questions**
Things that are unclear or worth discussing with the author.

**Checklist**
Go through `checklist.md` and mark each item. Only surface items that have findings — skip passing items unless the overall verdict is ✅.

---

**Principles to apply during review** (from project rules):
- Minimal, targeted changes — flag unnecessary scope creep
- Follow existing conventions — flag new patterns that diverge without justification
- Preserve behavior unless explicitly required by the task
- No architectural rewrites without explicit request
- No unnecessary dependency additions
