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
$SDD_WORKDIR/<STORY-KEY>/
├── description.md             # parent issue: metadata + rendered description (snapshot)
├── comments.md                # parent issue: all comments (snapshot)
├── statuses.md                # parent + subtasks status table (snapshot)
├── spec.md                    # always: high-level plan + architecture for the whole story
├── spec-<STORY-KEY>.md        # detailed spec — only when the story has NO subtasks
├── spec-<SUBTASK-KEY>.md      # detailed spec per subtask — when the story has subtasks
├── repo/                      # single git worktree for the entire story
└── <SUBTASK-KEY>/
    ├── description.md         # subtask: metadata + rendered description (snapshot)
    └── comments.md            # subtask: all comments (snapshot)
```

## Steps

### 1. Resolve parent key and platform

If no argument is given, ask for the Jira key.

Run a minimal Jira fetch to determine issue type and parent:

```bash
acli jira workitem view <JIRA-KEY> --fields 'issuetype,parent,project' --json
```

- If `fields.issuetype.subtask == true` → this is a **subtask**; extract `<STORY-KEY>` from `fields.parent.key`
- Otherwise → `<STORY-KEY>` = `<JIRA-KEY>`

Determine platform from the key prefix:
- `IOS-XXXXX` → iOS → `$IOS_DIR`
- `ANDR-XXXXX` → Android → `$ANDROID_DIR`

### 2. Run snapshot

```bash
bash scripts/snapshot.sh <STORY-KEY>
```

This will:
- Fetch all Jira data (parent + subtasks) and write snapshot files
- Create the git worktree at `$SDD_WORKDIR/<STORY-KEY>/repo/` (or skip if it already exists)
- Run iOS bootstrap if applicable (tuist, pods)

If the script exits with code 1, stop and report the error to the user.
If it exits with code 2 (partial success), note which subtasks failed but continue.

### 3. Determine task mode

Read `$SDD_WORKDIR/<STORY-KEY>/statuses.md` to understand the task structure:

- **Subtask** — `<JIRA-KEY>` differs from `<STORY-KEY>` (subtask was passed) → [Subtask mode](#subtask-mode)
- **Story without subtasks** — no subtask rows in `statuses.md` → [Story mode (no subtasks)](#story-mode-no-subtasks)
- **Story with subtasks** — subtask rows present in `statuses.md` → [Story mode (with subtasks)](#story-mode-with-subtasks)

### 3a. Check for existing work (resume detection)

Check if `spec.md` already exists:

```bash
ls "$SDD_WORKDIR/<STORY-KEY>/spec.md" 2>/dev/null
```

If `spec.md` **already exists** and the task is a **story with subtasks** → **Resume mode**:

1. Read `$SDD_WORKDIR/<STORY-KEY>/statuses.md` for current statuses (already refreshed by snapshot).
2. Show the user a status summary:
   ```
   Story: <STORY-KEY> — <summary>
   Branch: feature/<STORY-KEY>

   Subtasks:
   ✓ IOS-XXXXX  Done/Ready for test/Resolved  — <summary>
   ↩ IOS-XXXXX  Reopened                       — <summary>
   ○ IOS-XXXXX  To Do                          — <summary>
   ```
3. Suggest the next action based on subtask statuses — **priority order**:
   - If any subtask is **Reopened** → "Следующий шаг: `/fix-review <REOPENED-KEY>`"
   - Else if any subtask is **In Progress** → "Следующий шаг: `/implement <IN-PROGRESS-KEY>`"
   - Else if any subtask is **To Do** and has a spec file → "Следующий шаг: `/implement <NEXT-KEY>`"
   - Else if any subtask is **To Do** without a spec → "Следующий шаг: `/spec <NEXT-KEY>`"
   - If all subtasks are Done/Ready for test/Resolved → "Все подзадачи завершены. Следующий шаг: `/create-mr <STORY-KEY>`"
4. **Stop here** — do not re-run spec-writer for the story.

If `spec.md` **already exists** and the task is a **story without subtasks**:
- Check if `spec-<STORY-KEY>.md` also exists.
- If yes → show existing spec summary, suggest `/implement <STORY-KEY>`. Stop.
- If no → continue normally (write the detailed spec only).

If `spec.md` does **not** exist → continue with normal flow below.

---

## Story mode (no subtasks)

### 4a. Discuss the task with the user

Read `$SDD_WORKDIR/<STORY-KEY>/description.md` and `$SDD_WORKDIR/<STORY-KEY>/comments.md` for full context.

Present a brief summary of what you understood, then ask the user to clarify or add context:
- Summarize the task in 2–3 sentences
- Ask about details, edge cases, or implementation ideas not captured in Jira
- Ask about any constraints or decisions already made

**Wait for the user's response before proceeding.**

### 5a. Launch the spec-writer agent

Launch the `spec-writer` subagent (runs on Opus) to write **both** spec files:

```
Write a technical spec for Jira task <JIRA-KEY>.

