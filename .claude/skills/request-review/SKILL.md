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

Generate a Slack-ready message with the script:

- iOS: `request-review.sh ios <id>`
- Android: `request-review.sh android <id>`

The script:
- Fetches MR title + URL via `glab api`
- Fetches diff stats (files/additions/deletions) if available
- Prints the final Slack message in the required format

## Step 3 — Format message

Use the script output verbatim (it already uses Slack-safe `<URL>` / `<URL|text>` formatting).

## Step 4 — Preview and confirm

Show the formatted message and the target channel. Ask: "Send to #<channel>?" — wait for explicit confirmation.

## Step 5 — Send to Slack

Use `slack_send_message` with the hardcoded channel ID. No search needed.

On success, confirm: "✓ Sent to #<channel>"
On error, show the error and suggest what to fix.

## Step 6 — Offer to send to testing

After successful Slack send, ask: "Send <JIRA-KEY> to testing?"

If the user confirms, invoke the `send-to-test` skill with the Jira key.
