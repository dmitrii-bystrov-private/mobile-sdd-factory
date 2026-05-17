from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from backend.config import load_config


class ConfigTests(unittest.TestCase):
    def test_load_config_rejects_non_tmux_runtime_for_application_mode(self) -> None:
        env = {
            "SDD_FACTORY_RUNTIME_BACKEND": "recording",
            "SDD_FACTORY_USE_FAKE_ADAPTERS": "false",
        }
        with patch.dict(os.environ, env, clear=False):
            with self.assertRaisesRegex(
                ValueError,
                "supported operational host is tmux",
            ):
                load_config()

    def test_load_config_allows_non_tmux_runtime_for_fake_adapter_mode(self) -> None:
        env = {
            "SDD_FACTORY_RUNTIME_BACKEND": "recording",
            "SDD_FACTORY_USE_FAKE_ADAPTERS": "true",
        }
        with patch.dict(os.environ, env, clear=False):
            config = load_config()
        self.assertEqual("recording", config.runtime_backend)


if __name__ == "__main__":
    unittest.main()
