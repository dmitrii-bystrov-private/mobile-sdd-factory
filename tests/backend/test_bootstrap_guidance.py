import unittest

from factory.doctor.bootstrap_guidance import (
    build_bootstrap_guidance,
    format_bootstrap_guidance,
)


class BootstrapGuidanceTests(unittest.TestCase):
    def test_build_bootstrap_guidance_prioritizes_required_actions(self) -> None:
        guidance = build_bootstrap_guidance(
            {
                "overall_status": "warn",
                "checks": [
                    {
                        "id": "env.SDD_WORKDIR",
                        "label": "Task workdir root",
                        "required": True,
                        "status": "missing",
                        "details": "SDD_WORKDIR is not set.",
                        "hint": "Set SDD_WORKDIR.",
                    },
                    {
                        "id": "cli.codex",
                        "label": "Codex CLI",
                        "required": False,
                        "status": "missing",
                        "details": "codex is not installed.",
                        "hint": "Install Codex CLI if you want Codex-backed live roles.",
                    },
                ],
            }
        )

        self.assertEqual(1, guidance["required_action_count"])
        self.assertEqual(1, guidance["optional_action_count"])
        self.assertEqual("Resolve required setup issues first.", guidance["next_step"])
        self.assertEqual("bash factory/run-local-stack.sh", guidance["launch_command"])
        self.assertEqual("http://127.0.0.1:8000", guidance["backend_url"])
        self.assertEqual("http://127.0.0.1:4173", guidance["ui_url"])

    def test_format_bootstrap_guidance_handles_clean_report(self) -> None:
        text = format_bootstrap_guidance(
            {
                "overall_status": "ok",
                "next_step": "Environment is ready.",
                "launch_command": "bash factory/run-local-stack.sh",
                "backend_url": "http://127.0.0.1:8000",
                "ui_url": "http://127.0.0.1:4173",
                "required_actions": [],
                "optional_actions": [],
            }
        )

        self.assertIn("Environment is ready.", text)
        self.assertIn("Launch command: bash factory/run-local-stack.sh", text)
        self.assertIn("Backend URL: http://127.0.0.1:8000", text)
        self.assertIn("UI URL: http://127.0.0.1:4173", text)
        self.assertIn("No setup actions are currently required.", text)
