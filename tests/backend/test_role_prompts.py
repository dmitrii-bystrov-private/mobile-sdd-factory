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
        self.assertIn("Current routed work:\nStart implementation work for IOS-123.", text)
        self.assertIn('"task_key": "IOS-123"', text)
        self.assertIn("Per-round context:", text)
        self.assertNotIn("You are a persistent SDD Factory role.", text)
        self.assertNotIn("Role-specific rules:", text)
        self.assertNotIn("Preferred terminal outcome path:", text)

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
        self.assertIn("Run deterministic verification for IOS-123.", text)
        self.assertIn('"current_stage": "verification_requested"', text)
        self.assertNotIn("You are a persistent SDD Factory role.", text)
        self.assertNotIn("Role-specific rules:", text)
        self.assertNotIn("Preferred terminal outcome path:", text)


if __name__ == "__main__":
    unittest.main()
