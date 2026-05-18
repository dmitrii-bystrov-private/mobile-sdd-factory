from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

from backend.tools.fake_adapters import FakeSnapshotAdapter


class FakeAdaptersTests(unittest.TestCase):
    def test_fake_snapshot_creates_isolated_task_git_repo(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            adapter = FakeSnapshotAdapter(repo_root=root, workdir_root=root / "workdir")

            result = adapter.run("IOS-FAKE-001")

            self.assertEqual(0, result.returncode)
            task_dir = root / "workdir" / "IOS-FAKE-001"
            runtime_role_dir = task_dir / "runtime" / "role-workspaces" / "code-reviewer"
            runtime_role_dir.mkdir(parents=True, exist_ok=True)

            repo_top = subprocess.run(
                ["git", "-C", str(runtime_role_dir), "rev-parse", "--show-toplevel"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            status = subprocess.run(
                ["git", "-C", str(runtime_role_dir), "status", "--short"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()

            self.assertEqual(str(task_dir.resolve()), str(Path(repo_top).resolve()))
            self.assertEqual("", status)


if __name__ == "__main__":
    unittest.main()
