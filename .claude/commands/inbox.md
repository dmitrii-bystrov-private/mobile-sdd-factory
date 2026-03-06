Triage my email inbox.

1. Fetch the list of unread messages:
   `gws gmail users messages list --params '{"userId":"me","q":"is:unread","maxResults":20}'`

2. For each message, retrieve subject, from, and snippet via:
   `gws gmail users messages get --params '{"userId":"me","id":"<id>","format":"metadata","metadataHeaders":["Subject","From","Date"]}'`

3. Group messages into categories:
   - 🔴 **Needs reply** — questions, requests, waiting for a decision
   - 🟡 **FYI** — notifications, reports, informational
   - 🟢 **Can archive** — automated alerts, newsletters, digests

For each message in "Needs reply", suggest a short action plan (1 line).
