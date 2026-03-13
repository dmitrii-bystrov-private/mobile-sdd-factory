# Shared rules for all agents

These rules apply to every agent spawned from this project.

## Code quality

- Do not leave review/QA tracking markers in code (e.g. `// Issue 2:`, `// QA:`, `// Fix:`). Write clean code; if a non-obvious decision needs explanation, describe *why* without referencing ticket numbers.
- `// TODO: JIRA-XXXX` comments that link to a ticket for planned future work are acceptable.
- Do not make changes beyond the scope described in the spec or QA feedback file.

## RAG tools

RAG tools (ios-rag, android-rag) index only the `master` branch. Do NOT use RAG to read files that exist only on a feature branch — use Read, Grep, and Glob directly instead.

## Git

Always use `git -C <path> <command>` instead of `cd <path> && git <command>`. Compound `cd + git` commands trigger a permission prompt.
