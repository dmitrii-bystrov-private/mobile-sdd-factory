# ios-rag / android-rag — MCP codebase search

Connected via `.mcp.json`. **Requires VPN** — if tools fail or time out, connect to VPN first.

**Index limitation:** rebuilt once per day from `master` only. Local changes and feature branches are **not indexed** — for recently modified or unmerged files, fall back to local tools (Grep, Glob, Read).

## Tools

- `semantic_search` — **default** for high-level or fuzzy questions (behavior, flows, screens, features). Use when the query reads like natural language.
- `search` — precise lookup by exact identifiers (class/function/protocol names). Use when most tokens look like code identifiers. OK to pass multiple identifiers in one query.
- `graph_neighbors` — explore dependencies (`direction="in"/"out"/"both"`). `out` = what this block depends on; `in` = who depends on it.
- `read_file` — read file by relative path from the RAG index.

## Usage patterns

- For any non-trivial task: `semantic_search` to find 1–3 relevant blocks → `graph_neighbors` on each key block to explore context.
- Do NOT use `search` for natural-language descriptions — use `semantic_search` instead.
- All paths returned by RAG tools are relative to the repository root.
