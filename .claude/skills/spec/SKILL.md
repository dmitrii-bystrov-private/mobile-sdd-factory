---
description: Prepare a technical specification for a Jira task — read the task, discuss with the user, then delegate deep research and spec writing to an Opus subagent

TRIGGER when: user mentions a Jira key (e.g. ANDR-12345, IOS-67890) or a Jira URL (e.g. https://pnlfintech.atlassian.net/browse/IOS-12007) together with intent to work on it — plan, implement, start, tackle, pick up, figure out, break down, spec out, or any similar phrasing in any language.
DO NOT TRIGGER when: user only asks to view, check status, or discuss a task without intent to implement it.
---

Prepare a technical specification for a Jira task. Argument: Jira key (e.g. `/spec ANDR-12345` or `/spec IOS-67890`).

> **IMPORTANT: This skill produces spec files only. Do NOT modify any project source files. Implementation is done separately via `/implement`.**

## File layout

Every story uses a single workdir and a single worktree branch, regardless of whether it has subtasks:

```
workdir/<STORY-KEY>/
├── spec.md                    # always: high-level plan + architecture for the whole story
├── spec-<STORY-KEY>.md        # detailed spec — only when the story has NO subtasks
├── spec-<SUBTASK-KEY>.md      # detailed spec per subtask — when the story has subtasks
└── repo/                      # single git worktree for the entire story
```

## Steps

### 1. Load Jira task

```
acli jira workitem view <JIRA-KEY> --fields '*all' --json
```

Read: summary, description, acceptance criteria, story points, subtasks, linked issues, and **comments** (discussions in comments often contain refined requirements or implementation decisions that supersede the original description).

Determine platform from the key prefix:
- `IOS-XXXXX` → iOS → `~/Projects/Finom/finomcommon`
- `ANDR-XXXXX` → Android → `~/Projects/Finom/finom`

If no argument is given, ask for the Jira key.

**Determine task mode** — this controls the rest of the flow:

- **Subtask** — the task has a parent issue → go to [Subtask mode](#subtask-mode)
- **Story without subtasks** — the task has no subtasks → go to [Story mode (no subtasks)](#story-mode-no-subtasks)
- **Story with subtasks** — the task has subtasks listed → go to [Story mode (with subtasks)](#story-mode-with-subtasks)

### 1a. Check for existing work (resume detection)

Before doing anything else, check if work on this task has already started:

```bash
ls ~/Projects/Finom/workdir/<STORY-KEY>/spec.md 2>/dev/null
```

If `spec.md` **already exists** and the task is a **story with subtasks** → **Resume mode**:

1. Load all subtasks and their statuses:
   ```bash
   acli jira workitem search --jql "parent = <STORY-KEY>" --fields key,summary,status
   ```
2. Show the user a status summary:
   ```
   Story: <STORY-KEY> — <summary>
   Branch: feature/<STORY-KEY>

   Subtasks:
   ✓ IOS-XXXXX  Done/Ready for test/Resolved  — <summary>
   ○ IOS-XXXXX  To Do                          — <summary>
   ○ IOS-XXXXX  To Do                          — <summary>
   ```
3. Suggest the next To Do subtask: "Следующий шаг: `/spec <NEXT-SUBTASK-KEY>`"
4. **Stop here** — do not re-run spec-writer for the story.

If `spec.md` **already exists** and the task is a **story without subtasks**:
- Check if `spec-<STORY-KEY>.md` also exists.
- If yes → show existing spec summary, suggest `/implement <STORY-KEY>`. Stop.
- If no → continue normally (write the detailed spec only).

If `spec.md` does **not** exist → continue with normal flow below.

---

## Story mode (no subtasks)

### 2a. Set up workdir and worktree

Determine branch type from the Jira task type:
- `Bug` → `bugfix/<TASK-KEY>`
- anything else → `feature/<TASK-KEY>`

Set `<workdir>` = `~/Projects/Finom/workdir/<TASK-KEY>`.

```bash
mkdir -p <workdir>
```

Check if worktree already exists:
```bash
git -C <project_dir> worktree list | grep <workdir>/repo
```

If it does **not** exist:
1. Ensure the main repo is on master and up to date:
   ```bash
   git -C <project_dir> checkout master
   git -C <project_dir> pull origin master
   ```
2. Create the worktree:
   ```bash
   git -C <project_dir> worktree add <workdir>/repo -b <branch-name>
   ```

If it already exists, skip creation.

### 3a. Discuss the task with the user

Present a brief summary of what you understood from Jira, then ask the user to clarify or add context:
- Summarize the task in 2–3 sentences
- Ask about details, edge cases, or implementation ideas not captured in Jira
- Ask about any constraints or decisions already made

**Wait for the user's response before proceeding.**

### 4a. Launch the spec-writer agent

Launch the `spec-writer` subagent (runs on Opus) to write **both** spec files:

```
Write a technical spec for Jira task <JIRA-KEY>.

Task summary: <summary from Jira>
Description: <description from Jira>
Acceptance criteria: <criteria from Jira>
Comments: <comments from Jira>
Platform: <iOS/Android>
Project directory: <project_dir>
User context: <details from discussion>

Output two files:
1. ~/Projects/Finom/workdir/<TASK-KEY>/spec.md
   High-level: goals, architecture overview, key decisions, risks.

2. ~/Projects/Finom/workdir/<TASK-KEY>/spec-<TASK-KEY>.md
   Detailed implementation plan: exact files to create/modify, step-by-step changes,
   acceptance criteria checklist, code patterns to follow.
```

### 5a. Present results

Show the user:
- Spec files: `spec.md` and `spec-<TASK-KEY>.md`
- Worktree: `<workdir>/repo` on branch `<branch-name>`
- Brief summary of the plan
- Any open questions or risks
- Suggest next step: `/implement <TASK-KEY>`

---

## Story mode (with subtasks)

### 2b. Set up workdir and worktree

Same as [2a](#2a-set-up-workdir-and-worktree) — use the story key for the workdir and branch.

### 3b. Discuss the task with the user

Same as [3a](#3a-discuss-the-task-with-the-user) — discuss the story as a whole.

Also clarify: are the existing subtasks correct and complete, or does the story need to be decomposed first?

**Wait for the user's response before proceeding.**

### 4b. Launch the spec-writer agent

Launch the `spec-writer` subagent to write the high-level spec only:

```
Write a high-level technical spec for Jira story <JIRA-KEY>.

Task summary: <summary from Jira>
Description: <description from Jira>
Subtasks: <list of subtask keys and summaries>
Comments: <comments from Jira>
Platform: <iOS/Android>
Project directory: <project_dir>
User context: <details from discussion>

Output one file:
~/Projects/Finom/workdir/<TASK-KEY>/spec.md
Content: goals, architecture overview, key decisions, how subtasks relate to each other, risks.
Do NOT write detailed per-subtask specs — those are written separately per subtask.
```

### 5b. Handle decomposition (if needed)

If the story has no subtasks yet and the spec-writer recommends decomposition:
- Present the proposed breakdown to the user for approval
- After approval, create subtasks in Jira using the JSON file approach:
  ```bash
  cat > /tmp/jira_create.json << 'EOF'
  {
    "additionalAttributes": {"priority": {"name": "<priority>"}},
    "assignee": "d.bystrov@pnlfin.tech",
    "summary": "<subtask title>",
    "description": <description in ADF>,
    "projectKey": "<IOS|ANDR>",
    "parentIssueId": "<STORY-KEY>",
    "type": "Sub-task"
  }
  EOF
  acli jira workitem create --from-json /tmp/jira_create.json --json
  ```
- Always confirm before creating subtasks

### 6b. Present results

Show the user:
- Spec file: `spec.md`
- Worktree: `<workdir>/repo` on branch `<branch-name>`
- List of subtasks (existing or newly created)
- Suggest next step: `/spec <SUBTASK-KEY>` to write the first detailed subtask spec

---

## Subtask mode

### 2c. Resolve parent and workdir

Load the parent story key from the subtask's `parent` field.

Set `<workdir>` = `~/Projects/Finom/workdir/<STORY-KEY>` (parent's workdir, not the subtask's).

Verify the worktree exists:
```bash
git -C <project_dir> worktree list | grep <workdir>/repo
```

If it does **not** exist, tell the user: "The story worktree doesn't exist yet. Run `/spec <STORY-KEY>` first to set it up."

Read the parent's high-level spec for context:
```
<workdir>/spec.md
```

### 3c. Discuss the subtask with the user

- Summarize what you understood from Jira and from the parent spec
- Ask about implementation details, edge cases, or constraints specific to this subtask
- Ask if there are decisions from other already-implemented subtasks to be aware of

**Wait for the user's response before proceeding.**

### 4c. Launch the spec-writer agent

Launch the `spec-writer` subagent with full context:

```
Write a detailed implementation spec for subtask <SUBTASK-KEY> (part of story <STORY-KEY>).

Subtask summary: <summary from Jira>
Subtask description: <description from Jira>
Subtask comments: <comments from Jira>
Parent story spec: <contents of spec.md>
Platform: <iOS/Android>
Project directory: <workdir>/repo
User context: <details from discussion>

Output one file:
~/Projects/Finom/workdir/<STORY-KEY>/spec-<SUBTASK-KEY>.md
Content: exact files to create/modify, step-by-step changes, acceptance criteria checklist,
code patterns to follow, how this subtask fits into the overall story.
```

### 5c. Present results and offer to implement

Show the user:
- Spec file: `<workdir>/spec-<SUBTASK-KEY>.md`
- Brief summary of the implementation plan
- Any open questions or risks

Ask: "Перейти к имплементации?" — if yes, proceed directly to `/implement <SUBTASK-KEY>`.
