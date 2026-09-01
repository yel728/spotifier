import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from spotifierd.config import Config
from spotifierd.playback import LibrespotSupervisor


class DaemonLifecycleTests(unittest.TestCase):
    def test_stop_librespot_terminates_child_and_removes_pid_file(self) -> None:
        daemon = LibrespotSupervisor(Config())
        process = Mock()
        process.poll.return_value = None
        process.pid = 1234
        daemon.process = process

        with tempfile.TemporaryDirectory() as directory:
            pid_path = Path(directory) / "librespot.pid"
            pid_path.write_text("1234\n")
            with patch("spotifierd.playback.LIBRESPOT_PID_PATH", pid_path):
                daemon.stop()
                self.assertFalse(pid_path.exists())

        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=3)
        self.assertIsNone(daemon.process)

    def test_reset_credentials_restarts_without_cached_login(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            credentials = cache / "credentials.json"
            credentials.write_text("{}")
            daemon = LibrespotSupervisor(Config(librespot_args=["--cache", str(cache)]))

            with patch.object(daemon, "stop") as stop, patch.object(daemon, "start") as start:
                daemon.reset_credentials()

            stop.assert_called_once_with()
            start.assert_called_once_with()
            self.assertFalse(credentials.exists())


if __name__ == "__main__":
    unittest.main()
