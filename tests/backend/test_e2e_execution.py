import json
import os
from pathlib import Path
import sys
import signal
from types import ModuleType, SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from factory.e2e import runner
from factory.e2e.config import Machine
from factory.e2e.execution import E2EPlanError, configurations, selection, support_digests


class FakeNewConnectionError(Exception):
    pass


class FakeMaxRetryError(Exception):
    pass


def fake_appium_modules(driver):
    appium = ModuleType("appium.webdriver.webdriver")
    appium.WebDriver = driver
    transport = ModuleType("urllib3.exceptions")
    transport.NewConnectionError = FakeNewConnectionError
    transport.MaxRetryError = FakeMaxRetryError
    return {"appium.webdriver.webdriver": appium, "urllib3.exceptions": transport}


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

    def test_assigned_appium_capabilities_override_only_the_leased_resources(self):
        from factory.e2e import pytest_evidence
        class Driver:
            def start_session(self, capabilities, browser_profile=None):
                return capabilities
        module = ModuleType("appium.webdriver.webdriver")
        module.WebDriver = Driver
        cleanups = []
        assigned = {"appium:udid": "dedicated", "appium:wdaLocalPort": 8111,
                    "appium:derivedDataPath": "/isolated-wda", "appium:shutdownOtherSimulators": False}
        original = Driver.start_session
        with patch.dict(sys.modules, fake_appium_modules(Driver)), patch.dict(os.environ,
                {"FACTORY_E2E_APPIUM_CAPABILITIES": json.dumps(assigned)}):
            pytest_evidence.pytest_configure(SimpleNamespace(add_cleanup=cleanups.append))
            try:
                caps = {"appium:udid": "workspace", "appium:wdaLocalPort": 8100,
                        "appium:shutdownOtherSimulators": True, "appium:app": "task.app"}
                for supplied in (caps, SimpleNamespace(to_capabilities=lambda: caps)):
                    result = Driver().start_session(supplied)
                    self.assertEqual("dedicated", result["appium:udid"])
                    self.assertEqual(8111, result["appium:wdaLocalPort"])
                    self.assertFalse(result["appium:shutdownOtherSimulators"])
                    self.assertEqual("task.app", result["appium:app"])
                self.assertEqual("workspace", caps["appium:udid"])
            finally:
                for cleanup in cleanups: cleanup()
        self.assertIs(original, Driver.start_session)

    def test_interrupted_phase_terminates_its_child_before_device_cleanup(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            machine = Machine(root, Path(sys.executable), root, "device", "", "", root, "appium", 4743)
            policy = {"run_timeout_seconds": 10, "test_timeout_seconds": 10, "_task_root": root,
                      "_configurations": configurations(self.recipe())}
            child = Mock(pid=123456)
            child.wait.side_effect = [runner.E2EError("interrupted by signal"), -15]
            with patch.object(runner.subprocess, "Popen", return_value=child), patch.object(runner.os, "killpg") as kill:
                with self.assertRaisesRegex(runner.E2EError, "interrupted by signal"):
                    runner.phase(machine, root, "ios", {"udid": "device"}, None, policy, root, "run", ["opaque-check"])
            kill.assert_called_once_with(child.pid, signal.SIGTERM)

    def test_factory_endpoint_overrides_positional_keyword_and_client_config_defaults(self):
        from factory.e2e import pytest_evidence
        class Driver:
            def __init__(self, command_executor="http://localhost:4723/wd/hub", keep_alive=True,
                         options=None, direct_connection=True, client_config=None):
                self.endpoint = command_executor
                self.options = options
                self.direct = direct_connection
                self.client_config = client_config
                self.caps = self.start_session(options)
            def start_session(self, capabilities):
                return capabilities
        module = ModuleType("appium.webdriver.webdriver")
        module.WebDriver = Driver
        cleanups = []
        original_init, original_start = Driver.__init__, Driver.start_session
        endpoint = "http://127.0.0.1:4781/wd/hub"
        client = SimpleNamespace(remote_server_addr="http://localhost:4723/wd/hub", direct_connection=True)
        with patch.dict(sys.modules, fake_appium_modules(Driver)), patch.dict(os.environ,
                {"FACTORY_E2E_APPIUM_URL": endpoint, "FACTORY_E2E_APPIUM_CAPABILITIES": '{"appium:udid":"leased"}'}):
            pytest_evidence.pytest_configure(SimpleNamespace(add_cleanup=cleanups.append))
            try:
                options = {"appium:app": "task.app", "appium:udid": "other-device"}
                for args, kwargs in (((), {}), (("http://localhost:4723/wd/hub",), {}),
                                     ((), {"command_executor": "http://localhost:4723/wd/hub", "client_config": client})):
                    driver = Driver(*args, options=options, **kwargs)
                    self.assertEqual(endpoint, driver.endpoint)
                    self.assertFalse(driver.direct)
                    self.assertEqual("leased", driver.caps["appium:udid"])
                    self.assertEqual("task.app", driver.caps["appium:app"])
                    self.assertIs(options, driver.options)
                    if driver.client_config:
                        self.assertEqual(endpoint, driver.client_config.remote_server_addr)
                        self.assertFalse(driver.client_config.direct_connection)
                self.assertEqual("http://localhost:4723/wd/hub", client.remote_server_addr)
                self.assertTrue(client.direct_connection)
            finally:
                for cleanup in reversed(cleanups): cleanup()
        self.assertIs(original_init, Driver.__init__)
        self.assertIs(original_start, Driver.start_session)

    def test_appium_connection_failure_stops_pytest_with_environment_exit_code(self):
        import pytest
        from factory.e2e import pytest_evidence
        class Driver:
            def __init__(self, command_executor="unused"):
                self.start_session({})
            def start_session(self, capabilities):
                raise FakeMaxRetryError("Connection refused")
        module = ModuleType("appium.webdriver.webdriver")
        module.WebDriver = Driver
        cleanups = []
        with patch.dict(sys.modules, fake_appium_modules(Driver)), patch.dict(os.environ,
                {"FACTORY_E2E_APPIUM_URL": "http://127.0.0.1:4781/wd/hub", "FACTORY_E2E_APPIUM_CAPABILITIES": "{}"}):
            pytest_evidence.pytest_configure(SimpleNamespace(add_cleanup=cleanups.append))
            try:
                with self.assertRaises(pytest.exit.Exception) as raised:
                    Driver()
                self.assertEqual(2, raised.exception.returncode)
                self.assertIn("http://127.0.0.1:4781", str(raised.exception))
            finally:
                for cleanup in reversed(cleanups): cleanup()

    def test_platform_mismatch_is_reported_before_any_appium_request(self):
        import pytest
        from factory.e2e import pytest_evidence
        calls = []
        class Driver:
            def start_session(self, capabilities):
                calls.append(capabilities)
                return capabilities
        with tempfile.TemporaryDirectory() as directory:
            diagnostic = Path(directory) / "diagnostic.json"
            cleanups = []
            with patch.dict(sys.modules, fake_appium_modules(Driver)), patch.dict(os.environ, {
                "FACTORY_E2E_PLATFORM": "ios", "FACTORY_E2E_APPIUM_CAPABILITIES": '{"appium:udid":"leased"}',
                "FACTORY_E2E_DIAGNOSTIC": str(diagnostic), "FACTORY_E2E_APPIUM_URL": "",
            }):
                pytest_evidence.pytest_configure(SimpleNamespace(add_cleanup=cleanups.append))
                try:
                    for caps in ({"platformName": "Android"}, {}):
                        with self.assertRaises(pytest.exit.Exception) as raised:
                            Driver().start_session(caps)
                        self.assertEqual(2, raised.exception.returncode)
                        self.assertEqual([], calls)
                        self.assertEqual("execution_recipe", json.loads(diagnostic.read_text())["origin"])
                    diagnostic.unlink()
                    self.assertEqual("leased", Driver().start_session({"platformName": "iOS"})["appium:udid"])
                    self.assertEqual(1, len(calls))
                    self.assertFalse(diagnostic.exists())
                finally:
                    for cleanup in reversed(cleanups): cleanup()

    def test_native_recipe_diagnostic_keeps_receipt_and_requests_preparation_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "diagnose.py"
            script.write_text('import json,os\n'
                              'with open(os.environ["FACTORY_E2E_DIAGNOSTIC"],"w") as out:\n'
                              '    json.dump({"origin":"execution_recipe","details":"Client requested Android for iOS gate"},out)\n'
                              'raise SystemExit(2)\n')
            runner.git(root, "init")
            runner.git(root, "config", "user.name", "Test")
            runner.git(root, "config", "user.email", "test@example.invalid")
            runner.git(root, "add", ".")
            runner.git(root, "commit", "-m", "Diagnostic fixture")
            config = {"commands": {"run": ["{python}", "{repo}/diagnose.py", "{selectors}"]}}
            policy = {"run_timeout_seconds": 10, "test_timeout_seconds": 10, "_task_root": root,
                      "_configurations": {"ios": config}}
            machine = Machine(root, Path(sys.executable), root, "device", "", "", root, "appium", 4743)
            from factory.e2e.execution import E2EPlanError
            with self.assertRaisesRegex(E2EPlanError, "Client requested Android for iOS gate"):
                runner.phase(machine, root, "ios", {"udid": "device"}, None, policy, root, "run", ["opaque-check"])
            receipt = json.loads((root / "ios-run.json").read_text())
            self.assertEqual(2, receipt["exit_code"])
            self.assertFalse(receipt["ok"])

    def test_transport_failure_aborts_the_real_pytest_command_before_the_next_check(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for package in ("appium", "appium/webdriver", "urllib3", "checks"):
                path = root / package
                path.mkdir(parents=True, exist_ok=True)
                (path / "__init__.py").write_text("")
            (root / "urllib3/exceptions.py").write_text(
                'class MaxRetryError(Exception): pass\nclass NewConnectionError(Exception): pass\n')
            (root / "appium/webdriver/webdriver.py").write_text(
                'from urllib3.exceptions import MaxRetryError\n'
                'class WebDriver:\n'
                '    def __init__(self, command_executor="old-server"):\n'
                '        self.start_session({"platformName":"iOS"})\n'
                '    def start_session(self, caps):\n'
                '        raise MaxRetryError("Connection refused")\n')
            (root / "checks/test_transport.py").write_text(
                'from appium.webdriver.webdriver import WebDriver\nfrom pathlib import Path\n'
                'def test_first_session():\n    WebDriver()\n'
                'def test_remaining_check():\n    Path("second-check-ran").touch()\n')
            runner.git(root, "init")
            runner.git(root, "config", "user.name", "Test")
            runner.git(root, "config", "user.email", "test@example.invalid")
            runner.git(root, "add", ".")
            runner.git(root, "commit", "-m", "Transport fixture")
            recipe = self.recipe()
            recipe["e2e"]["platforms"]["ios"]["environment"]["PYTHONPATH"] = "{repo}:{factory_plugin_dir}"
            policy = {"run_timeout_seconds": 30, "test_timeout_seconds": 10, "_task_root": root,
                      "_configurations": configurations(recipe)}
            machine = Machine(root, Path(sys.executable), root, "device", "", "", root, "appium", 4781)
            receipt = runner.phase(machine, root, "ios", {"udid": "device"}, None,
                                   policy, root, "run", ["checks/test_transport.py"])
            self.assertEqual(2, receipt["exit_code"])
            self.assertFalse(receipt["ok"])
            self.assertFalse((root / "second-check-ran").exists())
            self.assertIn("factory endpoint http://127.0.0.1:4781", Path(receipt["log"]).read_text())

    def test_cli_interrupt_handler_is_restored_after_a_blocked_gate(self):
        import io
        from contextlib import redirect_stdout
        handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
        def verify(*args):
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        with patch.object(runner.Machine, "from_env"), patch.object(runner, "read_json", return_value={}), \
                patch.object(runner, "verify", side_effect=verify), patch.dict(os.environ, {"SDD_WORKDIR": "/tasks"}), \
                redirect_stdout(io.StringIO()) as output:
            self.assertEqual(2, runner.main(["verify", "QA-100"]))
        self.assertIn("interrupted", output.getvalue())
        self.assertEqual(handlers, {sig: signal.getsignal(sig) for sig in handlers})

    def test_timeout_diagnostic_identifies_total_gate_budget(self):
        import subprocess
        import time
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            machine = Machine(root, Path(sys.executable), root, "device", "", "", root, "appium", 4743)
            policy = {"run_timeout_seconds": 2400, "test_timeout_seconds": 600, "_task_root": root,
                      "_deadline": time.monotonic() + 5, "_configurations": configurations(self.recipe())}
            child = Mock(pid=123456)
            child.wait.side_effect = [subprocess.TimeoutExpired("pytest", 5), -15]
            with patch.object(runner.subprocess, "Popen", return_value=child), patch.object(runner.os, "killpg"):
                with self.assertRaisesRegex(runner.E2EError, "total verification time limit \\(2400s\\) exhausted"):
                    runner.phase(machine, root, "ios", {"udid": "device"}, None, policy, root, "fresh-run-rerun-1", ["opaque-check"])

    def test_qa_launcher_replaces_stale_tmux_pool_environment_and_clears_removed_values(self):
        import subprocess
        from backend.roles.launcher import RoleLauncherManager
        from backend.roles.workspace import RoleWorkspace
        name = "SDD_E2E_IOS_SIMULATOR_UDIDS"
        cache = "SDD_E2E_IOS_WDA_ROOT"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = RoleWorkspace("verification-coordinator", root, root / "AGENTS.md", root / "CLAUDE.md")
            code = 'import json,os; print(json.dumps({k:os.environ.get(k) for k in '+repr([name, cache])+ '}))'
            launcher = RoleLauncherManager(root, launcher_command=[sys.executable, "-c", code])
            script = root / "launch.sh"
            for configured in (True, False):
                with self.subTest(configured=configured), patch.dict(os.environ,
                        {name: "new-device", cache: "/new cache"} if configured else {}, clear=True):
                    script.write_text(launcher._build_launcher_script(task_key="QA-100", role_name=workspace.role_name, workspace=workspace))
                result = subprocess.run(["bash", str(script)],env=dict(os.environ, **{name:"stale-device",cache:"/stale"}),
                                        capture_output=True,text=True,check=True)
                env = json.loads(result.stdout.splitlines()[-1])
                self.assertEqual({name:"new-device",cache:"/new cache"} if configured else {name:None,cache:None}, env)


if __name__ == "__main__":
    unittest.main()
