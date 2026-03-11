---
description: Prepare a technical specification for a Jira task — read the task, research the codebase, build an implementation plan, optionally decompose into subtasks, and write spec files for AI agents

TRIGGER when: user mentions a Jira key (e.g. ANDR-12345, IOS-67890) together with intent to work on it — plan, implement, start, tackle, pick up, figure out, break down, spec out, or any similar phrasing in any language.
DO NOT TRIGGER when: user only asks to view, check status, or discuss a task without intent to implement it.
---

Prepare a technical specification for a Jira task. Argument: Jira key (e.g. `/spec ANDR-12345` or `/spec IOS-67890`).

> **IMPORTANT: This skill produces a spec file only. Do NOT modify any project source files. Implementation is done by a separate coding agent reading the spec.**

## Steps

### 1. Load Jira task

```
acli jira workitem view <JIRA-KEY>
```

Read: summary, description, acceptance criteria, story points, subtasks, linked issues.

Determine platform from the key prefix:
- `IOS-XXXXX` → iOS → `/Users/d.bystrov/Projects/Finom/finomcommon`
- `ANDR-XXXXX` → Android → `/Users/d.bystrov/Projects/Finom/finom`

If no argument is given, ask for the Jira key.

### 2. Discuss the task with the user

**Always do this before any codebase research.** Present a brief summary of what you understood from Jira, then ask the user to clarify or add context:

- Summarize the task in 2–3 sentences in your own words
- Ask if there are details, edge cases, or implementation ideas not captured in Jira
- Ask if there are any constraints or decisions already made (e.g. "we already decided to use X approach")

**Wait for the user's response before proceeding.** Do not load project rules or research the codebase until you have their input.

### 3. Load project rules

Read the project instructions to understand conventions before designing the spec:

1. `<project_dir>/CLAUDE.md` — root-level instructions (if present)
2. `<project_dir>/.claude/CLAUDE.md` — stack, core principles, module boundaries, links to further rules

Follow any links or references to additional rule files mentioned in those documents.

### 4. Research codebase with RAG tools

Use **ios-rag** for iOS, **android-rag** for Android.

Goal: find all existing code that the task will touch or depend on.

Strategy:
1. `semantic_search` — find relevant screens, features, flows mentioned in the task description
2. `search` — look up specific class/function names if known
3. `graph_neighbors` — map dependencies on key blocks (`out`: what they use, `in`: who uses them)
4. `semantic_search` again for patterns analogous to what needs to be built

Collect: file paths, class names, key interfaces/protocols, existing patterns to follow.

### 5. Assess task size and decide on decomposition

Estimate complexity based on research findings.

**Decompose if:**
- More than ~3 distinct areas of the codebase need changes
- Multiple independent features that can be developed/reviewed separately
- Task spans both UI and backend/API layers with significant work in each
- Story points suggest > 5 SP of work

**If decomposition is needed:**
- Present the proposed subtask breakdown to the user for approval
- After approval, create subtasks in Jira:
  ```
  acli jira workitem create --summary "<subtask title>" --project "<PROJECT>" --type Subtask --parent <JIRA-KEY>
  ```
- Always confirm before creating subtasks (mutating Jira)

### 6. Write spec files ← THIS IS THE ONLY DELIVERABLE

The spec file is the end product of this skill. Once the spec is written, your job is done.
Do not implement the changes — not even partially, not as a "preview". The coding agent will read the spec and do the implementation.

For each task (or approved subtask), create a spec file:

**Path:** `<project_dir>/workdir/<TASK-KEY>/spec.md`

Example: `/Users/d.bystrov/Projects/Finom/finom/workdir/ANDR-12345/spec.md`

The spec is a self-contained technical brief for an AI coding agent. Write it in English.

---

**Spec format:**

```markdown
# <TASK-KEY>: <Task summary>

## Context

<2-3 sentences: what this feature/fix is, why it matters, user-facing impact>

## Platform & Stack

- Platform: iOS / Android
- Key patterns: VIPER / MVP+Moxy, RxJava/Coroutines, Compose/UIKit, etc.
- Module: <module name if applicable>

## Objective

<Clear, single statement of what needs to be implemented>

## Acceptance Criteria

<Copy or rephrase from Jira — use checkboxes>
- [ ] ...
- [ ] ...

## Codebase Context

### Key files to modify
| File | Purpose |
|------|---------|
| `path/to/File.kt` | <what it does and why it needs to change> |

### Key files to read (do not modify)
| File | Purpose |
|------|---------|
| `path/to/Interface.kt` | <contract or pattern to follow> |

### Relevant patterns
<Describe existing patterns the agent must follow — e.g., how similar screens are structured, how DI is wired, how navigation works in this module>

## Implementation Plan

Step-by-step implementation in recommended execution order:

1. **<Step title>**
   - <concrete action>
   - <concrete action>

2. **<Step title>**
   - <concrete action>

...

## Out of Scope

<Explicit list of things NOT to do — prevents scope creep>
- Do not modify <X>
- Do not refactor <Y>
- UI changes are handled in <other task>

## Notes

<Any gotchas, non-obvious constraints, or decisions made during research>
```

---

### 7. Validate spec against checklist

Before presenting results, go through `checklist.md` and verify each item.
Surface only failed items — skip passing ones.

### 8. Prepare git environment

Use `git -C <project_dir>` for all git commands — do NOT use `cd && git` (triggers a security check).

1. **Check current branch:**
   ```
   git -C <project_dir> branch --show-current
   ```
   If not on `master`, switch to master first:
   ```
   git -C <project_dir> checkout master
   ```

2. **Pull latest master:**
   ```
   git -C <project_dir> pull origin master
   ```

3. **Determine branch type** from the Jira task:
   - Bug fix (task type is Bug, or summary contains "fix"/"bug") → `bugfix/<TASK-KEY>`
   - Everything else → `feature/<TASK-KEY>`

4. **Create and switch to the new branch:**
   ```
   git -C <project_dir> checkout -b feature/<TASK-KEY>
   # or
   git -C <project_dir> checkout -b bugfix/<TASK-KEY>
   ```

Do not commit anything. The branch is ready for the developer or AI agent to start implementation.

### 9. Confirm and summarize

After writing spec files, show the user:
- List of files created with their paths
- Brief summary of the implementation plan for each
- Git branch created (e.g. `feature/ANDR-12345`)
- Checklist findings (failed items only)
- Any open questions or risks identified during research
