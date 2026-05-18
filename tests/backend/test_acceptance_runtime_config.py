from __future__ import annotations

import os
import unittest
from unittest import mock

from factory.acceptance.runtime_config import (
    acceptance_default_runner,
    acceptance_role_config,
    acceptance_runner_config,
)


class AcceptanceRuntimeConfigTests(unittest.TestCase):
    def test_defaults_prefer_claude_sonnet_and_codex_spark(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            self.assertEqual("claude", acceptance_default_runner())
            self.assertEqual(
                {"runner": "claude", "model": "sonnet", "effort": "medium"},
                acceptance_runner_config("claude"),
            )
            self.assertEqual(
                {"runner": "codex", "model": "gpt-5.3-codex-spark", "effort": "medium"},
                acceptance_runner_config("codex"),
            )

    def test_role_config_allows_runner_specific_overrides(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            config = acceptance_role_config(
                ["implementer", "verification-coordinator"],
                runner_overrides={"implementer": "codex"},
            )

        self.assertEqual("codex", config["implementer"]["runner"])
        self.assertEqual("gpt-5.3-codex-spark", config["implementer"]["model"])
        self.assertEqual("claude", config["verification-coordinator"]["runner"])
        self.assertEqual("sonnet", config["verification-coordinator"]["model"])

    def test_env_overrides_take_precedence(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "SDD_FACTORY_ACCEPTANCE_DEFAULT_RUNNER": "codex",
                "SDD_FACTORY_ACCEPTANCE_CODEX_MODEL": "gpt-5.5",
                "SDD_FACTORY_ACCEPTANCE_CODEX_EFFORT": "high",
            },
            clear=False,
        ):
            config = acceptance_role_config(["implementer"])

        self.assertEqual(
            {"runner": "codex", "model": "gpt-5.5", "effort": "high"},
            config["implementer"],
        )


if __name__ == "__main__":
    unittest.main()
