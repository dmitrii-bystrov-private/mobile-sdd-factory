from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from backend.roles.prompts import role_handoff_prompt
from backend.roles.workspace import build_role_agents_md


class RolePromptTests(unittest.TestCase):
    def test_live_bootstrap_prompt_points_to_durable_role_files(self) -> None:
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

        self.assertIn("Read AGENTS.md/CLAUDE.md in the current directory once now", text)
        self.assertIn("Read HYDRATION.json for machine-readable routed IDs and paths.", text)
        self.assertIn("Current routed work:\nStart implementation work for IOS-123.", text)
        self.assertNotIn("Role-specific rules:", text)
        self.assertNotIn("Hydration payload:", text)
        self.assertNotIn('"task_key": "IOS-123"', text)

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

        self.assertIn("Continue from your existing role context.", text)
        self.assertNotIn("AGENTS.md/CLAUDE.md role context", text)
        self.assertIn("resume and finish it instead of restarting from zero", text)
        self.assertIn("Read the updated HYDRATION.json", text)
        self.assertIn("Run deterministic verification for IOS-123.", text)
        self.assertNotIn("Role-specific rules:", text)
        self.assertNotIn('"current_stage": "verification_requested"', text)

    def test_full_prompt_is_current_work_only_not_role_contract(self) -> None:
        text = role_handoff_prompt(
            role_name="convention-reviewer",
            instruction="Run convention review for IOS-123.",
            hydration_payload={
                "task_key": "IOS-123",
                "current_stage": "convention_review_requested",
                "work_item_id": 14,
            },
            prompt_mode="full",
        )

        self.assertIn("Read AGENTS.md/CLAUDE.md and HYDRATION.json", text)
        self.assertIn("Routed work item: 14.", text)
        self.assertIn("Current routed work:\nRun convention review for IOS-123.", text)
        self.assertNotIn("Role-specific rules:", text)
        self.assertNotIn("Primary project guidance", text)
        self.assertNotIn("Submit the terminal result", text)
        self.assertNotIn("Hydration payload:", text)

    def test_coding_roles_have_strict_verification_boundary_in_agents(self) -> None:
        implementer = self._agents("implementer")
        bug_fixer = self._agents("bug-fixer")

        expected = (
            "Do not run build, test, or lint verification. "
            "Submit your implementation result; verification happens after this role finishes."
        )
        self.assertIn(expected, implementer)
        self.assertIn(expected, bug_fixer)
        self.assertNotIn("run-test.sh", implementer)
        self.assertNotIn("run-lint.sh", implementer)
        self.assertNotIn("run-build.sh", implementer)
        self.assertNotIn("verifier lane", implementer)
        self.assertNotIn("coordinator", implementer.lower())

    def test_review_roles_have_strict_verification_boundary_without_tool_lists(self) -> None:
        for role_name in ("code-reviewer", "convention-reviewer", "requirements-reviewer"):
            agents = self._agents(role_name)
            self.assertIn(
                "Do not run build, test, or lint verification. "
                "Submit your review result; verification happens after this role finishes.",
                agents,
            )
            self.assertNotIn("run-test.sh", agents)
            self.assertNotIn("run-lint.sh", agents)
            self.assertNotIn("run-build.sh", agents)
            self.assertNotIn("ios-verify.sh", agents)
            self.assertNotIn("android-verify.sh", agents)
            self.assertNotIn("verification lane", agents)

    def test_planning_and_docs_roles_do_not_mention_code_verification(self) -> None:
        for role_name in (
            "proposal-context-worker",
            "requirements-clarifier-worker",
            "acceptance-criteria-worker",
            "constraints-worker",
            "task-decomposer-worker",
            "doc-harvest-worker",
            "documentation-reviewer",
        ):
            agents = self._agents(role_name).lower()
            self.assertNotIn("build, test, or lint", agents)
            self.assertNotIn("run-test.sh", agents)
            self.assertNotIn("run-lint.sh", agents)
            self.assertNotIn("run-build.sh", agents)
            self.assertNotIn("ios-verify.sh", agents)
            self.assertNotIn("android-verify.sh", agents)

    def test_verifier_agents_owns_verification_commands(self) -> None:
        agents = self._agents("verification-coordinator")

        self.assertIn("Start from the routed verification strategy file", agents)
        self.assertIn('bash scripts/ios-verify.sh "$SDD_FACTORY_TASK_KEY"', agents)
        self.assertIn('bash scripts/android-verify.sh "$SDD_FACTORY_TASK_KEY"', agents)
        self.assertIn("run-test.sh", agents)
        self.assertIn("run-lint.sh", agents)
        self.assertIn("Final verification report target:", agents)
        self.assertIn("Do not modify product code.", agents)

    def test_review_agents_include_terminal_result_cheat_sheet(self) -> None:
        agents = self._agents("convention-reviewer")

        self.assertIn("## Terminal Result Contract", agents)
        self.assertIn("--output-type passed", agents)
        self.assertIn("--output-type failed", agents)
        self.assertIn("--issues-markdown-file <path>", agents)
        self.assertIn("--output-type blocked_review_cycle", agents)
        self.assertIn("HYDRATION.json", agents)

    def test_implementer_agents_include_completion_and_subtask_result_templates(self) -> None:
        agents = self._agents("implementer")

        self.assertIn("## Terminal Result Contract", agents)
        self.assertIn("--output-type completed", agents)
        self.assertIn("--subtask-key <subtask_key>", agents)
        self.assertIn("--output-type failed", agents)

    def test_verifier_agents_include_result_payload_templates(self) -> None:
        agents = self._agents("verification-coordinator")

        self.assertIn("## Terminal Result Contract", agents)
        self.assertIn("--result passed", agents)
        self.assertIn("--result failed", agents)
        self.assertIn("--failure \"<failed check>\"", agents)
        self.assertIn("--output-type blocked_verification_cycle", agents)

    def _agents(self, role_name: str) -> str:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            return build_role_agents_md(
                role_name=role_name,
                task_key="IOS-123",
                repo_root=root / "factory",
                workdir_root=root / "workdir",
                role_directory=root / "workdir" / "IOS-123" / "runtime" / "role-workspaces" / role_name,
            )


if __name__ == "__main__":
    unittest.main()
