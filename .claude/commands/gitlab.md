Show MRs that need my attention.

Run `bash gitlab.sh` — it fetches all data in parallel and filters out already approved MRs.

Output format (pipe-separated): `platform|!id|title|author|date|stats`

Produce a summary in the following format:

**На ревью** (oldest first, only unapproved):
| Платформа | MR | Автор | Дата | Размер |
|-----------|-----|-------|------|--------|

**Мои MR без апрува:**
| Платформа | MR | Ревьюеры |
|-----------|-----|---------|

Show plain titles, not markdown links. If a section is empty — say "нет".
