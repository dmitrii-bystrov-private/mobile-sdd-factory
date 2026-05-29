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
        self.assertIn("If you need the exact machine-readable per-round context or routed IDs", text)
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
        self.assertIn("If you need the exact machine-readable per-round context or routed IDs", text)
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
                "verification_strategy_path": "/tmp/IOS-123/spec/verification-strategy.json",
            },
            prompt_mode="full",
        )

        self.assertIn("Start from the routed verification strategy file", text)
        self.assertIn("iOS impact mapping", text)
        self.assertIn("explicit commands", text)
        self.assertIn('bash scripts/ios-verify.sh "$SDD_FACTORY_TASK_KEY"', text)
        self.assertIn('bash scripts/android-verify.sh "$SDD_FACTORY_TASK_KEY"', text)
        self.assertIn("docs-only with no code-verification phases", text)
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
                "result_path": "/tmp/roles/implementer/RESULT.json",
            },
            prompt_mode="full",
        )

        self.assertIn('bash "$SDD_FACTORY_REPO_ROOT/scripts/write-result.sh" --work-item-id <work_item_id>', text)
        self.assertIn("Do not hand-write `RESULT.json`", text)
        self.assertIn("Do not run broad workflow-level wrappers", text)
        self.assertIn("Always copy `work_item_id` from the hydration payload below", text)
        self.assertIn("If the hydration payload below includes `subtask_key`", text)
        self.assertIn('--subtask-key "IOS-12345"', text)

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

    def test_full_prompt_restores_task_snapshot_path_resolution_rules(self) -> None:
        text = role_handoff_prompt(
            role_name="implementer",
            instruction="Implement IOS-123.",
            hydration_payload={
                "task_key": "IOS-123",
                "current_stage": "implementation_requested",
                "work_item_id": 10,
                "result_path": "/tmp/roles/implementer/RESULT.json",
            },
            prompt_mode="full",
        )

        self.assertIn("Treat paths written as `spec/...`, `review/...`, or `plan/...` as paths under the task snapshot metadata root", text)
        self.assertIn("When the hydration payload below includes explicit absolute `*_path` fields", text)

    def test_full_prompt_restores_code_scout_absolute_path_rules(self) -> None:
        text = role_handoff_prompt(
            role_name="code-scout",
            instruction="Run a Boy Scout pass for IOS-123.",
            hydration_payload={
                "task_key": "IOS-123",
                "current_stage": "boy_scout_requested",
                "work_item_id": 11,
                "diff_path": "/tmp/IOS-123/spec/diff.md",
                "findings_path": "/tmp/IOS-123/spec/findings.md",
                "result_path": "/tmp/roles/code-scout/RESULT.json",
                "result_writer_path": "/tmp/repo/scripts/write-result.sh",
            },
            prompt_mode="full",
        )

        self.assertIn("Start from the routed diff input when it is provided as an absolute path", text)
        self.assertIn("write them to the routed findings target when it is provided as an absolute path", text)
        self.assertIn('bash "/tmp/repo/scripts/write-result.sh" --work-item-id 11', text)
        self.assertIn("`result` set to `clean` or `findings_found`", text)
        self.assertIn("positive `findings_count`", text)

    def test_full_prompt_exposes_result_writer_for_verification(self) -> None:
        text = role_handoff_prompt(
            role_name="verification-coordinator",
            instruction="Run deterministic verification for IOS-123.",
            hydration_payload={
                "task_key": "IOS-123",
                "current_stage": "verification_requested",
                "work_item_id": 12,
                "result_path": "/tmp/roles/verifier/RESULT.json",
                "result_writer_path": "/tmp/repo/scripts/write-result.sh",
            },
            prompt_mode="full",
        )

        self.assertIn("do not hand-compose verification JSON", text)
        self.assertIn('bash "/tmp/repo/scripts/write-result.sh" --work-item-id 12', text)

    def test_full_prompt_for_reviewer_forbids_runtime_verification_commands(self) -> None:
        text = role_handoff_prompt(
            role_name="code-reviewer",
            instruction="Review the current routed changes for IOS-123.",
            hydration_payload={
                "task_key": "IOS-123",
                "current_stage": "self_review_requested",
                "work_item_id": 13,
                "result_writer_path": "/tmp/repo/scripts/write-result.sh",
            },
            prompt_mode="full",
        )

        self.assertIn("static review only", text)
        self.assertIn("do not run builds, tests, lint, simulator commands", text)
        self.assertIn("defer runtime validation to the verification lane", text)
        self.assertIn("scripts/run-test.sh", text)
        self.assertIn("scripts/ios-verify.sh", text)

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

    def test_full_prompt_restores_task_decomposer_contract(self) -> None:
        text = role_handoff_prompt(
            role_name="task-decomposer-worker",
            instruction="Prepare task decomposition for story IOS-123 before implementation starts.",
            hydration_payload={
                "task_key": "IOS-123",
                "current_stage": "task_decomposition_requested",
                "work_item_id": 6,
            },
            prompt_mode="full",
        )

        self.assertIn("decompose the verified story package into execution tasks", text)
        self.assertIn("plan/index.md", text)
        self.assertIn("self-contained", text)

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

        self.assertIn("Always produce a durable `plan/tasks.json` manifest plus `plan/NN-*.md` task files", text)
        self.assertIn("Make each task file self-contained", text)
        self.assertIn("without reopening the full planning process", text)


if __name__ == "__main__":
    unittest.main()
