import json
import unittest
from unittest.mock import Mock, patch

from spotifierd.config import Config
from spotifierd.playback import EventPlaybackState, LibrespotSupervisor


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.state = EventPlaybackState()
        self.state.apply({'PLAYER_EVENT': 'track_changed', 'URI': 'spotify:track:current', 'DURATION_MS': '180000'})
        self.state.apply({'PLAYER_EVENT': 'paused', 'POSITION_MS': '42000'})
        self.state.apply({'PLAYER_EVENT': 'volume_changed', 'VOLUME': '32768'})
        self.daemon = LibrespotSupervisor(Config(), self.state.apply, self.state.snapshot)
        self.daemon.context_uri = 'spotify:playlist:context'
        self.daemon.request = Mock(return_value='ok')

    def restart(self):
        self.daemon._remember_playback()
        self.state.apply({'PLAYER_EVENT': 'player_reset'})
        self.daemon.player_ready = True
        self.daemon._restore_playback()

    def payload(self):
        return json.loads(self.daemon.request.call_args.args[0].removeprefix('restore '))

    def test_paused_track_restores_position_context_and_volume_without_playing(self):
        self.restart()
        saved = self.payload()
        self.assertEqual(saved['uri'], 'spotify:track:current')
        self.assertEqual(saved['context_uri'], 'spotify:playlist:context')
        self.assertEqual(saved['position_ms'], 42000)
        self.assertEqual(saved['volume'], 32768)
        self.assertFalse(saved['playing'])
        self.daemon._restore_playback()
        self.daemon.request.assert_called_once()

    def test_playing_track_resumes_and_freezes_position_during_reconnect(self):
        with patch('spotifierd.playback.time.monotonic', return_value=100):
            self.state.apply({'PLAYER_EVENT': 'playing', 'POSITION_MS': '42000'})
        with patch('spotifierd.playback.time.monotonic', return_value=103):
            self.daemon._remember_playback()
        self.state.apply({'PLAYER_EVENT': 'player_reset'})
        with patch('spotifierd.playback.time.monotonic', return_value=200):
            self.restart()
        self.assertTrue(self.payload()['playing'])
        self.assertEqual(self.payload()['position_ms'], 45000)

    def test_repeated_failure_before_track_loaded_keeps_checkpoint(self):
        self.restart()
        self.restart()
        self.assertEqual(self.payload()['uri'], 'spotify:track:current')
        self.assertEqual(self.payload()['position_ms'], 42000)

    def test_connection_error_retries_when_ready(self):
        self.daemon.request.side_effect = [ConnectionRefusedError(), 'ok']
        self.restart()
        self.daemon._restore_playback()
        self.assertEqual(self.daemon.request.call_count, 2)
        self.assertTrue(self.daemon.restore_sent)

    def test_no_restore_without_ready_or_active_track(self):
        self.daemon._remember_playback()
        self.daemon._restore_playback()
        self.daemon.request.assert_not_called()
        self.state.apply({'PLAYER_EVENT': 'clear_selection'})
        self.daemon.recovery = None
        self.restart()
        self.daemon.request.assert_not_called()

    def test_pause_during_reconnect_changes_restore_state(self):
        self.state.apply({'PLAYER_EVENT': 'playing', 'POSITION_MS': '42000'})
        self.daemon._remember_playback()
        self.daemon.command('pause')
        self.daemon.request.assert_not_called()
        self.daemon.player_ready = True
        self.daemon._restore_playback()
        self.assertFalse(self.payload()['playing'])

    def test_pause_after_restore_is_sent_to_player(self):
        self.restart()
        self.daemon.command('pause')
        self.daemon.request.assert_called_with('pause')
        self.assertIsNone(self.daemon.recovery)

    def test_new_track_selection_cancels_old_recovery(self):
        self.daemon._remember_playback()
        self.daemon.process = Mock()
        self.daemon.process.poll.return_value = None
        with patch('spotifierd.playback.threading.Timer'):
            self.daemon.load('spotify:track:new')
        self.daemon.player_ready = True
        self.daemon._restore_playback()
        self.daemon.request.assert_not_called()
        self.assertIsNone(self.daemon.recovery)

    def test_shutdown_prevents_recovery(self):
        self.daemon._remember_playback()
        self.daemon.player_ready = True
        self.daemon.stopping.set()
        self.daemon._restore_playback()
        self.daemon.request.assert_not_called()
