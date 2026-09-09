import json
import unittest
from unittest.mock import Mock, patch

from spotifierd.config import Config
from spotifierd.playback import EventPlaybackState, LibrespotSupervisor


class IdleRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.state = EventPlaybackState()
        self.state.apply({'PLAYER_EVENT':'track_changed', 'URI':'spotify:track:saved',
                          'NAME':'Saved song', 'ARTISTS':'Artist', 'DURATION_MS':'180000'})
        self.state.apply({'PLAYER_EVENT':'paused','POSITION_MS':'45000'})
        self.daemon = LibrespotSupervisor(Config(), self.state.apply, self.state.snapshot)
        self.daemon.player_ready = True
        self.daemon.request = Mock(return_value='ok')

    def test_stopped_retains_selection_through_long_idle_and_play_reloads_it(self):
        self.state.apply({'PLAYER_EVENT':'stopped', 'TRACK_ID':'saved'})
        with patch('spotifierd.playback.time.monotonic', return_value=10**12):
            state = self.state.snapshot()
            self.assertEqual(state['title'],'Saved song')
            self.assertEqual(state['position_s'],45)
            self.assertEqual(state['status'],'Paused')
            self.assertFalse(state['track_loaded'])
            self.daemon.command('play_pause')
        command = self.daemon.request.call_args.args[0]
        self.assertTrue(command.startswith('restore '))
        payload=json.loads(command.removeprefix('restore '))
        self.assertEqual(payload['uri'],'spotify:track:saved')
        self.assertEqual(payload['position_ms'],45000)
        self.assertTrue(payload['playing'])

    def test_deactivation_never_automatically_takes_over_other_device(self):
        self.state.apply({'PLAYER_EVENT':'session_disconnected'})
        self.daemon._restore_playback()
        self.daemon.request.assert_not_called()
        self.assertTrue(self.state.snapshot()['has_track'])
        self.assertFalse(self.state.snapshot()['track_loaded'])
        self.daemon.command('pause')
        self.daemon.request.assert_not_called()
        self.daemon.command('play')
        self.assertTrue(self.daemon.request.call_args.args[0].startswith('restore '))

    def test_stale_stop_for_previous_track_does_not_unload_new_track(self):
        self.state.apply({'PLAYER_EVENT':'stopped','TRACK_ID':'old'})
        self.assertTrue(self.state.snapshot()['track_loaded'])

    def test_deactivation_freezes_extrapolated_playing_position(self):
        with patch('spotifierd.playback.time.monotonic',return_value=100):
            self.state.apply({'PLAYER_EVENT':'playing','POSITION_MS':'45000'})
        with patch('spotifierd.playback.time.monotonic',return_value=105):
            self.state.apply({'PLAYER_EVENT':'session_disconnected'})
        self.assertEqual(self.state.snapshot()['position_s'],50)
        self.assertEqual(self.state.snapshot()['status'],'Paused')

    def test_unconfirmed_recovery_retries_then_exposes_failure_and_allows_retry(self):
        self.state.apply({'PLAYER_EVENT':'stopped'})
        with patch('spotifierd.playback.time.monotonic',return_value=100):
            self.daemon.command('play')
        for now in (116,132,148):
            with patch('spotifierd.playback.time.monotonic',return_value=now):
                self.daemon._restore_playback()
        self.assertEqual(self.daemon.request.call_count,3)
        self.assertIn('did not confirm', self.state.snapshot()['playback_error'])
        self.assertIsNone(self.daemon.recovery)
        self.daemon.command('play')
        self.assertEqual(self.daemon.request.call_count,4)

    def test_logout_clears_retained_selection(self):
        self.state.apply({'PLAYER_EVENT':'session_disconnected'})
        self.state.apply({'PLAYER_EVENT':'clear_selection'})
        self.assertFalse(self.state.snapshot()['has_track'])

    def test_recovery_requires_matching_track_and_playback_confirmation(self):
        self.state.apply({'PLAYER_EVENT':'stopped'})
        self.daemon.command('play')
        self.daemon._handle_event({'PLAYER_EVENT':'playing','TRACK_ID':'other','POSITION_MS':'0'})
        self.assertIsNotNone(self.daemon.recovery)
        self.daemon._handle_event({'PLAYER_EVENT':'paused','TRACK_ID':'saved','POSITION_MS':'45000'})
        self.assertIsNotNone(self.daemon.recovery)
        self.daemon._handle_event({'PLAYER_EVENT':'playing','TRACK_ID':'saved','POSITION_MS':'45000'})
        self.assertIsNone(self.daemon.recovery)
