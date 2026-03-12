---
name: iOS/Android code verification before fixing
description: When investigating iOS or Android project configs, always verify each finding against current code before applying a fix
type: feedback
---

Verify each finding against the current code and only fix it if needed.

**Why:** Avoid unnecessary changes in mobile projects — static analysis or assumptions may not reflect the actual current state of the code.

**How to apply:** When asked to fix or update something in iOS/Android project files, read the relevant file first and confirm the issue actually exists before making any edit.
