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
            runtime = Path(directory)
            pid_path = runtime / "librespot.pid"
            event_path = runtime / "events.sock"
            control_path = runtime / "control.sock"
            pid_path.write_text("1234\n")
            with (
                patch("spotifierd.playback.LIBRESPOT_PID_PATH", pid_path),
                patch("spotifierd.playback.EVENT_SOCKET_PATH", event_path),
                patch("spotifierd.playback.CONTROL_SOCKET_PATH", control_path),
            ):
                daemon.stop()
                self.assertFalse(pid_path.exists())

        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=3)
        self.assertIsNone(daemon.process)

    def test_stop_waits_for_monitor_before_service_can_restart(self) -> None:
        daemon = LibrespotSupervisor(Config())
        monitor = Mock()
        daemon.monitor_thread = monitor

        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            with (
                patch("spotifierd.playback.LIBRESPOT_PID_PATH", runtime / "player.pid"),
                patch("spotifierd.playback.EVENT_SOCKET_PATH", runtime / "events.sock"),
                patch("spotifierd.playback.CONTROL_SOCKET_PATH", runtime / "control.sock"),
            ):
                daemon.stop()

        monitor.join.assert_called_once_with(timeout=3)
        self.assertIsNone(daemon.monitor_thread)

    def test_ready_requires_live_process_and_control_socket(self) -> None:
        daemon = LibrespotSupervisor(Config())
        daemon.process = Mock()
        daemon.process.poll.return_value = None
        daemon.player_ready = True

        with patch("spotifierd.playback.CONTROL_SOCKET_PATH") as control_socket:
            control_socket.is_socket.return_value = False
            self.assertFalse(daemon.ready)
            control_socket.is_socket.return_value = True
            self.assertTrue(daemon.ready)

    def test_monitor_terminates_unreachable_ready_player(self) -> None:
        daemon = LibrespotSupervisor(Config())
        daemon.process = Mock()
        daemon.process.poll.return_value = None
        daemon.player_ready = True
        daemon.stopping.wait = Mock(side_effect=[False, True])

        with patch("spotifierd.playback.CONTROL_SOCKET_PATH") as control_socket:
            control_socket.is_socket.return_value = False
            daemon._monitor()

        daemon.process.terminate.assert_called_once_with()
        self.assertFalse(daemon.player_ready)

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
        connection.__enter__.return_value.recv.side_effect = [b"ok\n", b""]

        with patch("spotifierd.playback.socket.socket", return_value=connection):
            daemon.command("pause")

        control = connection.__enter__.return_value
        control.sendall.assert_called_once_with(b"pause\n")

    def test_local_lyrics_command_reads_complete_json_response(self) -> None:
        daemon = LibrespotSupervisor(Config())
        daemon.process = Mock()
        daemon.process.poll.return_value = None
        connection = MagicMock()
        control = connection.__enter__.return_value
        control.recv.side_effect = [
            b'{"synced":true,"lines":[',
            b'{"time_ms":1250,"text":"Line"}]}',
            b"",
        ]

        with patch("spotifierd.playback.socket.socket", return_value=connection):
            result = daemon.lyrics("spotify:track:track-id")

        control.sendall.assert_called_once_with(b"lyrics track-id\n")
        self.assertTrue(result["synced"])
        self.assertEqual(result["lines"], [{"time_ms": 1250, "text": "Line"}])

    @patch("spotifierd.playback.threading.Timer")
    def test_rapid_loads_only_commit_latest_track(self, timer_class) -> None:
        daemon = LibrespotSupervisor(Config())
        daemon.process = Mock()
        daemon.process.poll.return_value = None
        first_timer = Mock()
        second_timer = Mock()
        timer_class.side_effect = [first_timer, second_timer]

        daemon.load("spotify:track:first", "spotify:playlist:context")
        daemon.load("spotify:track:second", "spotify:playlist:context")

        first_timer.cancel.assert_called_once_with()
        first_callback = timer_class.call_args_list[0].args[1]
        first_args = timer_class.call_args_list[0].kwargs["args"]
        second_callback = timer_class.call_args_list[1].args[1]
        second_args = timer_class.call_args_list[1].kwargs["args"]
        with patch.object(daemon, "command") as command:
            first_callback(*first_args)
            second_callback(*second_args)

        command.assert_called_once_with(
            "load spotify:track:second spotify:playlist:context"
        )

    def test_unavailable_track_does_not_interrupt_player_state(self) -> None:
        state = EventPlaybackState()
        state.apply({
            "PLAYER_EVENT": "track_changed",
            "TRACK_ID": "playing",
            "URI": "spotify:track:playing",
            "NAME": "Playing Track",
            "DURATION_MS": "180000",
        })
        state.apply({
            "PLAYER_EVENT": "playing",
            "TRACK_ID": "playing",
            "POSITION_MS": "12000",
        })

        state.apply({
            "PLAYER_EVENT": "unavailable",
            "TRACK_ID": "unavailable",
            "ERROR": "Spotify could not load the selected track",
        })

        snapshot = state.snapshot()
        self.assertTrue(snapshot["has_track"])
        self.assertEqual(snapshot["uri"], "spotify:track:playing")
        self.assertEqual(snapshot["status"], "Playing")
        self.assertEqual(snapshot["playback_error"], "")

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
