# claude-assistant

Personal productivity assistant built on top of [Claude Code](https://claude.ai/claude-code).
Automates day-to-day iOS/Android development workflows: planning, implementation, code review, and release handoff.

## What it does

- Writes technical specs for Jira tasks (story-level and subtask-level)
- Implements code changes via AI subagents in isolated git worktrees
- Manages GitLab MRs: creates, reviews, and posts for review
- Handles Jira transitions: task creation, send to QA, status tracking
- Compiles daily standups from Jira + GitLab state
- Monitors Firebase Crashlytics crash reports

## Project layout

```
.claude/
├── skills/          # slash commands (/spec, /implement, /create-mr, etc.)
├── agents/          # subagents launched by skills (spec-writer, implementer)
├── commands/        # simple slash commands (/standup, /gitlab, /crashes)
└── hooks/           # pre/post hooks (e.g. spec validation)
docs/                # tool reference docs (acli, glab, rag)
scripts/             # shell scripts available in $PATH
memory/              # persistent memory across sessions
CLAUDE.md            # assistant rules and configuration
```

## Scripts

Standalone shell helpers live in `scripts/`. See `scripts/README.md`.

## Workflow

### Working on a task

```
/spec IOS-12345       # write high-level + detailed spec, set up worktree
/implement IOS-12345  # implement from spec, commit
/create-mr            # push branch and open GitLab MR
/request-review       # post MR to team Slack channel
/send-to-test         # add QA comment + transition to Ready for test
```

### Large stories with subtasks

```
/spec IOS-11860           # high-level spec.md + create subtasks in Jira
/spec IOS-12033           # detailed spec-IOS-12033.md (uses story's worktree)
/implement IOS-12033      # implement subtask, commit
/spec IOS-12035           # next subtask ...
/implement IOS-12035
/create-mr IOS-11860      # after all subtasks are done
```

Resuming work on an existing story:
```
/spec IOS-11860           # detects existing spec.md, shows subtask status, suggests next step
```

### Other commands

```
/standup    # daily standup from Jira + GitLab
/gitlab     # MRs waiting for my attention
/crashes    # iOS crash report from Firebase (last 7 days)
/review-mr  # review a GitLab MR with RAG codebase search
```

## Worktree layout

Each story gets its own workdir:

```
$SDD_WORKDIR/IOS-11860/
├── spec.md                  # high-level plan and architecture
├── spec-IOS-11860.md        # detailed spec (stories without subtasks)
├── spec-IOS-12033.md        # detailed spec per subtask
└── repo/                    # git worktree on branch feature/IOS-11860
```

## Tools

| Tool | Purpose |
|------|---------|
| `acli` | Jira Cloud CLI — tasks, transitions, comments |
| `glab` | GitLab CLI — MRs, pipelines, reviews |
| `ios-rag` / `android-rag` | MCP codebase semantic search |
| Firebase MCP | Crashlytics — crash reports, issue tracking |
| Notion MCP | Read Notion pages and databases |
| Slack MCP | Send messages, post MR reviews, read channels |

## Mobile projects

| Platform | Path |
|----------|------|
| iOS | `$IOS_DIR` |
| Android | `$ANDROID_DIR` |
