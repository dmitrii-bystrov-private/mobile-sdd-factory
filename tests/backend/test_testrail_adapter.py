import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from factory.e2e.adapters.pytest_testrail import AdapterError, active_coverage
from factory.e2e.config import Machine
from factory.e2e import runner
from factory.e2e.execution import configurations
from backend.coordinator.verification_strategy import materialize_verification_strategy
from backend.runtime_defaults import save_runtime_defaults


class Catalog:
    def __init__(self):
        self.calls = []
        self.cases = {1: {"id": 1, "suite_id": 12, "type_id": 39, "is_deleted": False, "enabled_android": True,
                          "enabled_ios": False, "product": 8}}

    def send_get(self, path):
        self.calls.append(path)
        if path == "get_case_types":
            return [{"id": 39, "name": "Automated"}]
        if path == "get_case_fields":
            return [{"name": "android", "system_name": "enabled_android"},
                    {"name": "ios", "system_name": "enabled_ios"},
                    {"name": "product_name", "system_name": "product",
                     "configs": [{"options": {"items": "8, alpha\n9, beta"}}]}]
        if path == "get_suites/42":
            return {"suites": [{"id": 12, "name": "MOBILE"}], "_links": {"next": None}}
        return self.cases[int(path.split("/")[1])]


class TestRailAdapterTests(unittest.TestCase):
    def metadata(self, nodes, markers=("alpha",)):
        return {"version": 1, "checks": [{"nodeid": node, "markers": [
            {"name": "testrail", "kwargs": {"ids": ["C1"]}},
            *[{"name": marker, "kwargs": {}} for marker in markers]]} for node in nodes]}

    def test_project_fields_and_automation_ids_are_resolved_and_cases_cached(self):
        client = Catalog()
        nodes = ["feature[a]", "feature[b]"]
        result = active_coverage(client, self.metadata(nodes), nodes, "android")
        self.assertTrue(all(item["eligible"] for item in result))
        self.assertEqual(1, client.calls.count("get_case/1"))
        self.assertFalse(active_coverage(client, self.metadata(nodes), nodes, "ios")[0]["eligible"])

    def test_deleted_manual_disabled_and_unmarked_cases_are_excluded(self):
        for changed in ({"is_deleted": 1}, {"type_id": 7}, {"enabled_android": False}, {"product": 9}):
            with self.subTest(changed=changed):
                client = Catalog()
                client.cases[1].update(changed)
                self.assertFalse(active_coverage(client, self.metadata(["feature"]), ["feature"], "android")[0]["eligible"])
        self.assertFalse(active_coverage(Catalog(), self.metadata(["feature"], ()), ["feature"], "android")[0]["eligible"])

    def test_unbound_or_missing_metadata_cannot_guess_case_status(self):
        for metadata in ({}, self.metadata(["foreign"]), {"version": 1, "checks": []}):
            with self.subTest(metadata=metadata), self.assertRaises(AdapterError):
                active_coverage(Catalog(), metadata, ["feature"], "android")

    def test_a_case_from_another_suite_is_not_active_project_coverage(self):
        client = Catalog()
        client.cases[1]['suite_id'] = 13
        result = active_coverage(client, self.metadata(['feature']), ['feature'], 'android',
                                {'project_id':42, 'suite_name':'MOBILE'})
        self.assertFalse(result[0]['eligible'])
        self.assertIn('project/suite', result[0]['reason'])

    def test_factory_installs_bound_adapter_and_uses_real_collected_task_markers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task, integration = root / "QA-100", root / "configured-tests"
            repo = task / "repo"
            repo.mkdir(parents=True)
            (task / "spec").mkdir()
            (integration / "framework/configs").mkdir(parents=True)
            (integration / "framework/configs/testrail.cfg").write_text(
                "[API]\nurl=https://catalog.example\nemail=test@example.invalid\npassword=fixture-secret\n")
            (integration / "framework/configs/config.ini").write_text("[testrail]\nproject_id=42\nsuite_name=MOBILE\n")
            runner.git(repo, "init")
            runner.git(repo, "config", "user.name", "Acceptance")
            runner.git(repo, "config", "user.email", "acceptance@example.invalid")
            (repo / "test_feature.py").write_text("import pytest\n@pytest.mark.alpha\n"
                "@pytest.mark.testrail(ids=['C1'])\ndef test_changed():\n    pass\n")
            runner.git(repo, "add", ".")
            runner.git(repo, "commit", "-m", "fixture")
            runner.git(repo, "update-ref", "refs/remotes/origin/master", runner.git(repo, "rev-parse", "HEAD"))
            save_runtime_defaults(root, default_runner=None, role_defaults={}, policy_defaults={},
                e2e_defaults={"selection_adapter": "pytest_testrail", "include_smoke": False})
            strategy, path = materialize_verification_strategy(task_key="QA-100", workdir_root=root, repo_root=root, work_item_id=12)
            sdk = root / "sdk/testrail_client"
            sdk.mkdir(parents=True)
            (sdk / "__init__.py").write_text("")
            (sdk / "testrail.py").write_text("import json,os\nclass APIClient:\n"
                " def __init__(self,url):\n  assert url=='https://catalog.example'\n"
                " def send_get(self,path):\n  assert self.password=='fixture-secret'\n"
                "  return json.loads(os.environ['FIXTURE_CATALOG'])[path]\n")
            client = Catalog()
            data = {name: client.send_get(name) for name in ('get_case_types', 'get_case_fields', 'get_case/1', 'get_suites/42')}
            node = "test_feature.py::test_changed"
            strategy['e2e']['platforms'] = {'android': {'collection': ['.'], 'tests': [node], 'required_tests': [node],
                'application_id': 'fixture.app', 'environment': {'PYTHONPATH': '{factory_plugin_dir}:' + str(root/'sdk'),
                'FIXTURE_CATALOG': json.dumps(data)}, 'commands': {
                    'collect': ['{python}', '-m', 'pytest', '--collect-only', '-q', '{selectors}'],
                    'run': ['{python}', '-m', 'pytest', '{selectors}']}}}
            runner.write_json(path, strategy)
            machine = Machine(integration, Path(sys.executable), root, '', '', '', root, 'appium', 4743)
            policy = dict(strategy['e2e']['policy'], _task_root=task, _configurations=configurations(strategy))
            folder = root / 'evidence'; folder.mkdir()
            receipt = runner.phase(machine, repo, 'android', {}, None, policy, folder, 'selection', [node], collect=True)
            checked = runner.check_selection(machine, repo, 'android', {}, None, policy, folder, receipt['collected'])
            self.assertEqual([node], checked['collected'])
            runner.validate_receipts({'source': runner.source(repo), 'receipts': [receipt, checked]})
            Path(receipt['metadata_path']).write_text('{}')
            with self.assertRaisesRegex(runner.E2EError, 'Collection metadata changed'):
                runner.validate_receipts({'source': runner.source(repo), 'receipts': [receipt, checked]})
            self.assertTrue(all((task/name).exists() for name in strategy['e2e']['support_files']))
