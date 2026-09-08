import unittest
from unittest.mock import Mock, patch

from spotifierd.config import Config
from spotifierd.playback import EventPlaybackState, normalize_playback
from spotifierd.spotify import SpotifyAPI


class PlaybackTests(unittest.TestCase):
    def test_player_restart_clears_stale_track_and_notifies_clients(self) -> None:
        playback = EventPlaybackState()
        playback.apply({"PLAYER_EVENT": "track_changed", "URI": "spotify:track:old", "NAME": "Old track"})
        playback.apply({"PLAYER_EVENT": "paused", "POSITION_MS": "200000"})
        version, _ = playback.wait(-1, 0)
        playback.apply({"PLAYER_EVENT": "player_reset"})
        new_version, state = playback.wait(version, 0)
        self.assertGreater(new_version, version)
        self.assertEqual(state, normalize_playback(None))

    def test_service_notification_does_not_clear_current_track(self) -> None:
        playback = EventPlaybackState()
        playback.apply({"PLAYER_EVENT": "track_changed", "URI": "spotify:track:current"})
        playback.apply({"PLAYER_EVENT": "service_changed"})
        self.assertEqual(playback.snapshot()["uri"], "spotify:track:current")

    def test_normalizes_web_api_playback(self) -> None:
        state = normalize_playback({
            "device": {"volume_percent": 49},
            "repeat_state": "context",
            "shuffle_state": True,
            "progress_ms": 12500,
            "is_playing": True,
            "item": {
                "uri": "spotify:track:one-more-time",
                "name": "One More Time",
                "artists": [{"name": "Daft Punk"}],
                "duration_ms": 320000,
                "album": {"name": "Discovery", "images": [{"url": "cover"}]},
            },
        })
        self.assertEqual(state["title"], "One More Time")
        self.assertEqual(state["uri"], "spotify:track:one-more-time")
        self.assertEqual(state["status"], "Playing")
        self.assertEqual(state["position_s"], 12.5)
        self.assertEqual(state["repeat_mode"], "Playlist")
        self.assertTrue(state["shuffle"])

    def test_empty_playback_is_stopped(self) -> None:
        state = normalize_playback(None)
        self.assertFalse(state["has_track"])
        self.assertEqual(state["uri"], "")
        self.assertEqual(state["status"], "Stopped")

    def test_librespot_events_drive_complete_playback_state(self) -> None:
        playback = EventPlaybackState()
        playback.apply({
            "PLAYER_EVENT": "track_changed",
            "TRACK_ID": "track-id",
            "URI": "spotify:track:track-id",
            "NAME": "One More Time",
            "ARTISTS": "Daft Punk",
            "ALBUM": "Discovery",
            "COVERS": "cover-large\ncover-small",
            "DURATION_MS": "320000",
        })
        playback.apply({"PLAYER_EVENT": "playing", "TRACK_ID": "track-id", "POSITION_MS": "12500"})
        playback.apply({"PLAYER_EVENT": "volume_changed", "VOLUME": "32768"})
        playback.apply({"PLAYER_EVENT": "shuffle_changed", "SHUFFLE": "true"})
        playback.apply({"PLAYER_EVENT": "repeat_changed", "REPEAT": "true", "REPEAT_TRACK": "false"})

        state = playback.snapshot()

        self.assertEqual(state["title"], "One More Time")
        self.assertEqual(state["artist"], "Daft Punk")
        self.assertEqual(state["art_url"], "cover-large")
        self.assertEqual(state["status"], "Playing")
        self.assertGreaterEqual(state["position_s"], 12.5)
        self.assertAlmostEqual(state["volume"], 32768 / 65535)
        self.assertTrue(state["shuffle"])
        self.assertEqual(state["repeat_mode"], "Playlist")

        playback.apply({"PLAYER_EVENT": "stopped", "TRACK_ID": "track-id"})
        self.assertFalse(playback.snapshot()["has_track"])

    def test_pause_targets_only_configured_device(self) -> None:
        api = SpotifyAPI(Config(device_name="Spotifier"), Mock())
        with patch.object(api, "_discover_local_device_id", return_value="device-1"), patch.object(api, "request") as request:
            api.pause()
        request.assert_called_once_with("PUT", "/me/player/pause?device_id=device-1")

    def test_unavailable_selection_remains_explained_after_skip(self) -> None:
        playback = EventPlaybackState()
        playback.apply({"PLAYER_EVENT": "load_requested", "URI": "spotify:track:selected"})
        playback.apply({"PLAYER_EVENT": "unavailable", "TRACK_ID": "preloaded"})
        self.assertEqual(playback.snapshot()["playback_error"], "")
        playback.apply({"PLAYER_EVENT": "unavailable", "TRACK_ID": "selected"})
        error = playback.snapshot()["playback_error"]
        self.assertIn("unavailable", error)
        playback.apply({"PLAYER_EVENT": "stopped"})
        playback.apply({"PLAYER_EVENT": "track_changed", "TRACK_ID": "next", "NAME": "Next song"})
        playback.apply({"PLAYER_EVENT": "playing", "TRACK_ID": "next", "POSITION_MS": "0"})
        self.assertEqual(playback.snapshot()["playback_error"], error)
        self.assertEqual(playback.snapshot()["title"], "Next song")
        playback.apply({"PLAYER_EVENT": "load_requested", "URI": "spotify:track:another"})
        self.assertEqual(playback.snapshot()["playback_error"], "")


if __name__ == "__main__":
    unittest.main()
