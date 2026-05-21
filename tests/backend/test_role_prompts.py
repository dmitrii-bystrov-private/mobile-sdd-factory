from __future__ import annotations

import unittest

from backend.roles.prompts import role_handoff_prompt


class RolePromptTests(unittest.TestCase):
    def test_live_bootstrap_prompt_is_agents_first_and_shorter(self) -> None:
        text = role_handoff_prompt(
            role_name="implementer",
            instruction="Start implementation work for IOS-123.",
            hydration_payload={
                "task_key": "IOS-123",
                "current_stage": "implementation_requested",
                "work_item_id": 1,
            },
            prompt_mode="live_bootstrap",
        )

        self.assertIn("Read AGENTS.md/CLAUDE.md in the current directory now", text)
        self.assertIn("Read `HYDRATION.json` in the current directory", text)
        self.assertIn("Current routed work:\nStart implementation work for IOS-123.", text)
        self.assertNotIn("You are a persistent SDD Factory role.", text)
        self.assertNotIn("Role-specific rules:", text)
        self.assertNotIn("Preferred terminal outcome path:", text)
        self.assertNotIn('"task_key": "IOS-123"', text)
        self.assertNotIn("Per-round context:", text)

    def test_live_continuation_prompt_reuses_existing_agents_context(self) -> None:
        text = role_handoff_prompt(
            role_name="verification-coordinator",
            instruction="Run deterministic verification for IOS-123.",
            hydration_payload={
                "task_key": "IOS-123",
                "current_stage": "verification_requested",
                "work_item_id": 2,
            },
            prompt_mode="live_continuation",
        )

        self.assertIn("Continue from your existing AGENTS.md-based role context", text)
        self.assertIn("resume and finish that unfinished work now", text)
        self.assertIn("Refresh your per-round machine-readable context from `HYDRATION.json`", text)
        self.assertIn("Run deterministic verification for IOS-123.", text)
        self.assertNotIn("You are a persistent SDD Factory role.", text)
        self.assertNotIn("Role-specific rules:", text)
        self.assertNotIn("Preferred terminal outcome path:", text)
        self.assertNotIn('"current_stage": "verification_requested"', text)

    def test_full_prompt_restores_final_verification_report_contract(self) -> None:
        text = role_handoff_prompt(
            role_name="verification-coordinator",
            instruction="Run deterministic verification for IOS-123.",
            hydration_payload={
                "task_key": "IOS-123",
                "current_stage": "verification_requested",
                "work_item_id": 8,
            },
            prompt_mode="full",
        )

        self.assertIn("Always write or refresh `spec/final-verification.md`", text)
        self.assertIn("failed checks and their relevant command output", text)
        self.assertIn('bash scripts/run-test.sh "$SDD_FACTORY_TASK_KEY"', text)
        self.assertIn('bash scripts/run-lint.sh "$SDD_FACTORY_TASK_KEY"', text)

    def test_full_prompt_requires_addressed_terminal_payload_for_subtasks(self) -> None:
        text = role_handoff_prompt(
            role_name="implementer",
            instruction="Implement subtask IOS-55555 for parent task IOS-123.",
            hydration_payload={
                "task_key": "IOS-123",
                "current_stage": "subtask_implementation_requested",
                "work_item_id": 42,
                "subtask_key": "IOS-55555",
            },
            prompt_mode="full",
        )

        self.assertIn("Always copy `work_item_id` from `HYDRATION.json`", text)
        self.assertIn("If `HYDRATION.json` includes `subtask_key`", text)
        self.assertIn('{"output_type":"completed","payload":{"work_item_id":123,"subtask_key":"IOS-12345","summary":"short result"}}', text)

    def test_full_prompt_restores_proposal_context_fetch_and_conflict_rules(self) -> None:
        text = role_handoff_prompt(
            role_name="proposal-context-worker",
            instruction="Collect proposal and context foundations for story IOS-123.",
            hydration_payload={
                "task_key": "IOS-123",
                "current_stage": "proposal_context_requested",
                "work_item_id": 3,
            },
            prompt_mode="full",
        )

        self.assertIn("Read `description.md` and `comments.md` first; comments take precedence", text)
        self.assertIn("use Notion MCP for `notion.so` links", text)
        self.assertIn("treat non-Notion external links as operator-provided context references", text)

    def test_full_prompt_restores_acceptance_criteria_format_contract(self) -> None:
        text = role_handoff_prompt(
            role_name="acceptance-criteria-worker",
            instruction="Prepare explicit acceptance criteria for story IOS-123.",
            hydration_payload={
                "task_key": "IOS-123",
                "current_stage": "acceptance_criteria_requested",
                "work_item_id": 4,
            },
            prompt_mode="full",
        )

        self.assertIn("WHEN-THEN-SHALL form", text)
        self.assertIn("independently testable", text)
        self.assertIn("happy paths, edge cases, and error scenarios", text)

    def test_full_prompt_restores_constraints_ground_truth_contract(self) -> None:
        text = role_handoff_prompt(
            role_name="constraints-worker",
            instruction="Prepare grounded implementation constraints for story IOS-123.",
            hydration_payload={
                "task_key": "IOS-123",
                "current_stage": "constraints_requested",
                "work_item_id": 5,
            },
            prompt_mode="full",
        )

        self.assertIn("`spec/context/project.md` as the architectural ground truth", text)
        self.assertIn("MUST, MUST NOT, and SHOULD", text)
        self.assertIn("task-specific and grounded", text)

    def test_full_prompt_restores_story_spec_implementation_guide_contract(self) -> None:
        text = role_handoff_prompt(
            role_name="story-spec-worker",
            instruction="Prepare the final implementation-shaping story spec for IOS-123 before coding.",
            hydration_payload={
                "task_key": "IOS-123",
                "current_stage": "story_spec_requested",
                "work_item_id": 6,
            },
            prompt_mode="full",
        )

        self.assertIn("final implementation-shaping story spec", text)
        self.assertIn("durable implementation guide", text)
        self.assertIn("architecture-sensitive decisions", text)

    def test_full_prompt_restores_spec_verifier_optional_input_contract(self) -> None:
        text = role_handoff_prompt(
            role_name="spec-verifier-worker",
            instruction="Verify the assembled planning package for IOS-123.",
            hydration_payload={
                "task_key": "IOS-123",
                "current_stage": "spec_verification_requested",
                "work_item_id": 9,
            },
            prompt_mode="full",
        )

        self.assertIn("Do not require `spec/spec_verification.md` to exist before verification starts", text)
        self.assertIn("Their absence alone is not a blocker", text)

    def test_full_prompt_restores_task_decomposer_self_contained_plan_contract(self) -> None:
        text = role_handoff_prompt(
            role_name="task-decomposer-worker",
            instruction="Prepare task decomposition for story IOS-123 before implementation starts.",
            hydration_payload={
                "task_key": "IOS-123",
                "current_stage": "task_decomposition_requested",
                "work_item_id": 7,
            },
            prompt_mode="full",
        )

        self.assertIn("Always produce a durable `plan/index.md` plus `plan/NN-*.md` task package", text)
        self.assertIn("Make each task file self-contained", text)
        self.assertIn("without reopening the full planning process", text)


if __name__ == "__main__":
    unittest.main()
