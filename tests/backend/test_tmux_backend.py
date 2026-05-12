from pathlib import Path
import tempfile
import unittest

from backend.session_backend.tmux_backend import TmuxSessionBackend


class TmuxBackendTests(unittest.TestCase):
    def test_recording_mode_tracks_sent_inputs_without_tmux(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            backend = TmuxSessionBackend(
                mode="recording",
                runtime_root=Path(temp_dir),
            )
            session = backend.create_task_session("IOS-50000")
            role = backend.spawn_role(session, "implementer")

            backend.send_input(role, "hello world")

            self.assertEqual("recording", backend.effective_mode)
            self.assertEqual(["hello world"], backend.get_sent_inputs(role.role_id))


if __name__ == "__main__":
    unittest.main()
