Compile my daily standup.

Step 1: Run `bash standup.sh` — it fetches all data in parallel (GitLab iOS/Android + Jira).

Step 2: Fetch iOS crash data from Firebase Crashlytics in parallel:
- `crashlytics_get_report` appId=`1:174475617680:ios:565ee9f00f19a2eaefbf15`, report=`topIssues`, filter `issueErrorTypes:[FATAL]`, pageSize=10
- `crashlytics_get_report` appId=`1:174475617680:ios:565ee9f00f19a2eaefbf15`, report=`topVersions`, filter `issueErrorTypes:[FATAL]`, pageSize=5
- `crashlytics_get_report` appId=`1:174475617680:ios:565ee9f00f19a2eaefbf15`, report=`topIssues`, filter `issueErrorTypes:[FATAL], issueSignals:[SIGNAL_FRESH]`, pageSize=5

Produce a summary in the following format:

**Yesterday / In progress**
- ...

**Today's plan**
- ...

**Blockers / needs attention**
- ...

**iOS Crashes (last 7 days)**
- Top version by crashes: `vX.Y.Z — N crashes`
- Top issue: `<function name> — N users`
- New crashes (SIGNAL_FRESH with >1 user): list them or write "нет"

Be concise. Do not list every task — only what requires action today.

**Filtering rules:**
- Do NOT mention tasks with status "Waiting other platforms" — they require no action and are not relevant.
