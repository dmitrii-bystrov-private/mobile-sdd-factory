const ROLE_LABELS: Record<string, string> = {
  implementer: "Implementer",
  "verification-coordinator": "Verification Coordinator",
  "bug-fixer": "Bug Fixer",
  "code-reviewer": "Code Reviewer",
  "final-verifier": "Final Verifier",
  "code-scout": "Boy Scout",
  "mr-comments-analyst": "MR Comments Analyst",
  "doc-harvest-worker": "Doc Harvest",
  "doc-harvest": "Doc Harvest",
  "mr-comments-analyst-worker": "MR Comments Analyst",
  "proposal-context-worker": "Proposal Context",
  "context-collector": "Context Collector",
  "requirements-clarifier-worker": "Requirements Clarifier",
  "requirements-clarifier": "Requirements Clarifier",
  "acceptance-criteria-worker": "Acceptance Criteria",
  "acceptance-criteria-writer": "Acceptance Criteria",
  "constraints-worker": "Constraints",
  "constraints-definer": "Constraints",
  "spec-verifier-worker": "Spec Verifier",
  "spec-verifier": "Spec Verifier",
  "task-decomposer-worker": "Task Decomposer",
  "task-decomposer": "Task Decomposer",
};

export function roleDisplayName(roleName: string | null | undefined): string {
  if (!roleName) {
    return "unknown";
  }
  const known = ROLE_LABELS[roleName];
  if (known) {
    return known;
  }
  return roleName
    .split(/[-_]/)
    .filter((part) => part.length > 0)
    .map((part) => part[0].toUpperCase() + part.slice(1))
    .join(" ");
}
