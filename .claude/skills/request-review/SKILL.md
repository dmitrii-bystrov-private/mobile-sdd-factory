---
description: >
  Post an MR to the team Slack channel for review.
  TRIGGER when the user asks to send/post/share/submit an MR for review or post it to Slack.
  Examples: "send MR for review", "post MR to channel", "share MR", "request review".
  DO NOT TRIGGER for general MR questions, code reviews, or non-Slack tasks.
---

Post an MR to the team Slack channel for review. Arguments: `$ARGUMENTS`

## Combined invocation

If the message also contains an intent to send a task to testing (e.g. "send to test and request review"), execute **both** skills sequentially:
1. Complete all steps of `send-to-test` first.
2. Then complete all steps of this skill.

Collect all required parameters for both upfront, show a combined preview, confirm once, then execute both.

## Slack channel IDs
- iOS → `G01G6PSQT2L` (`#ios`)
- Android → `G01FP4KAKSQ` (`#android_dev`)

## Step 1 — Collect parameters

Parse `$ARGUMENTS`. Extract:
- **MR URL or ID** (required) — full GitLab URL or numeric MR ID
- **platform** — infer from URL if possible, else ask:
  - URL contains `finomcommon` or `/ios/` → iOS
  - URL contains `finom` (Android repo) → Android

If MR ID is provided without a URL, ask which platform it belongs to.

Extract the numeric MR ID from the URL if a full URL was given.

## Step 2 — Fetch MR details

Run from the appropriate project directory:
- iOS: `cd /Users/d.bystrov/Projects/Finom/finomcommon && glab mr view <id>`
- Android: `cd /Users/d.bystrov/Projects/Finom/finom && glab mr view <id>`

From the output extract:
- **title** — MR title (should already include Jira key, e.g. `IOS-11987: ...`)
- **web_url** — base MR URL (append `/diffs` for the final link)
- **diff stats** — typically shown as `N files changed, X insertions(+), Y deletions(-)`

## Step 3 — Format message

Build the Slack message in this exact format:
```
<title>
<web_url>/diffs
<N> files +<additions> −<deletions>
```

Example:
```
IOS-11987: Improve build info screen to better distinguish Beta and Prod builds
https://gitlab.com/M69/mobile/ios/finomcommon/-/merge_requests/2867/diffs
3 files +19 −4
```

If diff stats are unavailable, omit the third line.

## Step 4 — Preview and confirm

Show the formatted message and the target channel. Ask: "Отправить в #<channel>?" — wait for explicit confirmation.

## Step 5 — Send to Slack

Use `slack_send_message` with the hardcoded channel ID. No search needed.

On success, confirm: "✓ Отправлено в #<channel>"
On error, show the error and suggest what to fix.
