import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from spotifierd.config import Config
from spotifierd.playback import EventPlaybackState, LibrespotSupervisor
from spotifierd.server import Application


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
            daemon = LibrespotSupervisor(Config(player_cache=str(cache)))

            with patch.object(daemon, "stop") as stop, patch.object(daemon, "start") as start:
                daemon.reset_credentials()

            stop.assert_called_once_with()
            start.assert_called_once_with()
            self.assertFalse(credentials.exists())

    def test_local_playback_command_uses_control_socket(self) -> None:
        daemon = LibrespotSupervisor(Config())
        daemon.process = Mock()
        daemon.process.poll.return_value = None
        connection = MagicMock()
        connection.__enter__.return_value.recv.return_value = b"ok\n"

        with patch("spotifierd.playback.socket.socket", return_value=connection):
            daemon.command("pause")

        control = connection.__enter__.return_value
        control.sendall.assert_called_once_with(b"pause\n")

    def test_play_pause_uses_local_player_not_spotify(self) -> None:
        app = Application.__new__(Application)
        app.librespot = Mock()
        app.spotify = Mock()

        app.play_pause()

        app.librespot.command.assert_called_once_with("play_pause")
        app.spotify.assert_not_called()

    def test_status_uses_event_state_without_spotify_request(self) -> None:
        app = Application.__new__(Application)
        app.config = Config()
        app.oauth = Mock(logged_in=True)
        app.spotify = Mock()
        app.playback = EventPlaybackState()
        app.librespot = Mock(running=True, login_url="")
        app.playback.apply({
            "PLAYER_EVENT": "track_changed",
            "URI": "spotify:track:event-track",
            "NAME": "Event Track",
            "DURATION_MS": "180000",
        })

        state = app.status()

        self.assertEqual(state["title"], "Event Track")
        self.assertTrue(state["streaming_ready"])
        app.spotify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
