from __future__ import annotations

import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from factory.doctor.runtime_capabilities import build_runtime_capabilities


class RuntimeCapabilitiesTests(unittest.TestCase):
    def test_build_runtime_capabilities_collects_runner_catalogs_and_legacy_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            agent_dir = repo_root / ".claude" / "agents"
            agent_dir.mkdir(parents=True)
            (agent_dir / "implementer.md").write_text(
                textwrap.dedent(
                    """\
                    ---
                    name: implementer
                    model: sonnet
                    effort: medium
                    mcpServers:
                      - ios-rag
                      - android-rag
                    ---
                    """
                ),
                encoding="utf-8",
            )
            (agent_dir / "spec-verifier.md").write_text(
                textwrap.dedent(
                    """\
                    ---
                    name: spec-verifier
                    model: opus
                    effort: high
                    mcpServers: []
                    ---
                    """
                ),
                encoding="utf-8",
            )

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
                repo_root=repo_root,
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
            self.assertEqual(["ios-rag", "android-rag"], report["legacy_role_defaults"][0]["mcp_servers"])
            self.assertEqual([], report["legacy_role_defaults"][1]["mcp_servers"])
