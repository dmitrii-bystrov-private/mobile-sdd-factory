from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from factory import ios_verification_state as native


class IOSVerificationStateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.task = self.root / "IOS-100"
        (self.task / "spec").mkdir(parents=True)
        (self.task / "spec/verification-strategy.json").write_text('{"work_item_id":7}')
        self.dispatched = datetime.now(UTC) - timedelta(seconds=1)
        self.env = patch.dict(os.environ, {"SDD_WORKDIR": str(self.root)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.sha = patch.object(native, "source_sha", return_value="verified-sha")
        self.sha.start()
        self.addCleanup(self.sha.stop)
        with redirect_stdout(io.StringIO()):
            native.main(["start", "IOS-100", "--pid", "123"])
        self.record = json.loads(native.state_path(self.task).read_text())
        self.run_id = self.record["run_id"]

    def test_wait_resume_and_failure_completion_are_bound_to_one_run(self):
        lock = self.root / "lock"
        lock.mkdir()
        (lock / "owner.pid").write_text("456")
        native.main(["phase", "IOS-100", "--run-id", self.run_id, "--phase", "test_without_building"])
        with redirect_stdout(io.StringIO()) as output:
            native.main(["wait", "IOS-100", "--run-id", self.run_id,
                         "--resource", "iOS simulator SIM", "--lock-dir", str(lock)])
        with patch.object(native, "runner_is_alive", return_value=True):
            waiting = native.read_active_run(self.task, 7, self.dispatched)
            self.assertEqual("waiting_for_resource", waiting["state"])
            self.assertEqual("456", waiting["resource"]["owner_pid"])
            self.assertIn("SDD_PROGRESS:", output.getvalue())
            native.main(["running", "IOS-100", "--run-id", self.run_id])
            running = native.read_active_run(self.task, 7, self.dispatched)
            self.assertEqual("running", running["state"])
            self.assertNotIn("resource", running)
            native.main(["finish", "IOS-100", "--run-id", self.run_id, "--exit-code", "65"])
            self.assertIsNone(native.read_active_run(self.task, 7, self.dispatched))
        finished = json.loads(native.state_path(self.task).read_text())
        self.assertEqual("finished", finished["state"])
        self.assertEqual(65, finished["exit_code"])

    def test_dead_runner_stale_dispatch_work_item_and_changed_source_do_not_defer(self):
        with patch.object(native, "runner_is_alive", return_value=True):
            self.assertIsNotNone(native.read_active_run(self.task, 7, self.dispatched))
            self.assertIsNone(native.read_active_run(self.task, 8, self.dispatched))
            self.assertIsNone(native.read_active_run(self.task, 7, datetime.now(UTC)))
            with patch.object(native, "source_sha", return_value="changed-sha"):
                self.assertIsNone(native.read_active_run(self.task, 7, self.dispatched))
        with patch.object(native, "runner_is_alive", return_value=False):
            self.assertIsNone(native.read_active_run(self.task, 7, self.dispatched))

    def test_prior_run_cannot_overwrite_new_execution_state(self):
        before = native.state_path(self.task).read_bytes()
        native.main(["finish", "IOS-100", "--run-id", "old-run", "--exit-code", "0"])
        self.assertEqual(before, native.state_path(self.task).read_bytes())

    def test_process_identity_rejects_reused_pid_for_another_task(self):
        with patch.object(native.subprocess, "check_output", return_value="bash scripts/ios-verify.sh IOS-100"):
            self.assertTrue(native.runner_is_alive(123, "IOS-100"))
            self.assertFalse(native.runner_is_alive(123, "IOS-200"))
        with patch.object(native.subprocess, "check_output", return_value="sleep 100"):
            self.assertFalse(native.runner_is_alive(123, "IOS-100"))

    def test_lock_owner_ancestry_distinguishes_real_recursion_from_another_process(self):
        self.assertTrue(native.lock_owner_is_ancestor(os.getpid()))
        with patch.object(native.subprocess, "check_output", return_value="1"):
            self.assertFalse(native.lock_owner_is_ancestor(999999))
