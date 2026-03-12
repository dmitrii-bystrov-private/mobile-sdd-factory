---
name: implement
description: Implement a task from its spec using the implementer subagent, then review the result
TRIGGER when: user asks to implement, code, execute, or build a task that already has a spec — or says "implement" after running /spec.
DO NOT TRIGGER when: user asks to create a spec (that is the /spec skill), or asks about implementation without intent to start coding.
---

Implement a Jira task from its spec file. Argument: Jira key (e.g. `/implement ANDR-12345`).

## Steps

### 1. Locate the spec and worktree

Set `<workdir>` = `~/Projects/Finom/workdir/<TASK-KEY>`.

Read the spec file at `<workdir>/spec.md`. If it does not exist, tell the user and suggest running `/spec <TASK-KEY>` first.

Verify the worktree exists:
```bash
ls <workdir>/repo
```

If it does not exist, tell the user and suggest running `/spec <TASK-KEY>` first (spec creates the worktree).

The worktree at `<workdir>/repo` is the working directory for all implementation work — not the main project directory.

### 2. Launch the implementer agent

Use the Agent tool to launch the `implementer` subagent:

```
Implement the task following the spec at ~/Projects/Finom/workdir/<TASK-KEY>/spec.md

Read the spec first, then follow the implementation plan step by step.
Project directory: ~/Projects/Finom/workdir/<TASK-KEY>/repo
```

Wait for the agent to complete and capture its summary.

### 3. Review the implementation

After the agent finishes, review the changes yourself:

1. Read the spec's acceptance criteria and implementation plan.
2. Read each modified file and verify:
   - Changes match what the spec describes
   - Code follows existing patterns referenced in the spec
   - No files outside the spec's scope were modified
   - No obvious bugs, missing imports, or broken logic
3. Use RAG tools (ios-rag / android-rag) to cross-check patterns if needed.

### 4. Handle issues

If you find problems:
1. List each issue clearly.
2. Launch the implementer agent again with specific fix instructions:
   ```
   Fix the following issues in the implementation of <TASK-KEY>:
   1. <issue description + file + what to fix>
   2. ...

   Spec file: ~/Projects/Finom/workdir/<TASK-KEY>/spec.md
   Project directory: ~/Projects/Finom/workdir/<TASK-KEY>/repo
   ```
3. Review again after fixes. Repeat until satisfied.

### 5. Report results

Present to the user:
- Summary of what was implemented
- List of files changed
- Any issues found and fixed during review
- Any remaining concerns or manual steps needed
- Suggest next steps: run tests, create MR, etc.
