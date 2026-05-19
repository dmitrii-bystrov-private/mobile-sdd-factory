from __future__ import annotations

import json
import unittest
from pathlib import Path

from factory.doctor.runtime_capabilities import build_runtime_capabilities


class RuntimeCapabilitiesTests(unittest.TestCase):
    def test_build_runtime_capabilities_collects_runner_catalogs_and_role_defaults(self) -> None:
        def fake_which(command_name: str) -> str | None:
            if command_name in {"claude", "codex"}:
                return f"/usr/bin/{command_name}"
            return None

        def fake_command_runner(command: list[str]) -> tuple[int, str]:
            if command == ["claude", "--help"]:
                return 0, "--effort <level> Effort level for the current session (low, medium, high, xhigh, max)"
            if command == ["codex", "debug", "models"]:
                return 0, json.dumps(
                    {
                        "models": [
                            {
                                "slug": "gpt-5.5",
                                "display_name": "GPT-5.5",
                                "default_reasoning_level": "medium",
                                "supported_reasoning_levels": [
                                    {"effort": "low"},
                                    {"effort": "medium"},
                                    {"effort": "high"},
                                    {"effort": "xhigh"},
                                ],
                                "visibility": "list",
                                "supported_in_api": True,
                            },
                            {
                                "slug": "codex-auto-review",
                                "display_name": "Codex Auto Review",
                                "default_reasoning_level": "medium",
                                "supported_reasoning_levels": [{"effort": "medium"}],
                                "visibility": "hide",
                                "supported_in_api": True,
                            },
                        ]
                    }
                )
            raise AssertionError(f"Unexpected command: {command}")

        report = build_runtime_capabilities(
            repo_root=Path("."),
            which_func=fake_which,
            command_runner=fake_command_runner,
        )

        self.assertEqual(["claude", "codex"], report["available_runners"])
        self.assertEqual("claude", report["default_runner"])
        claude_runner = next(item for item in report["runners"] if item["runner"] == "claude")
        codex_runner = next(item for item in report["runners"] if item["runner"] == "codex")
        self.assertEqual(["low", "medium", "high", "xhigh", "max"], claude_runner["models"][0]["supported_efforts"])
        self.assertEqual("gpt-5.5", codex_runner["models"][0]["id"])
        self.assertEqual(["low", "medium", "high", "xhigh"], codex_runner["models"][0]["supported_efforts"])
        proposal_context = next(item for item in report["role_defaults"] if item["role_name"] == "proposal-context-worker")
        spec_verifier = next(item for item in report["role_defaults"] if item["role_name"] == "spec-verifier-worker")
        self.assertEqual(["notion", "ios-rag", "android-rag", "frontend-rag"], proposal_context["mcp_servers"])
        self.assertEqual("opus", spec_verifier["model"])
