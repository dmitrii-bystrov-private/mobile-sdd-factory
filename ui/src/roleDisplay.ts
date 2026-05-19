const ROLE_LABELS: Record<string, string> = {
  "task-coordinator": "Task Coordinator",
  implementer: "Implementer",
  "verification-coordinator": "Verification Coordinator",
  "bug-fixer": "Bug Fixer",
  "code-reviewer": "Code Reviewer",
  "code-scout": "Boy Scout",
  "doc-harvest-worker": "Doc Harvest",
  "mr-comments-analyst-worker": "MR Comments Analyst",
  "proposal-context-worker": "Proposal Context",
  "requirements-clarifier-worker": "Requirements Clarifier",
  "acceptance-criteria-worker": "Acceptance Criteria",
  "constraints-worker": "Constraints",
  "spec-verifier-worker": "Spec Verifier",
  "story-spec-worker": "Story Spec",
  "task-decomposer-worker": "Task Decomposer",
};

export function roleDisplayName(roleName: string | null | undefined): string {
  if (!roleName) {
    return "unknown";
  }
  return ROLE_LABELS[roleName] ?? roleName;
}
