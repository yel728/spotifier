import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from spotifierd.mpris import PLAYER, PlayerObject, track_path
from spotifierd.playback import EventPlaybackState


class MprisTests(unittest.TestCase):
    def setUp(self):
        self.state = EventPlaybackState()
        self.state.apply({"PLAYER_EVENT": "track_changed", "URI": "spotify:track:test",
                          "NAME": "Test song", "ARTISTS": "Artist", "DURATION_MS": "10000"})
        self.player = PlayerObject.__new__(PlayerObject)
        self.player.app = SimpleNamespace(playback=self.state, librespot=Mock(running=True))
        self.player.Seeked = Mock()

    def test_headset_methods_forward_to_one_local_player(self):
        for method, command in (("PlayPause", "play_pause"), ("Play", "play"),
                                ("Pause", "pause"), ("Next", "next"), ("Previous", "previous")):
            getattr(self.player, method)()
            self.player.app.librespot.command.assert_called_with(command)

    def test_idle_controls_do_not_start_another_session(self):
        self.state.apply({"PLAYER_EVENT": "stopped"})
        self.player.PlayPause()
        self.player.app.librespot.command.assert_not_called()

    def test_metadata_and_playback_changes_are_published_without_position_ticks(self):
        self.player.last = self.player.player_properties()
        self.player.PropertiesChanged = Mock()
        self.state.apply({"PLAYER_EVENT": "playing", "POSITION_MS": "1000"})
        self.player.publish()
        interface, changes, _ = self.player.PropertiesChanged.call_args.args
        self.assertEqual(interface, PLAYER)
        self.assertEqual(changes["PlaybackStatus"], "Playing")
        self.assertNotIn("Position", changes)
        properties = self.player.GetAll(PLAYER)
        self.assertEqual(properties["Metadata"]["xesam:title"], "Test song")
        self.assertEqual(properties["Metadata"]["mpris:length"], 10_000_000)
        self.player.PropertiesChanged.reset_mock()
        self.player.publish()
        self.player.PropertiesChanged.assert_not_called()

    def test_stale_seek_does_not_seek_the_new_track(self):
        track = track_path(self.state.snapshot())
        self.state.apply({"PLAYER_EVENT": "track_changed", "URI": "spotify:track:new",
                          "DURATION_MS": "10000"})
        self.player.SetPosition(track, 2_000_000)
        self.player.app.librespot.command.assert_not_called()
        self.player.SetPosition(track_path(self.state.snapshot()), 2_000_000)
        self.player.app.librespot.command.assert_called_once_with("seek 2000")
        self.player.Seeked.assert_called_once_with(2_000_000)
