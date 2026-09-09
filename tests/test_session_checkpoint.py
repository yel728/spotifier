import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from spotifierd.config import Config
from spotifierd.playback import EventPlaybackState, LibrespotSupervisor


class SessionCheckpointTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'playback.json'
        self.state=EventPlaybackState()
        self.state.apply({'PLAYER_EVENT':'track_changed','URI':'spotify:track:chosen','NAME':'Chosen','DURATION_MS':'180000'})
        self.state.apply({'PLAYER_EVENT':'paused','POSITION_MS':'45000'})
        self.state.apply({'PLAYER_EVENT':'volume_changed','VOLUME':'30000'})
        self.state.apply({'PLAYER_EVENT':'shuffle_changed','SHUFFLE':'true'})
        self.state.apply({'PLAYER_EVENT':'repeat_changed','REPEAT':'true','REPEAT_TRACK':'false'})
        self.daemon=LibrespotSupervisor(Config(),self.state.apply,self.state.snapshot,self.path)
        self.daemon.context_uri='spotify:playlist:source'
        self.daemon.request=Mock(return_value='ok')
        self.daemon.player_ready=True

    def test_full_session_survives_daemon_restart_for_playlist_and_album(self):
        for kind,mode in [('playlist','Playlist'),('album','Track')]:
            with self.subTest(kind=kind):
                self.daemon.context_uri=f'spotify:{kind}:source'
                self.state.apply({'PLAYER_EVENT':'repeat_changed','REPEAT':str(mode=='Playlist').lower(),
                                  'REPEAT_TRACK':str(mode=='Track').lower()})
                self.daemon._save_checkpoint()
                fresh=EventPlaybackState()
                restored=LibrespotSupervisor(Config(),fresh.apply,fresh.snapshot,self.path)
                restored._load_checkpoint()
                self.assertEqual(fresh.snapshot()['context_uri'],f'spotify:{kind}:source')
                restored.request=Mock(return_value='ok')
                restored.player_ready=True
                restored._restore_playback()
                payload=json.loads(restored.request.call_args.args[0].removeprefix('restore '))
                self.assertEqual(payload['uri'],'spotify:track:chosen')
                self.assertEqual(payload['context_uri'],f'spotify:{kind}:source')
                self.assertTrue(payload['shuffle'])
                self.assertEqual(payload['repeat_mode'],mode)
                self.assertEqual(payload['position_ms'],45000)
                self.assertEqual(payload['volume'],30000)
                self.assertFalse(payload['playing'])

    def test_activation_defaults_cannot_replace_recovered_options_or_next_checkpoint(self):
        self.daemon._remember_playback()
        self.state.apply({'PLAYER_EVENT':'player_reset'})
        self.daemon.player_ready=True
        self.daemon._restore_playback()
        self.daemon._handle_event({'PLAYER_EVENT':'shuffle_changed','SHUFFLE':'false'})
        self.daemon._handle_event({'PLAYER_EVENT':'repeat_changed','REPEAT':'false','REPEAT_TRACK':'false'})
        persisted=json.loads(self.path.read_text())['state']
        self.assertTrue(persisted['shuffle'])
        self.assertEqual(persisted['repeat_mode'],'Playlist')
        self.daemon._handle_event({'PLAYER_EVENT':'paused','TRACK_ID':'chosen','POSITION_MS':'45000'})
        for state in [self.state.snapshot(),json.loads(self.path.read_text())['state']]:
            self.assertTrue(state['shuffle'])
            self.assertEqual(state['repeat_mode'],'Playlist')
            self.assertEqual(state['context_uri'],'spotify:playlist:source')
        self.daemon._remember_playback()
        self.assertTrue(self.daemon.recovery['shuffle'])
        self.assertEqual(self.daemon.recovery['repeat_mode'],'Playlist')

    def test_failed_or_superseded_load_does_not_change_context(self):
        self.daemon.request.side_effect=RuntimeError('rejected')
        self.daemon._commit_load(0,'spotify:track:new','spotify:album:new')
        self.assertEqual(self.daemon.context_uri,'spotify:playlist:source')
        self.daemon.request.reset_mock()
        self.daemon._commit_load(-1,'spotify:track:new','spotify:album:new')
        self.daemon.request.assert_not_called()
        self.assertEqual(self.daemon.context_uri,'spotify:playlist:source')

    def test_successful_load_updates_context_and_standalone_track_clears_it(self):
        self.daemon._commit_load(0,'spotify:track:new','spotify:album:new')
        self.assertEqual(self.daemon.context_uri,'spotify:album:new')
        self.assertEqual(self.state.snapshot()['context_uri'],'spotify:album:new')
        self.daemon._commit_load(0,'spotify:track:single','')
        self.assertEqual(self.daemon.context_uri,'')
        self.assertEqual(self.state.snapshot()['context_uri'],'')
        self.daemon._commit_load(0,'spotify:playlist:whole','')
        self.assertEqual(self.daemon.context_uri,'spotify:playlist:whole')

    def test_logout_removes_saved_session(self):
        self.daemon._save_checkpoint()
        self.daemon.config.player_cache=str(self.path.parent/'librespot')
        with patch.object(self.daemon,'stop'),patch.object(self.daemon,'start'):
            self.daemon.reset_credentials()
        self.assertFalse(self.path.exists())
        self.assertFalse(self.state.snapshot()['has_track'])

    def test_corrupt_or_nonfinite_checkpoint_is_ignored(self):
        self.path.write_text('{bad json')
        self.daemon._load_checkpoint()
        self.assertIsNone(self.daemon.recovery)
        self.daemon._save_checkpoint()
        saved=json.loads(self.path.read_text())
        saved['state']['position_s']=float('nan')
        self.path.write_text(json.dumps(saved))
        self.daemon._load_checkpoint()
        self.assertIsNone(self.daemon.recovery)

    def test_genuine_option_changes_after_recovery_update_saved_state(self):
        self.daemon._save_checkpoint()
        self.daemon._handle_event({'PLAYER_EVENT':'shuffle_changed','SHUFFLE':'false'})
        saved=json.loads(self.path.read_text())['state']
        self.assertFalse(saved['shuffle'])
        self.daemon._handle_event({'PLAYER_EVENT':'repeat_changed','REPEAT':'false','REPEAT_TRACK':'true'})
        saved=json.loads(self.path.read_text())['state']
        self.assertEqual(saved['repeat_mode'],'Track')