Task description file: $SDD_WORKDIR/<JIRA-KEY>/description.md
Task comments file:    $SDD_WORKDIR/<JIRA-KEY>/comments.md
Platform: <iOS/Android>
Project directory: <project_dir>
User context: <details from discussion>

Output two files:
1. $SDD_WORKDIR/<JIRA-KEY>/spec.md
   High-level: goals, architecture overview, key decisions, risks.

2. $SDD_WORKDIR/<JIRA-KEY>/spec-<JIRA-KEY>.md
   Detailed implementation plan: exact files to create/modify, step-by-step changes,
   acceptance criteria checklist, code patterns to follow.
```

### 6a. Present results

Show the user:
- Spec files: `spec.md` and `spec-<JIRA-KEY>.md`
- Worktree: `$SDD_WORKDIR/<JIRA-KEY>/repo` on branch `<branch-name>`
- Brief summary of the plan
- Any open questions or risks
- Suggest next step: `/implement <JIRA-KEY>`

---

## Story mode (with subtasks)

### 4b. Discuss the task with the user

Read `$SDD_WORKDIR/<STORY-KEY>/description.md`, `$SDD_WORKDIR/<STORY-KEY>/comments.md`, and `$SDD_WORKDIR/<STORY-KEY>/statuses.md` for full context.

Present a brief summary, then discuss:
- Summarize the story in 2–3 sentences
- Ask about details, edge cases, or implementation ideas not captured in Jira
- Ask: are the existing subtasks correct and complete, or does the story need to be decomposed first?

**Wait for the user's response before proceeding.**

### 5b. Launch the spec-writer agent

Launch the `spec-writer` subagent to write the high-level spec only:

```
Write a high-level technical spec for Jira story <STORY-KEY>.

Story description file: $SDD_WORKDIR/<STORY-KEY>/description.md
Story comments file:    $SDD_WORKDIR/<STORY-KEY>/comments.md
Subtask statuses file:  $SDD_WORKDIR/<STORY-KEY>/statuses.md
Platform: <iOS/Android>
Project directory: <project_dir>
User context: <details from discussion>

Output one file:
$SDD_WORKDIR/<STORY-KEY>/spec.md
Content: goals, architecture overview, key decisions, how subtasks relate to each other, risks.
Do NOT write detailed per-subtask specs — those are written separately per subtask.
```

### 6b. Handle decomposition (if needed)

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
- After creating subtasks, re-run snapshot to refresh the workspace:
  ```bash
  bash scripts/snapshot.sh <STORY-KEY>
  ```

### 7b. Present results

Show the user:
- Spec file: `spec.md`
- Worktree: `$SDD_WORKDIR/<STORY-KEY>/repo` on branch `<branch-name>`
- List of subtasks (existing or newly created)
- Suggest next step: `/spec <SUBTASK-KEY>` to write the first detailed subtask spec

---

## Subtask mode

### 4c. Read context

Read the following files:
- `$SDD_WORKDIR/<STORY-KEY>/spec.md` — parent's high-level spec (if exists)
- `$SDD_WORKDIR/<STORY-KEY>/<SUBTASK-KEY>/description.md` — subtask details
- `$SDD_WORKDIR/<STORY-KEY>/<SUBTASK-KEY>/comments.md` — subtask comments

### 5c. Discuss the subtask with the user

- Summarize what you understood from the snapshot files and parent spec
- Ask about implementation details, edge cases, or constraints specific to this subtask
- Ask if there are decisions from other already-implemented subtasks to be aware of

**Wait for the user's response before proceeding.**

### 6c. Launch the spec-writer agent

Launch the `spec-writer` subagent with full context:

```
Write a detailed implementation spec for subtask <SUBTASK-KEY> (part of story <STORY-KEY>).

Subtask description file: $SDD_WORKDIR/<STORY-KEY>/<SUBTASK-KEY>/description.md
Subtask comments file:    $SDD_WORKDIR/<STORY-KEY>/<SUBTASK-KEY>/comments.md
Parent story spec:        $SDD_WORKDIR/<STORY-KEY>/spec.md
Platform: <iOS/Android>
Project directory: $SDD_WORKDIR/<STORY-KEY>/repo
User context: <details from discussion>

Output one file:
$SDD_WORKDIR/<STORY-KEY>/spec-<SUBTASK-KEY>.md
Content: exact files to create/modify, step-by-step changes, acceptance criteria checklist,
code patterns to follow, how this subtask fits into the overall story.
```

### 7c. Present results and offer to implement

Show the user:
- Spec file: `$SDD_WORKDIR/<STORY-KEY>/spec-<SUBTASK-KEY>.md`
- Brief summary of the implementation plan
- Any open questions or risks

Ask: "Перейти к имплементации?" — if yes, proceed directly to `/implement <SUBTASK-KEY>`.
