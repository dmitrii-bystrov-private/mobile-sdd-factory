---
description: Prepare a technical specification for a Jira task — read the task, discuss with the user, then delegate deep research and spec writing to an Opus subagent

TRIGGER when: user mentions a Jira key (e.g. ANDR-12345, IOS-67890) or a Jira URL (e.g. https://pnlfintech.atlassian.net/browse/IOS-12007) together with intent to work on it — plan, implement, start, tackle, pick up, figure out, break down, spec out, or any similar phrasing in any language.
DO NOT TRIGGER when: user only asks to view, check status, or discuss a task without intent to implement it.
---

Prepare a technical specification for a Jira task. Argument: Jira key (e.g. `/spec ANDR-12345` or `/spec IOS-67890`).

> **IMPORTANT: This skill produces a spec file only. Do NOT modify any project source files. Implementation is done separately via `/implement`.**

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

### 2. Set up workdir and worktree

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
2. Create the worktree from the fresh master:
   ```bash
   git -C <project_dir> worktree add <workdir>/repo -b <branch-name>
   ```

If it already exists, skip creation.

### 3. Discuss the task with the user

**Always do this before launching the spec-writer agent.** Present a brief summary of what you understood from Jira, then ask the user to clarify or add context:

- Summarize the task in 2–3 sentences in your own words
- Ask if there are details, edge cases, or implementation ideas not captured in Jira
- Ask if there are any constraints or decisions already made (e.g. "we already decided to use X approach")

**Wait for the user's response before proceeding.**

### 4. Launch the spec-writer agent

Use the Agent tool to launch the `spec-writer` subagent (runs on Opus) with all collected context:

```
Write a technical spec for Jira task <JIRA-KEY>.

Task summary: <summary from Jira>
Description: <description from Jira>
Acceptance criteria: <criteria from Jira>
Comments: <comments from Jira — may contain refined requirements or decisions that override the description>
Platform: <iOS/Android>
Project directory: <project_dir>
Spec output path: ~/Projects/Finom/workdir/<TASK-KEY>/spec.md

User context: <any details, constraints, or decisions from the discussion in step 3>
```

Wait for the agent to complete.

### 5. Handle decomposition (if proposed)

If the spec-writer agent recommends decomposition into subtasks:
- Present the proposed breakdown to the user for approval
- After approval, create subtasks in Jira:
  ```
  acli jira workitem create --summary "<subtask title>" --project "<PROJECT>" --type Subtask --parent <JIRA-KEY>
  ```
- Always confirm before creating subtasks (mutating Jira)
- If multiple subtasks need individual specs, launch the spec-writer agent again for each

### 6. Present results

Show the user:
- Spec file: `~/Projects/Finom/workdir/<TASK-KEY>/spec.md`
- Worktree: `~/Projects/Finom/workdir/<TASK-KEY>/repo` on branch `<branch-name>`
- Brief summary of the implementation plan
- Checklist findings (failed items only, if any)
- Any open questions or risks identified
- Suggest next step: `/implement <JIRA-KEY>`
