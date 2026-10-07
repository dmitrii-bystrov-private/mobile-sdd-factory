from contextlib import ExitStack
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.coordinator.intake import IntakeError
from backend.coordinator.service import CoordinatorService
from backend.coordinator.verification_strategy import materialize_verification_strategy
from backend.roles.contracts import DEFAULT_SESSION_ROLES, VERIFICATION_COORDINATOR_ROLE
from backend.roles.launcher import RoleLauncherManager
from backend.roles.workspace import RoleWorkspaceManager
from backend.runtime_defaults import load_runtime_defaults, save_runtime_defaults
from backend.session_backend.recording_backend import RecordingSessionBackend
from backend.state.artifact_repository import ArtifactRepository
from backend.state.db import Database
from backend.state.event_repository import EventRepository
from backend.state.role_repository import RoleRepository
from backend.state.session_repository import SessionRepository
from backend.state.work_item_repository import WorkItemRepository
from backend.tools.fake_adapters import FakeGitLabAdapter, FakeJiraAdapter
from factory.e2e.config import E2EError, Machine
from factory.e2e import runner


class E2EWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.key = "QA-100"
        self.task = self.root / self.key
        self.repo = self.task / "repo"
        self.repo.mkdir(parents=True)
        (self.task / "spec").mkdir()
        runner.git(self.repo, "init", "-b", "master")
        runner.git(self.repo, "config", "user.name", "Acceptance")
        runner.git(self.repo, "config", "user.email", "acceptance@example.invalid")
        file = self.repo / "tests/ios/test_example.py"
        file.parent.mkdir(parents=True)
        file.write_text("def test_example():\n    pass\n")
        runner.git(self.repo, "add", ".")
        runner.git(self.repo, "commit", "-m", "baseline")
        self.baseline = runner.git(self.repo, "rev-parse", "HEAD")
        runner.git(self.repo, "update-ref", "refs/remotes/origin/master", self.baseline)
        runner.git(self.repo, "switch", "-c", "feature/QA-100")
        file.write_text("def test_example():\n    assert True\n")
        runner.git(self.repo, "commit", "-am", "Update scenario")
        self.node = "tests/ios/test_example.py::test_example"
        save_runtime_defaults(self.root, default_runner=None, role_defaults={}, policy_defaults={},
                              e2e_defaults={"include_smoke": False})
        self.strategy, _ = materialize_verification_strategy(
            task_key=self.key, workdir_root=self.root, repo_root=self.root, work_item_id=123,
        )
        self.write_recipe({"platforms": {"ios": {"tests": [self.node]}}})
        self.machine = Machine(self.repo, Path("python"), self.root, "test-device", "test-avd",
                               "emulator-5584", self.root, "appium", 4743)
        app_path = self.root / "app.app"
        app_path.mkdir()
        self.app = {"path": str(app_path), "sha": "app-master-sha", "artifact_digest": "app-digest"}
        self.behavior = {}
        self.calls = []
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name, value in (("doctor", {"ok": True}), ("device", {"udid": "test-device", "version": "26.2"}),
                            ("resolve_app", self.app), ("install", None), ("ensure_server", None)):
            self.stack.enter_context(patch.object(runner, name, return_value=value))
        self.stack.enter_context(patch.object(runner, "pin_app", side_effect=lambda task, machine, platform, app: app))
        self.stack.enter_context(patch.object(runner, "phase", side_effect=self.fake_phase))
        self.stack.enter_context(patch.dict(os.environ, {"E2E_DEVICE_LOCK_ROOT": str(self.root / "locks")}))

    def fake_phase(self, machine, repo, platform, target, app, policy, folder, name, selectors, *, collect=False, fresh=False):
        self.calls.append((name, runner.source(repo), app, selectors))
        if hasattr(self, "platform_nodes"):
            from xml.sax.saxutils import escape
            nodes = [node for node in self.platform_nodes[platform]
                     if any(node == selector or node.startswith(selector + "/") or node.startswith(selector + "::") for selector in selectors)]
            failures = set(self.phase_failures.get((platform, name), [])) & set(nodes)
            ok = not failures and bool(nodes)
            log, junit = folder / f"{platform}-{name}.log", folder / f"{platform}-{name}.xml"
            log.write_text(name + "\n")
            cases = []
            for node in nodes:
                cases.append(f'<testcase classname="{node.split("::")[0].replace("/", ".")}" name="{node.split("::")[1]}">'
                             + (f'<failure>{escape("E AssertionError: test failure")}</failure>' if node in failures else "") + '</testcase>')
            junit.write_text('<testsuite>' + ''.join(cases) + '</testsuite>')
            receipt = {"phase": name, "platform": platform, "source": runner.source(repo), "app": app,
                       "device": target, "selectors": selectors, "exit_code": 0 if ok else 1, "ok": ok,
                       "collected": nodes if collect and ok else [], "results": None if collect else runner.junit_results(junit),
                       "fresh_install": fresh, "log": str(log), "junit": str(junit), "log_digest": runner.digest(log),
                       "fresh_install_receipt": {"application_id": "example.app", "artifact_digest": (app or {}).get("artifact_digest")} if fresh else None,
                       "junit_digest": runner.digest(junit), "outcomes": [] if collect else [
                           {"nodeid": node, "outcome": "failed" if node in failures else "passed"} for node in nodes]}
            path = folder / f"{platform}-{name}.json"
            runner.write_json(path, receipt)
            receipt["path"] = str(path)
            return receipt
        ok = self.behavior.get(name, True)
        log, junit = folder / (platform + "-" + name + ".log"), folder / (platform + "-" + name + ".xml")
        log.write_text(name + "\n")
        junit.write_text('<testsuite><testcase classname="tests.ios.test_example" name="test_example">'
                         + ("" if ok else '<failure>test failure</failure>') + '</testcase></testsuite>')
        receipt = {"phase": name, "platform": platform, "source": runner.source(repo), "app": app,
                   "device": target, "selectors": selectors, "exit_code": 0 if ok else 1, "ok": ok,
                   "collected": [self.node] if collect and ok else [],
                   "results": None if collect else runner.junit_results(junit), "fresh_install": fresh,
                   "fresh_install_receipt": {"application_id": "example.app", "artifact_digest": (app or {}).get("artifact_digest")} if fresh else None,
                   "log": str(log), "junit": str(junit), "log_digest": runner.digest(log),
                   "junit_digest": runner.digest(junit),
                   "outcomes": [] if collect else [{"nodeid": self.node, "outcome": "passed" if ok else "failed"}]}
        file = folder / (platform + "-" + name + ".json")
        runner.write_json(file, receipt)
        receipt["path"] = str(file)
        return receipt

    def run_gate(self):
        return runner.verify(self.key, self.task, self.strategy, self.machine)

    def write_recipe(self, recipe):
        platforms = recipe.get("platforms") if isinstance(recipe, dict) else recipe
        if isinstance(platforms, dict):
            for platform, config in platforms.items():
                if not isinstance(config, dict):
                    continue
                config.setdefault("collection", [f"tests/{platform}"])
                config.setdefault("commands", {"collect": ["{python}", "-m", "pytest", "{selectors}"],
                                               "run": ["{python}", "-m", "pytest", "{selectors}"]})
                if platform == "android":
                    config.setdefault("application_id", "example.test.app")
                if isinstance(recipe, dict) and "removed_tests" in recipe:
                    config["removed_tests"] = recipe["removed_tests"]
        self.strategy["e2e"]["platforms"] = platforms
        runner.write_json(self.task / "spec/verification-strategy.json", self.strategy)

    def block_baseline(self):
        service, session, _ = self.coordinator()
        self.behavior.update({"run": False, "rerun-1": False, "baseline-1": False})
        verdict = self.run_gate()
        session, _, _ = service.handle_role_output(session.id, VERIFICATION_COORDINATOR_ROLE, "failed",
                                                   {"work_item_id": self.strategy["work_item_id"]})
        context = service.get_interactive_state_summary(session.id)["e2e_decision"]
        return service, session, verdict, context

    def decide(self, service, session, context, *, action="accept", ids=None):
        return service.resolve_e2e_baseline(session.id, work_item_id=context["work_item_id"],
            verdict_digest=context["verdict_digest"], action=action,
            finding_ids=ids if ids is not None else [item["id"] for item in context["findings"]], comment="Known issue QA-200")

    def test_operator_acceptance_preserves_failed_evidence_and_delivery_warning(self):
        from types import SimpleNamespace
        from backend.api.routes_operator import resolve_e2e_baseline
        from backend.api.schemas import InteractiveStateSummaryResponse, ResolveE2EBaselineRequest
        service, session, original, context = self.block_baseline()
        self.assertIsNotNone(InteractiveStateSummaryResponse(**service.get_interactive_state_summary(session.id)).e2e_decision)
        response = resolve_e2e_baseline(ResolveE2EBaselineRequest(session_id=session.id,
            work_item_id=context["work_item_id"], verdict_digest=context["verdict_digest"], action="accept",
            finding_ids=[context["findings"][0]["id"]], comment="Known issue QA-200"),
            SimpleNamespace(coordinator_service=service))
        self.assertEqual("active", response.session.status)
        self.assertEqual("e2e_baseline_accepted_by_operator", response.event_type)
        self.assertFalse(service.get_interactive_state_summary(session.id)["available"])
        calls_before = len(self.calls)
        verdict = self.run_gate()
        self.assertEqual("accepted_with_warnings", verdict["result"])
        self.assertEqual(["collection", "selection"], [item[0] for item in self.calls[calls_before:]])
        self.assertEqual(original["classifications"][0]["evidence"], verdict["accepted_findings"][0]["evidence"])
        runner.validate_verdict(self.task, self.strategy["work_item_id"])
        session, event, followup = service.handle_role_output(session.id, VERIFICATION_COORDINATOR_ROLE, "passed",
            {"work_item_id": self.strategy["work_item_id"], "result": "passed"})
        self.assertEqual("accepted_with_warnings", event.payload["e2e_result"])
        self.assertEqual("accepted_with_warnings", service._verification_outcome_status(session))
        self.assertEqual("send_to_test_completed", followup.event_type)
        self.assertIn("QA-200", runner.mr_description(self.key, self.task))
        self.assertIn("These scenarios did not pass", (self.task / "spec/final-verification.md").read_text())
        self.assertEqual("blocked", runner.read_json(Path(verdict["operator_decisions"][0]["verdict_path"]))["result"])

    def test_operator_exception_cannot_be_forged_by_a_worker(self):
        service, session, _, context = self.block_baseline()
        self.decide(service, session, context)
        path = self.task / "spec/e2e-operator-decisions.json"
        record = runner.read_json(path)
        record["decisions"][0]["event_id"] = 999999
        runner.write_json(path, record)
        self.run_gate()
        with self.assertRaisesRegex(IntakeError, "matching operator decision"):
            service.handle_role_output(session.id, VERIFICATION_COORDINATOR_ROLE, "passed",
                {"work_item_id": self.strategy["work_item_id"]})

    def test_continuation_pins_accepted_master_build_when_a_new_build_appears(self):
        service, session, _, context = self.block_baseline()
        self.decide(service, session, context)
        newer_app = dict(self.app, path="/local/new-master.app", sha="new-master-sha", artifact_digest="new-digest")
        with patch.object(runner, "resolve_app", side_effect=lambda machine, platform, requested=None: requested or newer_app) as resolve:
            verdict = self.run_gate()
        self.assertEqual("accepted_with_warnings", verdict["result"])
        self.assertEqual(self.app, resolve.call_args.args[2])
        runner.validate_verdict(self.task, self.strategy["work_item_id"])

    def test_acceptance_drains_old_tmux_error_and_suppresses_its_replay(self):
        service, session, _, context = self.block_baseline()
        role = service.role_repository.get_by_name(session.id, VERIFICATION_COORDINATOR_ROLE)
        previous = service.event_repository.latest_for_session_by_type(session.id, {"verification_blocked"})
        error = "SDD_ERROR: " + json.dumps({"summary": "Worker summary differs from the canonical baseline summary",
            "needs_operator_input": True, "work_item_id": self.strategy["work_item_id"]})
        service.session_backend.simulate_output(role.runtime_handle, error)
        session, _, _ = self.decide(service, session, context)
        self.assertFalse(service.session_backend.pending_outputs.get(role.runtime_handle))
        service.session_backend.simulate_output(role.runtime_handle, error)
        session, _, _ = service.collect_role_output(session.id, role.role_name)
        self.assertEqual("active", session.status.value)
        self.assertEqual(role.role_name, session.current_owner)
        self.assertFalse(service.get_interactive_state_summary(session.id)["available"])
        self.run_gate()
        session, _, _, _, ignored = service.submit_role_result_document(document={
            "output_type": "passed", "payload": {"work_item_id": self.strategy["work_item_id"], "result": "passed"}})
        self.assertFalse(ignored)
        self.assertEqual("completed", session.status.value)

    def test_acceptance_restores_owner_after_a_prior_runtime_error(self):
        service, session, _, context = self.block_baseline()
        session = service.session_repository.update_stage_and_owner(session.id,
            current_stage=session.current_stage, current_owner=None)
        session, _, _ = self.decide(service, session, context)
        self.assertEqual(VERIFICATION_COORDINATOR_ROLE, session.current_owner)
        self.assertEqual("active", session.status.value)
        self.run_gate()
        session, _, _, _, ignored = service.submit_role_result_document(document={
            "output_type": "passed", "payload": {"work_item_id": self.strategy["work_item_id"], "result": "passed"}})
        self.assertFalse(ignored)
        self.assertEqual("completed", session.status.value)

    def test_operator_transition_and_runtime_collection_are_serialized(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        service, session, _, context = self.block_baseline()
        role = service.role_repository.get_by_name(session.id, VERIFICATION_COORDINATOR_ROLE)
        entered, release, collector_started, collector_read = (threading.Event() for _ in range(4))
        original = service.session_backend.read_output
        def read(handle):
            if threading.current_thread().name.endswith("_0"):
                entered.set()
                if not release.wait(5):
                    raise AssertionError("Operator transition did not resume")
            else:
                collector_read.set()
            return original(handle)
        def collect():
            collector_started.set()
            return service.collect_role_output(session.id, role.role_name)
        with patch.object(service.session_backend, "read_output", side_effect=read), ThreadPoolExecutor(max_workers=2) as executor:
            acceptance = executor.submit(self.decide, service, session, context)
            try:
                self.assertTrue(entered.wait(5))
                collection = executor.submit(collect)
                self.assertTrue(collector_started.wait(5))
                self.assertFalse(collector_read.wait(0.05))
            finally:
                release.set()
            acceptance.result(timeout=5)
            session, _, _ = collection.result(timeout=5)
        self.assertEqual("active", session.status.value)
        self.assertEqual(VERIFICATION_COORDINATOR_ROLE, session.current_owner)

    def test_new_infrastructure_error_uses_native_verdict_and_can_resume_same_gate(self):
        service, session, _, context = self.block_baseline()
        previous = service.event_repository.latest_for_session_by_type(session.id, {"verification_blocked"})
        session, _, _ = self.decide(service, session, context)
        role = service.role_repository.get_by_name(session.id, VERIFICATION_COORDINATOR_ROLE)
        with patch.object(runner, "doctor", return_value={"ok": False, "errors": ["Reserved iOS device is busy"]}):
            self.run_gate()
        service.session_backend.simulate_output(role.runtime_handle, "SDD_ERROR: " + json.dumps({
            "summary": previous.payload["summary"], "needs_operator_input": True,
            "work_item_id": self.strategy["work_item_id"]}))
        session, _, _ = service.collect_role_output(session.id, role.role_name)
        self.assertEqual("waiting_for_operator", session.status.value)
        self.assertEqual(role.role_name, session.current_owner)
        interactive = service.get_interactive_state_summary(session.id)
        self.assertEqual("e2e_environment", interactive["source_reason"])
        self.assertFalse(interactive["needs_operator_input"])
        self.assertIn("device is busy", interactive["details"])
        self.assertTrue(interactive["e2e_continuation_available"])
        session, _, _ = service.resume_session(session.id)
        self.assertEqual(self.strategy["work_item_id"], service._find_active_work_item_for_role(session.id, role.id).id)
        verdict = self.run_gate()
        self.assertEqual("accepted_with_warnings", verdict["result"])
        session, _, followup = service.handle_role_output(session.id, role.role_name, "passed",
            {"work_item_id": self.strategy["work_item_id"]})
        self.assertEqual("send_to_test_completed", followup.event_type)

    def test_unrelated_runtime_question_does_not_reuse_previous_native_gate(self):
        service, session, _, context = self.block_baseline()
        session, _, _ = self.decide(service, session, context)
        role = service.role_repository.get_by_name(session.id, VERIFICATION_COORDINATOR_ROLE)
        service.session_backend.simulate_output(role.runtime_handle, "SDD_ERROR: " + json.dumps({
            "summary": "A new operator question", "needs_operator_input": True,
            "work_item_id": self.strategy["work_item_id"]}))
        session, _, _ = service.collect_role_output(session.id, role.role_name)
        self.assertEqual("waiting_for_operator", session.status.value)
        interactive = service.get_interactive_state_summary(session.id)
        self.assertEqual("runtime_error", interactive["source_reason"])
        self.assertTrue(interactive["needs_operator_input"])
        self.assertEqual("A new operator question", interactive["summary"])

    def test_later_platform_findings_keep_decision_controls_after_runtime_question(self):
        _, android = self.multi_platform_plan()
        service, session, _, ios_context = self.block_baseline()
        self.decide(service, session, ios_context)
        self.phase_failures = {("android", name): [android] for name in ("run", "rerun-1", "baseline-1")}
        with patch.object(runner, "shutdown_android"):
            verdict = self.run_gate()
        self.assertEqual([self.node], [item["test"] for item in verdict["accepted_findings"]])
        session, _, _ = service.handle_role_output(session.id, VERIFICATION_COORDINATOR_ROLE, "failed",
            {"work_item_id": self.strategy["work_item_id"]})
        context = service.get_interactive_state_summary(session.id)["e2e_decision"]
        self.assertEqual([android], [item["test"] for item in context["findings"]])
        before = len(service.event_repository.list_for_session(session.id))
        with self.assertRaisesRegex(IntakeError, "explicit decision"):
            service.resume_session(session.id)
        self.assertEqual(before, len(service.event_repository.list_for_session(session.id)))
        role = service.role_repository.get_by_name(session.id, VERIFICATION_COORDINATOR_ROLE)
        service.session_backend.simulate_output(role.runtime_handle, "SDD_ERROR: " + json.dumps({
            "summary": "Verification blocked", "details": "Android checks failed; operator handling required",
            "needs_operator_input": True, "work_item_id": self.strategy["work_item_id"]}))
        # A generic question has no new run receipt; display the unresolved bound evidence.
        with patch.object(service, "_fresh_e2e_runtime_verdict_available", return_value=False):
            session, _, _ = service.collect_role_output(session.id, role.role_name)
        self.assertIsNone(session.current_owner)
        interactive = service.get_interactive_state_summary(session.id)
        self.assertEqual("e2e_environment", interactive["source_reason"])
        self.assertFalse(interactive["needs_operator_input"])
        self.assertFalse(interactive["e2e_continuation_available"])
        self.assertEqual(context, interactive["e2e_decision"])
        self.assertIn("Android:", interactive["details"])
        self.assertIn("Baseline failure accepted", interactive["details"])
        self.decide(service, session, interactive["e2e_decision"])
        with patch.object(runner, "shutdown_android"):
            verdict = self.run_gate()
        self.assertEqual("accepted_with_warnings", verdict["result"])
        self.assertEqual({"ios", "android"}, {item["platform"] for item in verdict["accepted_findings"]})
        runner.validate_verdict(self.task, self.strategy["work_item_id"])

    def test_generic_runtime_question_cannot_offer_changed_baseline_evidence(self):
        service, session, _, _ = self.block_baseline()
        role = service.role_repository.get_by_name(session.id, VERIFICATION_COORDINATOR_ROLE)
        self.strategy["e2e"]["policy"]["run_timeout_seconds"] += 1
        runner.write_json(self.task / "spec/verification-strategy.json", self.strategy)
        service.session_backend.simulate_output(role.runtime_handle, "SDD_ERROR: " + json.dumps({
            "summary": "Verification blocked", "needs_operator_input": True,
            "work_item_id": self.strategy["work_item_id"]}))
        with patch.object(service, "_fresh_e2e_runtime_verdict_available", return_value=False):
            service.collect_role_output(session.id, role.role_name)
        interactive = service.get_interactive_state_summary(session.id)
        self.assertEqual("runtime_error", interactive["source_reason"])
        self.assertIsNone(interactive["e2e_decision"])

    def test_missing_accepted_build_requires_a_new_gate_instead_of_retrying_continuation(self):
        service, session, _, context = self.block_baseline()
        self.decide(service, session, context)
        Path(self.app["path"]).rmdir()
        with patch.object(runner, "resolve_app", side_effect=E2EError("Missing ios app artifact")):
            self.assertEqual("blocked", self.run_gate()["result"])
        service.handle_role_output(session.id, VERIFICATION_COORDINATOR_ROLE, "failed",
            {"work_item_id": self.strategy["work_item_id"]})
        interactive = service.get_interactive_state_summary(session.id)
        self.assertIn("Missing ios app artifact", interactive["details"])
        self.assertFalse(interactive["e2e_continuation_available"])

    def test_operator_acceptance_expires_after_task_integration_changes(self):
        helper = self.task / "spec/adapter.py"
        helper.write_text("# task integration")
        self.strategy["e2e"]["support_files"] = ["spec/adapter.py"]
        runner.write_json(self.task / "spec/verification-strategy.json", self.strategy)
        service, session, _, context = self.block_baseline()
        self.decide(service, session, context)
        helper.write_text("# different integration")
        verdict = self.run_gate()
        self.assertNotEqual("accepted_with_warnings", verdict["result"])
        self.assertIn("support files changed", verdict["details"])

    def test_fresh_strategy_preserves_task_recipe_but_rebinds_work_item(self):
        previous = self.strategy["e2e"]["platforms"]
        strategy, _ = materialize_verification_strategy(task_key=self.key, workdir_root=self.root,
            repo_root=self.root, work_item_id=999)
        self.assertEqual(previous, strategy["e2e"]["platforms"])
        self.assertEqual(999, strategy["work_item_id"])
        self.assertFalse((self.task / "spec/e2e-plan.json").exists())

    def test_receipt_cannot_claim_success_for_unselected_checks(self):
        verdict = self.run_gate()
        run = next(item for item in verdict["receipts"] if item["phase"] == "run")
        run["outcomes"] = [{"nodeid": "unrelated-check", "outcome": "passed"}]
        runner.write_json(Path(run["path"]), {key: value for key, value in run.items() if key != "path"})
        runner.write_json(self.task / "spec/e2e-verdict.json", verdict)
        with self.assertRaisesRegex(E2EError, "Actual execution differs"):
            runner.validate_verdict(self.task, self.strategy["work_item_id"])

    def test_operator_decision_rejects_stale_cards_and_unknown_findings(self):
        service, session, _, context = self.block_baseline()
        for ids in ([], ["unknown"]):
            with self.assertRaises(IntakeError):
                self.decide(service, session, context, ids=ids)
        with self.assertRaisesRegex(IntakeError, "refresh the card"):
            self.decide(service, session, dict(context, verdict_digest="stale"))
        self.decide(service, session, context)
        with self.assertRaises(IntakeError):
            self.decide(service, session, context)

    def test_operator_can_request_corrections_without_claiming_a_regression(self):
        service, session, _, context = self.block_baseline()
        session, event, followup = self.decide(service, session, context, action="correct")
        self.assertEqual("operator", event.producer_type)
        self.assertEqual("blocked", event.payload["e2e_result"])
        self.assertIn("QA-200", event.payload["details"])
        self.assertEqual("verification_correction_requested", followup.event_type)
        self.assertFalse((self.task / "spec/e2e-operator-decisions.json").exists())

    def test_acceptance_expires_after_code_plan_strategy_or_app_change(self):
        service, session, _, context = self.block_baseline()
        self.decide(service, session, context)
        for name in ("verification-strategy.json",):
            path = self.task / "spec" / name
            original = path.read_text()
            path.write_text(original + "\n")
            self.assertEqual("blocked", self.run_gate()["result"])
            path.write_text(original)
        file = self.repo / "tests/ios/test_example.py"
        original = file.read_text()
        file.write_text(original + "\n")
        self.assertEqual("blocked", self.run_gate()["result"])
        file.write_text(original)
        with patch.object(runner, "resolve_app", return_value=dict(self.app, artifact_digest="another-build")):
            verdict = self.run_gate()
        self.assertEqual("blocked", verdict["result"])
        self.assertIn("App build changed", verdict["details"])
        self.assertIn("App build changed", runner.describe_verdict(verdict)["details"])

    def test_retry_does_not_reuse_operator_exceptions(self):
        service, session, _, context = self.block_baseline()
        self.decide(service, session, context)
        with patch.object(runner, "doctor", return_value={"ok": False, "errors": ["Appium unavailable"]}):
            self.run_gate()
        session, _, _ = service.handle_role_output(session.id, VERIFICATION_COORDINATOR_ROLE, "failed",
            {"work_item_id": self.strategy["work_item_id"]})
        self.assertIsNone(service.get_interactive_state_summary(session.id)["e2e_decision"])
        service.retry_session(session.id)
        self.strategy = runner.read_json(self.task / "spec/verification-strategy.json")
        self.assertEqual("blocked", self.run_gate()["result"])
        self.assertEqual([], runner.read_json(self.task / "spec/e2e-verdict.json")["accepted_findings"])

    def multi_platform_plan(self):
        other = "tests/ios/test_example.py::test_other"
        android = "tests/android/test_android.py::test_android"
        self.platform_nodes = {"ios": [self.node, other], "android": [android]}
        self.phase_failures = {("ios", name): [self.node] for name in ("run", "rerun-1", "baseline-1")}
        self.write_recipe({"platforms": {
            "ios": {"tests": self.platform_nodes["ios"]}, "android": {"tests": [android]}}})
        return other, android

    def test_continuation_runs_remaining_tests_fresh_and_later_platforms(self):
        other, android = self.multi_platform_plan()
        service, session, original, context = self.block_baseline()
        self.assertEqual({"ios"}, {item["platform"] for item in original["receipts"]})
        self.decide(service, session, context)
        before = len(self.calls)
        with patch.object(runner, "shutdown_android") as shutdown:
            verdict = self.run_gate()
        self.assertEqual("accepted_with_warnings", verdict["result"])
        execution = [(name, selectors) for name, _, _, selectors in self.calls[before:] if name in {"run", "fresh-run"}]
        self.assertEqual([("run", [other]), ("fresh-run", [other]), ("run", [android]), ("fresh-run", [android])], execution)
        shutdown.assert_called_once()
        runner.validate_verdict(self.task, self.strategy["work_item_id"])
        session, _, followup = service.handle_role_output(session.id, VERIFICATION_COORDINATOR_ROLE, "passed",
            {"work_item_id": self.strategy["work_item_id"]})
        self.assertEqual("send_to_test_completed", followup.event_type)

    def test_new_failure_outside_the_exception_still_routes_to_correction(self):
        other, _ = self.multi_platform_plan()
        service, session, _, context = self.block_baseline()
        self.decide(service, session, context)
        self.phase_failures = {("ios", name): [other] for name in ("run", "rerun-1")}
        verdict = self.run_gate()
        self.assertEqual("failed", verdict["result"])
        self.assertEqual(other, verdict["classifications"][0]["test"])
        session, _, followup = service.handle_role_output(session.id, VERIFICATION_COORDINATOR_ROLE, "failed",
            {"work_item_id": self.strategy["work_item_id"]})
        self.assertEqual("verification_correction_requested", followup.event_type)

    def test_partial_acceptance_requires_a_new_decision_for_other_baseline_failures(self):
        other, _ = self.multi_platform_plan()
        self.phase_failures = {("ios", name): self.platform_nodes["ios"] for name in ("run", "rerun-1", "baseline-1", "baseline-2")}
        service, session, _, context = self.block_baseline()
        self.assertEqual(2, len(context["findings"]))
        selected = next(item["id"] for item in context["findings"] if item["test"] == self.node)
        self.decide(service, session, context, ids=[selected])
        verdict = self.run_gate()
        self.assertEqual("blocked", verdict["result"])
        self.assertEqual([self.node], [item["test"] for item in verdict["accepted_findings"]])
        session, _, _ = service.handle_role_output(session.id, VERIFICATION_COORDINATOR_ROLE, "failed",
            {"work_item_id": self.strategy["work_item_id"]})
        context = service.get_interactive_state_summary(session.id)["e2e_decision"]
        self.assertEqual([other], [item["test"] for item in context["findings"]])
        self.decide(service, session, context)
        verdict = self.run_gate()
        self.assertEqual("accepted_with_warnings", verdict["result"])
        self.assertEqual(2, len(verdict["operator_decisions"]))
        runner.validate_verdict(self.task, self.strategy["work_item_id"])
        session, _, followup = service.handle_role_output(session.id, VERIFICATION_COORDINATOR_ROLE, "passed",
            {"work_item_id": self.strategy["work_item_id"]})
        self.assertEqual("send_to_test_completed", followup.event_type)

    def test_infrastructure_failure_cannot_be_accepted(self):
        service, session, _ = self.coordinator()
        with patch.object(runner, "doctor", return_value={"ok": False, "errors": ["Appium unavailable"]}):
            self.run_gate()
        session, _, _ = service.handle_role_output(session.id, VERIFICATION_COORDINATOR_ROLE, "failed",
            {"work_item_id": self.strategy["work_item_id"]})
        self.assertIsNone(service.get_interactive_state_summary(session.id)["e2e_decision"])
        with self.assertRaisesRegex(IntakeError, "infrastructure blockers require recovery"):
            service.resolve_e2e_baseline(session.id, work_item_id=self.strategy["work_item_id"],
                verdict_digest=runner.digest(self.task / "spec/e2e-verdict.json"), action="accept", finding_ids=["anything"])

    def test_setup_failures_on_both_revisions_cannot_be_accepted_as_baseline_tests(self):
        service, session, _ = self.coordinator()
        self.behavior.update({"run": False, "rerun-1": False, "baseline-1": False})
        original = self.fake_phase
        def setup_failure(*args, **kwargs):
            receipt = original(*args, **kwargs)
            for outcome in receipt["outcomes"]:
                outcome["stage"] = "setup"
            runner.write_json(Path(receipt["path"]), {key: value for key, value in receipt.items() if key != "path"})
            return receipt
        with patch.object(runner, "phase", side_effect=setup_failure):
            verdict = self.run_gate()
        self.assertEqual("blocked", verdict["result"])
        self.assertEqual("environment_failure", verdict["classifications"][0]["kind"])
        self.assertEqual([], runner.baseline_findings(verdict, self.strategy))
        service.handle_role_output(session.id, VERIFICATION_COORDINATOR_ROLE, "failed",
            {"work_item_id": self.strategy["work_item_id"]})
        interactive = service.get_interactive_state_summary(session.id)
        self.assertIsNone(interactive["e2e_decision"])
        self.assertIn("cannot be accepted", interactive["details"])

    def test_continuation_consumes_old_terminal_file_and_accepts_new_ingress(self):
        from backend.state.dispatch_repository import DispatchRepository
        service, session, _, context = self.block_baseline()
        service.dispatch_repository = DispatchRepository(service.event_repository.db)
        role = service.role_repository.get_by_name(session.id, VERIFICATION_COORDINATOR_ROLE)
        previous_hydration = role.last_hydration_version
        result_path = service.role_workspace_manager.role_directory(self.key, VERIFICATION_COORDINATOR_ROLE) / "RESULT.json"
        runner.write_json(result_path, {"output_type": "failed", "payload": {
            "work_item_id": self.strategy["work_item_id"], "result": "failed", "summary": "Previous blocked run"}})
        self.decide(service, session, context)
        self.assertFalse(result_path.exists())
        dispatches = service.dispatch_repository.list_for_session(session.id)
        self.assertGreater(dispatches[-1].hydration_version, previous_hydration)
        self.run_gate()
        session, _, mapped, followup, ignored = service.submit_role_result_document(document={
            "output_type": "passed", "payload": {"work_item_id": self.strategy["work_item_id"], "result": "passed"}})
        self.assertFalse(ignored)
        self.assertEqual("verification_passed", mapped)
        self.assertEqual("send_to_test_completed", followup)
        self.assertEqual("completed", session.status.value)
        self.assertEqual("accepted_with_warnings", service._verification_outcome_status(session))

    def test_real_gate_contract_requires_collection_and_fresh_execution(self):
        result = self.run_gate()
        self.assertEqual("passed", result["result"])
        self.assertEqual(["collection", "selection", "run", "fresh-run"], [r[0] for r in self.calls])
        self.assertEqual(result, runner.validate_verdict(self.task, 123))
        self.assertIn("app-master-sha", runner.mr_description(self.key, self.task))

    def test_regression_compares_baseline_tests_on_identical_app(self):
        self.behavior.update({"run": False, "rerun-1": False})
        verdict = self.run_gate()
        self.assertEqual("failed", verdict["result"])
        self.assertEqual("test_regression", verdict["classifications"][0]["kind"])
        baseline = self.calls[-1]
        self.assertEqual(self.baseline, baseline[1]["sha"])
        self.assertEqual(self.app, baseline[2])
        self.assertEqual([self.node], baseline[3])

    def test_baseline_failure_blocks_without_speculative_correction(self):
        self.behavior.update({"run": False, "rerun-1": False, "baseline-1": False})
        verdict = self.run_gate()
        self.assertEqual("blocked", verdict["result"])
        self.assertEqual("baseline_or_environment_failure", verdict["classifications"][0]["kind"])

    def test_transport_exit_blocks_without_retries_or_baseline_installations(self):
        self.behavior["run"] = False
        def phase(*args, **kwargs):
            receipt = self.fake_phase(*args, **kwargs)
            if receipt["phase"] == "run":
                receipt["exit_code"] = 2
                runner.write_json(Path(receipt["path"]), receipt)
            return receipt
        with patch.object(runner, "phase", side_effect=phase):
            verdict = self.run_gate()
        self.assertEqual("blocked", verdict["result"])
        self.assertEqual(["collection", "selection", "run"], [call[0] for call in self.calls])
        self.assertEqual([], verdict["classifications"])
        self.assertIn("runner failed before a valid test verdict", verdict["details"])

    def test_platform_recipe_failure_requests_preparation_without_retry_or_baseline(self):
        original = self.fake_phase
        def phase(*args, **kwargs):
            receipt = original(*args, **kwargs)
            if receipt["phase"] == "run":
                raise runner.E2EPlanError("Client requested Android while the gate selected iOS")
            return receipt
        with patch.object(runner, "phase", side_effect=phase):
            verdict = self.run_gate()
        self.assertEqual("blocked", verdict["result"])
        self.assertEqual("execution_recipe", verdict["failure_origin"])
        self.assertEqual(["collection", "selection", "run"], [call[0] for call in self.calls])
        self.assertEqual("E2E execution strategy needs correction", runner.describe_verdict(verdict)["summary"])

    def test_shared_server_preflight_failure_does_not_boot_or_install(self):
        with patch.object(runner, "ensure_server", side_effect=runner.E2EError("Appium unavailable")), \
                patch.object(runner, "install") as install, \
                patch.object(runner, "device", return_value={"udid": "test-device", "version": "26.2"}) as device:
            verdict = self.run_gate()
        self.assertEqual("blocked", verdict["result"])
        self.assertEqual("Appium unavailable", verdict["details"])
        install.assert_not_called()
        self.assertFalse(any(call.kwargs.get("boot") for call in device.call_args_list))

    def test_flaky_retry_still_requires_fresh_full_selection(self):
        self.behavior["run"] = False
        verdict = self.run_gate()
        self.assertEqual("passed", verdict["result"])
        self.assertEqual("flaky", verdict["classifications"][0]["kind"])
        self.assertEqual("fresh-run", self.calls[-1][0])
        runner.validate_verdict(self.task, 123)

    def test_fresh_failure_is_compared_with_baseline(self):
        self.behavior.update({"fresh-run": False, "fresh-run-rerun-1": False})
        self.assertEqual("failed", self.run_gate()["result"])
        self.assertEqual("baseline-1", self.calls[-1][0])

    def test_fresh_retry_keeps_successful_checks_and_reruns_only_failed_checks(self):
        first, failed = self.node, "tests/ios/test_example.py::test_other"
        self.platform_nodes = {"ios": [first, failed]}
        self.phase_failures = {("ios", "fresh-run"): [failed]}
        self.write_recipe({"platforms": {"ios": {"tests": [first, failed]}}})
        verdict = self.run_gate()
        self.assertEqual("passed", verdict["result"])
        fresh, retry = [receipt for receipt in verdict["receipts"] if receipt["phase"] in {"fresh-run", "fresh-run-rerun-1"}]
        self.assertEqual([first, failed], fresh["selectors"])
        self.assertEqual([failed], retry["selectors"])
        self.assertEqual("passed", fresh["outcomes"][0]["outcome"])
        self.assertEqual("failed", fresh["outcomes"][1]["outcome"])
        self.assertEqual("passed", retry["outcomes"][0]["outcome"])
        self.assertTrue(fresh["fresh_install"] and retry["fresh_install"])
        self.assertEqual(fresh["app"], retry["app"])
        self.assertFalse(any(call[0].startswith("baseline") for call in self.calls))
        runner.validate_verdict(self.task, 123)

    def test_failed_fresh_retry_compares_only_remaining_failure_with_baseline(self):
        first, failed = self.node, "tests/ios/test_example.py::test_other"
        self.platform_nodes = {"ios": [first, failed]}
        self.phase_failures = {("ios", "fresh-run"): [failed], ("ios", "fresh-run-rerun-1"): [failed],
                               ("ios", "baseline-1"): [failed]}
        self.write_recipe({"platforms": {"ios": {"tests": [first, failed]}}})
        verdict = self.run_gate()
        self.assertEqual("blocked", verdict["result"])
        self.assertEqual([failed], self.calls[-1][3])
        self.assertEqual([failed], [item["test"] for item in verdict["classifications"]])
        self.assertEqual("baseline_or_environment_failure", verdict["classifications"][0]["kind"])

    def test_fresh_retry_includes_checks_not_executed_before_early_exit(self):
        first, failed, unfinished = self.node, "tests/ios/test_example.py::test_other", "tests/ios/test_example.py::test_last"
        nodes = [first, failed, unfinished]
        self.platform_nodes = {"ios": nodes}
        self.phase_failures = {("ios", "fresh-run"): [failed]}
        self.write_recipe({"platforms": {"ios": {"tests": nodes}}})
        original = self.fake_phase
        def early_exit(machine, repo, platform, target, app, policy, folder, name, selectors, **kwargs):
            if name == "fresh-run":
                self.platform_nodes[platform] = [first, failed]
            try:
                return original(machine, repo, platform, target, app, policy, folder, name, selectors, **kwargs)
            finally:
                self.platform_nodes[platform] = nodes
        with patch.object(runner, "phase", side_effect=early_exit):
            verdict = self.run_gate()
        self.assertEqual("passed", verdict["result"])
        retry = next(item for item in verdict["receipts"] if item["phase"] == "fresh-run-rerun-1")
        self.assertEqual([failed, unfinished], retry["selectors"])
        runner.validate_verdict(self.task, 123)

    def test_partial_fresh_retry_cannot_hide_missing_skipped_or_changed_execution(self):
        from copy import deepcopy
        first, failed = self.node, "tests/ios/test_example.py::test_other"
        self.platform_nodes = {"ios": [first, failed]}
        self.phase_failures = {("ios", "fresh-run"): [failed]}
        self.write_recipe({"platforms": {"ios": {"tests": [first, failed]}}})
        original = self.run_gate()
        for defect, expected in (("missing", "every selected check"), ("skipped", "failed or skipped"),
                                 ("app", "changed the app/device"), ("device", "changed the app/device"),
                                 ("unplanned", "differs from the selected checks"), ("scope", "full fresh-install selection")):
            with self.subTest(defect=defect):
                verdict = deepcopy(original)
                fresh = next(item for item in verdict["receipts"] if item["phase"] == "fresh-run")
                retry = next(item for item in verdict["receipts"] if item["phase"] == "fresh-run-rerun-1")
                if defect == "missing": fresh["outcomes"] = [item for item in fresh["outcomes"] if item["nodeid"] != first]
                elif defect == "skipped": retry["outcomes"][0]["outcome"] = "skipped"
                elif defect == "app": retry["app"] = dict(retry["app"], artifact_digest="different")
                elif defect == "device": retry["device"] = {"udid": "different"}
                elif defect == "unplanned": retry["outcomes"][0]["nodeid"] = "unplanned-check"
                elif defect == "scope": fresh["selectors"] = [failed]
                runner.write_json(self.task / "spec/e2e-verdict.json", verdict)
                with self.assertRaisesRegex(runner.E2EError, expected):
                    runner.validate_verdict(self.task, 123)

    def test_earlier_full_selection_fresh_retries_remain_valid(self):
        first, failed = self.node, "tests/ios/test_example.py::test_other"
        self.platform_nodes = {"ios": [first, failed]}
        self.phase_failures = {("ios", "fresh-run"): [failed]}
        self.write_recipe({"platforms": {"ios": {"tests": [first, failed]}}})
        original = self.fake_phase
        def legacy_phase(machine, repo, platform, target, app, policy, folder, name, selectors, **kwargs):
            return original(machine, repo, platform, target, app, policy, folder, name,
                            [first, failed] if name == "fresh-run-rerun-1" else selectors, **kwargs)
        with patch.object(runner, "phase", side_effect=legacy_phase):
            self.assertEqual("passed", self.run_gate()["result"])
        runner.validate_verdict(self.task, 123)

    def test_collection_failure_classification_uses_baseline(self):
        self.behavior["collection"] = False
        self.assertEqual("failed", self.run_gate()["result"])
        self.behavior["baseline-collection"] = False
        self.assertEqual("blocked", self.run_gate()["result"])

    def test_removed_tests_cannot_be_kept_uncollected(self):
        self.strategy["e2e"]["platforms"]["ios"]["removed_tests"] = [self.node]
        runner.write_json(self.task / "spec/verification-strategy.json", self.strategy)
        self.assertEqual("failed", self.run_gate()["result"])

    def test_collection_only_recipe_cannot_pass(self):
        self.write_recipe({"platforms": {"ios": {"collection_only": True}}})
        self.assertEqual("blocked", self.run_gate()["result"])
        self.assertEqual([], self.calls)

    def test_malformed_recipe_requires_verification_preparation_recovery(self):
        for plan in (["ios"], {"platforms": {"ios": {"collection_only": "false"}}},
                     {"platforms": {"ios": {"tests": [self.node]}}, "removed_tests": [42]},
                     {"platforms": {"ios": {"app": {"sha": "explicit-sha"}}}}):
            with self.subTest(plan=plan):
                self.write_recipe(plan)
                verdict = self.run_gate()
                self.assertEqual("blocked", verdict["result"])
                self.assertEqual("execution_recipe", verdict["failure_origin"])
                self.assertIn("strategy needs correction", runner.describe_verdict(verdict)["summary"])

    def test_invalid_verifier_recipe_does_not_request_project_implementation_correction(self):
        service, session, _ = self.coordinator()
        self.strategy["e2e"]["platforms"]["ios"]["commands"] = {}
        runner.write_json(self.task / "spec/verification-strategy.json", self.strategy)
        self.assertEqual("blocked", self.run_gate()["result"])
        session, event, followup = service.handle_role_output(session.id, VERIFICATION_COORDINATOR_ROLE, "failed",
            {"work_item_id": self.strategy["work_item_id"]})
        self.assertEqual("verification_blocked", event.event_type)
        self.assertEqual("e2e_environment", followup.payload["reason"])
        self.assertEqual(VERIFICATION_COORDINATOR_ROLE, session.current_owner)
        self.assertEqual("verification_requested", session.current_stage)
        self.assertNotIn("verification_correction_requested", [event.event_type for event in service.event_repository.list_for_session(session.id)])

    def test_source_plan_work_item_and_artifacts_are_bound_to_verdict(self):
        verdict = self.run_gate()
        with self.assertRaisesRegex(E2EError, "another work item"):
            runner.validate_verdict(self.task, 124)
        log = Path(verdict["receipts"][-1]["log"])
        log.write_text("modified evidence")
        with self.assertRaisesRegex(E2EError, "log changed"):
            runner.validate_verdict(self.task, 123)
        self.run_gate()
        (self.repo / "tests/ios/test_example.py").write_text("# changed\n")
        with self.assertRaisesRegex(E2EError, "stale"):
            runner.validate_verdict(self.task, 123)
        self.assertEqual("blocked", self.run_gate()["result"])

    def test_mr_retains_verification_after_committed_documentation_changes(self):
        (self.repo / "README.md").write_text("Before review\n")
        (self.repo / "old.md").write_text("Old documentation\n")
        runner.git(self.repo, "add", ".")
        runner.git(self.repo, "commit", "-m", "Document behavior")
        verdict = self.run_gate()
        original = (self.task / "spec/e2e-verdict.json").read_bytes()
        calls = len(self.calls)
        (self.repo / "README.md").write_text("Reviewed documentation\n")
        (self.repo / "old.md").unlink()
        (self.repo / "new.rst").write_text("New documentation\n")
        runner.git(self.repo, "add", ".")
        runner.git(self.repo, "commit", "-m", "Documentation review corrections")

        description = runner.mr_description(self.key, self.task)

        self.assertIn(f"Verified test source: `{verdict['source']['sha']}`", description)
        self.assertIn(f"Delivery source: `{runner.git(self.repo, 'rev-parse', 'HEAD')}`", description)
        for name in ("README.md", "old.md", "new.rst"):
            self.assertIn(f"`{name}`", description)
        self.assertEqual(original, (self.task / "spec/e2e-verdict.json").read_bytes())
        self.assertEqual(calls, len(self.calls))
        with self.assertRaisesRegex(E2EError, "stale"):
            runner.validate_verdict(self.task, 123)

    def test_mr_rejects_post_verification_code_and_configuration_changes(self):
        verdict = self.run_gate()
        for name in ("tests/ios/test_example.py", "requirements.txt", "pytest.ini", "config.yml", "docs/setup.py"):
            with self.subTest(path=name):
                runner.git(self.repo, "reset", "--hard", verdict["source"]["sha"])
                path = self.repo / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("changed\n")
                runner.git(self.repo, "add", ".")
                runner.git(self.repo, "commit", "-m", "Change execution inputs")
                with self.assertRaisesRegex(E2EError, "fresh gate is required"):
                    runner.mr_description(self.key, self.task)

    def test_mr_rejects_executable_or_symlink_documentation_and_code_renames(self):
        verdict = self.run_gate()
        for kind in ("executable", "symlink", "renamed code"):
            with self.subTest(kind=kind):
                runner.git(self.repo, "reset", "--hard", verdict["source"]["sha"])
                path = self.repo / "README.md"
                if kind == "symlink":
                    path.symlink_to("tests/ios/test_example.py")
                elif kind == "renamed code":
                    (self.repo / "tests/ios/test_example.py").rename(path)
                else:
                    path.write_text("#!/bin/sh\nexit 1\n")
                    path.chmod(0o755)
                runner.git(self.repo, "add", ".")
                runner.git(self.repo, "commit", "-m", "Change execution inputs with documentation names")
                with self.assertRaisesRegex(E2EError, "fresh gate is required"):
                    runner.mr_description(self.key, self.task)

    def test_mr_rejects_uncommitted_docs_and_unrelated_history(self):
        self.run_gate()
        (self.repo / "README.md").write_text("Uncommitted documentation\n")
        with self.assertRaisesRegex(E2EError, "stale"):
            runner.mr_description(self.key, self.task)
        runner.git(self.repo, "switch", "--detach", self.baseline)
        runner.git(self.repo, "add", ".")
        runner.git(self.repo, "commit", "-m", "Documentation on another revision")
        with self.assertRaisesRegex(E2EError, "not an ancestor"):
            runner.mr_description(self.key, self.task)

    def test_mr_documentation_changes_do_not_relax_strategy_and_support_bindings(self):
        path = self.repo / "input.md"
        path.write_text("Bound execution input\n")
        runner.git(self.repo, "add", ".")
        runner.git(self.repo, "commit", "-m", "Add bound input")
        self.strategy["e2e"]["support_files"] = ["repo/input.md"]
        runner.write_json(self.task / "spec/verification-strategy.json", self.strategy)
        verdict = self.run_gate()
        path.write_text("Changed bound execution input\n")
        runner.git(self.repo, "commit", "-am", "Change bound input")
        with self.assertRaisesRegex(E2EError, "support files changed"):
            runner.mr_description(self.key, self.task)
        runner.git(self.repo, "reset", "--hard", verdict["source"]["sha"])
        (self.repo / "README.md").write_text("Documentation correction\n")
        runner.git(self.repo, "add", ".")
        runner.git(self.repo, "commit", "-m", "Documentation correction")
        self.strategy["reason"] = "Changed execution plan"
        runner.write_json(self.task / "spec/verification-strategy.json", self.strategy)
        with self.assertRaisesRegex(E2EError, "execution strategy changed"):
            runner.mr_description(self.key, self.task)

    def test_mr_keeps_accepted_baseline_failures_after_documentation_correction(self):
        service, session, _, context = self.block_baseline()
        self.decide(service, session, context)
        verdict = self.run_gate()
        decisions = (self.task / "spec/e2e-operator-decisions.json").read_bytes()
        (self.repo / "README.md").write_text("Documentation correction\n")
        runner.git(self.repo, "add", ".")
        runner.git(self.repo, "commit", "-m", "Documentation correction")

        description = runner.mr_description(self.key, self.task)

        self.assertIn("Verification result: accepted_with_warnings", description)
        self.assertIn("these tests did not pass", description)
        self.assertIn(verdict["source"]["sha"], description)
        self.assertEqual(decisions, (self.task / "spec/e2e-operator-decisions.json").read_bytes())
        with self.assertRaisesRegex(E2EError, "stale"):
            runner.accepted_baseline_findings(self.task, self.strategy["work_item_id"], self.strategy)

    def test_mr_cli_reports_failure_on_stderr_without_loading_device_configuration(self):
        self.run_gate()
        with patch.dict(os.environ, {"SDD_WORKDIR": str(self.root)}), patch.object(
            Machine, "from_env", side_effect=AssertionError("MR description does not need devices")
        ):
            stdout, stderr = io.StringIO(), io.StringIO()
            from contextlib import redirect_stdout, redirect_stderr
            with redirect_stdout(stdout), redirect_stderr(stderr):
                self.assertEqual(0, runner.main(["mr-description", self.key]))
            self.assertIn("Verified test source", stdout.getvalue())
            self.assertEqual("", stderr.getvalue())
            (self.repo / "tests/ios/test_example.py").write_text("changed\n")
            runner.git(self.repo, "commit", "-am", "Change scenario after verification")
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                self.assertEqual(2, runner.main(["mr-description", self.key]))
            self.assertEqual("", stdout.getvalue())
            self.assertIn("fresh gate is required", stderr.getvalue())

    def test_edited_plan_and_empty_green_receipt_are_rejected(self):
        verdict = self.run_gate()
        receipt = verdict["receipts"][-1]
        Path(receipt["junit"]).write_text("<testsuite/>")
        receipt["junit_digest"] = runner.digest(Path(receipt["junit"]))
        receipt["results"] = {"passed": [], "failed": [], "skipped": []}
        runner.write_json(Path(receipt["path"]), {k: v for k, v in receipt.items() if k != "path"})
        runner.write_json(self.task / "spec/e2e-verdict.json", verdict)
        with self.assertRaisesRegex(E2EError, "actual successful tests"):
            runner.validate_verdict(self.task, 123)
        self.run_gate()
        (self.task / "spec/verification-strategy.json").write_text('{}')
        with self.assertRaisesRegex(E2EError, "execution strategy changed"):
            runner.validate_verdict(self.task, 123)

    def test_settings_survive_legacy_save_and_strategy_snapshots_policy(self):
        save_runtime_defaults(self.root, default_runner="codex", role_defaults={}, policy_defaults={})
        self.assertFalse(load_runtime_defaults(self.root)["e2e_defaults"]["include_smoke"])
        self.assertFalse(self.strategy["e2e"]["policy"]["include_smoke"])
        self.assertEqual(self.baseline, self.strategy["e2e"]["baseline_sha"])
        self.assertEqual("e2e_gate", self.strategy["mode"])

    def coordinator(self):
        database = Database(self.root / "factory.sqlite3")
        database.initialize()
        service = CoordinatorService(
            session_repository=SessionRepository(database), role_repository=RoleRepository(database),
            event_repository=EventRepository(database), artifact_repository=ArtifactRepository(database),
            work_item_repository=WorkItemRepository(database), session_backend=RecordingSessionBackend(),
            default_roles=DEFAULT_SESSION_ROLES, workdir_root=self.root, artifacts_root=self.root / "artifacts",
            jira_adapter=FakeJiraAdapter(self.root), gitlab_adapter=FakeGitLabAdapter(self.root),
            role_workspace_manager=RoleWorkspaceManager(runtime_root=self.root, repo_root=self.root, workdir_root=self.root),
            role_launcher_manager=RoleLauncherManager(repo_root=self.root, workdir_root=self.root, launcher_command=["sh"]),
        )
        session, event, _ = service.create_task_session(
            self.key, "oneshot", policy={"review_policy": "disabled", "doc_harvest_policy": "disabled"},
        )
        session, requested = service._enqueue_verification(session, event)
        self.strategy = runner.read_json(self.task / "spec/verification-strategy.json")
        return service, session, requested

    def test_coordinator_rejects_claim_without_receipts(self):
        service, session, requested = self.coordinator()
        with self.assertRaises(IntakeError):
            service.handle_role_output(session.id, VERIFICATION_COORDINATOR_ROLE, "passed",
                                       {"work_item_id": self.strategy["work_item_id"], "result": "passed"})
        with self.assertRaises(IntakeError):
            service._handle_verification_passed(session, requested)

    def test_device_occupation_blocks_before_any_run(self):
        import fcntl
        locks = self.root / "locks"
        locks.mkdir()
        with (locks / "ios-device.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            verdict = self.run_gate()
        self.assertEqual("blocked", verdict["result"])
        self.assertIn("device is busy", verdict["details"])
        self.assertEqual([], self.calls)

    def test_environment_block_and_retry_refreshes_work_item_contract(self):
        service, session, requested = self.coordinator()
        previous_id = self.strategy["work_item_id"]
        self.behavior.update({"run": False, "rerun-1": False, "baseline-1": False})
        self.run_gate()
        session, event, followup = service.handle_role_output(
            session.id, VERIFICATION_COORDINATOR_ROLE, "failed", {"work_item_id": previous_id},
        )
        self.assertEqual("verification_blocked", event.event_type)
        self.assertEqual("waiting_for_operator", session.status.value)
        self.assertEqual("e2e_environment", followup.payload["reason"])
        self.assertFalse(any(item.work_type == "verification_correction" for item in service.work_item_repository.list_for_session(session.id)))
        session, _, _ = service.retry_session(session.id)
        self.assertEqual("active", session.status.value)
        self.strategy = runner.read_json(self.task / "spec/verification-strategy.json")
        self.assertNotEqual(previous_id, self.strategy["work_item_id"])
        with self.assertRaises(E2EError):
            runner.validate_verdict(self.task, self.strategy["work_item_id"])
        self.behavior.clear()
        self.run_gate()
        session, event, followup = service.handle_role_output(
            session.id, VERIFICATION_COORDINATOR_ROLE, "passed", {"work_item_id": self.strategy["work_item_id"]},
        )
        self.assertEqual("verification_passed", event.event_type)
        self.assertEqual("send_to_test_completed", followup.event_type)
        self.assertEqual("completed", session.status.value)
        artifacts = service.artifact_repository.list_for_session(session.id)
        self.assertTrue(any(item.artifact_type == "e2e_run_receipt" for item in artifacts))

    def test_blocked_cycle_output_uses_native_environment_verdict(self):
        service, session, _ = self.coordinator()
        work_item_id = self.strategy["work_item_id"]
        self.behavior.update({"run": False, "rerun-1": False, "baseline-1": False})
        verdict = self.run_gate()
        session, event, followup = service.handle_role_output(
            session.id, VERIFICATION_COORDINATOR_ROLE, "blocked_verification_cycle",
            {"work_item_id": work_item_id, "summary": "Verification cycle blocked"},
        )
        self.assertEqual("verification_blocked", event.event_type)
        self.assertEqual("blocked", event.payload["e2e_result"])
        self.assertEqual(verdict["report_path"], event.payload["e2e_report_path"])
        self.assertEqual("e2e_environment", followup.payload["reason"])
        self.assertEqual("waiting_for_operator", session.status.value)
        self.assertEqual("waiting_for_operator", service.work_item_repository.get_by_id(work_item_id).status.value)
        interactive = service.get_interactive_state_summary(session.id)
        self.assertEqual("e2e_environment", interactive["source_reason"])
        self.assertEqual(VERIFICATION_COORDINATOR_ROLE, interactive["role_name"])
        self.assertFalse(interactive["needs_operator_input"])
        self.assertIn("also fails on baseline", interactive["summary"])
        self.assertIn("same app build", interactive["details"])
        self.assertNotIn("baseline_evidence", interactive["details"])
        self.assertFalse(any(item.work_type == "verification_cycle_review"
                             for item in service.work_item_repository.list_for_session(session.id)))

    def test_blocked_cycle_output_cannot_bypass_native_evidence(self):
        service, session, _ = self.coordinator()
        with self.assertRaises(IntakeError):
            service.handle_role_output(
                session.id, VERIFICATION_COORDINATOR_ROLE, "blocked_verification_cycle",
                {"work_item_id": self.strategy["work_item_id"], "summary": "Environment blocked"},
            )

    def test_baseline_diagnostics_preserve_distinct_task_and_reference_errors(self):
        verdict = {
            "result": "blocked",
            "classifications": [{"platform": "ios", "test": self.node,
                                  "kind": "baseline_or_environment_failure",
                                  "evidence": "/local/rerun.json", "baseline_evidence": "/local/baseline.json"}],
            "receipts": [
                {"path": "/local/rerun.json", "outcomes": [{"nodeid": self.node, "outcome": "failed",
                    "details": "Traceback with local state\nE       AttributeError: 'NoneType' object has no attribute 'get_text'"}]},
                {"path": "/local/baseline.json", "results": {"failed": [{"test": "tests.ios.test_example::test_example",
                    "details": "E           Exception: No WEBVIEW context found within timeout"}]}},
            ],
        }
        diagnostics = runner.describe_verdict(verdict)
        self.assertIn("also fails on baseline", diagnostics["summary"])
        self.assertIn("Task failure: AttributeError:", diagnostics["details"])
        self.assertIn("Baseline failure: Exception: No WEBVIEW context", diagnostics["details"])
        self.assertNotIn("/local/", diagnostics["details"])
        self.assertNotIn("Traceback with local state", diagnostics["details"])

    def test_environment_diagnostics_keep_concrete_preflight_blocker(self):
        diagnostics = runner.describe_verdict({"result": "blocked", "details": "Reserved ios device is busy"})
        self.assertIn("environment recovery", diagnostics["summary"])
        self.assertEqual("Reserved ios device is busy", diagnostics["details"])

    def test_gate_rejects_running_appium_with_old_version(self):
        self.stack.close()
        with patch.object(runner.urllib.request, "urlopen", return_value=io.StringIO(
            json.dumps({"value": {"ready": True, "build": {"version": "2.12.1"}}})
        )), patch.object(runner.subprocess, "Popen") as launch:
            with self.assertRaisesRegex(E2EError, "stop the old server"):
                runner.ensure_server(self.machine, self.root / "appium.log")
            launch.assert_not_called()

    def test_blocked_cycle_output_does_not_override_proven_regression(self):
        service, session, _ = self.coordinator()
        self.behavior.update({"run": False, "rerun-1": False})
        self.run_gate()
        session, event, followup = service.handle_role_output(
            session.id, VERIFICATION_COORDINATOR_ROLE, "blocked_verification_cycle",
            {"work_item_id": self.strategy["work_item_id"], "summary": "Environment blocked"},
        )
        self.assertEqual("verification_failed", event.event_type)
        self.assertEqual("verification_correction_requested", followup.event_type)

    def test_blocked_cycle_output_does_not_override_passing_gate(self):
        service, session, _ = self.coordinator()
        self.run_gate()
        session, event, followup = service.handle_role_output(
            session.id, VERIFICATION_COORDINATOR_ROLE, "blocked_verification_cycle",
            {"work_item_id": self.strategy["work_item_id"], "summary": "Verification cycle blocked"},
        )
        self.assertEqual("verification_passed", event.event_type)
        self.assertEqual("send_to_test_completed", followup.event_type)
        self.assertEqual("completed", session.status.value)

    def test_retry_legacy_qa_cycle_review_creates_fresh_verification_contract(self):
        service, session, _ = self.coordinator()
        original_id = self.strategy["work_item_id"]
        self.behavior.update({"run": False, "rerun-1": False, "baseline-1": False})
        self.run_gate()
        source_event = service._append_event(
            session_id=session.id, event_type="verification_blocked", producer_type="role",
            payload={"work_item_id": original_id, "summary": "Legacy verification cycle blocked"},
        )
        session, _ = service._handle_verification_blocked(session, source_event)
        legacy_item = next(item for item in service.work_item_repository.list_for_session(session.id)
                           if item.work_type == "verification_cycle_review")
        session, retry_event, _ = service.retry_session(session.id)
        retry_id = retry_event.payload["retry_work_item_id"]
        self.assertEqual("active", session.status.value)
        self.assertEqual("verification", service.work_item_repository.get_by_id(retry_id).work_type)
        self.assertEqual("completed", service.work_item_repository.get_by_id(legacy_item.id).status.value)
        self.strategy = runner.read_json(self.task / "spec/verification-strategy.json")
        self.assertEqual(retry_id, self.strategy["work_item_id"])
        with self.assertRaises(E2EError):
            runner.validate_verdict(self.task, retry_id)
        self.behavior.clear()
        self.run_gate()
        session, event, _ = service.handle_role_output(
            session.id, VERIFICATION_COORDINATOR_ROLE, "passed", {"work_item_id": retry_id},
        )
        self.assertEqual("verification_passed", event.event_type)
        self.assertEqual("completed", session.status.value)

    def test_verified_regression_routes_to_implementation_correction(self):
        service, session, requested = self.coordinator()
        self.behavior.update({"run": False, "rerun-1": False})
        self.run_gate()
        session, event, followup = service.handle_role_output(
            session.id, VERIFICATION_COORDINATOR_ROLE, "failed", {"work_item_id": self.strategy["work_item_id"]},
        )
        self.assertEqual("verification_failed", event.event_type)
        self.assertEqual("verification_correction_requested", followup.event_type)

    def android_plan(self):
        self.node = "tests/android/test_example.py::test_example"
        file = self.repo / "tests/android/test_example.py"
        file.parent.mkdir(parents=True)
        file.write_text("def test_example():\n    assert True\n")
        runner.git(self.repo, "add", ".")
        runner.git(self.repo, "commit", "-m", "Add Android scenario")
        self.write_recipe({"platforms": {"android": {"tests": [self.node]}}})

    def test_android_shutdown_runs_under_lock_after_all_retries_and_comparisons(self):
        import fcntl
        self.android_plan()
        def shutdown(machine):
            with (self.root / "locks/android-device.lock").open("w") as lock:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for failures, result, last_phase in (({}, "passed", "fresh-run"),
                                            ({"run": False, "rerun-1": False}, "failed", "baseline-1")):
            with self.subTest(result=result), patch.object(runner, "shutdown_android", side_effect=shutdown) as stop:
                self.behavior = failures
                verdict = self.run_gate()
                self.assertEqual(result, verdict["result"])
                self.assertEqual(last_phase, self.calls[-1][0])
                stop.assert_called_once_with(self.machine)

    def test_android_shutdown_runs_on_timeout_and_partial_boot_failure(self):
        self.android_plan()
        for failure in ("run", "boot"):
            with self.subTest(failure=failure), ExitStack() as stack:
                stop = stack.enter_context(patch.object(runner, "shutdown_android"))
                if failure == "boot":
                    def boot(machine, platform, *, boot=False):
                        if boot:
                            raise E2EError("emulator boot timed out")
                        return {"serial": "emulator-5584"}
                    stack.enter_context(patch.object(runner, "device", side_effect=boot))
                else:
                    def phase(*args, **kwargs):
                        if args[7] == "run":
                            raise E2EError("pytest timed out")
                        return self.fake_phase(*args, **kwargs)
                    stack.enter_context(patch.object(runner, "phase", side_effect=phase))
                self.assertEqual("blocked", self.run_gate()["result"])
                stop.assert_called_once_with(self.machine)

    def test_android_collection_only_and_busy_devices_are_not_stopped(self):
        import fcntl
        plan = {"platforms": {"ios": {"tests": [self.node]}, "android": {"collection_only": True}}}
        self.write_recipe(plan)
        with patch.object(runner, "shutdown_android") as stop:
            self.assertEqual("passed", self.run_gate()["result"])
            stop.assert_not_called()
        self.android_plan()
        with (self.root / "locks/android-device.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch.object(runner, "shutdown_android") as stop:
                self.assertEqual("blocked", self.run_gate()["result"])
                stop.assert_not_called()

    def test_android_cleanup_errors_keep_evidence_and_are_reported(self):
        self.android_plan()
        with patch.object(runner, "shutdown_android", side_effect=E2EError("adb unavailable")):
            verdict = self.run_gate()
        self.assertEqual("passed", verdict["result"])
        self.assertIn("adb unavailable", verdict["cleanup_warnings"][0])
        self.assertIn("adb unavailable", Path(verdict["report_path"]).read_text())
        runner.validate_verdict(self.task, 123)

    def ios_pool(self):
        self.machine = replace(self.machine, ios_pool=("sim-a", "sim-b", "sim-c"), ios_wda_root=self.root / "wda")
        self.stack.enter_context(patch.object(runner, "device", side_effect=lambda machine, platform, **kw:
            {"udid": machine.ios_udid, "version": "26.2"}))

    def test_ios_pool_bypasses_workspace_lock_and_shuts_down_only_its_leased_device(self):
        import fcntl
        self.ios_pool()
        locks = self.root / "locks"
        locks.mkdir()
        def shutdown(machine):
            self.assertEqual("sim-b", machine.ios_udid)
            with (locks / "ios-sim-b.lock").open("a") as lock:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with ExitStack() as stack:
            for name in ("ios-device.lock", "ios-sim-a.lock"):
                lock = stack.enter_context((locks / name).open("a"))
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            stop = stack.enter_context(patch.object(runner, "shutdown_ios", side_effect=shutdown))
            verdict = self.run_gate()
        self.assertEqual("passed", verdict["result"])
        stop.assert_called_once()
        self.assertEqual([{"udid": "sim-b", "stopped": True}], verdict["ios_simulator_cleanup"])
        self.assertTrue(all(item["device"]["udid"] == "sim-b" for item in verdict["receipts"]))
        runner.validate_verdict(self.task, 123)

    def test_ios_pool_shutdown_covers_failures_timeouts_partial_boot_and_interruptions(self):
        self.ios_pool()
        for failure in ("failed", "timeout", "boot", "interrupt"):
            with self.subTest(failure=failure), ExitStack() as stack:
                stop = stack.enter_context(patch.object(runner, "shutdown_ios"))
                self.behavior = {"run": False, "rerun-1": False, "baseline-1": False} if failure == "failed" else {}
                if failure == "boot":
                    def boot(machine, platform, *, boot=False):
                        if boot: raise E2EError("simulator boot timed out")
                        return {"udid": machine.ios_udid, "version": "26.2"}
                    stack.enter_context(patch.object(runner, "device", side_effect=boot))
                elif failure in {"timeout", "interrupt"}:
                    def phase(*args, **kwargs):
                        if args[7] == "run":
                            if failure == "interrupt": raise KeyboardInterrupt()
                            raise E2EError("pytest timed out")
                        return self.fake_phase(*args, **kwargs)
                    stack.enter_context(patch.object(runner, "phase", side_effect=phase))
                if failure == "interrupt":
                    with self.assertRaises(KeyboardInterrupt): self.run_gate()
                else:
                    self.assertEqual("blocked", self.run_gate()["result"])
                stop.assert_called_once()
                self.assertEqual("sim-a", stop.call_args.args[0].ios_udid)

    def test_exhausted_ios_pool_does_not_stop_other_runs(self):
        import fcntl
        self.ios_pool()
        self.strategy["e2e"]["policy"]["run_timeout_seconds"] = 0
        locks = self.root / "locks"
        locks.mkdir()
        with ExitStack() as stack:
            for udid in self.machine.ios_pool:
                lock = stack.enter_context((locks / f"ios-{udid}.lock").open("a"))
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            stop = stack.enter_context(patch.object(runner, "shutdown_ios"))
            verdict = self.run_gate()
        self.assertEqual("blocked", verdict["result"])
        self.assertIn("pool remained busy", verdict["details"])
        self.assertEqual([], self.calls)
        stop.assert_not_called()

    def test_ios_pool_cleanup_failure_preserves_evidence_and_report(self):
        self.ios_pool()
        with patch.object(runner, "shutdown_ios", side_effect=E2EError("simctl unavailable")):
            verdict = self.run_gate()
        self.assertEqual("passed", verdict["result"])
        self.assertFalse(verdict["ios_simulator_cleanup"][0]["stopped"])
        self.assertIn("simctl unavailable", Path(verdict["report_path"]).read_text())
        runner.validate_verdict(self.task, 123)

    def test_ios_pool_collection_only_checks_do_not_stop_a_device(self):
        self.ios_pool()
        self.write_recipe({"platforms": {"ios": {"collection_only": True}, "android": {"tests": [self.node]}}})
        with patch.object(runner, "shutdown_ios") as stop, patch.object(runner, "shutdown_android"):
            self.assertEqual("passed", self.run_gate()["result"])
        stop.assert_not_called()


class IOSPoolTests(unittest.TestCase):
    def machine(self, root):
        return Machine(root, Path("python"), root, "workspace-device", "", "", root, "appium", 4743,
                       ios_pool=("sim-a", "sim-b", "sim-c"), ios_wda_root=root / "wda")

    def test_three_parallel_leases_are_distinct_and_a_fourth_waits_for_release(self):
        import threading
        import time
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            machine = self.machine(root)
            leases = [runner.reserve_ios(machine, root, time.monotonic() + 5) for _ in range(3)]
            selected = [stack.enter_context(lease).ios_udid for lease in leases]
            self.assertEqual(list(machine.ios_pool), selected)
            waiting, acquired = threading.Event(), threading.Event()
            values, errors = [], []
            original_sleep = time.sleep
            def sleep(seconds):
                waiting.set()
                original_sleep(seconds)
            def fourth():
                try:
                    with runner.reserve_ios(machine, root, time.monotonic() + 5) as chosen:
                        values.append(chosen.ios_udid)
                        acquired.set()
                except BaseException as exc: errors.append(exc)
            with patch.object(runner.time, "sleep", side_effect=sleep):
                thread = threading.Thread(target=fourth)
                thread.start()
                try:
                    self.assertTrue(waiting.wait(2))
                    self.assertFalse(acquired.is_set())
                    leases[1].__exit__(None, None, None)
                    self.assertTrue(acquired.wait(2))
                finally:
                    thread.join(6)
            self.assertEqual([], errors)
            self.assertEqual(["sim-b"], values)

    def test_each_slot_has_its_own_ports_cache_and_assigned_capabilities(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            machine = self.machine(root)
            wda_ports, mjpeg_ports, paths = set(), set(), set()
            for udid in machine.ios_pool:
                selected = replace(machine, ios_udid=udid)
                with patch.object(runner, "ios_simulator", return_value={"state": "Shutdown", "version": "26.2"}):
                    target = runner.device(selected, "ios")
                context = {"device_id": udid, "platform_version": "26.2", "appium_port": "4743",
                           "application_id": "example.app", "adb": "", "app_path": "app.app", "results": "r", "collected": "c"}
                env = runner.execution_environment(selected, root, "ios", target, {}, context)
                assigned = json.loads(env["FACTORY_E2E_APPIUM_CAPABILITIES"])
                self.assertEqual(udid, assigned["appium:udid"])
                self.assertFalse(assigned["appium:shutdownOtherSimulators"])
                wda_ports.add(assigned["appium:wdaLocalPort"])
                mjpeg_ports.add(assigned["appium:mjpegServerPort"])
                paths.add(assigned["appium:derivedDataPath"])
            self.assertEqual({8110, 8111, 8112}, wda_ports)
            self.assertEqual({9110, 9111, 9112}, mjpeg_ports)
            self.assertEqual(3, len(paths))

    def test_shutdown_targets_only_the_selected_simulator_and_waits(self):
        with tempfile.TemporaryDirectory() as directory:
            machine = replace(self.machine(Path(directory)), ios_udid="sim-b")
            with patch.object(runner, "ios_simulator", side_effect=[{"state": "Booted"}, {"state": "Shutting Down"}, {"state": "Shutdown"}]), \
                    patch.object(runner, "execute") as execute, patch.object(runner.time, "sleep"):
                runner.shutdown_ios(machine)
            execute.assert_called_once_with(["xcrun", "simctl", "shutdown", "sim-b"])
            with patch.object(runner, "ios_simulator", return_value={"state": "Shutdown"}), patch.object(runner, "execute") as execute:
                runner.shutdown_ios(machine)
            execute.assert_not_called()

    def test_pool_env_is_separate_from_workspace_and_rejects_invalid_resources(self):
        env = {"E2E_DIR": "/tests", "E2E_PYTHON": "/python", "E2E_IOS_SIMULATOR_UDID": "workspace-device",
               "SDD_E2E_IOS_SIMULATOR_UDIDS": "00000000-0000-0000-0000-000000000001,00000000-0000-0000-0000-000000000002",
               "SDD_E2E_IOS_WDA_PORT_BASE": "8110", "SDD_E2E_IOS_MJPEG_PORT_BASE": "9110", "SDD_E2E_IOS_WDA_ROOT": "/wda"}
        with patch.dict(os.environ, env, clear=True):
            machine = Machine.from_env()
        self.assertEqual("workspace-device", machine.ios_udid)
        self.assertEqual(2, len(machine.ios_pool))
        for invalid in ({"SDD_E2E_IOS_SIMULATOR_UDIDS": "../outside"},
                        {"SDD_E2E_IOS_SIMULATOR_UDIDS": ",".join(["00000000-0000-0000-0000-000000000001"] * 2)},
                        {"SDD_E2E_IOS_WDA_PORT_BASE": "9110"}, {"SDD_E2E_IOS_MJPEG_PORT_BASE": "65535"},
                        {"SDD_E2E_IOS_WDA_ROOT": ""}):
            with self.subTest(invalid=invalid), patch.dict(os.environ, dict(env, **invalid), clear=True), self.assertRaises(E2EError):
                Machine.from_env()

    def test_shared_device_cannot_be_accessed_in_pool_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            machine = self.machine(Path(directory))
            with patch.object(runner, "ios_simulator") as discover, patch.object(runner, "execute") as execute:
                with self.assertRaisesRegex(E2EError, "Acquire a dedicated iOS pool lease"):
                    runner.device(machine, "ios", boot=True)
            discover.assert_not_called()
            execute.assert_not_called()


class AppiumServerTests(unittest.TestCase):
    def setUp(self):
        self.machine = Machine(Path("repo"), Path("python"), None, "", "avd", "emulator-5584", Path("sdk"), "appium", 4743)
        self.status = {"ready": True, "build": {"version": "3.0.2"}}

    def listener(self, arguments):
        def execute(command, **kwargs):
            if command[0] == "lsof":
                self.assertIn("-iTCP:4743", command)
                self.assertIn("-sTCP:LISTEN", command)
                return "1234\n1234"
            if command[0] == "ps":
                self.assertIn("1234", command)
                return "node /local/appium -p 4743 " + arguments
            raise AssertionError(f"Unexpected command: {command}")
        return execute

    def test_factory_launches_and_validates_scoped_chromedriver_permission(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(runner, "appium_server_status", side_effect=[None, self.status]), \
                patch.object(runner, "execute", side_effect=self.listener("--allow-insecure uiautomator2:chromedriver_autodownload")), \
                patch.object(runner.subprocess, "Popen") as launch:
            runner.ensure_server(self.machine, Path(directory) / "appium.log")
        command = launch.call_args.args[0]
        self.assertEqual(["appium", "-a", "127.0.0.1", "-p", "4743", "--base-path", "/wd/hub",
                          "--allow-insecure", "uiautomator2:chromedriver_autodownload"], command)
        self.assertNotIn("--relaxed-security", command)

    def test_reuses_shared_server_with_scoped_or_wildcard_permission(self):
        for arguments in ("--allow-insecure uiautomator2:chromedriver_autodownload",
                          "--allow-insecure=xcuitest:get_server_logs,UiAutomator2:chromedriver_autodownload",
                          "--allow-insecure=*:chromedriver_autodownload",
                          "--allow-insecure=uiautomator2:chromedriver_autodownload --deny-insecure=xcuitest:get_server_logs"):
            with self.subTest(arguments=arguments), patch.object(runner, "appium_server_status", return_value=self.status), \
                    patch.object(runner, "execute", side_effect=self.listener(arguments)), patch.object(runner.subprocess, "Popen") as launch:
                runner.ensure_server(self.machine, Path("unused.log"))
                launch.assert_not_called()

    def test_rejects_missing_unscoped_or_denied_permission_before_reuse(self):
        for arguments in ("", "--allow-insecure chromedriver_autodownload", "--relaxed-security",
                          "--allow-insecure=uiautomator2:chromedriver_autodownload --deny-insecure=uiautomator2:chromedriver_autodownload",
                          "--allow-insecure=uiautomator2:chromedriver_autodownload --deny-insecure *:chromedriver_autodownload"):
            with self.subTest(arguments=arguments), patch.object(runner, "appium_server_status", return_value=self.status), \
                    patch.object(runner, "execute", side_effect=self.listener(arguments)), patch.object(runner.subprocess, "Popen") as launch:
                with self.assertRaisesRegex(E2EError, "requires --allow-insecure.*restart it"):
                    runner.ensure_server(self.machine, Path("unused.log"))
                launch.assert_not_called()

    def test_listener_inspection_failure_is_actionable_without_starting_another_server(self):
        for result in ("", "1234\n5678", "not-a-pid"):
            with self.subTest(result=result), patch.object(runner, "appium_server_status", return_value=self.status), \
                    patch.object(runner, "execute", return_value=result), patch.object(runner.subprocess, "Popen") as launch:
                with self.assertRaisesRegex(E2EError, "Cannot inspect shared Appium launch flags"):
                    runner.ensure_server(self.machine, Path("unused.log"))
                launch.assert_not_called()

    def test_doctor_checks_running_server_flags_and_allows_no_running_server(self):
        expected = runner.read_json(Path(runner.__file__).with_name("toolchain.json"))
        installed = json.dumps({name: {"version": version} for name, version in expected["drivers"].items()})
        for status, arguments, ok in ((None, "", True), (self.status, "", False),
                (self.status, "--allow-insecure=uiautomator2:chromedriver_autodownload", True)):
            with self.subTest(status=status, arguments=arguments):
                replies = [expected["python"] + ".9", expected["appium"], installed]
                if status is not None:
                    replies += ["1234", "node appium " + arguments]
                with patch.object(runner, "execute", side_effect=replies), \
                        patch.object(runner, "appium_server_status", return_value=status), patch.object(runner.subprocess, "Popen") as launch:
                    health = runner.doctor(self.machine)
                self.assertEqual(ok, health["ok"])
                if not ok:
                    self.assertIn("uiautomator2:chromedriver_autodownload", health["errors"][0])
                launch.assert_not_called()


class E2EArtifactSelectionTests(unittest.TestCase):
    def test_pinned_artifact_survives_removal_from_shared_store(self):
        import shutil
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            machine = Machine(root, Path("python"), root, "", "", "", root, "appium", 4743)
            for platform, suffix in (("ios", ".app"), ("android", ".apk")):
                with self.subTest(platform=platform):
                    artifact = root / ("shared-master" + suffix)
                    if platform == "ios":
                        artifact.mkdir()
                        (artifact / "binary").write_bytes(b"app contents")
                    else:
                        artifact.write_bytes(b"app contents")
                    app = runner.resolve_app(machine, platform, {"path": str(artifact), "sha": "master-sha"})
                    pinned = runner.pin_app(root / "task", machine, platform, app)
                    self.assertEqual(app["artifact_digest"], pinned["artifact_digest"])
                    self.assertEqual(artifact.name, Path(pinned["path"]).name)
                    if artifact.is_dir():shutil.rmtree(artifact)
                    else:artifact.unlink()
                    self.assertEqual(pinned, runner.resolve_app(machine, platform, pinned))
                    self.assertEqual(pinned, runner.pin_app(root / "task", machine, platform, pinned))

    def test_shutdown_targets_only_reserved_android_serial_and_waits_for_disappearance(self):
        machine = Machine(Path("repo"), Path("python"), None, "", "avd", "emulator-5584", Path("sdk"), "appium", 4743)
        with patch.object(runner, "execute", side_effect=["emulator-5584\tdevice\nemulator-5554\tdevice", "OK", "emulator-5554\tdevice"]) as command:
            runner.shutdown_android(machine)
        self.assertEqual(["sdk/platform-tools/adb", "-s", "emulator-5584", "emu", "kill"], command.call_args_list[1].args[0])
        self.assertEqual(3, command.call_count)
        with patch.object(runner, "execute", return_value="emulator-5554\tdevice") as command:
            runner.shutdown_android(machine)
        command.assert_called_once_with(["sdk/platform-tools/adb", "devices"])
        with patch.object(runner, "execute", return_value="emulator-5584\tdevice"), patch.object(runner.time, "monotonic", side_effect=[0, 21]):
            with self.assertRaisesRegex(E2EError, "did not shut down"):
                runner.shutdown_android(machine)

    def test_master_build_selection_requires_provenance_and_explicit_build_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = root / "ios/artifacts"
            artifacts.mkdir(parents=True)
            app = artifacts / "master-abc.app"
            app.mkdir()
            (app / "binary").write_bytes(b"application")
            receipt = {"platform": "ios", "label": "master", "branch": "master", "sha": "abc",
                       "dirty": False, "built_at": "2026-10-05T10:00:00Z"}
            runner.write_json(app.with_suffix(".json"), receipt)
            machine = Machine(root, Path("python"), root, "", "", "", root, "appium", 4743)
            selected = runner.resolve_app(machine, "ios")
            self.assertEqual("abc", selected["sha"])
            self.assertEqual("master", selected["label"])
            receipt["dirty"] = True
            runner.write_json(app.with_suffix(".json"), receipt)
            with self.assertRaisesRegex(E2EError, "No clean master"):
                runner.resolve_app(machine, "ios")
            explicit = runner.resolve_app(machine, "ios", {"path": str(app), "sha": "explicit-sha"})
            self.assertEqual("explicit-sha", explicit["sha"])
            self.assertEqual(selected["artifact_digest"], explicit["artifact_digest"])


if __name__ == "__main__":
    unittest.main()
