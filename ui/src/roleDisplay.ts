const ROLE_LABELS: Record<string, string> = {
  implementer: "Implementer",
  "verification-coordinator": "Build Verifier",
  "bug-fixer": "Bug Fixer",
  "code-reviewer": "Code Reviewer",
  "convention-reviewer": "Convention Reviewer",
  "requirements-reviewer": "Requirements Reviewer",
  "final-verifier": "Final Verifier",
  "code-scout": "Code Scout",
  "mr-comments-analyst": "Comments Analyst",
  "doc-harvest-worker": "Documentation Writer",
  "doc-harvest": "Documentation Writer",
  "documentation-reviewer": "Documentation Reviewer",
  "mr-comments-analyst-worker": "Comments Analyst",
  "proposal-context-worker": "Context Builder",
  "context-collector": "Context Collector",
  "requirements-clarifier-worker": "Requirements Clarifier",
  "requirements-clarifier": "Requirements Clarifier",
  "acceptance-criteria-worker": "Acceptance Criteria",
  "acceptance-criteria-writer": "Acceptance Criteria",
  "constraints-worker": "Design Constraints",
  "constraints-definer": "Design Constraints",
  "spec-verifier-worker": "Spec Verifier",
  "spec-verifier": "Spec Verifier",
  "task-decomposer-worker": "Task Decomposer",
  "task-decomposer": "Task Decomposer",
};

const ROLE_DESCRIPTIONS: Record<string, string> = {
  implementer: "Delivers the code changes and correction passes for the active task or subtask.",
  "verification-coordinator": "Runs deterministic verification and decides whether the branch passes the gate.",
  "bug-fixer": "Carries bug-specific analysis and fixes across the full bug workflow.",
  "code-reviewer": "Checks the diff for correctness, regressions, and contract mismatches.",
  "convention-reviewer": "Checks the diff against local repository conventions and nearby code patterns.",
  "requirements-reviewer": "Checks the implementation against current Jira scope, follow-ups, edge cases, and regressions.",
  "code-scout": "Looks for maintainability and structural cleanup opportunities in the changed area.",
  "mr-comments-analyst": "Turns unresolved merge request comments into grouped follow-up work for the coding lane.",
  "mr-comments-analyst-worker": "Turns unresolved merge request comments into grouped follow-up work for the coding lane.",
  "doc-harvest-worker": "Updates feature-level docs and readme files from the completed diff.",
  "doc-harvest": "Updates feature-level docs and readme files from the completed diff.",
  "documentation-reviewer": "Checks docs and doc comments against the repository documentation guide.",
  "proposal-context-worker": "Builds the proposal and focused project context package before story planning starts.",
  "requirements-clarifier-worker": "Turns the proposal into explicit, implementable requirements.",
  "requirements-clarifier": "Turns the proposal into explicit, implementable requirements.",
  "acceptance-criteria-worker": "Converts requirements into clear, testable acceptance criteria.",
  "acceptance-criteria-writer": "Converts requirements into clear, testable acceptance criteria.",
  "constraints-worker": "Captures task-specific implementation constraints and architectural guardrails.",
  "constraints-definer": "Captures task-specific implementation constraints and architectural guardrails.",
  "spec-verifier-worker": "Reviews the planning package for contradictions and missing implementation detail.",
  "spec-verifier": "Reviews the planning package for contradictions and missing implementation detail.",
  "task-decomposer-worker": "Splits the verified story package into self-contained implementation tasks.",
  "task-decomposer": "Splits the verified story package into self-contained implementation tasks.",
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

export function roleDescription(roleName: string | null | undefined): string {
  if (!roleName) {
    return "Handles its routed part of the workflow.";
  }
  const known = ROLE_DESCRIPTIONS[roleName];
  if (known) {
    return known;
  }
  return "Handles its routed part of the workflow.";
}
