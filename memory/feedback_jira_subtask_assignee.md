---
name: Jira subtask assignee
description: When creating Jira subtasks, always assign them to the same person as the parent story
type: feedback
---

When creating subtasks in Jira, always include `--assignee` set to the parent story's assignee.

**Why:** User expects subtasks to be assigned immediately — unassigned subtasks get lost in the backlog.

**How to apply:** Before creating subtasks, read the parent story's assignee (from `acli jira workitem view --json | jq -r '.fields.assignee.emailAddress'`). Pass that email via `--assignee` to every `acli jira workitem create` call.
