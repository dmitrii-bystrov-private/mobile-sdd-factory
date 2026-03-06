Show MRs that need my attention.

1. MRs where I am a reviewer:
   `glab mr list --state opened --reviewer @me --output json | jq '[.[] | {id:.iid, title:.title, author:.author.username, created:.created_at, url:.web_url}]'`

2. My MRs without approval (stuck in review):
   `glab mr list --state opened --assignee @me --output json | jq '[.[] | {id:.iid, title:.title, reviewers:[.reviewers[].username], url:.web_url}]'`

For each MR from step 1, show:
- Title and URL
- Author and creation date
- How many days it has been waiting in review

Sort by date (oldest first). Flag with 🔴 if the MR has been open for more than 2 days.
