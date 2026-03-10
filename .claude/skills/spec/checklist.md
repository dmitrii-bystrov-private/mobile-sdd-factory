# Spec Quality Checklist

## Task understanding
- [ ] Jira summary and description fully read
- [ ] Acceptance criteria extracted and listed
- [ ] Clarifying questions asked (if any ambiguities found)

## Codebase research
- [ ] Relevant screens / features found via semantic_search
- [ ] Key files to modify identified
- [ ] Dependencies mapped via graph_neighbors
- [ ] Existing patterns documented (not just file paths — how they work)

## Plan quality
- [ ] Each step is concrete and actionable (not vague like "implement X")
- [ ] Steps are in a logical execution order (dependencies first)
- [ ] No step requires knowledge that isn't in the spec itself
- [ ] Out-of-scope section prevents scope creep

## Decomposition (if applied)
- [ ] Each subtask is independently deliverable
- [ ] No subtask depends on another that hasn't been specced yet
- [ ] Subtask keys match the Jira subtasks created

## Completeness
- [ ] Platform and module clearly stated
- [ ] All files to modify listed with reason
- [ ] All files to read (contracts, interfaces) listed
- [ ] Acceptance criteria map to concrete steps in the plan
- [ ] Edge cases and gotchas captured in Notes
