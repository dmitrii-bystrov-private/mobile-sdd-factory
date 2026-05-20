import time
import unittest

from backend.coordinator.loop_runner import CoordinatorLoopRunner


class LoopRunnerTests(unittest.TestCase):
    def test_run_once_updates_counters(self) -> None:
        calls = []

        def callback():
            calls.append(1)
            return None, 2, 3

        runner = CoordinatorLoopRunner(callback=callback, interval_seconds=0.01)

        runner.run_once()
        status = runner.status()

        self.assertEqual(1, len(calls))
        self.assertEqual(1, status.tick_count)
        self.assertEqual(2, status.last_session_count)
        self.assertEqual(3, status.last_chunk_count)

    def test_start_and_stop_background_loop(self) -> None:
        calls = []

        def callback():
            calls.append(time.time())
            return None, 1, 0

        runner = CoordinatorLoopRunner(callback=callback, interval_seconds=0.01)

        started = runner.start()
        time.sleep(0.05)
        stopped = runner.stop()
        status = runner.status()

        self.assertTrue(started)
        self.assertTrue(stopped)
        self.assertFalse(status.running)
        self.assertGreaterEqual(status.tick_count, 1)
        self.assertGreaterEqual(len(calls), 1)

    def test_background_loop_survives_callback_exception(self) -> None:
        calls = []

        def callback():
            calls.append(time.time())
            if len(calls) == 1:
                raise RuntimeError("boom")
            return None, 1, 0

        runner = CoordinatorLoopRunner(callback=callback, interval_seconds=0.01)

        started = runner.start()
        time.sleep(0.06)
        stopped = runner.stop()
        status = runner.status()

        self.assertTrue(started)
        self.assertTrue(stopped)
        self.assertFalse(status.running)
        self.assertGreaterEqual(len(calls), 2)
        self.assertGreaterEqual(status.tick_count, 1)


if __name__ == "__main__":
    unittest.main()
