# acli — Jira Cloud CLI

Installed: `brew tap atlassian/homebrew-acli && brew install acli`
Auth: `acli jira auth login` (requires Atlassian account)

Saved filters:
- `10494` — current backlog: in-progress + todo tasks
- `10495` — tasks passed to testing

Common commands:
```
# My backlog (in progress + todo) — primary filter
acli jira workitem search --filter 10494 --fields key,summary,status,priority

# Tasks in testing
acli jira workitem search --filter 10495 --fields key,summary,status,priority

# View a work item
acli jira workitem view PROJ-123

# View a work item in browser
acli jira workitem view PROJ-123 --web

# Search with JQL
acli jira workitem search --jql "assignee = currentUser() AND status != Done ORDER BY priority DESC" --fields key,summary,status,priority

# Subtasks of a task — always use JQL parent query (never fields.subtasks from workitem view)
acli jira workitem search --jql "parent = PROJ-123 ORDER BY key ASC" --fields key,summary,status

# Create a work item
acli jira workitem create --summary "Title" --project "PROJ" --type Task

# Edit a work item
acli jira workitem edit --key PROJ-123 --summary "Updated title"

# List projects
acli jira project list
```

## JSON response structure

`--json` flag changes output format. **Do not use Jira REST API assumptions** — acli wraps responses differently:

- `workitem search --json` → returns a **JSON array** `[...]` directly (NOT `{"issues": [...]}`)
  ```bash
  # Correct jq for search results:
  acli jira workitem search ... --json | jq -r '.[] | "\(.key)\t\(.fields.status.name)\t\(.fields.summary)"'
  ```

- `workitem view --json` → returns a **single JSON object** (NOT wrapped in array)
  ```bash
  # Correct jq for single item:
  acli jira workitem view PROJ-123 --json | jq -r '"\(.fields.summary) | \(.fields.status.name)"'
  ```
