import errno
import asyncio
from pathlib import Path
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from factory.disk_space import DiskSpaceGuard, disk_space_failure


class DiskSpaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'IOS-CACHE/tmp/verification/ios/derived-data').mkdir(parents=True)
        self.guard = DiskSpaceGuard(self.root, self.root)
        self.environment = patch.dict('os.environ', {'IOS_MIN_FREE_DISK_GB': '50', 'IOS_DERIVED_DATA_PRUNE_ENABLED': '1'})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_low_space_cleanup_protects_unfinished_sessions_and_is_throttled(self):
        with sqlite3.connect(self.guard.database_path) as connection:
            connection.execute('CREATE TABLE sessions(task_key TEXT, status TEXT)')
            connection.executemany('INSERT INTO sessions VALUES (?, ?)',
                [('IOS-A', 'active'), ('IOS-B', 'waiting_for_operator'), ('IOS-C', 'completed')])
        with patch('factory.disk_space.shutil.disk_usage', return_value=SimpleNamespace(free=1)), \
             patch('factory.disk_space.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout='pruned', stderr='')) as run:
            self.guard.check(current_key='IOS-CURRENT')
            self.guard.check()
            run.assert_called_once()
            self.assertEqual(['IOS-CURRENT', 'IOS-A', 'IOS-B'], run.call_args.args[0][2:])
            self.guard.check(force=True)
            self.assertEqual(2, run.call_count)

    def test_healthy_volume_never_starts_cleanup(self):
        with patch('factory.disk_space.shutil.disk_usage', return_value=SimpleNamespace(free=100 * 1024**3)), \
             patch('factory.disk_space.subprocess.run') as run:
            self.guard.check()
            run.assert_not_called()

    def test_unreadable_task_state_does_not_guess_removable_caches(self):
        with patch('factory.disk_space.shutil.disk_usage', return_value=SimpleNamespace(free=1)), \
             patch.object(self.guard, 'protected_tasks', side_effect=sqlite3.OperationalError('database is locked')), \
             patch('factory.disk_space.subprocess.run') as run:
            self.guard.check()
            run.assert_not_called()

    def test_concurrent_cleanup_is_not_started(self):
        with patch('factory.disk_space.shutil.disk_usage', return_value=SimpleNamespace(free=1)), \
             patch('factory.disk_space.fcntl.flock', side_effect=BlockingIOError()), \
             patch('factory.disk_space.subprocess.run') as run:
            self.guard.check()
            run.assert_not_called()

    def test_disabled_cleanup_is_honored(self):
        with patch.dict('os.environ', {'IOS_DERIVED_DATA_PRUNE_ENABLED': '0'}), \
             patch('factory.disk_space.subprocess.run') as run:
            self.guard.check(force=True)
            run.assert_not_called()

    def test_disk_errors_are_distinct_from_transport_or_capacity_failures(self):
        for error in (OSError(errno.ENOSPC, 'write failed'), 'database or disk is full',
                      'No space left on device', 'Transcript writes are failing (disk full — ENOSPC)'):
            self.assertTrue(disk_space_failure(error))
        for error in ('transport failure', 'database is locked', 'model capacity exceeded'):
            self.assertFalse(disk_space_failure(error))

    def test_api_disk_failure_checks_caches_and_returns_503_without_replaying_mutation(self):
        from backend.api.app import create_app
        dependencies = SimpleNamespace(config=SimpleNamespace(workdir_root=self.root, repo_root=self.root,
                                        database_path=self.guard.database_path), loop_runner=None)
        with patch('backend.api.app.build_dependencies', return_value=dependencies):
            app = create_app()
        dispatch = next(item.kwargs['dispatch'] for item in app.user_middleware if 'dispatch' in item.kwargs)
        call_next = AsyncMock(side_effect=OSError(errno.ENOSPC, 'write failed'))
        with patch('backend.api.app.DiskSpaceGuard') as guard:
            response = asyncio.run(dispatch(object(), call_next))
            guard.return_value.check.assert_called_once_with(force=True)
        self.assertEqual(503, response.status_code)
        self.assertIn(b'disk space', response.body)
        call_next.assert_awaited_once()

    def test_api_does_not_misclassify_other_failures_as_disk_pressure(self):
        from backend.api.app import create_app
        with patch('backend.api.app.build_dependencies', return_value=SimpleNamespace(loop_runner=None)):
            app = create_app()
        dispatch = next(item.kwargs['dispatch'] for item in app.user_middleware if 'dispatch' in item.kwargs)
        with self.assertRaisesRegex(ValueError, 'other failure'):
            asyncio.run(dispatch(object(), AsyncMock(side_effect=ValueError('other failure'))))
