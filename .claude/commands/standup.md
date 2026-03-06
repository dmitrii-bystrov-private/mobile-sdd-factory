Compile my daily standup. Run the following steps in parallel:

1. **GitLab** — my open MRs (`glab mr list --state opened --assignee @me`) and MRs where I am a reviewer (`glab mr list --state opened --reviewer @me`)
2. **Jira** — current backlog via saved filter 10494 (`acli jira workitem search --filter 10494 --fields key,summary,status,priority`)
3. **Gmail** — unread messages from today (`gws gmail users messages list` with filter `is:unread newer_than:1d`)

Produce a summary in the following format:

**Yesterday / In progress**
- ...

**Today's plan**
- ...

**Blockers / needs attention**
- ...

Be concise. Do not list every task — only what requires action today.
