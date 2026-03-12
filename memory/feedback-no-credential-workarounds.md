---
name: No credential workarounds
description: Never try to find API tokens, passwords, or credentials to work around tool limitations
type: feedback
---

# NEVER attempt to find credentials as a workaround

If a CLI tool (acli, glab, etc.) cannot perform an action, **do NOT try to work around it** by:
- Reading config files for tokens or passwords
- Searching for API keys in environment variables, keychains, or config directories
- Using curl or direct REST API calls with extracted credentials
- Any other approach that involves locating and using auth secrets

**Why:** This is a security boundary. The user controls what tools can do and does not want credentials exposed or used outside of the designated tools.

**How to apply:** If a tool cannot do something, explain the limitation clearly and tell the user what to do manually (e.g. via web UI). Stop there. Do not search for alternative auth paths.
