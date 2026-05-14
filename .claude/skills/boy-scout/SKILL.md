---
description: >
  Boy Scout pass: scan changed code for SOLID/DRY/code-quality improvement opportunities, present findings,
  and optionally create Jira subtasks or tech-debt stories. Runs silently when nothing is found.
  Can be invoked standalone: /boy-scout <KEY>.
---

Run a Boy Scout pass for Jira task `$ARGUMENTS`.

Parse `<KEY>` from `$ARGUMENTS`. If missing, ask for it.

## Step 0 — Check feature flag

```bash
echo "${BOY_SCOUT_ENABLED:-false}"
```

If the output is not `true` — stop immediately with no output. Do not proceed to Step 1.
This skill is opt-in. Enable it by setting `BOY_SCOUT_ENABLED=true` in `.claude/settings.local.json` under the `env` key.

## Step 1 — Generate diff

```bash
bash scripts/generate-diff.sh <KEY>
```

This writes `$SDD_WORKDIR/<KEY>/spec/diff.md`.

## Step 2 — Pre-check signals

Read `$SDD_WORKDIR/<KEY>/spec/diff.md` and decide whether the branch has strong enough signals for a Boy Scout pass.

Use these rules:
- **Skip silently** when the diff looks tiny and local:
  - `<= 2` source files
  - no shared/core/infrastructure paths
  - no structural file types like coordinator/assembly/router/manager/repository/service/factory/module/presenter/view model/interactor/use case
  - looks like copy/text/config/wiring-only work
- **Run automatically** when the diff has strong structural signals:
  - multiple source files or feature areas
  - shared/core/infrastructure changes
  - public interfaces or structural file types changed
  - repeated similar changes across files
- **Ask the user before running** when the diff is borderline:
  - neither clearly tiny/local nor clearly structural

If the diff is borderline, ask:

```
Boy Scout signals are mixed for <KEY>. Run the improvement scan?

1. **Run now** — perform the Boy Scout pass
2. **Skip** — continue without it
```

If the user chooses Skip, stop immediately with no output.

## Step 3 — Scan for improvements

Clear any stale findings file before invoking the scout:

```bash
rm -f "$SDD_WORKDIR/<KEY>/spec/findings.md"
```

Check whether deferred findings exist from previous sessions:

```bash
ls "$SDD_WORKDIR/<KEY>/spec/scout-deferred.md" 2>/dev/null && echo "exists" || echo "missing"
```

If the file exists, include `Deferred: $SDD_WORKDIR/<KEY>/spec/scout-deferred.md` in the scout invocation.

Invoke the `code-scout` subagent:

```
Key: <KEY>
Diff: $SDD_WORKDIR/<KEY>/spec/diff.md
Project directory: $SDD_WORKDIR/<KEY>/repo
Context dir: $SDD_WORKDIR/<KEY>/spec/context
Output: $SDD_WORKDIR/<KEY>/spec/findings.md
Deferred: $SDD_WORKDIR/<KEY>/spec/scout-deferred.md   ← include only if file exists
```

## Step 4 — Read result

Read the **first line** of `$SDD_WORKDIR/<KEY>/spec/findings.md`:

- `SCOUT_RESULT: clean` → print "No improvement opportunities found." Stop — caller continues.
- `SCOUT_RESULT: findings_found` → proceed to Step 5.

## Step 5 — Present findings

Read the full `spec/findings.md` and present each finding to the user in a readable format.

Then ask:

```
Boy Scout found N improvement opportunity(-ies). How would you like to handle them?

1. **Implement now** — apply all improvements directly in the current worktree
2. **Subtasks** — create a subtask on <KEY> for each finding; continue the flow after
3. **Tech-debt stories** — create a separate Story in the backlog for each finding; continue the flow after
```

Wait for user choice.

## Step 6 — Handle choice

### Implement now

For each finding in `spec/findings.md`, invoke the `implementer` subagent with:

```
Key: <KEY>
Repo dir: $SDD_WORKDIR/<KEY>/repo
Task: Apply the following Boy Scout improvement to the codebase:

<finding title>
<finding problem>
<finding suggestion>
<finding files>
```

Stop — caller continues.

### Subtasks

Derive `<PROJECT>` from `<KEY>` (e.g. `IOS-1234` → `IOS`, `ANDR-5678` → `ANDR`).

First, create a temp directory for description files:

```bash
mkdir -p "/tmp/sdd-findings/<KEY>"
```

For each finding extracted from `spec/findings.md`:

1. Write its description to `/tmp/sdd-findings/<KEY>/<N>-description.md`:

   ```markdown
   ## <finding title>

   **Files**: <files>
   **Principle**: <principle>

   ### Problem

   <problem>

   ### Suggestion

   <suggestion>
   ```

2. Run:
   ```bash
   bash scripts/create-subtask.sh \
     --parent <KEY> \
     --title "<finding title>" \
     --description "/tmp/sdd-findings/<KEY>/<N>-description.md"
   ```

3. Collect the returned subtask key.

After all subtasks are created, append each finding title to `$SDD_WORKDIR/<KEY>/spec/scout-deferred.md`:

```bash
echo "- <finding title> (<SUBTASK-KEY>)" >> "$SDD_WORKDIR/<KEY>/spec/scout-deferred.md"
```

Then report the list:

```
Created improvement subtasks on <KEY>:
- <SUBTASK-KEY-1>: <title>
- <SUBTASK-KEY-2>: <title>
```

Stop — caller continues to doc-harvest.

### Tech-debt stories

Derive `<PROJECT>` from `<KEY>`.

First, create a temp directory for description files:

```bash
mkdir -p "/tmp/sdd-findings/<KEY>"
```

For each finding extracted from `spec/findings.md`:

1. Write its description to `/tmp/sdd-findings/<KEY>/<N>-description.md` (same format as above).

2. Run:
   ```bash
   bash scripts/create-issue.sh \
     --project <PROJECT> \
     --type Story \
     --summary "[Tech debt] <finding title>" \
     --description-file "/tmp/sdd-findings/<KEY>/<N>-description.md"
   ```

3. Collect the returned story key and URL.

After all stories are created, append each finding title to `$SDD_WORKDIR/<KEY>/spec/scout-deferred.md`:

```bash
echo "- <finding title> (<STORY-KEY>)" >> "$SDD_WORKDIR/<KEY>/spec/scout-deferred.md"
```

Then report the list:

```
Created tech-debt stories:
- <STORY-KEY-1>: <title> — <URL>
- <STORY-KEY-2>: <title> — <URL>
```

Stop — caller continues to doc-harvest.

## Rules

- MUST stop silently (no output except "No improvement opportunities found.") when `SCOUT_RESULT: clean`.
- MUST NOT auto-create tasks without user confirmation.
- MUST continue (return control to caller) after creating tasks — do not halt the flow.
- MUST derive project key from the Jira key prefix.
- MUST write individual finding description files to `/tmp/sdd-findings/<KEY>/` before calling create scripts.
