import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from factory.e2e import runner
from factory.e2e.config import Machine
from factory.e2e.execution import E2EPlanError, configurations, selection, support_digests


class ExecutionRecipeTests(unittest.TestCase):
    def recipe(self):
        return {"e2e": {"platforms": {"ios": {"collection": ["checks"], "tests": ["checks/test_local.py::test_config"],
            "commands": {
                "collect": ["{python}", "-m", "pytest", "-p", "pytest_evidence", "--collect-only", "-q", "{selectors}"],
                "run": ["{python}", "-m", "pytest", "-p", "pytest_evidence", "--junitxml={junit}", "-q", "{selectors}"]},
            "environment": {"PYTHONPATH": "{factory_plugin_dir}", "RECIPE_DEVICE": "{device_id}"},
            "unset_environment": ["PYTEST_ADDOPTS"]}}}}

    def test_real_commands_collect_and_run_checks_without_project_layout_assumptions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, folder = root / "repo", root / "evidence"
            (repo / "checks").mkdir(parents=True)
            folder.mkdir()
            (repo / "checks/test_local.py").write_text(
                'import os\ndef test_config():\n    assert os.environ["RECIPE_DEVICE"] == "isolated-device"\n')
            runner.git(repo, "init")
            runner.git(repo, "config", "user.name", "Test")
            runner.git(repo, "config", "user.email", "test@example.invalid")
            runner.git(repo, "add", ".")
            runner.git(repo, "commit", "-m", "Local checks")
            machine = Machine(repo, Path(sys.executable), root, "isolated-device", "", "", root, "appium", 4743)
            policy = {"run_timeout_seconds": 30, "test_timeout_seconds": 10, "_task_root": root,
                      "_configurations": configurations(self.recipe())}
            target = {"udid": "isolated-device", "version": "1.0"}
            with patch.dict(os.environ, {"PYTEST_ADDOPTS": "--invalid-inherited-option"}):
                collected = runner.phase(machine, repo, "ios", target, None, policy, folder, "collection", ["checks"], collect=True)
                result = runner.phase(machine, repo, "ios", target, None, policy, folder, "run", collected["collected"])
            self.assertTrue(collected["ok"])
            self.assertEqual(["checks/test_local.py::test_config"], collected["collected"])
            self.assertTrue(result["ok"])
            self.assertEqual(1, len(result["results"]["passed"]))
            verdict = {"source": runner.source(repo), "receipts": [collected, result]}
            runner.validate_receipts(verdict)
            Path(collected["collection"]).write_text("[]")
            with self.assertRaisesRegex(runner.E2EError, "Collection evidence changed"):
                runner.validate_receipts(verdict)

    def test_smoke_and_removed_identifiers_are_supplied_by_the_task(self):
        config = self.recipe()["e2e"]["platforms"]["ios"]
        config["tests"] = ["opaque:case-a"]
        config["smoke_tests"] = ["opaque:case-b"]
        self.assertEqual(["opaque:case-a", "opaque:case-b"], selection(config, "ios", {"include_smoke": True}))
        self.assertEqual(["opaque:case-a"], selection(config, "ios", {"include_smoke": False}))
        del config["smoke_tests"]
        with self.assertRaises(E2EPlanError):
            selection(config, "ios", {"include_smoke": True})

    def test_non_pytest_command_runs_after_factory_fresh_install_with_task_app_id(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner.git(root, "init")
            runner.git(root, "config", "user.name", "Test")
            runner.git(root, "config", "user.email", "test@example.invalid")
            runner.git(root, "commit", "--allow-empty", "-m", "Fixture")
            script = root / "check.py"
            script.write_text('''import json, os, sys, unittest
from xml.etree.ElementTree import Element, SubElement, ElementTree
class Check(unittest.TestCase):
    def runTest(self):
        self.assertEqual(os.environ["FACTORY_E2E_APP_ID"], "example.custom.app")
result = unittest.TextTestRunner().run(Check())
tree = Element("testsuite")
case = SubElement(tree, "testcase", name="opaque-check")
if not result.wasSuccessful():
    SubElement(case, "failure").text = "metadata was incorrect"
ElementTree(tree).write(sys.argv[1])
with open(os.environ["FACTORY_E2E_RESULTS"], "w") as output:
    json.dump([{"nodeid": sys.argv[2], "outcome": "passed" if result.wasSuccessful() else "failed"}], output)
sys.exit(0 if result.wasSuccessful() else 1)
''')
            runner.git(root, "add", ".")
            runner.git(root, "commit", "-m", "Check")
            config = {"application_id": "example.custom.app", "commands": {
                "run": ["{python}", "{repo}/check.py", "{junit}", "{selectors}"]}}
            policy = {"run_timeout_seconds": 10, "test_timeout_seconds": 10, "_task_root": root,
                      "_configurations": {"android": config}}
            machine = Machine(root, Path(sys.executable), root, "", "", "emulator-5584", root, "appium", 4743)
            app = {"path": "opaque.apk", "artifact_digest": "identified-build"}
            target = {"serial": "emulator-5584", "adb": "adb"}
            with patch.object(runner, "execute", wraps=runner.execute) as execute, patch.object(runner, "install") as install:
                execute.side_effect = lambda command, **kwargs: "" if command[0] == "adb" else execute._mock_wraps(command, **kwargs)
                receipt = runner.phase(machine, root, "android", target, app, policy, root, "run", ["opaque-check"], fresh=True)
            self.assertTrue(receipt["ok"])
            self.assertEqual("example.custom.app", receipt["fresh_install_receipt"]["application_id"])
            execute.assert_any_call(["adb", "-s", "emulator-5584", "uninstall", "example.custom.app"], timeout=unittest.mock.ANY)
            install.assert_called_once_with(machine, "android", app, target)

    def test_support_files_are_bound_to_the_snapshot_and_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "adapter.py").write_text("# task-owned integration")
            strategy = {"e2e": {"support_files": ["adapter.py"]}}
            original = support_digests(root, strategy)
            (root / "adapter.py").write_text("# changed integration")
            self.assertNotEqual(original, support_digests(root, strategy))
            for path in ("../outside.py", "/absolute.py", "missing.py"):
                with self.subTest(path=path), self.assertRaises(E2EPlanError):
                    support_digests(root, {"e2e": {"support_files": [path]}})

    def test_commands_require_explicit_selectors_instead_of_factory_defaults(self):
        strategy = self.recipe()
        strategy["e2e"]["platforms"]["ios"]["commands"]["run"] = ["echo", "done"]
        with self.assertRaisesRegex(E2EPlanError, "one.*selectors"):
            configurations(strategy)


if __name__ == "__main__":
    unittest.main()
