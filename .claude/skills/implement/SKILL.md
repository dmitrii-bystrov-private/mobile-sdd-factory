---
name: implement
description: Implement a task from its spec using the implementer subagent, then review the result
TRIGGER when: user asks to implement, code, execute, or build a task that already has a spec — or says "implement" after running /spec.
DO NOT TRIGGER when: user asks to create a spec (that is the /spec skill), or asks about implementation without intent to start coding.
---

Implement a Jira task from its spec file. Argument: Jira key (e.g. `/implement ANDR-12345` or `/implement IOS-12033`).

## Steps

### 1. Locate the spec and worktree

**Resolve workdir and spec path:**

Load the task from Jira to check if it is a subtask:
```bash
acli jira workitem view <TASK-KEY> --json
```

- If it is a **subtask**: `<workdir>` = `~/Projects/Finom/workdir/<STORY-KEY>` (parent's workdir), spec file = `<workdir>/spec-<TASK-KEY>.md`
- If it is a **story**: `<workdir>` = `~/Projects/Finom/workdir/<TASK-KEY>`, spec file = `<workdir>/spec-<TASK-KEY>.md`

Read the spec file. If it does not exist, tell the user and suggest running `/spec <TASK-KEY>` first.

Also read the high-level `<workdir>/spec.md` as background context if it exists.

Verify the worktree exists:
```bash
ls <workdir>/repo
```

If it does not exist, tell the user and suggest running `/spec <STORY-KEY>` first.

The worktree at `<workdir>/repo` is the working directory for all implementation — not the main project directory.

### 2. Launch the implementer agent

Use the Agent tool to launch the `implementer` subagent:

```
Implement the task following the spec at <workdir>/spec-<TASK-KEY>.md

Read the spec first, then follow the implementation plan step by step.
Project directory: <workdir>/repo

Background context (high-level architecture): <workdir>/spec.md
```

Wait for the agent to complete and capture its summary.

### 3. Review the implementation

After the agent finishes, review the changes yourself:

1. **iOS only — always regenerate Xcode project after implementation:**
   ```bash
   mise exec -- tuist generate --no-open --path <workdir>/repo
   pod install --project-directory <workdir>/repo
   ```
   Run this unconditionally for any iOS task — SourceKit errors like "No such module" are caused by a stale project, not by bad code.

2. Read the spec's acceptance criteria and implementation plan.
3. Read each modified file and verify:
   - Changes match what the spec describes
   - Code follows existing patterns referenced in the spec
   - No files outside the spec's scope were modified
   - No obvious bugs, missing imports, or broken logic
4. Use RAG tools (ios-rag / android-rag) to cross-check patterns if needed.

### 4. Handle issues

If you find problems:
1. List each issue clearly.
2. Launch the implementer agent again with specific fix instructions:
   ```
   Fix the following issues in the implementation of <TASK-KEY>:
   1. <issue description + file + what to fix>
   2. ...

   Spec file: <workdir>/spec-<TASK-KEY>.md
   Project directory: <workdir>/repo
   ```
3. Review again after fixes. Repeat until satisfied.

### 5. Commit

Once the implementation is reviewed and correct, commit the changes:

```bash
git -C <workdir>/repo add -A
git -C <workdir>/repo commit -m "<TASK-KEY>: <subtask summary from Jira>"
```

Confirm the commit was created successfully.

### 6. Check remaining work and suggest next step

**If the task is a subtask:**

1. Run the `send-to-test` skill to post a QA comment and transition the subtask to Ready for test:
   ```
   /send-to-test <TASK-KEY>
   ```

2. Fetch all subtasks of the parent story and their statuses:
   ```bash
   acli jira workitem search --jql "parent = <STORY-KEY>" --fields key,summary,status
   ```
   - If there are subtasks still in **To Do** or **In Progress** → list them and suggest: `/spec <NEXT-SUBTASK-KEY>`
   - If **all subtasks are Done / Ready for test / Resolved** → suggest: `/create-mr <STORY-KEY>`

**If the task is a story (no subtasks):**

Suggest: `/create-mr <STORY-KEY>`

### 7. Report results

Present to the user:
- Summary of what was implemented
- List of files changed
- Commit hash and message
- Any remaining concerns or manual steps needed
- Next step (per step 6)
