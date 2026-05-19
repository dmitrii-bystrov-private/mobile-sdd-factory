const STAGE_LABELS: Record<string, string> = {
  task_started: "Task Started",
  task_prepared: "Task Prepared",
  bug_analysis_requested: "Bug Analysis",
  proposal_context_requested: "Proposal Context",
  requirements_requested: "Requirements",
  acceptance_criteria_requested: "Acceptance Criteria",
  constraints_requested: "Constraints",
  spec_verification_requested: "Spec Verification",
  story_spec_requested: "Story Spec",
  task_decomposition_requested: "Task Decomposition",
  implementation_requested: "Implementation",
  subtask_creation_requested: "Subtask Creation",
  subtask_implementation_requested: "Subtask Implementation",
  self_review_requested: "Self Review",
  self_review_correction_requested: "Self Review Correction",
  boy_scout_requested: "Boy Scout",
  boy_scout_correction_requested: "Boy Scout Correction",
  verification_requested: "Verification",
  verification_correction_requested: "Verification Correction",
  qa_reopen_requested: "QA Reopen",
  mr_comments_analysis_requested: "MR Comments Analysis",
  mr_followup_requested: "MR Follow-up",
  doc_harvest_requested: "Doc Harvest",
  mr_handoff_completed: "MR Handoff Complete",
  mr_handoff_failed: "MR Handoff Failed",
  send_to_test_completed: "Sent To Test",
  send_to_test_failed: "Send To Test Failed",
  task_completed: "Task Completed",
};

export function stageDisplayName(stageName: string | null | undefined): string {
  if (!stageName) {
    return "unknown";
  }
  return (
    STAGE_LABELS[stageName] ??
    stageName
      .split("_")
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(" ")
  );
}
