Check iOS crash report from Firebase Crashlytics for the last 7 days.

iOS app ID: `1:174475617680:ios:565ee9f00f19a2eaefbf15` (project: finom-prod-279011)

Steps:
1. Call `crashlytics_get_report` with report=`topIssues`, filter `issueErrorTypes: [FATAL]`, pageSize=15
2. Call `crashlytics_get_report` with report=`topVersions`, filter `issueErrorTypes: [FATAL]`, pageSize=10
3. Call `crashlytics_get_report` with report=`topIssues`, filter `issueErrorTypes: [FATAL], issueSignals: [SIGNAL_FRESH]`, pageSize=10

Run all three in parallel.

Output format:

### Краши по версиям
Table: Version | Crashes (last 7 days). Only show versions with crashes > 0, plus the latest version even if 0.

### Топ крашей
Table: # | Users | Events | Description | Versions | Signal
- Description = short title (function name + error type)
- Signal = mark SIGNAL_REPETITIVE as ⚠️ repetitive, SIGNAL_REGRESSED as 🔴 regressed
- Sort by impactedUsersCount descending
- Show top 10

### Новые краши (за неделю)
List only SIGNAL_FRESH issues with more than 1 user. If all have 1 user — write "нет значимых новых крашей".

Keep it concise. Do not dump raw data.
