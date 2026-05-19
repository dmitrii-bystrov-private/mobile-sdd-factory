---
description: >
  Create or enrich one or more feature-level README.md files from structured branch diff anchors and selective source reads.
  Can be invoked standalone after a story is complete.
  TRIGGER when the user explicitly asks to run doc-harvest for a key.
---

Parse `<KEY>` from `$ARGUMENTS`. If missing, ask for it.

This skill defines the legacy slash-command doc-harvest surface. The current primary product flow runs doc harvest through the backend session runtime and workflow policy.

## Step 0 — Check feature flag

```bash
echo "${DOC_HARVEST_ENABLED:-false}"
```

If the output is not `true` — stop immediately with no output. Do not proceed.
This env flag gates the legacy slash-command surface only. The current platform normally configures doc-harvest policy through `.sdd-factory/settings.local.json` and the operator UI.

## Step 1 — Run harvest

Invoke the `doc-harvest` subagent with key `<KEY>`.

The agent resolves targets in this order:
- changed README / doc anchors already present on the branch
- nearby existing docs for changed code
- feature discovery from code structure only as a fallback

It may update multiple READMEs when the branch genuinely spans multiple documented areas, and it may skip with an explicit explanation when targets are ambiguous.
